# FAQ

## Why does the villager reminder not know how many Town Centers I have?

The app is screen/OCR based. It only sees the global queue and determines
whether a villager portrait is currently present in the production row. It does
not read game memory, inspect selected buildings, or count Town Centers.

## Why can a reminder be one or two seconds late?

Screen capture, image processing, OCR, and confirmation windows all take time.
The queue is scanned once per second, and villager or research reminders also
require repeated evidence to avoid reacting to a single bad frame.

## Can recognition make mistakes?

Yes. This is visual recognition, so terrain, HUD effects, cursor overlap,
motion, low contrast, screen scaling, and unusual UI states can cause missed or
false matches. The app intentionally uses confirmation windows to trade a
little speed for fewer false reminders.

## Where can I find a capture for a false age-up or research detection?

During a live session with debug events enabled, look in:

```text
captures/debug-events/
```

Development runs write there in the repository. Installed builds write the
same `captures/debug-events/` structure under the app's user-data directory.
Age-up events include a matching JSON file; research-confirmed events include
the queue capture and annotation data. Send both the image and JSON when
reporting a problem.

## Why is a special civilization technology missing or incorrect?

The current catalog focuses on the tracked common economy and military
technologies. It is not a complete civilization-by-civilization technology
database. Special icons, unique upgrades, renamed upgrades, and different
artwork can be untracked or incorrectly matched until their templates and
catalog entries are added.

## Why is a normal technology still shown after I researched it?

The app does not directly observe technology completion. It confirms that the
icon has been in the queue, marks it in progress, then assumes completion after
30 seconds of active game time. Long researches, bonuses, or an incorrect icon
match can make this estimate wrong.

## Why is the overlay on the wrong monitor or in the wrong position?

Set the monitor and resolution in overlay settings, then use the position reset
or recalibration action. A calibration belongs to a specific monitor and
resolution profile; changing monitor configuration without recalibrating can
misalign captures.

## Why do captures not align after changing resolution or Windows display scaling?

The project supports 1920x1080, 2560x1440, and 3840x2160 profiles using scaled
calibration and template matching. This is an approximation, not a guarantee
for every display scale, HUD scale, aspect ratio, or multi-monitor arrangement.
Recalibrate after changing those settings.

## Why does `npm run dev` fail in PowerShell with an execution-policy error?

PowerShell can block `npm.ps1`. Run this from the repository root instead:

```powershell
npm.cmd run dev
```

The same applies to `npm.cmd run dist`.

## Why does PowerShell say `Unexpected token '&'`?

The `&` prefix belongs to PowerShell and cannot be used in Command Prompt or
the Electron developer console. In PowerShell:

```powershell
& "C:\Python313\python.exe" .\src\backend\app\aoe4_assistant.py --help
```

In Command Prompt, remove the `&`.

## Why does development OCR say Tesseract is missing?

The installed Windows app bundles Tesseract. Source development uses the local
Tesseract installation unless a path is passed with `--tesseract-cmd`. Install
Tesseract or pass the path to `tesseract.exe` explicitly.

## Why does a fresh match start with Age I and only Wheelbarrow active?

That is the intended conservative default state. The app waits for timer and
age evidence before enabling later age technologies and reminders.
