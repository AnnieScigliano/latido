# latido

A two-person Harmonic Beacon performance, expressed as **data on top of the
`harmonic-weaver` engine** — a scene, not a fork.

> One person's **ECG heartbeat** pulses the beacon's amplitude (the laser figure
> brightens on each beat); a second person **dances** and their body's posture
> drives the per-harmonic **phase** (the laser figure morphs). Harmonic 1 stays
> unrouted as the phase anchor the others move against. In HIT's terms: the field
> is tuned to a body's own resonance, and *relation becomes visible as form*.

## What's here

| Path | What |
|---|---|
| `scenes/latido.scene.json` | the scene — real weaver schema, compiles clean |
| `scripts/validate_scene.py` | compile-checks the scene against the real weaver + Shaper manifest |

The one piece of **engine** code the piece needs — the `phase_accumulator`
transform — lives in the weaver, not here: branch
`feat/phase-accumulator-transform` on `AlterMundi/harmonic-weaver` (see that
repo's `docs/TRANSFORM_PHASE_ACCUMULATOR.md`). The laser rig is physical and
needs no software.

## The signal path

```
person A ─► AD8232 ECG ─► weaver ecg driver ─►  ecg.beat
                                                    │
person B ─► HarMoCAP ─► weaver harmocap driver ─►  harmocap.slot_{0,1}_{expansion,verticality,symmetry,angle_elbow_r,focused}
(dancer)                                            │
                                                    ▼
                                          harmonic-weaver  (latido.scene.json)
                                                    │  /digital/* :9002
                                                    ▼
                                          harmonic-shaper  (additive synth)
                                                    │ stereo out
                                        ┌───────────┴───────────────────────┐
                                        ▼                                   ▼
                                   speakers (room)      tube → balloon+mirror → LASER → wall
```

## The mapping (as built in the scene)

**Focus-follow.** Both dancers' features exist as `harmocap.slot_0_*` and
`slot_1_*`; five **aggregators** collapse each feature to the *focused* slot via
an `include_when: slot_N_focused == 1` predicate (the same pattern
`event_demo.scene.json` uses for keypoints), producing `focused_energy.value`,
`focused_expansion.value`, `focused_verticality.value`, `focused_symmetry.value`,
`focused_elbow_r.value`.

**Sounding the field (the figure exists at all).** Phase does nothing to a silent
partial, so the focused dancer's `kinetic_energy` sounds harmonics 1–5 via the
Shaper's `harmonic_envelope` capability — each with a **floor** (so the field is
audible even when the dancer is still) and a **descending rolloff** (H1 loudest →
H5 softest, a natural harmonic timbre). Movement swells the partials in; when the
dancer leaves frame the field releases to silent. This is also what makes the
heartbeat's master-gain pulse visible — a brighter flash on an already-lit figure.

| harmonic | envelope gain range (floor → full) |
|---|---|
| H1 (fundamental / anchor) | 0.55 → 0.90 |
| H2 | 0.45 → 0.78 |
| H3 | 0.35 → 0.66 |
| H4 | 0.28 → 0.56 |
| H5 | 0.22 → 0.48 |

**Movement → phase (the figure morphs).** Each focused feature is scaled to an
angular velocity (deg/s) and integrated by `phase_accumulator` into a harmonic's
phase:

| feature | → | destination | laser effect |
|---|---|---|---|
| `expansion` | scale → accumulate | `harmonic_phase` N=2 | largest-scale reshape (2:1 with the anchor) |
| `verticality` | scale → accumulate | `harmonic_phase` N=3 | posture bends the figure |
| `symmetry` | scale → accumulate | `harmonic_phase` N=4 | symmetric body → symmetric figure |
| `angle_elbow_r` | scale → accumulate | `harmonic_phase` N=5 | arm extension → finest, fastest morph |

Harmonic 1 is left unrouted — the fixed reference the others move against.
Phase routes use `invalid: "suppress"`, so if the dancer leaves frame the Shaper
holds its last phase (the figure freezes rather than snapping to zero), and the
accumulator's `max_dt_ms` clamps the step on resume so it re-enters smoothly.

**Heartbeat → amplitude (the figure pulses).** `ecg.beat` → a `rising_edge` gate
→ `master_gain`, flashing 0.8→1.0 per beat (the same edge pattern `event_demo`
uses for its nature pulse). A smoother decaying pulse awaits a future
`beat_envelope` transform; the edge flash is the stock mechanism today.

## Validate it loads

```bash
python3 scripts/validate_scene.py            # assumes ../harmonic-weaver
# or: python3 scripts/validate_scene.py /path/to/harmonic-weaver
```

Expected: `OK scene 'latido' compiled — 4 aggregators, 5 routes`, with the phase
routes resolving to `/digital/harmonic/{2..5}/phase` and the beat to
`/digital/master`.

## Run it (once the weaver branch is merged)

Load `scenes/latido.scene.json` through the weaver's Stage WS API, the way
`rehearsal/push_scene.py` loads `event_demo`. Rehearse with no hardware by
replaying `HarMoCAP/examples/fixtures/two_persons.jsonl` through the harmocap
driver and `cymatic-control/test_ecg_stream.py` through the ecg driver.

## Notes to reconcile against a live install

- Feature channel ranges are taken as canonical (`verticality` signed `[-1,1]`,
  the rest `[0,1]`). If the installed HarMoCAP source manifest declares different
  ranges, adjust each route's `scale_range.in` to match.
- The `max_rate`/velocity constants (`±22–30 deg/s`) are a starting point tuned
  for "visible but not frantic" (~12 s per full rotation); calibrate on the rig.

## Status

`v0.2` — 5 aggregators, 10 routes; compiles against the real weaver compiler.
The `phase_accumulator` transform is **merged** into `harmonic-weaver` (PR #1).
The `harmonic_envelope` capability is validated against a *synthesized* manifest
entry (the local rehearsal artifact predates it) — **confirm against the live
Shaper manifest** on first launch. Heartbeat is still a per-beat flash; a
`beat_envelope` transform would make it breathe.
