#!/usr/bin/env python3
"""latido_smoke.py — headless end-to-end proof of the Latido scene.

Runs the REAL harmonic-weaver engine with the REAL harmonic-shaper manifest,
installs the harmocap + ecg sources, activates latido.scene.json, and drives it
with synthetic HarMoCAP + ECG frames — NO camera, NO GPU, NO SuperCollider, NO
audio. It records every value the engine would send to the Shaper and asserts:

  * /digital/harmonic/{1..5}/envelope  sound the field, track dancer energy, in [floor,peak]
  * /digital/harmonic/{2..5}/phase      ACCUMULATE (morph), stay in [0,360)
  * /digital/master                     PULSE per beat and decay, in [0.8,1.0]

This validates the whole routing/mapping (aggregators, phase_accumulator,
beat_envelope, envelope rolloff) against the real engine + real manifest, short
of actual sound/laser. It also exercises the safety profile the live stack needs.

Usage:  python3 scripts/latido_smoke.py [path/to/harmonic-weaver]
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LATIDO = HERE.parent
BEACON = LATIDO.parent
WEAVER = Path(sys.argv[1]) if len(sys.argv) > 1 else BEACON / "harmonic-weaver"
SHAPER_CONTRACT = BEACON / "harmonic-shaper" / "contracts" / "shaper.contract.json"
SCENE = LATIDO / "scenes" / "latido.scene.json"

sys.path.insert(0, str(WEAVER / "src"))
sys.path.insert(0, str(WEAVER))  # for the `rehearsal` package

from harmonic_weaver.engine import RecordingOutputTransport, WeaverEngine  # noqa: E402
from harmonic_weaver.contract_codec import contract_id_from_manifest       # noqa: E402
from rehearsal.weaver_runtime import (                                     # noqa: E402
    harmocap_manifest, ecg_manifest, shaper_safety_profile,
)

OBSERVED = "observed"
FPS = 60
DURATION_S = 12
BPM = 72
BEAT_PERIOD_S = 60.0 / BPM


def latido_shaper_safety(contract_id: str) -> dict:
    """The stock shaper safety profile only resets harmonic_envelope + panic.
    Latido also writes harmonic_phase (2-5) and master_gain, so extend the
    reset defaults to cover them — the live stack needs the same extension."""
    profile = shaper_safety_profile(contract_id)
    for n in range(1, 6):
        profile["reset_defaults"].append(
            {"capability": "harmonic_phase", "bindings": {"N": n}, "argument": "phase_degrees", "value": 0.0}
        )
    profile["reset_defaults"].append(
        {"capability": "master_gain", "bindings": {}, "argument": "gain", "value": 0.8}
    )
    return profile


HM_MANIFEST = harmocap_manifest()
EC_MANIFEST = ecg_manifest()
HM_CHANNELS = [c["name"] for c in HM_MANIFEST["channels"]]
EC_CHANNELS = [c["name"] for c in EC_MANIFEST["channels"]]

# A controllable clock so scene activation and ingested frames share one
# timeline (the engine stamps scene-transition start with clock_us(); if that
# used wall-clock while frames used a small now_us, every route would stay in
# its crossfade/reset window forever).
CLOCK = {"us": 0}


def build_engine():
    engine = WeaverEngine(transport=(rec := RecordingOutputTransport()),
                          clock_us=lambda: CLOCK["us"])
    shaper = json.loads(SHAPER_CONTRACT.read_text(encoding="utf-8"))
    scid = contract_id_from_manifest(shaper)
    engine.install_instrument(shaper, latido_shaper_safety(scid))
    assert engine.instrument_hello("shaper", "a" * 16, scid), "shaper hello rejected"
    assert engine.instrument_sync_complete("shaper", "a" * 16, scid), "shaper sync rejected"
    hcid = engine.install_source(HM_MANIFEST)
    assert engine.source_hello("harmocap", "b" * 16, hcid), "harmocap hello rejected"
    ecid = engine.install_source(EC_MANIFEST)
    assert engine.source_hello("ecg", "c" * 16, ecid), "ecg hello rejected"
    return engine, rec, hcid, ecid


def activate_scene(engine) -> None:
    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    engine.upsert_scene(scene, engine.stage_revision)              # install (rev bumps)
    engine.switch_scene(scene["scene_id"], scene["scene_version"], engine.stage_revision)
    print(f"activated scene {scene['scene_id']!r} v{scene['scene_version']}")


def drive(engine, hcid, ecid) -> None:
    # The engine requires every declared channel in each frame; fill all with a
    # neutral default, then override the handful the choreography drives.
    hm_base = {name: (0.0, OBSERVED, 1.0) for name in HM_CHANNELS}
    last_beat = -1e9
    for i in range(FPS * DURATION_S):
        t = i / FPS
        now_us = int(t * 1_000_000)
        CLOCK["us"] = now_us
        chans = dict(hm_base)
        chans["slot_0_focused"] = (1.0, OBSERVED, 1.0)
        chans["slot_1_focused"] = (0.0, OBSERVED, 1.0)
        chans["slot_0_expansion"] = (0.5 + 0.45 * math.sin(2 * math.pi * 0.15 * t), OBSERVED, 1.0)
        chans["slot_0_verticality"] = (0.8 * math.sin(2 * math.pi * 0.10 * t), OBSERVED, 1.0)
        chans["slot_0_symmetry"] = (0.5 + 0.40 * math.sin(2 * math.pi * 0.07 * t + 1), OBSERVED, 1.0)
        chans["slot_0_angle_elbow_r"] = (0.5 + 0.40 * math.sin(2 * math.pi * 0.20 * t + 2), OBSERVED, 1.0)
        chans["slot_0_kinetic_energy"] = (0.30 + 0.50 * abs(math.sin(2 * math.pi * 0.12 * t)), OBSERVED, 1.0)
        engine.ingest_source_frame("harmocap", "b" * 16, hcid, i + 1, chans, now_us=now_us)

        beat = 1.0 if (t - last_beat) >= BEAT_PERIOD_S else 0.0
        if beat:
            last_beat = t
        ecg = {name: (0.0, OBSERVED, 1.0) for name in EC_CHANNELS}
        ecg["beat"] = (beat, OBSERVED, 1.0)
        ecg["bpm"] = (float(BPM), OBSERVED, 1.0)
        ecg["signal_quality"] = (1.0, OBSERVED, 1.0)
        engine.ingest_source_frame("ecg", "c" * 16, ecid, i + 1, ecg, now_us=now_us)


def report_and_assert(rec) -> bool:
    series: dict[str, list[float]] = defaultdict(list)
    for r in rec.records:
        if r.address and r.value is not None and r.reason == "route":
            series[r.address].append(float(r.value))

    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    print("\n— envelope (sound the field) —")
    for n in range(1, 6):
        a = f"/digital/harmonic/{n}/envelope"
        v = series.get(a, [])
        print(f"  {a}: n={len(v)} min={min(v):.3f} max={max(v):.3f}" if v else f"  {a}: MISSING")
        check(f"H{n} envelope present & varies & in-range",
              bool(v) and 0.0 <= min(v) and max(v) <= 1.0 and (max(v) - min(v)) > 0.02)

    print("\n— phase (morph) —")
    for n in range(2, 6):
        a = f"/digital/harmonic/{n}/phase"
        v = series.get(a, [])
        span = (max(v) - min(v)) if v else 0.0
        print(f"  {a}: n={len(v)} min={min(v):.1f} max={max(v):.1f} distinct={len(set(round(x,1) for x in v))}" if v else f"  {a}: MISSING")
        check(f"H{n} phase present, in [0,360), accumulates (span>30deg)",
              bool(v) and 0.0 <= min(v) and max(v) < 360.0 and span > 30.0)

    print("\n— master (heartbeat pulse) —")
    m = series.get("/digital/master", [])
    if m:
        print(f"  /digital/master: n={len(m)} min={min(m):.3f} max={max(m):.3f}")
    check("master present, in [0.8,1.0], pulses (max>0.95) and decays (min<0.85)",
          bool(m) and min(m) >= 0.8 - 1e-6 and max(m) <= 1.0 + 1e-6 and max(m) > 0.95 and min(m) < 0.85)

    # count distinct pulses (rising through 0.95)
    beats = sum(1 for i in range(1, len(m)) if m[i] > 0.95 >= m[i - 1]) if m else 0
    expected = int(DURATION_S / BEAT_PERIOD_S)
    print(f"  detected ~{beats} pulses over {DURATION_S}s (expected ~{expected} at {BPM} bpm)")
    check("pulse count within 2 of expected", abs(beats - expected) <= 2)

    return ok


def main() -> int:
    print(f"weaver:  {WEAVER}")
    print(f"shaper:  {SHAPER_CONTRACT}  ({'found' if SHAPER_CONTRACT.exists() else 'MISSING'})")
    engine, rec, hcid, ecid = build_engine()
    activate_scene(engine)
    drive(engine, hcid, ecid)
    ok = report_and_assert(rec)
    print("\n" + ("SMOKE PASSED — Latido routes emit correctly against the real engine + shaper manifest"
                  if ok else "SMOKE FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
