import json
import os
import time
import uuid
from pathlib import Path


OVERLAY_AGES = ("unknown", "age_1", "age_2", "age_3", "age_4")
OVERLAY_VILLAGER_STATES = ("unknown", "active", "idle")


def parse_technology_keys(value):
    if not value:
        return []
    return [key.strip() for key in value.split(",") if key.strip()]


def write_overlay_state(
    output_path,
    *,
    civilization="sis",
    age="unknown",
    villager_production_active=None,
    villager_reminder=None,
    researched_technologies=None,
    in_progress_technologies=None,
    detected_technologies=None,
    available_technologies=None,
    locked_technologies=None,
    reminders_paused=False,
    session=None,
):
    state = {
        "version": 1,
        "civilization": civilization,
        "age": age,
        "villagerProductionActive": villager_production_active,
        "villagerReminder": villager_reminder,
        "researchedTechnologies": researched_technologies or [],
        "inProgressTechnologies": in_progress_technologies or [],
        "detectedTechnologies": detected_technologies or [],
        "remindersPaused": reminders_paused,
    }
    if available_technologies is not None:
        state["availableTechnologies"] = available_technologies
    if locked_technologies is not None:
        state["lockedTechnologies"] = locked_technologies
    if session is not None:
        state["session"] = session

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        for attempt in range(4):
            try:
                os.replace(temporary_path, output_path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.025 * (attempt + 1))
    finally:
        temporary_path.unlink(missing_ok=True)
    return state


def command_write_overlay_state(args):
    villager_active = {
        "unknown": None,
        "active": True,
        "idle": False,
    }[args.villager_production]
    state = write_overlay_state(
        args.output,
        civilization=args.civilization,
        age=args.age,
        villager_production_active=villager_active,
        researched_technologies=args.researched,
        in_progress_technologies=args.in_progress,
    )
    print(json.dumps({"output": str(args.output), "state": state}, indent=2))
    return 0
