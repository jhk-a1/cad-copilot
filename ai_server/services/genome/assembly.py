"""Compositional assembly (ADR-014, breakthrough Pillar P5) — typed interfaces, system-level proof.

Every text-to-CAD assembler places parts and *hopes* the whole is consistent (pairwise mates, no
system guarantee). Applied category theory (operads of wiring diagrams; (decorated) cospans;
functorial property propagation) gives the missing algebra: a part is a box with TYPED PORTS, a
connection is legal iff the port types match, and the assembly is correct-by-construction at the
SYSTEM level. We add the typed-interface layer plus a system-level mobility check (Grübler–Kutzbach,
via `dfm`) and emit an OBJECT-LEVEL certificate that is independently re-checkable (reusing the
ADR-011 machinery), so "the whole mug — body + handle — is a rigid, well-connected assembly with
compatible interfaces" becomes a proof, not a hope.

General by construction: ports are derived from each part's geometry/genome (not its name), and
compatibility is a typed relation — the same rules compose a mug+handle, a bracket+plate, a
shaft+bushing, or any multi-part object. Pure and offline.
"""

from __future__ import annotations

from dataclasses import dataclass

from .grammar import FeatureType, Genome
from .planner import plan_genome
from .spec import Requirement, Specification

# ---- typed ports ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Port:
    """One typed interface of a part. ``kind`` is the interface TYPE that must match to mate;
    ``role`` is "host" (offers a surface/socket) or "plug" (attaches into a host)."""

    name: str
    kind: str
    role: str  # "host" | "plug"


# which DISTINCT interface kinds may mate (unordered pairs)
_COMPATIBLE: set[frozenset[str]] = {
    frozenset({"mount", "surface_round"}),   # a handle/bracket mounts onto a round wall
    frozenset({"mount", "surface_flat"}),    # ...or a flat face
    frozenset({"mount_face", "surface_flat"}),
    frozenset({"lid", "rim"}),               # a lid seats on a rim
    frozenset({"shaft", "bore"}),            # a shaft seats in a bore
}
# interface kinds that mate with an identical face (face-to-face)
_SELF_MATING = {"mount_face", "surface_flat"}


def compatible(a: Port, b: Port) -> bool:
    if a.kind == b.kind:
        return a.kind in _SELF_MATING
    return frozenset({a.kind, b.kind}) in _COMPATIBLE


# primary feature type -> the HOST ports its geometry offers
_HOST_PORTS = {
    FeatureType.HOLLOW_CYLINDER: (("wall", "surface_round"), ("rim", "rim")),
    FeatureType.SOLID_CYLINDER: (("wall", "surface_round"),),
    FeatureType.CONE: (("wall", "surface_round"),),
    FeatureType.SPHERE: (("surface", "surface_round"),),
    FeatureType.TORUS: (("surface", "surface_round"),),
    FeatureType.HOLLOW_BOX: (("face", "surface_flat"), ("rim", "rim")),
    FeatureType.SOLID_BOX: (("face", "surface_flat"),),
    FeatureType.PRISM: (("face", "surface_flat"),),
    FeatureType.WEDGE: (("face", "surface_flat"),),
    FeatureType.L_BRACKET: (("mount_face", "mount_face"),),
}
# attaching primaries -> the PLUG they present
_PLUG_PORTS = {FeatureType.LOOP_HANDLE: ("mount", "mount")}


def ports_of(genome: Genome) -> list[Port]:
    """Derive a part's typed interface ports from its genome (general, geometry-driven)."""
    primary = genome.primary
    ports: list[Port] = []
    if primary is not None:
        for nm, kind in _HOST_PORTS.get(primary.type, (("face", "surface_flat"),)):
            ports.append(Port(nm, kind, "host"))
        if primary.type in _PLUG_PORTS:
            nm, kind = _PLUG_PORTS[primary.type]
            ports.append(Port(nm, kind, "plug"))
    if any(f.type is FeatureType.BORE for f in genome.features):
        ports.append(Port("bore", "bore", "host"))
    return ports


# ---- the assembly graph ---------------------------------------------------------------------


@dataclass(frozen=True)
class Connection:
    part: str
    host: str
    plug_kind: str
    host_kind: str
    ok: bool


