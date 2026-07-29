import json
import shutil
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .age import load_monitor, read_age_roman, read_game_timer, resolve_age_timer_rect
from .common import (
    RESOLUTION_MULTIPLIERS,
    grab_region_bgr,
    load_json,
    load_region,
    parse_rect,
    parse_scales,
    resolution_multiplier,
    scale_pixels,
)
from .overlay import write_overlay_state
from .tech import (
    DEFAULT_TECH_CATALOG,
    DEFAULT_TECH_TEMPLATE_ROOT,
    crop_research_queue,
    default_research_threshold,
    load_technology_catalog,
    match_research_technologies,
    save_research_debug_image,
)
from .villager import (
    DEFAULT_VILLAGER_TEMPLATE,
    crop_production_queue,
    match_villager_icon,
)


VILLAGER_REMINDER_CUTOFF_SECONDS = 20 * 60
AGE_TIERS = {"age_1": 1, "age_2": 2, "age_3": 3, "age_4": 4}
TECH_AGE_TIERS = {"dark": 1, "feudal": 2, "castle": 3, "imperial": 4}
def timer_to_seconds(value):
    if value is None:
        return None
    minutes, seconds = value.split(":", 1)
    return int(minutes) * 60 + int(seconds)


def format_timer(value):
    if value is None:
        return None
    minutes, seconds = divmod(max(0, round(value)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def display_age(age):
    return age if age in AGE_TIERS else "age_1"


def scaled_template_scales(scales, resolution):
    multiplier = resolution_multiplier(resolution)
    return [round(scale * multiplier, 4) for scale in scales]


@dataclass
class TimerDecision:
    mode: str
    estimated_seconds: float | None
    mismatch_count: int
    reminders_enabled: bool


class TimerSynchronizer:
    """Run a smooth local timer and use OCR solely to confirm game pauses."""

    def __init__(self, pause_confirmation_checks=5, pause_confirmation_wins=3):
        self.pause_confirmation_checks = pause_confirmation_checks
        self.pause_confirmation_wins = pause_confirmation_wins
        self.anchor_game_seconds = None
        self.anchor_monotonic = None
        self.last_observed_seconds = None
        self.paused_seconds = None
        self.pause_observations = []
        self.mode = "starting"

    def estimated_seconds(self, now):
        if self.anchor_game_seconds is None:
            return None
        if self.mode == "paused":
            return self.paused_seconds
        return self.anchor_game_seconds + (now - self.anchor_monotonic)

    def _decision(self, mode, now, reminders_enabled):
        return TimerDecision(
            mode,
            self.estimated_seconds(now),
            len(self.pause_observations),
            reminders_enabled,
        )

    def _start_tracking(self, observed_seconds, now):
        self.anchor_game_seconds = observed_seconds
        self.anchor_monotonic = now
        self.last_observed_seconds = observed_seconds
        self.paused_seconds = None
        self.pause_observations = []
        self.mode = "tracking"
        return TimerDecision("tracking", observed_seconds, 0, True)

    def _start_pause_check(self):
        self.mode = "pause_checking"
        self.pause_observations = []

    def _record_pause_check(self, observed_seconds, now):
        self.pause_observations.append(observed_seconds)
        if len(self.pause_observations) < self.pause_confirmation_checks:
            return self._decision("pause_checking", now, True)

        matches = sum(
            observed == self.last_observed_seconds
            for observed in self.pause_observations
        )
        if matches >= self.pause_confirmation_wins:
            self.paused_seconds = self.last_observed_seconds
            self.anchor_game_seconds = self.paused_seconds
            self.anchor_monotonic = now
            self.pause_observations = []
            self.mode = "paused"
            return TimerDecision("paused", self.paused_seconds, self.pause_confirmation_checks, False)

        if observed_seconds is not None:
            self.last_observed_seconds = observed_seconds
        self.pause_observations = []
        self.mode = "tracking"
        return self._decision("tracking", now, True)

    def observe(self, observed_seconds, now):
        if self.anchor_game_seconds is None:
            if observed_seconds is None:
                return TimerDecision("starting", None, 0, False)
            return self._start_tracking(observed_seconds, now)

        if self.mode == "tracking":
            if observed_seconds is None:
                return self._decision("tracking", now, True)
            if observed_seconds == self.last_observed_seconds:
                self._start_pause_check()
                return self._decision("pause_checking", now, True)
            self.last_observed_seconds = observed_seconds
            return self._decision("tracking", now, True)

        if self.mode == "paused":
            if observed_seconds is None or observed_seconds <= self.paused_seconds:
                return TimerDecision(
                    "paused",
                    self.paused_seconds,
                    0,
                    False,
                )
            return self._start_tracking(observed_seconds, now)

        return self._record_pause_check(observed_seconds, now)


@dataclass
class AgeDecision:
    age: str
    pending: bool
    confirmation_count: int


class AgeProgression:
    """Accept only confirmed, one-age-at-a-time forward transitions."""

    def __init__(self, confirmation_checks, confirmation_wins):
        self.confirmation_checks = confirmation_checks
        self.confirmation_wins = confirmation_wins
        self.age = "age_1"
        self.confirmation = None

    def observe(self, detected_age):
        current_tier = AGE_TIERS[self.age]
        next_age = f"age_{current_tier + 1}"
        if next_age not in AGE_TIERS:
            return AgeDecision(self.age, False, 0)

        # A clear reading of the current age is evidence that a tentative
        # advance was a false positive. Unknown frames remain neutral.
        if self.confirmation is not None and detected_age == self.age:
            self.confirmation = None
            return AgeDecision(self.age, False, 0)

        if self.confirmation is None and detected_age != next_age:
            return AgeDecision(self.age, False, 0)

        if self.confirmation is None:
            self.confirmation = {
                "candidate": next_age,
                "observations": [],
                "votes": 0,
            }

        confirmation = self.confirmation
        confirmation["observations"].append(detected_age)
        if detected_age == confirmation["candidate"]:
            confirmation["votes"] += 1

        if len(confirmation["observations"]) < self.confirmation_checks:
            return AgeDecision(self.age, True, len(confirmation["observations"]))

        accepted_age = (
            confirmation["candidate"]
            if confirmation["votes"] >= self.confirmation_wins
            else None
        )
        self.confirmation = None
        if accepted_age:
            self.age = accepted_age
        return AgeDecision(self.age, False, 0)


class ResearchProgressTracker:
    """Confirm queued research, then complete it after a game-time delay."""

    def __init__(
        self,
        confirmation_checks,
        confirmation_wins,
        completion_delay_seconds,
    ):
        self.confirmation_checks = confirmation_checks
        self.confirmation_wins = confirmation_wins
        self.completion_delay_seconds = completion_delay_seconds
        self.researched = set()
        self.in_progress = set()
        self.observations = {}
        self.confirmed_at_game_seconds = {}

    def observe(self, detected_keys, game_seconds):
        detected = set(detected_keys)
        observed_keys = (
            set(self.observations) | self.in_progress | (detected - self.researched)
        )

        for key in observed_keys:
            observations = self.observations.setdefault(
                key,
                deque(maxlen=self.confirmation_checks),
            )
            observations.append(key in detected)
            if len(observations) < self.confirmation_checks:
                continue

            matches = sum(observations)
            if key in self.in_progress:
                confirmed_at = self.confirmed_at_game_seconds.get(key)
                if confirmed_at is None and game_seconds is not None:
                    self.confirmed_at_game_seconds[key] = game_seconds
                    confirmed_at = game_seconds
                if (
                    confirmed_at is not None
                    and game_seconds is not None
                    and game_seconds - confirmed_at >= self.completion_delay_seconds
                ):
                    self.in_progress.remove(key)
                    self.researched.add(key)
            elif matches >= self.confirmation_wins:
                self.in_progress.add(key)
                if game_seconds is not None:
                    self.confirmed_at_game_seconds[key] = game_seconds

        for key in tuple(self.observations):
            if key in self.researched:
                self.observations.pop(key, None)
                self.confirmed_at_game_seconds.pop(key, None)


def available_technology_keys(technologies, age, researched_keys):
    """Return unresearched catalog entries unlocked by age and prerequisites."""

    age_tier = AGE_TIERS.get(age, 0)
    researched = set(researched_keys)
    return [
        technology["key"]
        for technology in technologies
        if technology["key"] not in researched
        and TECH_AGE_TIERS.get(technology.get("ageAvailable"), 0) <= age_tier
        and set(technology.get("prerequisites", [])).issubset(researched)
    ]


def locked_technology_keys(technologies, age, researched_keys):
    """Preview selected opening upgrades and completed-chain upgrades before age unlock."""

    age_tier = AGE_TIERS.get(age, 0)
    researched = set(researched_keys)
    return [
        technology["key"]
        for technology in technologies
        if technology["key"] not in researched
        and TECH_AGE_TIERS.get(technology.get("ageAvailable"), 0) > age_tier
        and set(technology.get("prerequisites", [])).issubset(researched)
        and (technology.get("prerequisites") or technology.get("previewBeforeAge"))
    ]


def apply_technology_state(current_state, technologies, age, tracker):
    """Derive overlay fields from the recognized queue and catalog dependency graph."""

    current_state["researched_technologies"] = [
        technology["key"]
        for technology in technologies
        if technology["key"] in tracker.researched
    ]
    current_state["in_progress_technologies"] = [
        technology["key"]
        for technology in technologies
        if technology["key"] in tracker.in_progress
    ]
    current_state["available_technologies"] = available_technology_keys(
        technologies,
        age,
        tracker.researched,
    )
    current_state["locked_technologies"] = locked_technology_keys(
        technologies,
        age,
        tracker.researched,
    )


def age_reader_args(args):
    return SimpleNamespace(
        rect=args.age_rect,
        use_calibrated_region=True,
        config=args.config,
        monitor=args.monitor,
        age_scale=args.age_scale,
        timer_scale=args.timer_scale,
        tesseract_cmd=args.tesseract_cmd,
    )


def villager_reader_args(args):
    resolution_scale = resolution_multiplier(args.template_resolution)
    return SimpleNamespace(
        threshold=args.villager_threshold,
        scales=scaled_template_scales(args.villager_scales, args.template_resolution),
        queue_scale=resolution_scale,
        number_mask_ratio=args.number_mask_ratio,
        border_mask_ratio=args.villager_border_mask_ratio,
    )


def research_reader_args(args):
    resolution_scale = resolution_multiplier(args.template_resolution)
    return SimpleNamespace(
        threshold=(
            args.research_threshold
            if args.research_threshold is not None
            else default_research_threshold(args.template_resolution)
        ),
        scales=scaled_template_scales(args.research_scales, args.template_resolution),
        border_mask_ratio=args.research_border_mask_ratio,
        min_distance=scale_pixels(args.research_min_distance, resolution_scale, 1),
        max_detections=args.research_max_detections,
    )


def should_remind_villager(villager_queued, game_seconds):
    return (
        not villager_queued
        and game_seconds is not None
        and game_seconds < VILLAGER_REMINDER_CUTOFF_SECONDS
    )


class VillagerReminderTracker:
    """Require repeated missing-queue reads before alerting the player."""

    def __init__(self, required_misses=3):
        self.required_misses = required_misses
        self.consecutive_misses = 0

    def observe(self, villager_queued, game_seconds):
        if game_seconds is None or game_seconds >= VILLAGER_REMINDER_CUTOFF_SECONDS:
            self.consecutive_misses = 0
            return False
        if villager_queued:
            self.consecutive_misses = 0
            return False
        self.consecutive_misses += 1
        return self.consecutive_misses >= self.required_misses


def read_overlay_controls(path):
    """Read optional UI controls without interrupting the monitor loop."""

    try:
        controls = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"paused": False, "resetToken": None}
    return {
        "paused": controls.get("paused") is True,
        "resetToken": controls.get("resetToken"),
    }


def build_disabled_state(decision, age="age_1", reset_ready=False):
    return {
        "age": display_age(age),
        "villager_production_active": None,
        "villager_reminder": False,
        "researched_technologies": [],
        "in_progress_technologies": [],
        "detected_technologies": [],
        "available_technologies": [],
        "locked_technologies": [],
        "reminders_paused": False,
        "session": {
            "status": decision.mode,
            "estimatedTimer": format_timer(decision.estimated_seconds) or "00:00",
            "timerMismatchCount": decision.mismatch_count,
            "resetReady": reset_ready,
        },
    }


def publish_overlay_state(args, current_state):
    try:
        state = write_overlay_state(
            args.output,
            civilization=args.civilization,
            age=current_state["age"],
            villager_production_active=current_state["villager_production_active"],
            villager_reminder=current_state["villager_reminder"],
            researched_technologies=current_state["researched_technologies"],
            in_progress_technologies=current_state["in_progress_technologies"],
            detected_technologies=current_state["detected_technologies"],
            available_technologies=current_state["available_technologies"],
            locked_technologies=current_state["locked_technologies"],
            reminders_paused=current_state["reminders_paused"],
            session=current_state["session"],
        )
    except OSError as exc:
        print(f"overlay state publish failed: {exc}", flush=True)
        return
    print({"overlayState": state}, flush=True)


def save_debug_event(args, event, frame, metadata, annotated_frame=None):
    """Save the exact confirmed-event frame and its matching context."""
    import cv2

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    output_dir = Path(args.debug_event_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{event}-{timestamp}.png"
    metadata_path = output_dir / f"{event}-{timestamp}.json"
    if not cv2.imwrite(str(raw_path), frame):
        raise RuntimeError(f"could not save debug image: {raw_path}")

    artifacts = {"image": str(raw_path), "metadata": str(metadata_path)}
    if annotated_frame is not None:
        annotated_path = output_dir / f"{event}-{timestamp}-matches.png"
        save_research_debug_image(annotated_frame, metadata["researchResult"], annotated_path)
        artifacts["matches"] = str(annotated_path)

    metadata_path.write_text(
        json.dumps(
            {
                "event": event,
                "timestamp": timestamp,
                "artifacts": artifacts,
                **metadata,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"DEBUG_EVENT: event={event} image={raw_path}", flush=True)
    return artifacts


def clear_debug_events(output_dir):
    """Remove prior event diagnostics while keeping the output directory available."""

    output_path = Path(output_dir)
    if not output_path.exists():
        return 0
    if not output_path.is_dir():
        raise RuntimeError(f"debug event path is not a directory: {output_path}")

    removed = 0
    for child in output_path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def command_watch_monitor(args):
    if (
        args.timer_interval <= 0
        or args.pause_check_interval <= 0
        or args.queue_interval <= 0
    ):
        raise RuntimeError("timer, pause-check, and queue intervals must be greater than zero")
    if args.pause_confirmation_checks < 1:
        raise RuntimeError("pause confirmation checks must be at least one")
    if not 1 <= args.pause_confirmation_wins <= args.pause_confirmation_checks:
        raise RuntimeError("pause confirmation wins must fit within the check count")
    if args.age_interval <= 0 or args.age_confirmation_interval <= 0:
        raise RuntimeError("age intervals must be greater than zero")
    if args.age_confirmation_checks < 1:
        raise RuntimeError("age confirmation checks must be at least one")
    if not 1 <= args.age_confirmation_wins <= args.age_confirmation_checks:
        raise RuntimeError("age confirmation wins must fit within the check count")
    if args.research_confirmation_checks < 1:
        raise RuntimeError("research confirmation checks must be at least one")
    if not 1 <= args.research_confirmation_wins <= args.research_confirmation_checks:
        raise RuntimeError("research confirmation wins must fit within the check count")
    if args.research_completion_delay <= 0:
        raise RuntimeError("research completion delay must be greater than zero")

    age_args = age_reader_args(args)
    age_rect = resolve_age_timer_rect(age_args)
    calibration = load_json(Path(args.config)) or {}
    calibrated_monitor = int(calibration.get("monitor", 1))
    selected_monitor = args.monitor if args.monitor is not None else calibrated_monitor
    if (
        selected_monitor != calibrated_monitor
        and calibration.get("coordinateSpace") != "monitor"
    ):
        raise RuntimeError(
            f"selected monitor {selected_monitor} does not match calibration monitor "
            f"{calibrated_monitor}; recalibrate the selected monitor first"
        )
    monitor = load_monitor(selected_monitor)
    queue_rect = load_region(Path(args.config), "globalQueue", monitor)
    technologies, missing_templates = load_technology_catalog(
        Path(args.catalog),
        args.template_root,
        args.categories,
        [args.civilization],
    )
    synchronizer = TimerSynchronizer(
        args.pause_confirmation_checks,
        args.pause_confirmation_wins,
    )
    age_progression = AgeProgression(
        args.age_confirmation_checks,
        args.age_confirmation_wins,
    )
    research_tracker = ResearchProgressTracker(
        args.research_confirmation_checks,
        args.research_confirmation_wins,
        args.research_completion_delay,
    )
    villager_reminder_tracker = VillagerReminderTracker()
    last_reset_token = None
    next_timer_check = 0.0
    next_age_check = 0.0
    next_queue_check = float("inf")
    current_state = build_disabled_state(
        TimerDecision("starting", None, 0, False)
    )
    apply_technology_state(current_state, technologies, current_state["age"], research_tracker)

    print(
        f"Session watcher ready. Timer region {age_rect}; queue region {queue_rect}. "
        "Press Ctrl+C to stop.",
        flush=True,
    )
    if missing_templates:
        print(f"Warning: {len(missing_templates)} technology template(s) are missing.", flush=True)

    try:
        while True:
            now = time.monotonic()
            state_changed = False
            controls = read_overlay_controls(args.controls)
            if controls["resetToken"] is not None and controls["resetToken"] != last_reset_token:
                try:
                    cleared_debug_events = clear_debug_events(args.debug_event_dir)
                    print(
                        f"DEBUG_EVENTS: cleared={cleared_debug_events}",
                        flush=True,
                    )
                except (OSError, RuntimeError) as exc:
                    print(f"DEBUG_EVENTS_FAILED: clear error={exc}", flush=True)
                synchronizer = TimerSynchronizer(
                    args.pause_confirmation_checks,
                    args.pause_confirmation_wins,
                )
                age_progression = AgeProgression(
                    args.age_confirmation_checks,
                    args.age_confirmation_wins,
                )
                research_tracker = ResearchProgressTracker(
                    args.research_confirmation_checks,
                    args.research_confirmation_wins,
                    args.research_completion_delay,
                )
                villager_reminder_tracker = VillagerReminderTracker()
                next_timer_check = now
                next_age_check = now
                next_queue_check = float("inf")
                last_reset_token = controls["resetToken"]
                current_state = build_disabled_state(
                    TimerDecision("starting", None, 0, False),
                    reset_ready=True,
                )
                apply_technology_state(
                    current_state,
                    technologies,
                    current_state["age"],
                    research_tracker,
                )
                state_changed = True
                print({"control": "reset", "status": "handled"}, flush=True)

            if current_state["reminders_paused"] != controls["paused"]:
                was_paused = current_state["reminders_paused"]
                current_state["reminders_paused"] = controls["paused"]
                state_changed = True
                print(
                    {
                        "control": "pause",
                        "status": "paused" if controls["paused"] else "resumed",
                    },
                    flush=True,
                )
                if was_paused and not controls["paused"]:
                    next_timer_check = now
                    next_age_check = now
                    next_queue_check = now

            if controls["paused"]:
                if state_changed:
                    publish_overlay_state(args, current_state)
                if args.once:
                    return 0
                time.sleep(0.25)
                continue

            timer_due = now >= next_timer_check
            age_due = now >= next_age_check
            if timer_due or age_due:
                age_frame = grab_region_bgr(age_rect)
                if age_due:
                    previous_age = age_progression.age
                    detected_age, age_attempts = read_age_roman(age_frame, age_args)
                    age_decision = age_progression.observe(detected_age)
                    print(
                        "AGE: "
                        f"detected={detected_age or 'unknown'} "
                        f"accepted={age_decision.age} "
                        f"pending={age_decision.pending}",
                        flush=True,
                    )
                    if (
                        args.debug_events
                        and previous_age in AGE_TIERS
                        and AGE_TIERS.get(age_decision.age, 0) > AGE_TIERS.get(previous_age, 0)
                    ):
                        try:
                            save_debug_event(
                                args,
                                "age-up",
                                age_frame,
                                {
                                    "previousAge": previous_age,
                                    "detectedAge": detected_age,
                                    "acceptedAge": age_decision.age,
                                    "ageAttempts": age_attempts,
                                    "confirmationChecks": args.age_confirmation_checks,
                                    "confirmationWins": args.age_confirmation_wins,
                                },
                            )
                        except (OSError, RuntimeError, TypeError) as exc:
                            print(f"DEBUG_EVENT_FAILED: event=age-up error={exc}", flush=True)
                    next_age_check = now + (
                        args.age_confirmation_interval
                        if age_decision.pending
                        else args.age_interval
                    )
                    if synchronizer.mode in {"tracking", "pause_checking"}:
                        current_state["age"] = display_age(age_decision.age)
                        apply_technology_state(
                            current_state,
                            technologies,
                            current_state["age"],
                            research_tracker,
                        )
                        state_changed = True

                if timer_due:
                    detected_timer, _timer_attempts = read_game_timer(age_frame, age_args)
                    decision = synchronizer.observe(timer_to_seconds(detected_timer), now)
                    current_state = build_disabled_state(
                        decision,
                        age_progression.age,
                        reset_ready=last_reset_token is not None,
                    )
                    apply_technology_state(
                        current_state,
                        technologies,
                        current_state["age"],
                        research_tracker,
                    )
                    next_timer_check = now + (
                        args.timer_interval
                        if decision.mode == "tracking"
                        else args.pause_check_interval
                    )
                    if decision.reminders_enabled:
                        next_queue_check = now
                    else:
                        next_queue_check = float("inf")
                    state_changed = True
                    print(
                        {
                            "timer": detected_timer,
                            "estimatedTimer": format_timer(decision.estimated_seconds),
                            "status": decision.mode,
                            "timerMismatchCount": decision.mismatch_count,
                            "age": age_progression.age,
                        },
                        flush=True,
                    )

            if synchronizer.mode in {"tracking", "pause_checking"} and now >= next_queue_check:
                queue_frame = grab_region_bgr(queue_rect)
                research_frame = crop_research_queue(queue_frame)
                villager_result = match_villager_icon(
                    crop_production_queue(
                        queue_frame,
                        resolution_multiplier(args.template_resolution),
                    ),
                    Path(args.villager_template),
                    villager_reader_args(args),
                )
                research_result = match_research_technologies(
                    research_frame,
                    technologies,
                    research_reader_args(args),
                )
                current_state["detected_technologies"] = [
                    detection["key"] for detection in research_result["researching"]
                ]
                current_state["villager_production_active"] = villager_result["villagerQueued"]
                previous_villager_reminder = current_state["villager_reminder"]
                current_state["villager_reminder"] = villager_reminder_tracker.observe(
                    villager_result["villagerQueued"],
                    synchronizer.estimated_seconds(now),
                )
                if current_state["villager_reminder"] and not previous_villager_reminder:
                    print(
                        "VILLAGER_REMINDER: fired reason=no_villager_detected",
                        flush=True,
                    )
                elif previous_villager_reminder and not current_state["villager_reminder"]:
                    print("VILLAGER_REMINDER: cleared", flush=True)
                previous_in_progress = set(research_tracker.in_progress)
                research_tracker.observe(
                    (detection["key"] for detection in research_result["researching"]),
                    synchronizer.estimated_seconds(now),
                )
                confirmed_research = sorted(
                    research_tracker.in_progress - previous_in_progress
                )
                if args.debug_events and confirmed_research:
                    try:
                        save_debug_event(
                            args,
                            "research-confirmed",
                            queue_frame,
                            {
                                "confirmedResearch": confirmed_research,
                                "detectedResearch": [
                                    detection["key"]
                                    for detection in research_result["researching"]
                                ],
                                "researchResult": research_result,
                                "confirmationChecks": args.research_confirmation_checks,
                                "confirmationWins": args.research_confirmation_wins,
                                "estimatedTimer": format_timer(
                                    synchronizer.estimated_seconds(now)
                                ),
                            },
                            annotated_frame=research_frame,
                        )
                    except (OSError, RuntimeError, TypeError) as exc:
                        print(
                            f"DEBUG_EVENT_FAILED: event=research-confirmed error={exc}",
                            flush=True,
                        )
                apply_technology_state(
                    current_state,
                    technologies,
                    current_state["age"],
                    research_tracker,
                )
                for detection in research_result["researching"]:
                    print(
                        "TECH_DETECTED: "
                        f"key={detection['key']} "
                        f"score={detection['score']:.4f} "
                        f"position={detection['match']['x']},{detection['match']['y']}",
                        flush=True,
                    )
                print(
                    "TECH_SCAN: "
                    f"detected={len(research_result['researching'])} "
                    f"candidates={research_result['candidateCount']} "
                    f"threshold={research_result['threshold']:.2f} "
                    f"confirmed={','.join(sorted(research_tracker.in_progress)) or 'none'} "
                    f"researched={','.join(sorted(research_tracker.researched)) or 'none'}",
                    flush=True,
                )
                next_queue_check = now + args.queue_interval
                state_changed = True

            if state_changed:
                current_state["reminders_paused"] = controls["paused"]
                publish_overlay_state(args, current_state)

            if args.once:
                return 0

            sleep_until = min(
                next_timer_check,
                next_age_check,
                next_queue_check,
            )
            time.sleep(max(0.05, min(0.25, sleep_until - time.monotonic())))
    except KeyboardInterrupt:
        print("Stopped session watcher.", flush=True)
        return 0


def add_monitor_args(parser):
    parser.add_argument("--output", default="runtime/overlay-state.json")
    parser.add_argument("--controls", default="runtime/overlay-controls.json")
    parser.add_argument("--civilization", default="sis")
    parser.add_argument("--config", default="config/calibration.2560x1440.json")
    parser.add_argument("--age-rect", type=parse_rect)
    parser.add_argument("--monitor", type=int)
    parser.add_argument(
        "--template-resolution",
        choices=sorted(RESOLUTION_MULTIPLIERS),
        default="2560x1440",
    )
    parser.add_argument("--use-calibrated-region", action="store_true")
    parser.add_argument("--age-scale", type=float, default=8.0)
    parser.add_argument("--timer-scale", type=float, default=4.0)
    parser.add_argument("--tesseract-cmd")
    parser.add_argument("--timer-interval", type=float, default=5.0)
    parser.add_argument("--pause-check-interval", type=float, default=1.0)
    parser.add_argument("--pause-confirmation-checks", type=int, default=5)
    parser.add_argument("--pause-confirmation-wins", type=int, default=3)
    parser.add_argument("--age-interval", type=float, default=5.0)
    parser.add_argument("--age-confirmation-interval", type=float, default=1.0)
    parser.add_argument("--age-confirmation-checks", type=int, default=5)
    parser.add_argument("--age-confirmation-wins", type=int, default=4)
    parser.add_argument("--queue-interval", type=float, default=1.0)
    parser.add_argument("--villager-template", default=DEFAULT_VILLAGER_TEMPLATE)
    parser.add_argument("--villager-threshold", type=float, default=0.85)
    parser.add_argument(
        "--villager-scales",
        type=parse_scales,
        default=[0.82, 0.86, 0.90, 0.94, 0.98, 1.0],
    )
    parser.add_argument("--number-mask-ratio", type=float, default=0.40)
    parser.add_argument("--villager-border-mask-ratio", type=float, default=0.04)
    parser.add_argument("--catalog", default=DEFAULT_TECH_CATALOG)
    parser.add_argument("--template-root", default=DEFAULT_TECH_TEMPLATE_ROOT)
    parser.add_argument("--categories", nargs="+", default=["economy", "military"])
    parser.add_argument("--research-threshold", type=float)
    parser.add_argument(
        "--research-scales",
        type=parse_scales,
        default=[0.86, 0.90, 0.94, 0.98, 1.0, 1.04],
    )
    parser.add_argument("--research-border-mask-ratio", type=float, default=0.04)
    parser.add_argument("--research-min-distance", type=float, default=28.0)
    parser.add_argument("--research-max-detections", type=int, default=8)
    parser.add_argument("--research-confirmation-checks", type=int, default=10)
    parser.add_argument("--research-confirmation-wins", type=int, default=6)
    parser.add_argument("--research-completion-delay", type=float, default=30.0)
    parser.add_argument("--debug-events", action="store_true")
    parser.add_argument("--debug-event-dir", default="captures/debug-events")
    parser.add_argument("--once", action="store_true")


def command_watch_session(args):
    """Backward-compatible command handler for the former session name."""
    return command_watch_monitor(args)


def add_session_args(parser):
    """Backward-compatible parser helper for the former session name."""
    add_monitor_args(parser)
