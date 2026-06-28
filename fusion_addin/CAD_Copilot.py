"""CAD-Copilot Autodesk Fusion add-in — entry point.

Platform constraints honored (verified June 2026):
  * Pure .py only — Python 3.14; no compiled .pyc, no native wheels.
  * 0.005 s startup budget — heavy imports are LAZY (inside handlers), not module-level.
  * adsk.fusionSendData is ASYNC (Promise) under the Qt browser — handled JS-side.
  * Palettes are deleted on workspace switch — recreated on demand.
  * Design-Intent gate runs before any modeling (assembly designs hard-fail otherwise).

This skeleton registers a command, opens the palette, and gates on design intent. The
full bidirectional wiring (highlighting, execution) lands in M1-W2/W3/W5 tasks.
"""

import json
import os
import sys
import threading
import traceback

# Make this add-in's own folder importable so `from core import ...` works inside the event
# handlers (Fusion does not reliably put the add-in directory on sys.path).
_ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)

import adsk.core  # noqa: E402 - must follow the sys.path setup above
import adsk.fusion  # noqa: E402

# Keep handler references alive (else Fusion garbage-collects them).
_handlers: list = []
_app: adsk.core.Application | None = None
_ui: adsk.core.UserInterface | None = None
_palette = None

_CMD_ID = "CADCopilotCmd"
_PALETTE_ID = "cadCopilotPalette"
_PALETTE_HTML = "ui/html/palette.html"

# Custom event used to marshal a worker-thread HTTP result back to the main (UI) thread, where it
# is safe to push to the palette. This is what makes the bridge non-blocking (no UI freeze).
_RESULT_EVENT_ID = "CADCopilotApiResult"
_result_event = None


def run(context):
    global _app, _ui
    try:
        if _ADDIN_DIR not in sys.path:  # also here, in case Fusion re-runs run() without reimport
            sys.path.insert(0, _ADDIN_DIR)
        # Drop cached `core.*` modules so a plain Stop->Run reloads edited code (no full Fusion
        # restart needed). The handlers import core lazily, so they'll pick up the fresh modules.
        for _mod in [m for m in list(sys.modules) if m == "core" or m.startswith("core.")]:
            del sys.modules[_mod]
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        cmd_def = _ui.commandDefinitions.itemById(_CMD_ID)
        if not cmd_def:
            # Empty resource folder -> Fusion uses a default icon (no resources/icons dir needed).
            cmd_def = _ui.commandDefinitions.addButtonDefinition(
                _CMD_ID, "CAD Copilot", "AI-powered CAD assistant", ""
            )

        created = _CommandCreatedHandler()
        cmd_def.commandCreated.add(created)
        _handlers.append(created)

        panel = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        if panel and not panel.controls.itemById(_CMD_ID):
            panel.controls.addCommand(cmd_def)

        # Register the worker-result custom event (re-register cleanly if a prior run left it).
        global _result_event
        try:
            _app.unregisterCustomEvent(_RESULT_EVENT_ID)
        except Exception:
            pass
        _result_event = _app.registerCustomEvent(_RESULT_EVENT_ID)
        result_handler = _ApiResultHandler()
        _result_event.add(result_handler)
        _handlers.append(result_handler)

    except Exception:
        if _ui:
            _ui.messageBox(f"CAD-Copilot failed to start:\n{traceback.format_exc()}")


def stop(context):
    try:
        global _palette
        if _palette:
            _palette.deleteMe()
            _palette = None

        if _ui:
            panel = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
            if panel:
                ctrl = panel.controls.itemById(_CMD_ID)
                if ctrl:
                    ctrl.deleteMe()
            cmd_def = _ui.commandDefinitions.itemById(_CMD_ID)
            if cmd_def:
                cmd_def.deleteMe()

        if _app:
            try:
                _app.unregisterCustomEvent(_RESULT_EVENT_ID)
            except Exception:
                pass
        _handlers.clear()
    except Exception:
        if _ui:
            _ui.messageBox(f"CAD-Copilot failed to stop:\n{traceback.format_exc()}")


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            executed = _CommandExecuteHandler()
            args.command.execute.add(executed)
            _handlers.append(executed)
        except Exception:
            if _ui:
                _ui.messageBox(f"commandCreated error:\n{traceback.format_exc()}")


