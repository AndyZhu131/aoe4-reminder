# Icon Templates

Put small cropped PNG templates here for phase 1 matching.

Suggested first template:

```text
templates/queue/villager.png
```

Capture a global queue crop with `python scripts/phase1_tool.py capture`, then crop the villager icon from that image and save it as the template.

Villager matching uses a mask over the top-left number area, so the template can contain a queue count as long as the stable villager artwork is visible.

Quick test:

```sh
python scripts/phase1_tool.py watch-villager --debug-images
```
