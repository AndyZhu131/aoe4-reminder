# CLI Manual

Run backend commands from the repository root. In PowerShell, use:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py --help
```

In Command Prompt, omit the leading `&`.

## Common Commands

| Command | Purpose |
| --- | --- |
| `monitors` | List capture monitors visible to the backend. |
| `calibrate` | Select the resource panel, age/timer, and global queue regions. |
| `capture` | Save one calibrated region. |
| `capture-queue` | Save the global queue and one research-icon crop. |
| `capture-age` | Save the age/timer HUD area. |
| `watch-monitor` | Run the live coordinator used by the overlay. |
| `match-villager` | Run one villager-queue detection. |
| `match-research` | Run one research-queue detection. |
| `watch-age` | Repeatedly read age and timer. |
| `inject-technologies` | Refresh the technology catalog from template folders. |

## Setup and Calibration

List the available monitors:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py monitors
```

Calibrate monitor 1 for 2560x1440:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py calibrate --monitor 1 --output config\calibration.2560x1440.json
```

The overlay's settings action is the usual way to calibrate during normal use.

## One-Shot Captures

Capture the full calibrated global queue on monitor 2 at 1920x1080:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py capture-queue --monitor 2 --config config\calibration.1920x1080.json --template-resolution 1920x1080 --once --delay 3
```

Capture the age and timer HUD once:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py capture-age --monitor 1 --config config\calibration.2560x1440.json --once --delay 3
```

Without `--once`, capture sessions wait for `Ctrl+Alt+S` before saving each image.

## Recognition Tests

Run a single research match against a saved queue image:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py match-research --source-image captures\research-queue\globalQueue-example.png --template-resolution 2560x1440 --debug-images
```

Run a single villager match against a saved queue image:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py match-villager --source-image captures\queue\globalQueue-example.png --template-resolution 2560x1440
```

Run the live coordinator without the Electron overlay:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py watch-monitor --monitor 1 --template-resolution 2560x1440 --config config\calibration.2560x1440.json --debug-events
```

## Overlay and Release Commands

From the repository root:

```powershell
npm.cmd run dev
npm.cmd run build:backend
npm.cmd run dist
```

`npm.cmd` avoids the PowerShell execution-policy issue that can block `npm.ps1`.
`dev` starts the source version; `dist` creates the installer under
`release/<version>/`.

Use `--help` after any command for every available option, for example:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py watch-monitor --help
```
