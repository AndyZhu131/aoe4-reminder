# AoE4 Reminder Implementation Plan

## Product Direction

Build a passive in-game overlay assistant for Age of Empires IV that helps players remember core macro actions during live play.

The first target user is the developer and their regular AoE4 group. The initial supported setup is:

- Resolution: 2560x1440
- UI scale: 100%
- Mode: live play only
- Input model: passive screen observation only
- Reminder style: small in-game overlay icons
- Detection style: icon matching for UI symbols and constrained number reading for numeric state

The app should behave like a lightweight reminder HUD, not a strategic coach. It should not read game memory, automate inputs, or interact with the game client.

## MVP Scope

### Included

- A transparent always-on-top overlay.
- Three calibrated screen regions:
  - resource and population counts,
  - age indicator and timer,
  - global research and production queue.
- Villager production reminder.
- Basic population cap reminder if number reading is reliable enough.
- Age-based common technology checklist.
- Manual override for tech reminders if automatic completion detection is uncertain.
- Local config files for calibration, templates, and reminder thresholds.

### Excluded For Now

- Army production reminders.
- Strategic coaching or army composition advice.
- Civilization-specific technology trees.
- Multi-resolution support beyond calibration.
- Replay analysis.
- Full automatic detection of every researched technology.

## Three Calibrated Regions

The first version should require calibration for only three rectangles.

```json
{
  "resolution": "2560x1440",
  "uiScale": "100%",
  "regions": {
    "resources": [0, 0, 0, 0],
    "ageAndTimer": [0, 0, 0, 0],
    "globalQueue": [0, 0, 0, 0]
  }
}
```

### 1. Resources

Used for:

- food,
- wood,
- gold,
- stone,
- current population,
- population cap.

Number reading should be smoothed over multiple frames instead of trusted frame-by-frame. Tesseract digit-only reading is acceptable for phase 1, but the long-term target should be a constrained digit reader or template-based digit matching if OCR proves noisy.

### 2. Age Indicator And Timer

Used for:

- current age,
- elapsed game time,
- timing gates for technology reminders.

Age should preferably be detected through icon/template matching. Timer may use constrained number reading if direct visual matching is not practical.

### 3. Global Queue

Used for:

- villager production icon detection,
- active research icon detection,
- future unit production icon detection.

This is the most important region for MVP reliability.

## Reminder Overlay Behavior

### Villager Icon

- Dim or neutral when villager production is detected.
- Bright/flashing when villager production appears idle.
- Small enough to stay visible during combat without demanding attention.
- No text required during normal play.

### Technology Icons

- Bright: technology is age-relevant and likely not completed.
- Dark: technology is done, dismissed, or no longer urgent.
- Hidden: technology chain is fully completed or irrelevant for the current phase.

Because the global queue only reveals active research, not all completed research, v1 should use a hybrid state model:

```text
unknown -> due -> researching_seen -> assumed_done -> hidden_or_dimmed
```

Manual mark-done or dismiss controls should be available in overlay edit mode.

## Initial Reminder Logic

### Villager Production

Trigger the villager reminder when:

```text
food >= 50
AND current_population < population_cap
AND villager icon is not detected in the global queue
AND missing-villager state has persisted for 8-12 seconds
AND the last villager reminder was more than 20-30 seconds ago
```

Important implementation details:

- Do not react to a single missed frame.
- Use confidence thresholds for template matching.
- Keep a short rolling history of detections.
- Allow thresholds to be tuned in config.

### Population Cap

Trigger only if the number reader can confidently read population:

```text
current_population >= population_cap
OR population_cap - current_population <= configured_warning_margin
```

This should be secondary to the villager reminder.

### Technology Checklist

Start with generic technologies common across civilizations.

Example categories:

- economy upgrades,
- Wheelbarrow,
- blacksmith upgrades,
- age-tier economy upgrades.

The first version should not try to perfectly infer every available tech from buildings. Instead, use:

- current age,
- game timer,
- configured reminder timings,
- research icon detection in the global queue,
- optional manual completion.

