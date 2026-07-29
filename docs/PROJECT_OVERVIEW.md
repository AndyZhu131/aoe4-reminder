# Project Overview

## Purpose

AoE4 Reminder is a Windows overlay assistant for Age of Empires IV. It captures
small HUD regions, uses template matching and OCR to infer game state, and
shows reminders for villager production and common research technologies.

It is a screen-reading tool only: it does not read game memory, control the
game, or inspect replays.

## Quick Orientation

```text
src/
  backend/       Python capture, recognition, monitoring, and build code
  frontend/      Electron overlay application
  templates/     Age, villager, and research icon reference images
  tests/         Python tests and image fixtures
  requirements*.txt  Python runtime and release-build dependencies

config/          Per-resolution calibration profiles
data/            Technology catalog and resolution profiles
sound/            Optional villager reminder sounds
captures/         Local captures and debug-event output (not committed)
runtime/          Overlay state and controls written during development
docs/             User, developer, and logic documentation
```

## Backend (`src/backend`)

| Folder | Responsibility |
| --- | --- |
| `app/` | CLI entry point and command registration. Start with `app/aoe4_assistant.py` and `app/cli.py`. |
| `recognition/` | Reads the HUD: `ageAndTimer.py`, `villager.py`, `tech.py`, and `resources.py`. |
| `runtime/` | Coordinates live state and reminder policy. `monitor.py` is the main backend loop; `apm.py` tracks input activity. |
| `calibration/` | UI workflow for choosing capture regions. |
| `catalog/` | Creates and updates the technology catalog from templates. |
| `shared/` | Capture utilities, scaling, file paths, and reusable helpers. |
| `build/` | PyInstaller backend build and Electron installer launcher. |

The main backend command is:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py --help
```

## Frontend (`src/frontend`)

- `main.cjs`: Electron process, overlay window, settings, backend process
  launch, and packaged-versus-development paths.
- `renderer/`: Overlay HTML, styling, and interaction behavior.
- `preload.cjs`: Safe bridge between Electron and the overlay UI.
- `developer-console.*`: The in-app diagnostic window.
- `package.json`: Frontend dependencies plus build and installer configuration.

Run the source overlay from the repository root with:

```powershell
npm.cmd run dev
```

## State Flow

```text
screen capture
  -> recognition readers
  -> runtime/monitor.py
  -> runtime/overlay-state.json
  -> Electron overlay
```

The monitor owns confirmation windows, age progression, timer pause detection,
technology state, villager reminder decisions, and debug-event saves. Individual
recognizers should report what they see rather than decide whether to fire a
reminder.

## Important Assets and Data

- `config/calibration.*.json`: Capture rectangles for each resolution profile.
- `data/technologies.json`: Tracked technology keys, age requirements,
  prerequisites, categories, and template paths.
- `data/resolution-profiles.json`: Resolution multipliers used for captures and
  template scaling.
- `src/templates/`: The actual image templates used by age, villager, and
  research recognition.
- `captures/debug-events/`: Saved false-positive investigation material from a
  development live session.

## Useful Reading Order

For a new contributor or an AI handoff, read these in order:

1. This file.
2. [Recognition logic](RECOGNITION_LOGIC.md).
3. [Reminder trigger logic](REMINDER_LOGIC.md).
4. `src/backend/runtime/monitor.py` for the live coordinator.
5. `src/frontend/main.cjs` for the backend-to-overlay integration.

Use [FAQ.md](FAQ.md) for known limitations and common setup problems, and
[CLI_MANUAL.md](CLI_MANUAL.md) for commands.
