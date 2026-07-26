# aoe4-reminder
OCR based aoe4 live reminder for in-game activities

## CLI

Use `scripts/aoe4_assistant.py` as the command entry point:

```sh
python scripts/aoe4_assistant.py --help
```

Core vision modules live under `scripts/aoe4/`:

- `resources.py` reads the resource/population panel.
- `villager.py` detects villager production in the bottom half of `globalQueue`.
- `tech.py` classifies active research icons in the top half of `globalQueue`.
