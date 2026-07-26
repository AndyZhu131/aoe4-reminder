# Research Templates

Put cropped active-research queue icons here. The detector scans the top half of
the calibrated `globalQueue` region and classifies every matching template from
`data/technologies.json`.

Initial folders:

```text
templates/tech/economy/
templates/tech/military/
```

Recommended capture flow:

```sh
python scripts/aoe4_assistant.py match-research --debug-images --show-missing-templates
```

Then crop one clean icon tile from `captures/research/research-*.png` and save
it to the catalog path, for example:

```text
templates/tech/economy/wheelbarrow.png
templates/tech/military/blacksmith_melee_attack_1.png
```

The first classifier is template-based. If two templates match the same visible
slot, the detector keeps the highest-confidence classification for that slot.
