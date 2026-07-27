# Research Templates

Put cropped active-research queue icons here. The detector scans both rows of
the calibrated `globalQueue` region and classifies every matching template from
`data/technologies.json`.

Initial folders:

```text
templates/tech/economy/
templates/tech/military/
```

Recommended capture flow:

```sh
python scripts/aoe4_assistant.py capture-queue
```

Press `Ctrl+Alt+S` to save the full queue and its top research tile. Use
`--research-row bottom` when production is empty and research has moved down.

For the current 2560x1440 calibration, keep at least one unit in production
while collecting templates. This keeps research in the first top queue tile,
so crop this fixed rectangle from the saved `globalQueue` image:

```text
x=10, y=8, width=48, height=44
```

Save the crop to the catalog path, for example:

```text
templates/tech/economy/wheelbarrow.png
templates/tech/military/blacksmith_melee_attack_1.png
```

When production is empty, research moves into the first production tile at
`x=10, y=66, width=48, height=44`; recognition handles that position too.
These coordinates apply only to this calibration and AoE4 UI scale.

The first classifier is template-based. If two templates match the same visible
slot, the detector keeps the highest-confidence classification for that slot.
