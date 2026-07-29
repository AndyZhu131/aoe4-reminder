# AoE4 Reminder App Spec

## 1. Product Intent

Build an in-game assistant for Age of Empires IV that helps players maintain core macro habits without playing the game for them.

The assistant observes the game screen, identifies production and upgrade states through OCR and visual icon analysis, and fires concise reminders when the player likely missed an important action.

Primary examples:

- Keep villagers producing from Town Centers.
- Keep military production buildings active.
- Track common economy, blacksmith, and age-specific technologies.
- Warn when the player has resources, production capacity, or idle buildings but no matching queue activity.

The app should feel like a coach and tracker, not an automation tool.

## 2. Target User

Primary user: competitive or improving AoE4 players who understand basic macro goals but forget them under pressure.

Secondary user: newer players who want structured reminders for build-order fundamentals.

The assistant should be most useful during live games, replays, or training sessions. The MVP should prioritize live-game reminders.

## 3. Core Problem

Players lose games because attention collapses under pressure:

- Town Centers stop producing villagers.
- Military buildings sit idle.
- Upgrade timings are forgotten.
- Economy floats resources without converting them into production.
- Players miss repeatable macro actions while microing fights.

The app reduces attention tax by detecting common omissions and nudging the player at the right moment.

## 4. Product Principles

- Low interruption: reminders should be brief, sparse, and confidence-gated.
- Explainable: each reminder should be tied to a visible reason.
- Configurable: players should tune reminders by skill level, civilization, strategy, and game phase.
- Non-invasive: no game-memory reading, input automation, or hidden game interaction.
- Patch-resilient: visual templates and technology catalogs should be data-driven.
- Multiplayer-safe: avoid features that could reasonably be considered automation or unfair play.

## 5. MVP Scope

### Included

- Windows desktop app.
- Screen/window capture for AoE4.
- Configurable capture regions for common resolutions and UI scale settings.
- Reminder overlay or desktop notification layer.
- Visual/icon detection for production queues and technology states.
- OCR for readable UI text where useful.
- Manual game phase selection as a fallback.
- Reminder rules for:
  - villager production,
  - idle Town Center,
  - idle military production buildings,
  - common economy technologies,
  - common blacksmith upgrades,
  - housed / near-pop-cap warnings if detectable.
- Session timeline of reminders and detected states.
- Basic confidence/debug view showing what the app thinks it sees.

### Excluded From MVP

- Build-order coaching for every civilization.
- Full strategic recommendation engine.
- Reading game memory or network packets.
- Automated clicks, hotkeys, or queueing.
- Perfect support for every resolution and UI scale on day one.
- Voice assistant.
- Multiplayer opponent scouting analysis.

## 6. User Experience

### First Run

1. User launches app.
2. App asks for capture permission if needed.
3. User selects the AoE4 window or monitor.
4. App asks for UI scale/resolution or auto-detects it.
5. App shows a calibration preview with highlighted regions.
6. User chooses reminder profile:
   - Beginner,
   - Ranked Macro,
   - Build Order Practice,
   - Custom.

### In Game

The app runs quietly while observing:

- current age,
- selected/candidate civilization if detectable,
- Town Center queue state,
- villager production state,
- military production building state,
- relevant technology icons,
- population/resource cues when available.

Reminder examples:

- "Town Center idle: queue villagers."
- "Barracks idle and you have food/gold."
- "Consider Wheelbarrow soon."
- "Blacksmith upgrades missing for current army type."

### After Game

The app shows a simple session review:

- reminder count by category,
- longest villager production gap,
- production idle periods,
- technologies remembered/missed,
- false-positive correction options.

## 7. Detection Strategy

The app should combine three signal types.

### 7.1 Screen Capture

Capture the AoE4 window or selected monitor at a low frame rate, likely 1-3 FPS for MVP.

Higher frame rates are not necessary for macro reminders and increase CPU/GPU cost.

### 7.2 Visual Icon Recognition

Use icon/template matching or a lightweight computer-vision model for:

- Town Center icon,
- villager icon,
- military building icons,
- unit queue slots,
- technology icons,
- researched/unresearched visual states,
- age icons,
- pop-cap warning state.

This should be the primary signal for icons because OCR is unreliable on small stylized UI elements.

### 7.3 OCR

Use OCR for:

- resource numbers,
- population numbers,
- selected building names,
- technology names in tooltips if the user hovers,
- scoreboard/session metadata if needed.

OCR should not be the only production detection method.

## 8. Reminder Engine

The reminder engine should operate on inferred game state, not raw pixels.

Example state model:

```text
GameState
  timestamp
  phase: dark_age | feudal_age | castle_age | imperial_age | unknown
  civ: known | unknown
  resources: food, wood, gold, stone, unknown
  population: current, cap, unknown
  town_centers[]
    detected
    producing_villager
    queue_count
    confidence
  production_buildings[]
    type
    active
    queue_count
    confidence
  technologies[]
    key
    available
    researched
    in_progress
    confidence
```

Rules should include:

- cooldowns,
- confidence thresholds,
- game-phase gates,
- resource gates,
- suppression windows after a reminder fires,
- user dismiss/snooze support.

Example villager rule:

```text
IF age is known or unknown
AND at least one Town Center is detected
AND no Town Center is producing villagers
AND player is not housed
AND confidence >= threshold
AND last villager reminder was more than N seconds ago
THEN remind "Town Center idle: queue villagers."
```

## 9. Technology Tracker

Technologies should be stored in a versioned data catalog rather than hard-coded in app logic.

Initial common tracker categories:

- Economy:
  - Wheelbarrow,
  - survival/economy upgrades,
  - lumber, mill, and mining upgrades.
