import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from .age import read_age_and_timer, resolve_age_timer_rect
from .common import grab_region_bgr, load_region, parse_rect, parse_scales
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


@dataclass
class TimerDecision:
    mode: str
    estimated_seconds: float | None
    mismatch_count: int
    reminders_enabled: bool


class TimerSynchronizer:
    """Maintain a local game-time estimate and gate reminders on OCR confidence."""

    def __init__(self, tolerance, mismatch_limit):
        self.tolerance = tolerance
        self.mismatch_limit = mismatch_limit
        self.anchor_game_seconds = None
        self.anchor_monotonic = None
        self.last_observed_seconds = None
        self.mismatch_count = 0
        self.mode = "starting"

    def estimated_seconds(self, now):
        if self.anchor_game_seconds is None:
            return None
        return self.anchor_game_seconds + (now - self.anchor_monotonic)

    def observe(self, observed_seconds, now):
        if observed_seconds is None:
            if self.anchor_game_seconds is None:
                return TimerDecision("starting", None, 0, False)
            self.mismatch_count += 1
            self.mode = (
                "paused" if self.mismatch_count >= self.mismatch_limit else "resyncing"
            )
            return TimerDecision(
                self.mode,
                self.estimated_seconds(now),
                self.mismatch_count,
                False,
            )

        if self.anchor_game_seconds is None:
            self.anchor_game_seconds = observed_seconds
            self.anchor_monotonic = now
            self.last_observed_seconds = observed_seconds
            self.mismatch_count = 0
            self.mode = "tracking"
            return TimerDecision("tracking", observed_seconds, 0, True)

        estimated = self.estimated_seconds(now)
        error = observed_seconds - estimated
        previous_mode = self.mode
        observed_advanced = (
            self.last_observed_seconds is not None
            and observed_seconds > self.last_observed_seconds
        )
        self.last_observed_seconds = observed_seconds

        if abs(error) <= self.tolerance:
            self.anchor_game_seconds = observed_seconds
            self.anchor_monotonic = now
            self.mismatch_count = 0
            self.mode = "tracking"
            return TimerDecision("tracking", observed_seconds, 0, True)

        if previous_mode in {"resyncing", "paused"} and observed_advanced:
            self.anchor_game_seconds = observed_seconds
            self.anchor_monotonic = now
            self.mismatch_count = 0
            self.mode = "tracking"
            return TimerDecision("tracking", observed_seconds, 0, True)

        self.mismatch_count += 1
        self.mode = "paused" if self.mismatch_count >= self.mismatch_limit else "resyncing"
        return TimerDecision(self.mode, estimated, self.mismatch_count, False)


def age_reader_args(args):
    return SimpleNamespace(
        rect=args.age_rect,
        use_calibrated_region=args.use_calibrated_region,
        config=args.config,
        monitor=args.monitor,
        age_scale=args.age_scale,
        timer_scale=args.timer_scale,
        tesseract_cmd=args.tesseract_cmd,
    )


def villager_reader_args(args):
    return SimpleNamespace(
        threshold=args.villager_threshold,
        scales=args.villager_scales,
        number_mask_ratio=args.number_mask_ratio,
        border_mask_ratio=args.villager_border_mask_ratio,
    )


def research_reader_args(args):
    return SimpleNamespace(
        threshold=args.research_threshold,
        scales=args.research_scales,
        border_mask_ratio=args.research_border_mask_ratio,
        min_distance=args.research_min_distance,
        max_detections=args.research_max_detections,
    )


def build_disabled_state(decision):
    return {
        "age": "unknown",
        "villager_production_active": None,
        "in_progress_technologies": [],
        "session": {
            "status": decision.mode,
            "estimatedTimer": format_timer(decision.estimated_seconds),
            "timerMismatchCount": decision.mismatch_count,
        },
    }


