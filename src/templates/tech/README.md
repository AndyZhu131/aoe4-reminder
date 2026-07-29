# Research Templates

Put cropped active-research queue icons here. The detector scans both rows of
the calibrated `globalQueue` region and classifies every matching template from
`data/technologies.json`.

Current SIS folders:

```text
src/templates/tech/economy/age1/
src/templates/tech/economy/age2/
src/templates/tech/military/age2/
```

The catalog records a `civilization` for every technology. The current set is
`sis`. To add a future civilization, use a civilization-first namespace:

```text
src/templates/tech/<civilization>/economy/ageN/<icon>.png
src/templates/tech/<civilization>/military/ageN/<icon>.png
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

Crop only the icon tile from the saved queue image, excluding surrounding HUD
background, borders, and queue-count text. Save it to the catalog path, for
example:

```text
src/templates/tech/economy/age1/wheelbarrow.png
src/templates/tech/military/age2/blacksmith_melee_attack_1.png
```

Research can occupy either queue row when production is empty. The recognizer
searches the full research-queue crop and does not depend on hard-coded icon
slots. If two templates overlap the same visible icon, it retains the
highest-confidence classification.