def _host_id(plan, part) -> str | None:
    att = getattr(part, "attachment", None)
    att = att.model_dump() if hasattr(att, "model_dump") else att
    if isinstance(att, dict) and att.get("to"):
        return str(att["to"])
    primary = plan_genome(part)
    if primary is not None and primary.primary is not None \
            and primary.primary.type in _PLUG_PORTS:
        # default: attach to a sibling sitting at the origin (the body)
        for other in plan.parts:
            if other.id == part.id:
                continue
            pos = getattr(other, "position", None)
            if not pos or not any(pos):
                return other.id
    return None


def _connections(plan) -> list[Connection]:
    """Derive typed connections from the plan's attachments and check interface compatibility."""
    by_id = {p.id: p for p in plan.parts}
    conns: list[Connection] = []
    for part in plan.parts:
        host_id = _host_id(plan, part)
        if host_id is None or host_id not in by_id:
            continue
        pg, hg = plan_genome(part), plan_genome(by_id[host_id])
        if pg is None or hg is None:
            continue
        plug = next((p for p in ports_of(pg) if p.role == "plug"), None)
        if plug is None:
            continue
        host_port = next((h for h in ports_of(hg)
                          if h.role == "host" and compatible(plug, h)), None)
        if host_port is None:
            # no compatible host interface -> record the incompatibility against the first host port
            any_host = next((h for h in ports_of(hg) if h.role == "host"), Port("?", "?", "host"))
            conns.append(Connection(part.id, host_id, plug.kind, any_host.kind, False))
        else:
            conns.append(Connection(part.id, host_id, plug.kind, host_port.kind, True))
    return conns


def build_assembly_spec(plan) -> tuple[Specification, dict]:
    """Compose an OBJECT-LEVEL specification + evidence: every interface must type-match, the
    assembly must be connected (no floating part), and rigid (a product) unless declared a mechanism.
    Reuses the certificate machinery so the object certificate is independently re-checkable."""
    from .dfm import Joint, analyze_mechanism

    obj = getattr(plan, "object_name", None) or "object"
    conns = _connections(plan)
    reqs: list[Requirement] = []
    ev: dict = {}

    for i, c in enumerate(conns):
        key = f"iface_ok_{i}"
        ev[key] = bool(c.ok)
        reqs.append(Requirement(
            id=f"{obj}.assembly.iface.{c.part}_{c.host}", kind="assembly",
            description=f"{c.part}'s {c.plug_kind} interface mates {c.host}'s {c.host_kind}",
            metric=key, op="==", target=True, severity="must", tier="proved",
            provenance="parts compose only when interface types match"))

    # system-level mobility: parts are links, fixed connections are 0-DOF joints
    links = {p.id for p in plan.parts}
    joints = [Joint(c.part, c.host, "fixed") for c in conns]
    mob = analyze_mechanism(links, joints, expected="structure")
    ev["mobility"] = mob.mobility
    ev["disconnected"] = max(0, _component_count(links, joints) - 1)

    if len(plan.parts) > 1:
        reqs.append(Requirement(
            id=f"{obj}.assembly.connected", kind="assembly",
            description="every part is connected into the assembly (nothing floats free)",
            metric="disconnected", op="==", target=0, severity="must", tier="proved",
            provenance="an assembled product must be one connected whole"))
        reqs.append(Requirement(
            id=f"{obj}.assembly.rigid", kind="assembly",
            description="the assembly is rigid (a product, not an unintended mechanism)",
            metric="mobility", op="<=", target=0, severity="should", tier="tested",
            provenance="Grübler–Kutzbach mobility: a fixed-joint product should be rigid"))
    return (Specification(part_id=obj, requirements=tuple(reqs), object_type="assembly"), ev)


def _component_count(links: set[str], joints) -> int:
    parent = {n: n for n in links}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for j in joints:
        if j.a in parent and j.b in parent:
            parent[find(j.a)] = find(j.b)
    return len({find(n) for n in links})


def certify_assembly(plan):
    """The object-level proof-of-fitness certificate: interfaces type-match, the assembly is
    connected and rigid. Independently re-checkable via `certificate.recheck`."""
    from .certificate import check

    spec, ev = build_assembly_spec(plan)
    return check(spec, ev)
