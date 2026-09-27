# Latido — setup & launch (compatible PC)

How to bring up the full **Latido** stack on a machine that can actually run it,
and how to prove it without hardware. The piece:

> Person A's **ECG heartbeat** pulses the beacon's master gain (the laser figure
> breathes); person B **dances** and HarMoCAP drives per-harmonic **phase** (the
> figure morphs) and **envelope** (the field sounds); a laser off a vibrating
> membrane throws the interference figure on the wall.

## 0. Hardware / OS requirements

The full live stack needs, at minimum:

- **Linux** remains the production target for the one-command launcher and the
  R24 audio path. A manual macOS stack was nevertheless proven live on an Intel
  Mac in July 2026 (C920e, CPU HarMoCAP, CoreAudio Shaper, laser output); the
  Linux launcher itself should not be assumed portable without checking its
  current audio-device commands.
- **NVIDIA GPU with CUDA 12** is recommended for the full HarMoCAP model and
  sustained performance. CPU operation is available for rehearsal and fallback
  (`--harmocap-device cpu`); use a lightweight HarMoCAP preset/model when needed.
- **SuperCollider** (`scsynth`/`sclang`) for beacon-spatial — optional for Latido
  if you launch with `--beacon-mute` or `--no-beacon`, but the launcher expects it
  present unless skipped.
- Python ≥ 3.11, `uv`, `git`. A webcam (the dancer) and the ECG rig (§4).

## 1. Clone the repos

The launcher resolves sibling repos under `~/Projects` by default:

```bash
mkdir -p ~/Projects && cd ~/Projects
git clone https://github.com/AlterMundi/harmonic-weaver
git clone https://github.com/AlterMundi/harmonic-shaper
git clone https://github.com/AlterMundi/beacon-spatial
git clone https://github.com/AlterMundi/HarMoCAP
git clone https://github.com/AnnieScigliano/latido
```

> **Keep harmonic-shaper and harmonic-weaver in sync.** The weaver's safety
> profile references shaper capabilities (`arp_*`, `harmonic_phase`, `master_gain`,
> …); a stale shaper manifest makes instrument install fail with
> `unknown capability shaper.<name>`. `git pull` both before a session.

If your repos are **not** under `~/Projects`, point the launcher at them:

```bash
export BEACON_DIR=/path/to/beacon-spatial
export SHAPER_DIR=/path/to/harmonic-shaper
export HARMOCAP_DIR=/path/to/HarMoCAP
```

## 2. Environments

```bash
# weaver
cd ~/Projects/harmonic-weaver && uv sync --extra rehearsal --extra test
# shaper
cd ~/Projects/harmonic-shaper && python3 -m venv .venv && .venv/bin/pip install -e .
# beacon-spatial + HarMoCAP: create their envs per each repo's README
#   (HarMoCAP needs the CUDA torch/ultralytics stack from its requirements.lock)
```

## 3. Wire the scene + safety profile

The launcher resolves `--scene latido` from `harmonic-weaver/rehearsal/scenes/`.
Symlink it so the single source of truth stays in this repo:

```bash
ln -sf ../../../latido/scenes/latido.scene.json \
   ~/Projects/harmonic-weaver/rehearsal/scenes/latido.scene.json
```

**Safety profile:** Latido drives `harmonic_phase` + `master_gain`; the Shaper
safety profile must reset those or the scene won't activate (`unsafe_instrument`).
Those defaults are present on current Weaver `main`.

## 4. The laser rig (physical, no software)

The laser figure is a physical consequence of the shaper's stereo output:

```
harmonic-shaper stereo out → sealed tube → balloon membrane + glued mirror → laser → wall
```

Route the shaper's audio out to the tube's speaker(s). On this membrane **phase =
figure shape, amplitude = size/brightness** — which is exactly how Latido maps
(movement → phase, heartbeat → master).

## 5. Launch

**Dry run first — no chest sensor, you're the dancer:**

```bash
cd ~/Projects/harmonic-weaver
scripts/start-live-stack.sh --scene latido --beacon-mute --with-ecg-sim
```

- `--beacon-mute` — only the shaper is audible (it feeds the laser).
- `--with-ecg-sim` — synthetic ~72 bpm heartbeat, to verify the master pulse
  before wiring the AD8232.
- Camera defaults to index 0 (`--camera <index|path>` to change).

**Watch for:** the figure is **lit** (H1–5 sounding from your movement energy),
**morphs** as you open / rise / turn (phase), and **breathes** ~72/min (master).

**Then the real heart** — wire the AD8232 + ESP32 to stream `/ecg/raw` to UDP
`:5001` (the weaver's ECG driver listens there), and drop `--with-ecg-sim`:

```bash
scripts/start-live-stack.sh --scene latido --beacon-mute
```

Logs land in `harmonic-weaver/rehearsal/artifacts/<run-id>/logs/`.
`scripts/start-live-stack.sh --stop latest` tears the tree down.

## 6. Prove it without hardware (works anywhere, incl. macOS)

Two levels, both offline:

```bash
cd ~/Projects/latido
python3 scripts/validate_scene.py         # compiles the scene vs the real shaper manifest
python3 scripts/latido_smoke.py            # runs the REAL engine headless with synthetic
                                           # HarMoCAP+ECG frames; asserts envelopes sound,
                                           # phase accumulates, master pulses ~72bpm
```

The smoke needs the weaver env on `PYTHONPATH`; run it with the weaver venv if
the imports aren't found:
`~/Projects/harmonic-weaver/.venv/bin/python scripts/latido_smoke.py`.

## 7. Calibration (first live session)

The starting numbers are guesses — tune on the rig:

- **Phase velocities** — `scale_range.out` on the four `*-to-h*-phase` routes
  (±22–30 deg/s). Higher = faster morph.
- **Envelope floors/ceilings** — the `sound-harmonic-*` routes; raise floors if
  the field is too quiet when the dancer is still.
- **Heartbeat depth** — `beat_envelope` `floor`/`peak` (0.8→1.0) on the master route.
- **Which harmonics the membrane shows** — the laser may favor certain partials;
  reweight envelope ranges accordingly.
- **Camera domain** — HarMoCAP wants a fixed, ~frontal view with the dancer's
  torso ≥ ~15% of frame; features degrade silently outside that.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `unknown capability shaper.<name>` on install | shaper clone stale — `git pull` harmonic-shaper |
| Scene won't activate: `unsafe_instrument` | Weaver/Shaper revisions are out of sync; update both and re-run the scene validator |
| `new scenes must start at scene_version 1` | scene_version must be `1` for a first push |
| Figure dark / silent | no focused dancer in frame (envelopes only sound while tracked); establish the camera view |
| HarMoCAP CUDA/ReID crash | `--harmocap-device cpu` fallback; the stack also has supervised GPU restart |
| Dancer leaves frame and audio latches | see the `--lease-ms` note in the launcher (live default is generous) |

## Layout recap

- **`scenes/latido.scene.json`** — the piece, as data (5 aggregators, 10 routes).
- **`scripts/validate_scene.py`** — compile-check against the real shaper manifest.
- **`scripts/latido_smoke.py`** — headless end-to-end proof.
- Engine transforms it depends on (`phase_accumulator`, `beat_envelope`) live in
  `harmonic-weaver` and are merged to `main`.
