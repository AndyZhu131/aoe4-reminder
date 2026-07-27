# aoe4-reminder
OCR based aoe4 live reminder for in-game activities

## CLI

Use `scripts/aoe4_assistant.py` as the command entry point:

```sh
python scripts/aoe4_assistant.py --help
```

Start a queue capture session, then press `Ctrl+Alt+S` whenever the research
icon is ready to save:

```sh
python scripts/aoe4_assistant.py capture-queue
```

The command saves the full queue image and an immediate `48 x 44` crop of the
top research slot under `captures/queue/`. When production is empty, use
`--research-row bottom` to extract the lower-row research icon.

For a one-shot capture with a short countdown, add `--once --delay 3`.

Capture the calibrated age icon and timer for reader examples:

```sh
python scripts/aoe4_assistant.py capture-age
```

Press `Ctrl+Alt+S` to save each top-center HUD capture under `captures/age/`.
The automatic crop is the top 20% of the selected monitor and 100 px wide at
2048 px screen width. Use `--use-calibrated-region` to fall back to the saved
`ageAndTimer` rectangle.

Age recognition OCRs the fixed Roman-numeral location (`I` through `IV`) and
timer location inside this crop. Run it against labeled captures named
`MM-SS-AGE.png`:

```sh
python scripts/aoe4_assistant.py test-age
```

Read the current automatic top-center capture once:

```sh
python scripts/aoe4_assistant.py watch-age --once
```

For a live recognition test, press `Ctrl+Alt+S` to capture and classify the
entire calibrated `globalQueue` region:

```sh
python scripts/aoe4_assistant.py test-research-queue
```

Each press saves the queue capture and a labeled debug image under
`captures/research-queue/`.

Core vision modules live under `scripts/aoe4/`:

- `resources.py` reads the resource/population panel.
- `villager.py` detects villager production in the bottom half of `globalQueue`.
- `tech.py` classifies active research icons in either row of `globalQueue`.

## Overlay Prototype

The first desktop overlay lives under `frontend/`. It is a transparent,
always-on-top Electron rail. Drag the top control strip to position it; the
selected position is saved locally. The settings button contains the persistent
`Flash` preference, position reset, and a `Recalibrate screen` action. That
action launches the existing calibration workflow after hiding the rail. `-`
hides the rail and `Ctrl+Alt+O` restores it. The `x` button closes the overlay
process.

```sh
cd frontend
npm install
npm run dev
```

The overlay polls `runtime/overlay-state.json` every half second. Copy
`runtime/overlay-state.example.json` to that path to try the visual state. The
current contract is:

```json
{
  "civilization": "sis",
  "age": "age_2",
  "villagerProductionActive": false,
  "researchedTechnologies": ["wheelbarrow"],
  "inProgressTechnologies": ["wood_1"]
}
```

To drive the overlay from the live readers, start the session coordinator:

```sh
python scripts/aoe4_assistant.py watch-session
```

It begins with reminders disabled, anchors a monotonic local clock from the
recognized game timer, then validates that timer every five seconds. A timer
mismatch disables queue recognition and switches to one-second checks. After
five consecutive mismatches the session is treated as paused; a later advancing
timer resumes recognition and re-anchors the local clock. The coordinator is
the only backend-to-frontend bridge: it writes `runtime/overlay-state.json`,
which keeps recognition and reminder logic out of Electron.

Write a live test state without editing JSON manually:

```sh
python scripts/aoe4_assistant.py overlay-state --age age_2 --villager-production idle --researched wheelbarrow --in-progress wood_1
```

The rail pulses a large villager icon only while villager production is idle.
It renders common technology icons whose `ageAvailable` value is at or below
the detected age, excluding any keys listed as researched. The current vision
commands do not yet maintain a researched-technology history; a future state
watcher will populate that field.

Technology templates are classified by `civilization`, category, and age. The
current templates are `sis`; after adding or moving templates, refresh the
catalog with:

```sh
python scripts/aoe4_assistant.py inject-technologies --civilization sis
```
