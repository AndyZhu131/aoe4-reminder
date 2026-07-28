import json
import time
from collections import deque
from dataclasses import dataclass
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
    load_technology_catalog,
    match_research_technologies,
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
    """Maintain a local game-time estimate and gate reminders on OCR confidence."""

    def __init__(
        self,
        tolerance,
        confirmation_checks,
        confirmation_wins,
        pause_confirmation_checks=6,
        pause_confirmation_wins=5,
    ):
        self.tolerance = tolerance
        self.confirmation_checks = confirmation_checks
        self.confirmation_wins = confirmation_wins
        self.pause_confirmation_checks = pause_confirmation_checks
        self.pause_confirmation_wins = pause_confirmation_wins
        self.anchor_game_seconds = None
        self.anchor_monotonic = None
        self.mode = "starting"
        self.paused_seconds = None
        self.confirmation = None
        self.confirmation_count = 0

    def estimated_seconds(self, now):
        if self.anchor_game_seconds is None:
            return None
        return self.anchor_game_seconds + (now - self.anchor_monotonic)

    def _decision(self, mode, now, reminders_enabled):
        return TimerDecision(
            mode,
            self.estimated_seconds(now),
            len(self.confirmation["observations"])
            if self.confirmation
            else self.confirmation_count,
            reminders_enabled,
        )

    def _anchor_tracking(self, observed_seconds, now):
        self.anchor_game_seconds = observed_seconds
        self.anchor_monotonic = now
        self.paused_seconds = None
        self.confirmation = None
        self.confirmation_count = 0
        self.mode = "tracking"
        return TimerDecision("tracking", observed_seconds, 0, True)

    def _begin_confirmation(self, observed_seconds, now, paused_baseline=None):
        self.mode = "resyncing"
        self.confirmation_count = 0
        self.confirmation = {
            "observations": [],
            "trackingVotes": 0,
            "pausedVotes": 0,
            "resumedVotes": 0,
            "pauseCandidate": paused_baseline
            if paused_baseline is not None
            else observed_seconds,
        }
        return self._record_confirmation(observed_seconds, now)

    def _record_confirmation(self, observed_seconds, now):
        confirmation = self.confirmation
        confirmation["observations"].append(observed_seconds)
        self.confirmation_count = len(confirmation["observations"])
        expected = self.estimated_seconds(now)
        pause_candidate = confirmation["pauseCandidate"]

        if observed_seconds is not None:
            if expected is not None and abs(observed_seconds - expected) <= self.tolerance:
                confirmation["trackingVotes"] += 1
            if (
                pause_candidate is not None
                and abs(observed_seconds - pause_candidate) <= self.tolerance
            ):
                confirmation["pausedVotes"] += 1
            if pause_candidate is not None and observed_seconds > pause_candidate:
                confirmation["resumedVotes"] += 1

        observations = [value for value in confirmation["observations"] if value is not None]
        latest_observation = observations[-1] if observations else None
        if len(confirmation["observations"]) >= self.confirmation_checks:
            if (
                confirmation["trackingVotes"] >= self.confirmation_wins
                and latest_observation is not None
            ):
                return self._anchor_tracking(latest_observation, now)
            if (
                confirmation["resumedVotes"] >= self.confirmation_wins
                and latest_observation is not None
            ):
                return self._anchor_tracking(latest_observation, now)
        if (
            len(confirmation["observations"]) >= self.pause_confirmation_checks
            and confirmation["pausedVotes"] >= self.pause_confirmation_wins
        ):
            self.paused_seconds = pause_candidate
            self.confirmation = None
            self.mode = "paused"
            return TimerDecision("paused", pause_candidate, self.confirmation_count, False)

        if len(confirmation["observations"]) < self.pause_confirmation_checks:
            return self._decision("resyncing", now, True)

        return self._begin_confirmation(latest_observation, now, self.paused_seconds)

    def observe(self, observed_seconds, now):
        if self.anchor_game_seconds is None:
            if observed_seconds is None:
                return TimerDecision("starting", None, 0, False)
            self.anchor_game_seconds = observed_seconds
            self.anchor_monotonic = now
            self.mode = "tracking"
            return TimerDecision("tracking", observed_seconds, 0, True)

        if self.mode == "tracking":
            estimated = self.estimated_seconds(now)
            if observed_seconds is not None and abs(observed_seconds - estimated) <= self.tolerance:
                return self._anchor_tracking(observed_seconds, now)
            return self._begin_confirmation(observed_seconds, now)

        if self.mode == "paused":
            if (
                observed_seconds is None
                or observed_seconds == self.paused_seconds
            ):
                return TimerDecision(
                    "paused",
                    self.paused_seconds,
                    self.confirmation_count,
                    False,
                )
            return self._begin_confirmation(
                observed_seconds,
                now,
                paused_baseline=self.paused_seconds,
            )

        return self._record_confirmation(observed_seconds, now)


@dataclass
class AgeDecision:
    age: str
    pending: bool
    confirmation_count: int


