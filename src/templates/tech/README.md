# Research Templates

Put cropped active-research queue icons here. The detector scans both rows of
the calibrated `globalQueue` region and classifies every matching template from
`data/technologies.json`.

Current SIS folders:

```text
templates/tech/economy/age1/
templates/tech/economy/age2/
templates/tech/military/age2/
```

The catalog records a `civilization` for every technology. The current set is
`sis`. To add a future civilization, use a civilization-first namespace:

```text
templates/tech/<civilization>/economy/ageN/<icon>.png
templates/tech/<civilization>/military/ageN/<icon>.png
```

After adding or moving template files, regenerate the catalog:

```sh
python src/backend/app/aoe4_assistant.py inject-technologies --civilization sis
```

The injector derives category, age, and template path from the directory. It
preserves existing keys where a filename is already known and uses the filename
as the key for newly added technologies.

Recommended capture flow:

```sh
python src/backend/app/aoe4_assistant.py capture-queue
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
templates/tech/economy/age1/wheelbarrow.png
templates/tech/military/age2/blacksmith_melee_attack_1.png
```

When production is empty, research moves into the first production tile at
`x=10, y=66, width=48, height=44`; recognition handles that position too.
These coordinates apply only to this calibration and AoE4 UI scale.

The first classifier is template-based. If two templates match the same visible
slot, the detector keeps the highest-confidence classification for that slot.
