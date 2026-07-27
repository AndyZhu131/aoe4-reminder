# aoe4-reminder
OCR based aoe4 live reminder for in-game activities

## CLI

Use `scripts/aoe4_assistant.py` as the command entry point:

```sh
python scripts/aoe4_assistant.py --help
```

Start a queue capture session, then press `Ctrl+Alt+S` whenever the research
icon is ready to save:

```sh
python scripts/aoe4_assistant.py capture-queue
```

The command saves the full queue image and an immediate `48 x 44` crop of the
top research slot under `captures/queue/`. When production is empty, use
`--research-row bottom` to extract the lower-row research icon.

For a one-shot capture with a short countdown, add `--once --delay 3`.

For a live recognition test, press `Ctrl+Alt+S` to capture and classify the
entire calibrated `globalQueue` region:

```sh
python scripts/aoe4_assistant.py test-research-queue
```

Each press saves the queue capture and a labeled debug image under
`captures/research-queue/`.

Core vision modules live under `scripts/aoe4/`:

- `resources.py` reads the resource/population panel.
- `villager.py` detects villager production in the bottom half of `globalQueue`.
- `tech.py` classifies active research icons in either row of `globalQueue`.
