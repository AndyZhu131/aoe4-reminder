# Recognition Logic

The backend reads only configured HUD areas. It does not connect to Age of
Empires IV, inspect memory, or parse replay data.

## Age

- Captures the top-center age/timer area.
- Looks for the Roman numeral `I`, `II`, `III`, or `IV` in its fixed HUD
  location.
- For the compact calibrated layout, first normalizes and reads the inline
  glyph shapes.
- Otherwise uses edge-based template matching against the four age templates.
- Falls back to Tesseract OCR limited to `I` and `V` when template matching is
  not confident enough.
- Handles both normal timer placement and the lower timer placement used while
  aging up.

## Timer

- Reads the same top-center capture as age recognition.
- Uses Tesseract OCR restricted to digits and `:`.
- Tries the normal and age-up timer locations.
- If the raw timer read fails, applies a neutral-white mask, enlarges the
  image, and retries OCR with multiple thresholds and segmentation modes.

## Global Queue and Research

- Captures the full calibrated `globalQueue` region rather than fixed icon
  slots.
- Searches the whole queue because research can occupy either row when unit
  production is empty.
- Compares every enabled technology template against the queue at several
  resolution-scaled sizes.
- Uses masked `TM_CCOEFF_NORMED` template matching. The border mask and
  coefficient matching reduce background-driven matches.
- Uses a default similarity threshold of `0.80` for the supported resolution
  profiles and removes nearby duplicate detections.
- Writes a labeled match image when a command uses `--debug-images`; live
  event captures are controlled by `--debug-events`.

## Villager Queue

- Uses the bottom half of the global queue, which is the unit-production row.
- Looks for the villager portrait with a masked template match rather than OCR.
- Masks the tile border and production-count area so the portrait contributes
  more than queue numbers or frame decoration.
- Scales queue geometry and template sizes for the selected 1920x1080,
  2560x1440, or 3840x2160 profile.

## What Recognition Does Not Know

- The number of Town Centers or other production buildings.
- Whether a queued technology has actually finished; that is inferred by the
  reminder coordinator after a fixed game-time delay.
- Civilization-specific research that has no matching template in the catalog.
