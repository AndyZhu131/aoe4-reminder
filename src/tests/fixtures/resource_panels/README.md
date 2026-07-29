# Resource Panel Fixtures

These screenshots are fixed-resource-panel samples for tuning the phase 1 number reader.

The expected values live in `expected.json`.

Run a fixture manually:

```sh
python src/backend/app/aoe4_assistant.py watch-resources --source-image src/tests/fixtures/resource_panels/resource_panel_idle_1.png
```

Run all fixtures:

```sh
python src/backend/app/aoe4_assistant.py test-resources
```
