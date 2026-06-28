/* CAD-Copilot palette app.
 *
 * Runs in two modes:
 *   - Fusion: adsk.fusionSendData(action, json) -> Promise (Qt browser, async).
 *     Network goes JS -> Python -> server (no browser CORS). Geometry highlight + execute
 *     are routed to the add-in.
 *   - Browser (no adsk): fetch() the server directly for click-through testing without Fusion.
 */
(function () {
  "use strict";

  // Detect Fusion at CALL time — `adsk.fusionSendData` may be injected AFTER this script loads,
  // and `adsk` is a global that isn't always reflected on `window`. A load-time check fell back
  // to fetch() (which the Qt browser blocks -> "Failed to fetch").
  function inFusion() {
    return typeof adsk !== "undefined" && adsk && typeof adsk.fusionSendData === "function";
  }
  var state = {
    serverUrl: "http://localhost:8000",
    plan: null,
    partId: null,
    drawings: {},   // partId -> PartDrawing
    dims: {},       // partId -> { slotId: mm }
    unit: "mm",
  };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // -------------------------------------------------------------- transport (non-blocking)
  // In Fusion the request goes to a Python WORKER thread; the result comes back later via
  // sendInfoToHTML -> onApiResult, which resolves the promise. So the UI never freezes.
  var _pending = {};
  var _seq = 0;
  async function api(path, body) {
    if (inFusion()) {
      var id = "rq" + (++_seq);
      return new Promise(function (resolve, reject) {
        _pending[id] = { resolve: resolve, reject: reject };
        _pending[id].timer = setTimeout(function () {
          if (_pending[id]) { delete _pending[id]; reject(new Error("timed out")); }
        }, 120000);  // long safety net; the worker, not the UI, is doing the waiting
        adsk.fusionSendData("apiRequest", JSON.stringify({ id: id, path: path, body: body }));
      });
    }
    var r = await fetch(state.serverUrl + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Version": "2.1.0" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function onApiResult(payload) {
    var pend = _pending[payload.id];
    if (!pend) return;
    clearTimeout(pend.timer);
    delete _pending[payload.id];
    if (payload.error) pend.reject(new Error(payload.error));
    else pend.resolve(payload.data);
  }

  function toFusion(action, data) {
    if (inFusion()) {
      try { adsk.fusionSendData(action, JSON.stringify(data || {})); } catch (e) { /* ignore */ }
    }
  }

  // Like toFusion but awaits the handler's reply (used for the build, which runs on the main
  // thread and returns its result/error synchronously).
  async function execFusion(action, data) {
    if (!inFusion()) return { status: "browser" };
    try {
      var res = await adsk.fusionSendData(action, JSON.stringify(data || {}));
      return JSON.parse(res || "{}");
    } catch (e) { return { status: "error", message: String(e && e.message ? e.message : e) }; }
  }

  // -------------------------------------------------------------- units
  function fromMm(v) { return state.unit === "in" ? v / 25.4 : state.unit === "cm" ? v / 10 : v; }
  function toMm(v) { return state.unit === "in" ? v * 25.4 : state.unit === "cm" ? v * 10 : v; }

  // -------------------------------------------------------------- steps
  // Steps are independent (not an accordion) so the user can dimension+generate part after part.
  function openStep(stepId) { $(stepId).classList.remove("collapsed"); $(stepId).classList.add("active"); }
  function collapseStep(stepId) { $(stepId).classList.add("collapsed"); }
  function setStatus(ok, text) {
    $("dot").className = "dot" + (ok === true ? " ok" : ok === false ? " err" : "");
    $("statusText").textContent = text;
  }

  // -------------------------------------------------------------- Stage 1: plan object
  async function planObject() {
    var text = $("objectInput").value.trim();
    if (!text) { setStatus(false, "Enter a description"); return; }
    setStatus(null, "Planning…");
    try {
      var plan = await api("/api/object/plan", { text: text, context: null });
      state.plan = plan; state.drawings = {}; state.dims = {};
      renderPlan(plan);
      setStatus(true, "Ready");
    } catch (e) { setStatus(false, "Plan failed: " + e.message); }
  }

  function renderPlan(plan) {
    if (!plan.parts || plan.parts.length === 0) {
      var q = (plan.clarifications_needed && plan.clarifications_needed[0]) || { question: "Could you describe a supported object?" };
      $("step-result").classList.remove("collapsed");
      $("resultArea").innerHTML = "";
      var box = el("div", "msg warn refusal");
      box.appendChild(el("div", null, "<strong>" + esc(q.question) + "</strong>"));
      if (q.options && q.options.length) box.appendChild(el("div", "hint", "Try: " + q.options.map(esc).join(", ")));
      $("resultArea").appendChild(box);
      $("step-parts").classList.add("collapsed");
      return;
    }
    $("objectSummary").textContent = (plan.object_name || "object") + " — " + (plan.summary || "");
    var tabs = $("partTabs"); tabs.innerHTML = "";
    plan.parts.forEach(function (p, i) {
      var t = el("div", "tab", esc(p.name || p.id));
      t.onclick = function () { selectPart(p.id); };
      t.dataset.part = p.id;
      tabs.appendChild(t);
      if (i === 0) { /* select first below */ }
    });
    openStep("step-parts");
    collapseStep("step-object");   // tuck the prompt away; click its header to reopen
    selectPart(plan.parts[0].id);
  }

  // -------------------------------------------------------------- Stage 2: per-part drawing
  async function selectPart(partId) {
    state.partId = partId;
    Array.prototype.forEach.call($("partTabs").children, function (t) {
      t.classList.toggle("active", t.dataset.part === partId);
    });
    if (!state.drawings[partId]) {
      // clear the previous part's drawing immediately so switching is visibly responsive
      $("views").innerHTML = '<div class="hint">Generating the structure for ' + esc(partId) + " — a few seconds…</div>";
      $("dims").innerHTML = "";
      setStatus(null, "Drawing " + partId + "…");
      try {
        var d = await api("/api/sketch/generate", { object_plan: state.plan, part_id: partId, user_feedback: null });
        if (d.reason_code) { setStatus(false, d.message || "Cannot draw this part"); renderRefusal(d); return; }
        state.drawings[partId] = d;
        state.dims[partId] = {};
        d.dimension_slots.forEach(function (s) { state.dims[partId][s.id] = s.default_value; });
      } catch (e) { $("views").innerHTML = ""; setStatus(false, "Draw failed: " + e.message); return; }
    }
    renderDrawing(state.drawings[partId]);
    setStatus(true, "Ready");
  }

  function isCount(slot) { return /count$/.test(slot.id); }

  function buildDimRow(slot) {
    var row = el("div", "dim");
    row.dataset.ref = slot.geometry_ref;
    var label = el("label", null, esc(slot.label));
    label.setAttribute("for", "dim_" + slot.id);
    var wrap = el("div", "inwrap");
    var input = el("input");
    input.type = "number"; input.id = "dim_" + slot.id;
    input.step = isCount(slot) ? "1" : "0.1";
    var raw = state.dims[state.partId][slot.id];
    input.value = isCount(slot) ? raw : round(fromMm(raw));
    input.onfocus = function () { highlight(slot.geometry_ref, true); };
    input.onblur = function () { highlight(slot.geometry_ref, false); };
    input.onchange = function () {
      var n = parseFloat(input.value) || 0;
      state.dims[state.partId][slot.id] = isCount(slot) ? n : toMm(n);
    };
    wrap.appendChild(input);
    wrap.appendChild(el("span", "u", isCount(slot) ? "x" : state.unit));
    row.appendChild(label); row.appendChild(wrap);
    return row;
  }

  function renderDrawing(d) {
    var v = $("views"); v.innerHTML = "";
    d.views.forEach(function (view) {
      var card = el("div", "view");
      card.appendChild(el("div", "label", view.view));
      card.insertAdjacentHTML("beforeend", view.svg);
      v.appendChild(card);
    });
    // group dimensions by feature (Overall, Mounting holes, Fillets, …) like a real schedule
    var dims = $("dims"); dims.innerHTML = "";
    var groups = {}, order = [];
    d.dimension_slots.forEach(function (slot) {
      var g = slot.group || "Dimensions";
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(slot);
    });
    order.forEach(function (gname) {
      var box = el("div", "dimgroup");
      box.appendChild(el("div", "gh", esc(gname) + '<span class="gcount">' + groups[gname].length + '</span>'));
      var body = el("div", "gb");
      groups[gname].forEach(function (slot) { body.appendChild(buildDimRow(slot)); });
      box.appendChild(body);
      dims.appendChild(box);
    });
  }

  function highlight(ref, on) {
    // highlight the dimension row + every matching geometry across the views
    document.querySelectorAll(".dim").forEach(function (r) {
      if (r.dataset.ref === ref) r.classList.toggle("hl", on);
    });
    document.querySelectorAll('#views [data-ref="' + cssEsc(ref) + '"]').forEach(function (g) {
      g.classList.toggle("hl", on);
    });
    toFusion(on ? "highlight" : "clearHighlight", { geometry_ref: ref });
  }

  function changeUnit() {
    state.unit = $("unitSelect").value;
    if (state.partId && state.drawings[state.partId]) renderDrawing(state.drawings[state.partId]);
  }

  // -------------------------------------------------------------- Stage 4: generate
  async function generatePart() {
    if (!state.plan || !state.partId) return;
    var partId = state.partId;  // capture — the user may switch tabs while this awaits
    setStatus(null, "Generating " + partId + "…");
    try {
      // For a novel (LLM) part, send back the parametric IR the sketch stage produced so the server
      // just substitutes the dimensions the user set (no second model call).
      var d = state.drawings[partId];
      var drawingData = d && d.base_ir ? { base_ir: d.base_ir } : null;
      var resp = await api("/api/codegen/generate", {
        object_plan: state.plan, part_id: partId,
        dimensions: state.dims[partId] || {}, drawing_data: drawingData,
      });
      openStep("step-result");  // show the result but KEEP the parts step open for the next part
      if (resp.refusal) { addResult(partId, false, resp.refusal.message || "Cannot build this part"); setStatus(true, "Ready"); return; }
      var r = resp.result;
      var params = r.command_ir.commands.filter(function (c) { return c.type === "CREATE_USER_PARAMETER"; })
        .map(function (c) { return c.params.name + "=" + c.params.value + "mm"; });
      // ADR-011: proof-of-fitness certificate — does the part PROVABLY meet its spec?
      var cert = r.certificate;
      var certMsg = cert ? (cert.ok ? " — ✓ " + (cert.summary || "certified fit")
                                    : " — ✗ " + (cert.summary || "NOT certified")) : "";
      markTabDone(partId);
      showEditRow();  // ADR-016: offer natural-language editing once a part is built
      if (!inFusion()) {
        addResult(partId, true, r.command_ir.commands.length + " operations." + certMsg + (params.length ? " " + params.join("  ") : ""));
        setStatus(true, "Done: " + partId); return;
      }
      addResult(partId, true, r.command_ir.commands.length + " operations — building in Fusion…");
      var part = (state.plan.parts || []).filter(function (p) { return p.id === partId; })[0];
      var build = await execFusion("executeCode", {
        command_ir: r.command_ir, part_id: r.part_id,
        position: part && part.position ? part.position : [0, 0, 0],
        placement: r.placement || null,  // ADR-008: solved mate transform seats the part on its host
      });
      if (build && build.status === "ok") {
        var v = build.verify && build.verify.checked && !build.verify.matched
          ? " (size differs from the model's estimate — verify it)" : "";
        var sk = build.skipped && build.skipped.length
          ? " — skipped " + build.skipped.length + " refinement(s): " + build.skipped.join("; ") : "";
        var pl = "";  // closed-loop read-back (ADR-009): where the part actually landed
        if (build.placed && build.placed.seat_gap_mm !== undefined) {
          pl = build.placed.seated
            ? " — seats on host (gap " + build.placed.seat_gap_mm + "mm)"
            : " — ⚠ NOT seated: " + build.placed.seat_gap_mm + "mm from target (center " +
              (build.placed.center_mm || []).join(",") + ")";
        }
        // ADR-010: surface texture lands as a robust watertight mesh skin (a displacement field)
        var tx = build.mesh_skins ? " — applied " + build.mesh_skins + " textured skin(s)" : "";
        addResult(partId, true, "built " + (build.features || "") + " features in Fusion" + v + sk + pl + tx + certMsg +
          (params.length ? ". " + params.join("  ") : "."));
        setStatus(true, "Built " + partId + ". Pick another part.");
      } else {
        addResult(partId, false, "build failed: " + ((build && build.message) || "unknown error"));
        setStatus(false, "Build failed for " + partId);
      }
    } catch (e) { setStatus(false, "Generate failed: " + e.message); }
  }

  function showEditRow() { var row = $("editRow"); if (row) row.style.display = "block"; }

  // ADR-016: apply a natural-language edit, then rebuild. Bidirectional + reference-safe — the new
  // dimensions keep the SAME parameter names, so nothing downstream breaks.
  async function applyEdit() {
    if (!state.plan || !state.partId) return;
    var text = ($("editInput").value || "").trim();
    if (!text) return;
    setStatus(null, "Applying edit…");
    try {
      var out = await api("/api/codegen/edit", {
        object_plan: state.plan, part_id: state.partId, text: text,
        dimensions: state.dims[state.partId] || {},
      });
      if (!out || !out.edited) {
        addResult(state.partId, false, "couldn't apply “" + text + "” — try size " +
          "(“make the wall thicker”, “20% bigger”), texture (“sharper / finer / make it knurled / " +
          "hexagonal / spiky”), or edges (“round the edges”, “bevel it”).");
        setStatus(true, "Ready"); return;
      }
      // texture / geometry edits change the part itself (pattern, added fillet/chamfer) — update the
      // plan so the rebuild uses them
      var part = (state.plan.parts || []).filter(function (p) { return p.id === state.partId; })[0];
      if (part) {
        if (out.pattern !== undefined && out.pattern !== null) part.pattern = out.pattern;
        if (out.features) part.features = out.features;
      }
      var dims = out.dimensions || {};
      state.dims[state.partId] = state.dims[state.partId] || {};
      Object.keys(dims).forEach(function (k) {
        state.dims[state.partId][k] = dims[k];
        var inp = $("dim_" + k);
        if (inp) inp.value = round(fromMm(dims[k]));   // reflect the new value in the schedule
      });
      $("editInput").value = "";
      addResult(state.partId, true, "edit applied: “" + text + "” — rebuilding…");
      await generatePart();
    } catch (e) { setStatus(false, "Edit failed: " + e.message); }
  }

  function addResult(partId, ok, text) {
    var area = $("resultArea");
    var prev = document.getElementById("res-" + partId);
    if (prev) prev.remove();  // re-generating a part replaces its entry
    var box = el("div", "msg " + (ok ? "ok" : "warn"));
    box.id = "res-" + partId;
    box.innerHTML = "<strong>" + esc(partId) + "</strong> — " + esc(text);
    area.appendChild(box);
  }

  function markTabDone(partId) {
    Array.prototype.forEach.call($("partTabs").children, function (t) {
      if (t.dataset.part === partId) t.classList.add("done");
    });
  }

  function renderRefusal(ref) {
    var area = $("resultArea"); area.innerHTML = "";
    var box = el("div", "msg warn refusal");
    box.appendChild(el("div", null, "<strong>" + esc(ref.message || "Cannot build this") + "</strong>"));
    if (ref.decomposition_suggestion && ref.decomposition_suggestion.length) {
      box.appendChild(el("div", "hint", "Suggested parts: " + ref.decomposition_suggestion.map(esc).join(", ")));
    }
    area.appendChild(box);
  }

  // -------------------------------------------------------------- helpers
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function cssEsc(s) { return String(s).replace(/"/g, '\\"'); }
  function round(v) { return Math.round(v * 1000) / 1000; }

  // Fusion -> JS callback (palette.sendInfoToHTML): worker results + status updates arrive here.
  window.fusionJavaScriptHandler = { handle: function (action, data) {
    var d;
    try { d = JSON.parse(data || "{}"); } catch (e) { d = {}; }
    if (action === "apiResult") onApiResult(d);
    else if (action === "status") setStatus(d.ok, d.text || "");
    return '{"status":"ok"}';
  }};

  // -------------------------------------------------------------- init
  function init() {
    $("planBtn").onclick = planObject;
    $("clearBtn").onclick = function () { $("objectInput").value = ""; setStatus(null, "Ready"); };
    $("generateBtn").onclick = generatePart;
    $("editBtn").onclick = applyEdit;
    $("editInput").onkeydown = function (e) { if (e.key === "Enter") applyEdit(); };
    $("unitSelect").onchange = changeUnit;
    // click any step header to expand/collapse it (free navigation between steps)
    document.querySelectorAll(".step .head").forEach(function (h) {
      h.style.cursor = "pointer";
      h.onclick = function () { h.parentElement.classList.toggle("collapsed"); };
    });
    $("modeTag").textContent = inFusion() ? "Fusion" : "browser test";
    if (inFusion()) {
      setStatus(true, "Connected");
    } else {
      // browser mode: ping the server so the user knows it's reachable
      fetch(state.serverUrl + "/health/").then(function (r) { return r.json(); })
        .then(function (h) { setStatus(true, "Server " + h.contract_version); })
        .catch(function () { setStatus(false, "Start the server: uvicorn ai_server.main:app"); });
    }
  }
  document.addEventListener("DOMContentLoaded", init);
})();
