"""Compile-check latido.scene.json against the real Weaver compiler + Shaper manifest.

Proves the scene loads: runs the weaver's compile_scene with the installed Shaper
instrument manifest (extracted from a rehearsal runtime_status artifact) and the
HarMoCAP/ECG channel ranges the scene references. Exits non-zero on any validation
error.

Usage:
    python3 scripts/validate_scene.py [path/to/harmonic-weaver]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENE = HERE.parent / "scenes" / "latido.scene.json"
# Default sibling checkout of the weaver.
WEAVER = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / "harmonic-weaver"


def main() -> int:
    sys.path.insert(0, str(WEAVER / "src"))
    from harmonic_weaver.engine.compiler import compile_scene, destination_key  # noqa: E402

    scene = json.loads(SCENE.read_text(encoding="utf-8"))

    # Prefer the real Shaper manifest from a sibling harmonic-shaper checkout;
    # fall back to a rehearsal runtime_status artifact (synthesizing the
    # harmonic_envelope capability if that artifact predates it).
    real_contract = WEAVER.parent / "harmonic-shaper" / "contracts" / "shaper.contract.json"
    if real_contract.exists():
        capabilities = json.loads(real_contract.read_text(encoding="utf-8"))["capabilities"]
        print(f"using real Shaper manifest: {real_contract}")
    else:
        artifacts = sorted((WEAVER / "rehearsal" / "artifacts").glob("*/runtime_status.json"))
        if not artifacts:
            print("no shaper manifest and no runtime_status artifact found", file=sys.stderr)
            return 2
        status = json.loads(artifacts[-1].read_text(encoding="utf-8"))
        shaper = next(i for i in status["engine"]["instruments"] if i["instrument_id"] == "shaper")
        capabilities = list(shaper["capabilities"])
        if not any(c.get("name") == "harmonic_envelope" for c in capabilities):
            print("note: synthesizing harmonic_envelope capability (absent from local artifact)")
            capabilities.append({
                "name": "harmonic_envelope",
                "address_pattern": "/digital/harmonic/{N}/envelope",
                "parameters": {"N": {"type": "int32", "bounds": [1, 32]}},
                "arguments": [{"name": "gain", "type": "float32", "range": [0.0, 1.0]}],
                "read": True, "write": True,
            })
    instrument_manifests = {"shaper": {"capabilities": capabilities}}

    # Channel ranges the scene references (canonical HarMoCAP feature ranges + ecg.beat).
    unit, signed = (0.0, 1.0), (-1.0, 1.0)
    channel_ranges: dict[str, tuple[float, float]] = {"ecg.beat": unit}
    for slot in (0, 1):
        channel_ranges[f"harmocap.slot_{slot}_focused"] = unit
        channel_ranges[f"harmocap.slot_{slot}_kinetic_energy"] = unit
        channel_ranges[f"harmocap.slot_{slot}_expansion"] = unit
        channel_ranges[f"harmocap.slot_{slot}_verticality"] = signed
        channel_ranges[f"harmocap.slot_{slot}_symmetry"] = unit
        channel_ranges[f"harmocap.slot_{slot}_angle_elbow_r"] = unit

    # Synthesize a safety default for every destination the scene writes.
    safety_defaults = {}
    for route in scene["routes"]:
        safety_defaults[destination_key(route["destination"])] = 0.0

    compiled = compile_scene(scene, channel_ranges, instrument_manifests, safety_defaults)
    print(f"OK  scene {compiled.definition['scene_id']!r} compiled")
    print(f"    {len(compiled.aggregators)} aggregators, {len(compiled.routes)} routes")
    for route in compiled.routes:
        print(f"    - {route.route_id}: output range {route.static_range} -> "
              f"{route.destination.address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