class _CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            # Lazy imports keep the startup path light.
            from core import design_gate

            design = adsk.fusion.Design.cast(_app.activeProduct)
            if design is not None:
                gate = design_gate.evaluate(design)
                if not gate.allowed:
                    _ui.messageBox(gate.message, "CAD Copilot")
                    return

            _open_palette()
        except Exception:
            if _ui:
                _ui.messageBox(f"execute error:\n{traceback.format_exc()}")


def _open_palette():
    """Create or reveal the palette (recreated after workspace switches)."""
    global _palette
    _palette = _ui.palettes.itemById(_PALETTE_ID)
    if _palette:
        _palette.isVisible = True
        return

    _palette = _ui.palettes.add(
        _PALETTE_ID,
        "CAD Copilot",
        _PALETTE_HTML,
        True,   # isVisible
        True,   # showCloseButton
        True,   # isResizable
        400,
        700,
    )
    _palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight

    # HTML->Python event wiring lands in M1-W2-UI-03 (Promise-based bridge).
    incoming = _HTMLEventHandler()
    _palette.incomingFromHTML.add(incoming)
    _handlers.append(incoming)


class _HTMLEventHandler(adsk.core.HTMLEventHandler):
    """Routes palette events. The Qt browser awaits args.returnData as a Promise.

    - apiRequest: proxy HTTP to the AI server (palette JS never calls the network directly,
      which sidesteps the Qt browser's CORS restrictions). Synchronous for now; the threaded
      non-blocking version lands with M1-W3.
    - highlight / clearHighlight: drawing highlight is client-side in the palette SVG;
      3D highlighting of built geometry -> M1-W3-UI-05 (acknowledged here).
    - executeCode: Safe Executor realizes the validated Command IR in Fusion -> M1-W3-UI-04.
    """

    def notify(self, args):
        try:
            data = json.loads(args.data) if args.data else {}
            action = args.action

            if action == "apiRequest":
                # Do the (possibly slow, LLM-backed) HTTP call on a WORKER thread so Fusion's UI
                # never blocks. The result is marshaled back via the custom event (see below).
                threading.Thread(target=_do_api_request, args=(data,), daemon=True).start()
                args.returnData = '{"queued": true}'
            elif action in ("highlight", "clearHighlight"):
                args.returnData = '{"status": "ok"}'  # M1-W3-UI-05
            elif action == "executeCode":
                args.returnData = json.dumps(self._execute_ir(data))
            else:
                args.returnData = '{"status": "ok"}'
        except Exception:
            if _ui:
                _ui.messageBox(f"HTML event error:\n{traceback.format_exc()}")

    def _execute_ir(self, data: dict) -> dict:
        """Run the Safe Executor on a validated Command IR, re-gating on design intent."""
        from core import design_gate
        from core.safe_executor import ExecutionError, SafeExecutor

        ir = data.get("command_ir")
        if not isinstance(ir, dict):
            return {"status": "error", "message": "no command_ir supplied"}

        design = adsk.fusion.Design.cast(_app.activeProduct)
        if design is None:
            return {"status": "error", "message": "open a Part or Hybrid design first"}
        gate = design_gate.evaluate(design)
        if not gate.allowed:
            return {"status": "blocked", "message": gate.message}

        try:
            result = SafeExecutor().execute(ir, design=design, position=data.get("position"),
                                            placement=data.get("placement"),
                                            part_id=data.get("part_id"))
        except ExecutionError as exc:
            return {"status": "error", "message": str(exc)}
        return {"status": "ok", "part_id": data.get("part_id"), **result}


def _do_api_request(data: dict) -> None:
    """Worker thread: call the AI server, then fire the custom event to deliver the result safely."""
    req_id = data.get("id")
    try:
        from core.server_client import ServerClient

        result = ServerClient()._request("POST", data.get("path", ""), data.get("body"))
        payload = {"id": req_id, "data": result}
    except Exception as exc:
        payload = {"id": req_id, "error": str(exc)}
    try:
        if _app:
            _app.fireCustomEvent(_RESULT_EVENT_ID, json.dumps(payload))
    except Exception:
        pass  # palette/app may be gone; nothing to deliver to


class _ApiResultHandler(adsk.core.CustomEventHandler):
    """Runs on the MAIN thread (custom events marshal here) — push the worker's result to the palette."""

    def notify(self, args):
        try:
            if _palette:
                _palette.sendInfoToHTML("apiResult", args.additionalInfo)
        except Exception:
            if _ui:
                _ui.messageBox(f"apiResult delivery error:\n{traceback.format_exc()}")