class AgeProgression:
    """Accept only confirmed forward age transitions from the OCR reader."""

    def __init__(self, confirmation_checks, confirmation_wins):
        self.confirmation_checks = confirmation_checks
        self.confirmation_wins = confirmation_wins
        self.age = "unknown"
        self.confirmation = None

    def observe(self, detected_age):
        if self.age == "unknown" and detected_age in AGE_TIERS:
            self.age = detected_age
            return AgeDecision(self.age, False, 0)

        current_tier = AGE_TIERS.get(self.age, 0)
        detected_tier = AGE_TIERS.get(detected_age, 0)
        if self.confirmation is None and detected_tier <= current_tier:
            return AgeDecision(self.age, False, 0)

        if self.confirmation is None:
            self.confirmation = {"observations": [], "votes": {}}

        confirmation = self.confirmation
        confirmation["observations"].append(detected_age)
        if detected_tier > current_tier:
            confirmation["votes"][detected_age] = confirmation["votes"].get(detected_age, 0) + 1

        if len(confirmation["observations"]) < self.confirmation_checks:
            return AgeDecision(self.age, True, len(confirmation["observations"]))

        accepted_age = next(
            (
                age
                for age, votes in sorted(
                    confirmation["votes"].items(),
                    key=lambda item: (item[1], AGE_TIERS[item[0]]),
                    reverse=True,
                )
                if votes >= self.confirmation_wins
            ),
            None,
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
        threshold=args.research_threshold,
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


def build_disabled_state(decision, age="age_1"):
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
        },
    }


def publish_overlay_state(args, current_state):
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
    print({"overlayState": state}, flush=True)


def command_watch_monitor(args):
    if (
        args.timer_interval <= 0
        or args.resync_interval <= 0
        or args.queue_interval <= 0
    ):
        raise RuntimeError("timer, resource, and queue intervals must be greater than zero")
    if args.timer_tolerance < 0:
        raise RuntimeError("timer tolerance cannot be negative")
    if args.timer_confirmation_checks < 1:
        raise RuntimeError("timer confirmation checks must be at least one")
    if not 1 <= args.timer_confirmation_wins <= args.timer_confirmation_checks:
        raise RuntimeError("timer confirmation wins must fit within the check count")
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
        args.timer_tolerance,
        args.timer_confirmation_checks,
        args.timer_confirmation_wins,
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
                synchronizer = TimerSynchronizer(
                    args.timer_tolerance,
                    args.timer_confirmation_checks,
                    args.timer_confirmation_wins,
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
                next_timer_check = now
                next_age_check = now
                next_queue_check = float("inf")
                current_state = build_disabled_state(
                    TimerDecision("starting", None, 0, False)
                )
                apply_technology_state(
                    current_state,
                    technologies,
                    current_state["age"],
                    research_tracker,
                )
                last_reset_token = controls["resetToken"]
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
                    detected_age, _age_attempts = read_age_roman(age_frame, age_args)
                    age_decision = age_progression.observe(detected_age)
                    print(
                        "AGE: "
                        f"detected={detected_age or 'unknown'} "
                        f"accepted={age_decision.age} "
                        f"pending={age_decision.pending}",
                        flush=True,
                    )
                    next_age_check = now + (
                        args.age_confirmation_interval
                        if age_decision.pending
                        else args.age_interval
                    )
                    if synchronizer.mode in {"tracking", "resyncing"}:
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
                        else args.resync_interval
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

            if synchronizer.mode in {"tracking", "resyncing"} and now >= next_queue_check:
                queue_frame = grab_region_bgr(queue_rect)
                villager_result = match_villager_icon(
                    crop_production_queue(
                        queue_frame,
                        resolution_multiplier(args.template_resolution),
                    ),
                    Path(args.villager_template),
                    villager_reader_args(args),
                )
                research_result = match_research_technologies(
                    crop_research_queue(queue_frame),
                    technologies,
                    research_reader_args(args),
                )
                current_state["detected_technologies"] = [
                    detection["key"] for detection in research_result["researching"]
                ]
                current_state["villager_production_active"] = villager_result["villagerQueued"]
                previous_villager_reminder = current_state["villager_reminder"]
                current_state["villager_reminder"] = should_remind_villager(
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
                research_tracker.observe(
                    (detection["key"] for detection in research_result["researching"]),
                    synchronizer.estimated_seconds(now),
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
    parser.add_argument("--resync-interval", type=float, default=1.0)
    parser.add_argument("--timer-tolerance", type=float, default=1.5)
    parser.add_argument("--timer-confirmation-checks", type=int, default=5)
    parser.add_argument("--timer-confirmation-wins", type=int, default=3)
    parser.add_argument("--pause-confirmation-checks", type=int, default=6)
    parser.add_argument("--pause-confirmation-wins", type=int, default=5)
    parser.add_argument("--age-interval", type=float, default=5.0)
    parser.add_argument("--age-confirmation-interval", type=float, default=1.0)
    parser.add_argument("--age-confirmation-checks", type=int, default=3)
    parser.add_argument("--age-confirmation-wins", type=int, default=2)
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
    parser.add_argument("--research-threshold", type=float, default=0.95)
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
    parser.add_argument("--once", action="store_true")


def command_watch_session(args):
    """Backward-compatible command handler for the former session name."""
    return command_watch_monitor(args)


def add_session_args(parser):
    """Backward-compatible parser helper for the former session name."""
    add_monitor_args(parser)
