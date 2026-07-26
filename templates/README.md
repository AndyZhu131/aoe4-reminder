# Icon Templates

Put small cropped PNG templates here for phase 1 matching.

Suggested first template:

```text
templates/queue/villager.png
```

Capture a global queue crop with `python scripts/aoe4_assistant.py capture`, then crop a clean villager queue tile with no count number and save it as the template. The template must include the dark-blue queue-tile background as well as the villager artwork.

Villager matching masks the top-left queue-count area in the live image. Its default threshold is `0.85`, and it checks a small range of template sizes to tolerate minor capture differences.

Before matching the villager artwork, the reader checks the fixed dark-blue production-card slots. A candidate must also contain enough gold/beige portrait pixels in both upper halves of the card, which represents the two-person villager artwork. This keeps terrain, empty dark-blue backgrounds, and orange military queue cards out of the villager comparison.

The calibrated global queue contains research and production. Villager detection reads only its bottom half, which contains the production queue.

Research detection reads the top half of the same calibrated `globalQueue` region. Unlike villager detection, it scans a catalog of economy and military technology templates and returns every active research icon it can classify. The catalog lives at:

```text
data/technologies.json
```

The templates live under:

```text
templates/tech/
```

Quick test:

```sh
python scripts/aoe4_assistant.py watch-villager --debug-images
python scripts/aoe4_assistant.py match-research --debug-images --show-missing-templates
```
