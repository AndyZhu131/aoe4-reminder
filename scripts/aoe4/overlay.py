import json
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
    researched_technologies=None,
    in_progress_technologies=None,
    session=None,
):
    state = {
        "version": 1,
        "civilization": civilization,
        "age": age,
        "villagerProductionActive": villager_production_active,
        "researchedTechnologies": researched_technologies or [],
        "inProgressTechnologies": in_progress_technologies or [],
    }
    if session is not None:
        state["session"] = session

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(output_path)
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