def command_watch_session(args):
    if args.timer_interval <= 0 or args.resync_interval <= 0 or args.queue_interval <= 0:
        raise RuntimeError("timer and queue intervals must be greater than zero")
    if args.timer_tolerance < 0:
        raise RuntimeError("timer tolerance cannot be negative")
    if args.timer_mismatch_limit < 1:
        raise RuntimeError("timer mismatch limit must be at least one")

    age_args = age_reader_args(args)
    age_rect = resolve_age_timer_rect(age_args)
    queue_rect = load_region(Path(args.config), "globalQueue")
    technologies, missing_templates = load_technology_catalog(
        Path(args.catalog),
        args.template_root,
        args.categories,
        [args.civilization],
    )
    synchronizer = TimerSynchronizer(args.timer_tolerance, args.timer_mismatch_limit)
    last_age = "unknown"
    next_timer_check = 0.0
    next_queue_check = 0.0
    current_state = build_disabled_state(
        TimerDecision("starting", None, 0, False)
    )

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

            if now >= next_timer_check:
                age_frame = grab_region_bgr(age_rect)
                age_result = read_age_and_timer(age_frame, age_args)
                if age_result["age"]:
                    last_age = age_result["age"]
                decision = synchronizer.observe(
                    timer_to_seconds(age_result["timer"]), now
                )
                current_state = build_disabled_state(decision)
                if decision.reminders_enabled:
                    current_state["age"] = last_age
                next_timer_check = now + (
                    args.timer_interval
                    if decision.mode == "tracking"
                    else args.resync_interval
                )
                next_queue_check = now if decision.reminders_enabled else next_queue_check
                state_changed = True
                print(
                    {
                        "timer": age_result["timer"],
                        "estimatedTimer": format_timer(decision.estimated_seconds),
                        "status": decision.mode,
                        "timerMismatchCount": decision.mismatch_count,
                    },
                    flush=True,
                )

            if synchronizer.mode == "tracking" and now >= next_queue_check:
                queue_frame = grab_region_bgr(queue_rect)
                villager_result = match_villager_icon(
                    crop_production_queue(queue_frame),
                    Path(args.villager_template),
                    villager_reader_args(args),
                )
                research_result = match_research_technologies(
                    crop_research_queue(queue_frame),
                    technologies,
                    research_reader_args(args),
                )
                current_state["villager_production_active"] = villager_result[
                    "villagerQueued"
                ]
                current_state["in_progress_technologies"] = [
                    detection["key"] for detection in research_result["researching"]
                ]
                next_queue_check = now + args.queue_interval
                state_changed = True

            if state_changed:
                state = write_overlay_state(
                    args.output,
                    civilization=args.civilization,
                    age=current_state["age"],
                    villager_production_active=current_state[
                        "villager_production_active"
                    ],
                    in_progress_technologies=current_state[
                        "in_progress_technologies"
                    ],
                    session=current_state["session"],
                )
                print({"overlayState": state}, flush=True)

            if args.once:
                return 0

            sleep_until = min(next_timer_check, next_queue_check)
            time.sleep(max(0.05, min(0.25, sleep_until - time.monotonic())))
    except KeyboardInterrupt:
        print("Stopped session watcher.", flush=True)
        return 0


def add_session_args(parser):
    parser.add_argument("--output", default="runtime/overlay-state.json")
    parser.add_argument("--civilization", default="sis")
    parser.add_argument("--config", default="config/calibration.2560x1440.json")
    parser.add_argument("--age-rect", type=parse_rect)
    parser.add_argument("--monitor", type=int)
    parser.add_argument("--use-calibrated-region", action="store_true")
    parser.add_argument("--age-scale", type=float, default=8.0)
    parser.add_argument("--timer-scale", type=float, default=4.0)
    parser.add_argument("--tesseract-cmd")
    parser.add_argument("--timer-interval", type=float, default=5.0)
    parser.add_argument("--resync-interval", type=float, default=1.0)
    parser.add_argument("--timer-tolerance", type=float, default=1.5)
    parser.add_argument("--timer-mismatch-limit", type=int, default=5)
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
    parser.add_argument("--once", action="store_true")