## Architecture

```text
Capture
  screen/window frame capture
  calibrated region cropper

Vision
  OpenCV template matching
  constrained number reading for resource/pop/timer numbers
  confidence scoring
  rolling state smoothing

State
  current game age
  game timer
  resources
  population
  global queue icons
  technology reminder states

Reminder Engine
  villager production rule
  population cap rule
  technology timing rules
  cooldowns
  dismiss/snooze state

Overlay
  always-on-top transparent window
  click-through normal mode
  editable mode behind a hotkey
  calibration mode behind a hotkey
```

## Suggested Prototype Stack

Start with the fastest detection loop.

- Python
- OpenCV
- `mss` or another Windows screen capture library
- Tesseract digit-only reading for phase 1 numeric fields, with template-based digit reading as a likely replacement if needed
- PyQt/PySide for a first overlay, or Electron later if the UI needs polish

The first goal is detection reliability, not packaging.

## Milestones

### Milestone 1: Screenshot Detection Lab

- Capture representative 2560x1440 screenshots from live games.
- Manually crop the three target regions.
- Collect villager queue icon templates.
- Test template matching against the global queue region.
- Test constrained number reading against resources and population.
- Output a JSON state estimate for each screenshot.

Success condition:

- Villager icon detection is stable on screenshots from multiple matches.

### Milestone 2: Live Capture Debugger

- Capture the live screen at 1-3 FPS.
- Apply calibrated crops.
- Display a debug window with:
  - cropped regions,
  - detected icons,
  - number-reader output,
  - confidence values.
- Log state changes to a local file.

Success condition:

- The app can observe live play without meaningful performance impact.

### Milestone 3: Villager Overlay MVP

- Add the transparent overlay.
- Render one villager reminder icon.
- Flash the icon only when the villager rule triggers.
- Add cooldown and smoothing.
- Add config values for timing thresholds.

Success condition:

- During live play, the villager reminder correctly flashes when villager production is missed and stays quiet when villagers are queued.

### Milestone 4: Tech Checklist MVP

- Add a small row or column of common tech icons.
- Add age and timer based visibility rules.
- Detect research icons when they appear in the global queue.
- Mark techs assumed done after their research duration.
- Add manual mark-done/dismiss in overlay edit mode.

Success condition:

- The overlay gives useful, low-noise reminders for common age-relevant technologies.

### Milestone 5: Calibration UI

- Add a calibration mode for selecting the three regions.
- Save region coordinates to local JSON.
- Show live previews of the selected regions.
- Validate that the selected regions match the expected resolution.

Success condition:

- A user can recalibrate the supported setup without editing JSON manually.

## Data Files

Recommended initial structure:

```text
config/
  calibration.2560x1440.json
  reminders.json

templates/
  queue/
    villager.png
  age/
    dark.png
    feudal.png
    castle.png
    imperial.png
  tech/
    wheelbarrow.png
    double_broadaxe.png
    horticulture.png
    specialized_pick.png

data/
  technologies.json
```

## Success Metrics

- Villager reminder precision is high enough that it does not feel annoying.
- Reminder latency is under 5 seconds after the configured idle threshold.
- Number-reader errors are smoothed so single-frame mistakes do not trigger reminders.
- Overlay remains small and readable during combat.
- The app stays passive and does not automate gameplay.

## Open Questions

- Which exact villager icon should be used for template matching in the global queue?
- Does the global queue visually distinguish multiple simultaneous villager queues clearly enough?
- Can population number reading be made reliable at 2560x1440 and 100% UI scale?
- Should tech completion be mostly automatic, mostly manual, or hybrid?
- Which technology list should be included in the first shared crew version?

## Immediate Next Step

Build Milestone 1 before the full overlay:

1. Take 20-50 screenshots at the target resolution.
2. Save the three calibrated regions for each screenshot.
3. Test villager icon template matching in the global queue.
4. Test number reading for food and population.
5. Produce a small detection report showing hit rate, false positives, and failure cases.
