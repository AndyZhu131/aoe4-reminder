# aoe4-reminder
OCR based aoe4 live reminder for in-game activities

## CLI

Use `src/backend/app/aoe4_assistant.py` as the command entry point:

```sh
python src/backend/app/aoe4_assistant.py --help
```

## Documentation

- [CLI manual](docs/CLI_MANUAL.md)
- [Project overview](docs/PROJECT_OVERVIEW.md)
- [Recognition logic](docs/RECOGNITION_LOGIC.md)
- [Reminder trigger logic](docs/REMINDER_LOGIC.md)
- [FAQ](docs/FAQ.md)

## Entry Points

- `src/backend/app/aoe4_assistant.py` launches the Python backend CLI.
- `src/frontend/main.cjs` launches the Electron desktop overlay.

The backend launcher is intentionally small. `src/backend/app/cli.py` registers
commands, while `src/backend/runtime/monitor.py` centrally coordinates readers and
applies reminder policy.

Start a queue capture session, then press `Ctrl+Alt+S` whenever the research
icon is ready to save:

```sh
python src/backend/app/aoe4_assistant.py capture-queue
```

The command saves the full queue image and an immediate `48 x 44` crop of the
top research slot under `captures/queue/`. When production is empty, use
`--research-row bottom` to extract the lower-row research icon.

For a one-shot capture with a short countdown, add `--once --delay 3`.

Capture the calibrated age icon and timer for reader examples:

```sh
python src/backend/app/aoe4_assistant.py capture-age
```

Press `Ctrl+Alt+S` to save each top-center HUD capture under `captures/age/`.
The automatic crop is the top 20% of the selected monitor and 100 px wide at
2048 px screen width. Use `--use-calibrated-region` to fall back to the saved
`ageAndTimer` rectangle.

Age recognition matches visual templates at the fixed Roman-numeral location
(`I` through `IV`) and falls back to OCR; timer recognition uses OCR inside this
crop. Run it against labeled captures named
`MM-SS-AGE.png`:

```sh
python src/backend/app/aoe4_assistant.py test-age
```

Read the current automatic top-center capture once:

```sh
python src/backend/app/aoe4_assistant.py watch-age --once
```

For a live recognition test, press `Ctrl+Alt+S` to capture and classify the
entire calibrated `globalQueue` region:

```sh
python src/backend/app/aoe4_assistant.py test-research-queue
```

Each press saves the queue capture and a labeled debug image under
`captures/research-queue/`.

Core backend modules live under `src/backend/`:

- `recognition/resources.py` reads the resource/population panel.
- `recognition/villager.py` detects villager production in the bottom half of `globalQueue`.
- `recognition/tech.py` classifies active research icons in either row of `globalQueue`.

## Overlay Prototype

The first desktop overlay lives under `src/frontend/`. It is a transparent,
always-on-top Electron rail. Drag the top control strip to position it; the
selected position is saved locally. The settings button contains resolution and
monitor selectors, position reset, and a `Recalibrate screen` action. The
1920x1080 and 3840x2160 calibration profiles are scaled from the 2560x1440
reference calibration and rebased to the selected monitor. That action launches
the existing calibration workflow after hiding the rail. `-` hides the rail and
`Ctrl+Alt+O` restores it. The `x` button closes the overlay process.

```sh
npm run dev
```

Opening the Electron overlay also starts the Python `watch-monitor` backend and
stops it when the overlay process closes. Its logs are forwarded to the Electron
console, so no separate monitor command is needed for normal use.

## Windows Installer

The distributable Windows installer bundles the Electron overlay, Python
backend, vision dependencies, and Tesseract OCR. Players do not need Python,
Node.js, or any OCR dependency installed. Build and clean-machine verification
steps are in [docs/RELEASING.md](docs/RELEASING.md).

The overlay polls `runtime/overlay-state.json` every half second. Copy
`runtime/overlay-state.example.json` to that path to try the visual state. Its
starting state is Age I at `00:00`, with Wheelbarrow active and common Feudal
technology previews muted. The current contract is:

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
python src/backend/app/aoe4_assistant.py watch-monitor
```

It begins with reminders disabled, anchors a monotonic local clock from the
recognized game timer, then validates that timer every five seconds. The
overlay advances that confirmed time locally between validations. A timer
mismatch keeps the current state while switching to one-second verification
checks. The monitor marks the game paused only after five matching frozen timer
reads within six samples; ordinary timer recovery needs three confirming reads
within five samples. Age is checked every five seconds, never moves backward,
and advances after a two-of-three majority vote from one-second confirmation
reads. The coordinator is the only backend-to-frontend bridge: it
writes `runtime/overlay-state.json`, which keeps recognition and reminder logic
out of Electron.

The central monitor owns cross-reader reminder policy. The villager recognizer
only reports whether an icon is queued. The villager alert appears before
`20:00` whenever no villager icon is queued.

Write a live test state without editing JSON manually:

```sh
python src/backend/app/aoe4_assistant.py overlay-state --age age_2 --villager-production idle --researched wheelbarrow --in-progress wood_1
```

The rail pulses a large villager icon only while villager production is idle.
The pause button suppresses urgency and flashing while recognition continues;
the reset button clears the current monitor session's timer, age, and technology
history.
  It renders only technologies unlocked by the detected age and their catalog
  prerequisites. Unresearched technologies carry forward through later ages;
  upgrade chains such as `wood_1` -> `wood_2` -> `wood_3` never skip a level.
  When the prior level is complete but the next age is not yet reached, the
  next-level icon stays visible as a muted preview and becomes a normal reminder
  when that age is confirmed.
  Catalog entries can also set `previewBeforeAge` for an opening-game preview;
  the SiS catalog uses this for the common Feudal upgrades shown muted in Age I.
  A technology is confirmed in progress after it appears in at least six of
  ten queue reads. It remains in progress for 30 seconds of game time, then is
  marked researched and removed from reminders. Game pauses do not consume this
  completion window.

Technology templates are classified by `civilization`, category, and age. The
current templates are `sis`; after adding or moving templates, refresh the
catalog with:

```sh
python src/backend/app/aoe4_assistant.py inject-technologies --civilization sis
```