- Military:
  - blacksmith attack upgrades,
  - blacksmith armor upgrades,
  - university upgrades when relevant.
- Production and utility:
  - siege/production-enabling upgrades,
  - monastery/religious upgrades if strategy profile enables them.
- Civilization-specific:
  - disabled in MVP unless data is easy to maintain.

Each technology entry should define:

```text
Technology
  key
  display_name
  category
  age_available
  building
  icon_template
  reminder_profiles
  prerequisites
  civ_scope
  priority
```

## 10. Suggested Architecture

```text
Desktop App
  Capture Service
    window selection
    frame sampling
    region extraction

  Vision Pipeline
    template matching
    OCR
    confidence scoring
    state smoothing

  Game State Store
    current inferred state
    recent history
    session timeline

  Reminder Engine
    rules
    cooldowns
    profiles
    false-positive suppression

  UI
    overlay/reminders
    calibration
    settings
    debug view
    post-game summary

  Data Catalog
    icon templates
    technology metadata
    civilization profiles
    resolution/UI layouts
```

## 11. Candidate Tech Stack

Recommended MVP stack:

- Language: Python or TypeScript.
- Capture:
  - Python: `mss`, Windows Graphics Capture wrappers, or OpenCV-compatible capture.
  - TypeScript: Electron plus native capture APIs.
- Vision: OpenCV.
- OCR: Tesseract, EasyOCR, PaddleOCR, or Windows OCR.
- UI:
  - Electron/React for a polished desktop app,
  - or Python + Qt for a faster prototype.
- Storage: local JSON or SQLite.
- Config/catalog: JSON or YAML.

Best first prototype path:

1. Python proof of concept for capture, template matching, and OCR.
2. Validate detection reliability on screenshots and short recordings.
3. Move to Electron/React only after detection proves viable.

## 12. Data Collection Plan

The hardest part is reliable detection, so collect examples early.

Needed assets:

- screenshots for each age,
- common resolutions,
- different UI scale settings,
- multiple civilizations,
- Town Center idle vs producing,
- production buildings idle vs active,
- technology available/researched/in-progress,
- housed and near-housed states,
- high-action game states with clutter.

For each screenshot, store:

```text
image_path
game_version
resolution
ui_scale
civilization
age
labels
notes
```

## 13. Success Metrics

MVP success:

- Detect villager production idle state with at least 90% precision in tested layouts.
- Reminder latency under 5 seconds.
- False reminders are rare enough that users keep the app enabled.
- CPU/GPU usage stays modest during live play.
- User can calibrate a new resolution/UI scale in under 2 minutes.

Product success:

- User reduces villager idle gaps across a session.
- User researches key technologies closer to intended timings.
- User reports reminders feel helpful instead of distracting.

## 14. Risks

- OCR may fail on small UI text, stylized fonts, motion blur, or scaling.
- Icon templates may break after patches or UI setting changes.
- False positives may annoy users quickly.
- Overlay behavior may conflict with fullscreen modes.
- Some competitive communities may consider real-time assistance controversial.
- Civilization-specific technology tracking can become a maintenance burden.

Mitigations:

- Prefer visual detection over OCR for icons.
- Keep catalogs/versioning separate from code.
- Provide confidence thresholds and debug views.
- Support borderless/windowed mode first.
- Keep assistant informational and avoid automation.

## 15. Grilling Questions

These are the decisions that should be answered before implementation gets large.

1. Is the assistant intended for live ranked multiplayer, solo practice, replay review, or all three?
2. Are reminders allowed during multiplayer from a fairness/community perspective?
3. Should the app only remind about generic macro, or should it make strategic recommendations?
4. What is the first supported display setup: 1080p, 1440p, 4K, ultrawide, or all through calibration?
5. Will the user play in borderless windowed mode if fullscreen capture is unreliable?
6. Should the app detect all production buildings or start with Town Centers only?
7. Should military production reminders be based on selected buildings, visible control groups, or production UI only?
8. How should the app know the player's intended army composition?
9. Should technology reminders be generic or tied to a chosen build/strategy profile?
10. Should the app give audio reminders, visual overlay reminders, or both?
11. What false-positive rate is acceptable before the app becomes annoying?
12. Should users be able to mark a reminder as wrong to improve future detection?
13. How often should the app capture frames?
14. Should capture and detection run locally only?
15. How will icon templates and technology catalogs be updated after patches?

## 16. MVP Build Plan

### Milestone 1: Offline Detection Lab

- Collect 50-100 labeled screenshots.
- Build screen-region cropper.
- Implement template matching for Town Center/villager queue.
- Implement OCR test for resources and population.
- Output a JSON state estimate per screenshot.

### Milestone 2: Live Capture Prototype

- Capture AoE4 window at 1 FPS.
- Run detector continuously.
- Show debug overlay with confidence values.
- Log state changes to local file.

### Milestone 3: Villager Reminder MVP

- Add reminder rule engine.
- Add cooldowns and snooze.
- Fire only one reminder type: Town Center idle.
- Track reminder precision manually.

### Milestone 4: Production And Tech Tracker

- Add military production building detection.
- Add common technology catalog.
- Add session timeline and post-game summary.

### Milestone 5: Polished Desktop App

- Add calibration UI.
- Add profiles.
- Add settings.
- Add packaged installer.

## 17. Immediate Next Step

Start with an offline detection lab before building the full desktop app.

The first useful deliverable should be:

- a folder of labeled AoE4 screenshots,
- a detector script,
- a simple JSON output format,
- a measured accuracy report.

This proves whether OCR/icon detection is reliable enough before committing to a full overlay application.
