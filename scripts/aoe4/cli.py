import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from aoe4.age import command_capture_age, command_test_age, command_watch_age
from aoe4.calibration import command_calibrate
from aoe4.overlay import (
    OVERLAY_AGES,
    OVERLAY_VILLAGER_STATES,
    command_write_overlay_state,
    parse_technology_keys,
)
from aoe4.monitor import add_monitor_args, command_watch_monitor
from aoe4.technology_catalog import add_inject_technologies_args, command_inject_technologies
from aoe4.common import (
    REGIONS,
    capture_region_to_png,
    command_monitors,
    match_template,
    parse_rect,
    parse_scales,
    resolve_rect,
    wait_before_capture,
    run_windows_hotkey_session,
)
from aoe4.resources import command_test_resources, command_watch_resources
from aoe4.tech import (
    DEFAULT_TECH_CATALOG,
    DEFAULT_TECH_TEMPLATE_ROOT,
    command_match_research,
    command_test_research_queue,
    command_watch_research,
    extract_research_capture,
    parse_categories,
)
from aoe4.villager import (
    DEFAULT_VILLAGER_TEMPLATE,
    command_match_villager,
    command_test_villagers,
    command_watch_villager,
)


def command_capture(args):
    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rect = resolve_rect(args)
    source_path = output_dir / f"{args.region}-{timestamp}.png"
    capture_region_to_png(rect, source_path)
    print(f"Captured {args.region} {rect} -> {source_path}", file=sys.stderr)
    print(json.dumps({"region": args.region, "source": str(source_path)}, indent=2))
    return 0


def capture_queue_once(args):
    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    rect = args.rect or resolve_rect(args)
    source_path = output_dir / f"globalQueue-{timestamp}.png"
    capture_region_to_png(rect, source_path)
    research_path = output_dir / f"research-icon-{timestamp}.png"
    research_rect = extract_research_capture(
        source_path,
        research_path,
        args.research_row,
    )
    print(f"Captured globalQueue {rect} -> {source_path}", file=sys.stderr)
    print(
        f"Captured {args.research_row} research slot {research_rect} -> {research_path}",
        file=sys.stderr,
    )
    return {
        "region": "globalQueue",
        "source": str(source_path),
        "researchIcon": {
            "source": str(research_path),
            "row": args.research_row,
            "rect": research_rect,
        },
    }


def command_capture_queue(args):
    if args.once:
        wait_before_capture(args.delay)
        print(json.dumps(capture_queue_once(args), indent=2))
        return 0

    print(
        "Queue capture session ready. Press Ctrl+Alt+S to save a queue and research-icon "
        "capture. Press Ctrl+C to stop.",
        file=sys.stderr,
    )

    def capture_on_hotkey():
        try:
            print(json.dumps(capture_queue_once(args), indent=2))
        except Exception as exc:
            print(f"capture failed: {exc}", file=sys.stderr)

    try:
        run_windows_hotkey_session(capture_on_hotkey)
    except KeyboardInterrupt:
        print("Stopped queue capture session.", file=sys.stderr)
    return 0

def command_match(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if args.source_image:
        source_path = Path(args.source_image)
        if not source_path.exists():
            raise RuntimeError(f"source image not found: {source_path}")
        print(f"Using source image: {source_path}", file=sys.stderr)
    else:
        rect = resolve_rect(args)
        source_path = output_dir / f"{args.region}-{timestamp}.png"
        capture_region_to_png(rect, source_path)
        print(f"Captured {args.region} {rect} -> {source_path}", file=sys.stderr)

    template_path = Path(args.template)
    if not template_path.exists():
        raise RuntimeError(f"template image not found: {template_path}")

    debug_path = output_dir / f"{args.region}-{timestamp}-match.png"
    result = {
        "region": args.region,
        "source": str(source_path),
        "template": str(template_path),
    }
    result.update(match_template(source_path, template_path, args.threshold, debug_path))
    print(json.dumps(result, indent=2))
    return 0

def add_region_args(parser):
    parser.add_argument("--config", default="config/calibration.2560x1440.json")
    parser.add_argument("--region", default="globalQueue", choices=REGIONS)
    parser.add_argument("--rect", type=parse_rect)
    parser.add_argument("--output-dir", default="captures")

def add_villager_args(parser):
    parser.add_argument("--config", default="config/calibration.2560x1440.json")
    parser.add_argument("--rect", type=parse_rect)
    parser.add_argument("--template", default=DEFAULT_VILLAGER_TEMPLATE)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument(
        "--scales",
        type=parse_scales,
        default=[0.82, 0.86, 0.90, 0.94, 0.98, 1.0],
    )
    parser.add_argument("--number-mask-ratio", type=float, default=0.40)
    parser.add_argument("--border-mask-ratio", type=float, default=0.04)
    parser.add_argument("--source-image")
    parser.add_argument("--output-dir", default="captures/queue")
    parser.add_argument("--debug-images", action="store_true")

def add_research_args(parser):
    parser.add_argument("--config", default="config/calibration.2560x1440.json")
    parser.add_argument("--rect", type=parse_rect)
    parser.add_argument("--catalog", default=DEFAULT_TECH_CATALOG)
    parser.add_argument("--template-root", default=DEFAULT_TECH_TEMPLATE_ROOT)
    parser.add_argument("--civilization", default="sis")
    parser.add_argument(
        "--categories",
        type=parse_categories,
        default=["economy", "military"],
        help="comma-separated catalog categories to scan",
    )
    parser.add_argument("--threshold", type=float, default=0.88)
    parser.add_argument(
        "--scales",
        type=parse_scales,
        default=[0.86, 0.90, 0.94, 0.98, 1.0, 1.04],
    )
    parser.add_argument("--border-mask-ratio", type=float, default=0.04)
    parser.add_argument("--min-distance", type=float, default=28.0)
    parser.add_argument("--max-detections", type=int, default=8)
    parser.add_argument("--source-image")
    parser.add_argument("--output-dir", default="captures/research")
    parser.add_argument("--debug-images", action="store_true")
    parser.add_argument("--show-missing-templates", action="store_true")

def build_parser():
    parser = argparse.ArgumentParser(description="AoE4 Reminder phase 1 vision tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    monitors = subparsers.add_parser("monitors", help="list available capture monitors")
    monitors.set_defaults(func=command_monitors)

    calibrate = subparsers.add_parser(
        "calibrate", help="visually select the three screen regions"
    )
    calibrate.add_argument("--output", default="config/calibration.2560x1440.json")
    calibrate.add_argument("--seed", default="config/calibration.sample.json")
    calibrate.add_argument("--monitor", type=int, default=1)
    calibrate.add_argument("--ui-scale", default="100%")
    calibrate.add_argument("--screenshot", default="captures/calibration-background.png")
    calibrate.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="seconds to wait before taking the calibration screenshot",
    )
    calibrate.add_argument(
        "--source-image",
        help="use an existing screenshot instead of capturing the monitor",
    )
    calibrate.set_defaults(func=command_calibrate)

    capture = subparsers.add_parser("capture", help="capture one calibrated region")
    add_region_args(capture)
    capture.set_defaults(func=command_capture)

    capture_queue = subparsers.add_parser(
        "capture-queue",
        help="capture globalQueue and its research icon with Ctrl+Alt+S",
    )
    capture_queue.add_argument("--config", default="config/calibration.2560x1440.json")
    capture_queue.add_argument("--rect", type=parse_rect)
    capture_queue.add_argument("--output-dir", default="captures/queue")
    capture_queue.add_argument(
        "--research-row",
        choices=("top", "bottom"),
        default="top",
        help="row containing the research icon to extract after the queue capture",
    )
    capture_queue.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="seconds to wait before a --once screenshot",
    )
    capture_queue.add_argument(
        "--once",
        action="store_true",
        help="capture once immediately after --delay instead of starting the hotkey session",
    )
    capture_queue.set_defaults(region="globalQueue", func=command_capture_queue)

    capture_age = subparsers.add_parser(
        "capture-age",
        help="capture the calibrated ageAndTimer region with Ctrl+Alt+S",
    )
    capture_age.add_argument("--config", default="config/calibration.2560x1440.json")
    capture_age.add_argument("--rect", type=parse_rect)
    capture_age.add_argument(
        "--monitor",
        type=int,
        help="physical monitor to capture; defaults to the monitor stored in --config",
    )
    capture_age.add_argument(
        "--use-calibrated-region",
        action="store_true",
        help="use the saved ageAndTimer rectangle instead of the automatic top-center crop",
    )
    capture_age.add_argument("--output-dir", default="captures/age")
    capture_age.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="seconds to wait before a --once screenshot",
    )
    capture_age.add_argument(
        "--once",
        action="store_true",
        help="capture once immediately after --delay instead of starting the hotkey session",
    )
    capture_age.set_defaults(region="ageAndTimer", func=command_capture_age)

    test_age = subparsers.add_parser(
        "test-age",
        help="run age icon and timer recognition against labeled captures",
    )
    test_age.add_argument("--fixture-dir", default="captures/age")
    test_age.add_argument("--age-scale", type=float, default=8.0)
    test_age.add_argument("--timer-scale", type=float, default=4.0)
    test_age.add_argument("--tesseract-cmd")
    test_age.set_defaults(func=command_test_age)

    watch_age = subparsers.add_parser(
        "watch-age",
        help="read the current age marker and game timer repeatedly",
    )
    watch_age.add_argument("--config", default="config/calibration.2560x1440.json")
    watch_age.add_argument("--rect", type=parse_rect)
    watch_age.add_argument("--monitor", type=int)
    watch_age.add_argument("--use-calibrated-region", action="store_true")
    watch_age.add_argument("--age-scale", type=float, default=8.0)
    watch_age.add_argument("--timer-scale", type=float, default=4.0)
    watch_age.add_argument("--tesseract-cmd")
    watch_age.add_argument("--interval", type=float, default=1.0)
    watch_age.add_argument("--source-image")
    watch_age.add_argument("--once", action="store_true")
    watch_age.set_defaults(func=command_watch_age)

    overlay_state = subparsers.add_parser(
        "overlay-state",
        help="write the current reminder state consumed by the desktop overlay",
    )
    overlay_state.add_argument("--output", default="runtime/overlay-state.json")
    overlay_state.add_argument("--civilization", default="sis")
    overlay_state.add_argument("--age", choices=OVERLAY_AGES, default="unknown")
    overlay_state.add_argument(
        "--villager-production",
        choices=OVERLAY_VILLAGER_STATES,
        default="unknown",
    )
    overlay_state.add_argument(
        "--researched",
        type=parse_technology_keys,
        default=[],
        help="comma-separated technology keys",
    )
    overlay_state.add_argument(
        "--in-progress",
        type=parse_technology_keys,
        default=[],
        help="comma-separated technology keys",
    )
    overlay_state.set_defaults(func=command_write_overlay_state)

    inject_technologies = subparsers.add_parser(
        "inject-technologies",
        aliases=["sync-tech-catalog"],
        help="sync the technology catalog from the template directory structure",
    )
    add_inject_technologies_args(inject_technologies)
    inject_technologies.set_defaults(func=command_inject_technologies)

    watch_monitor = subparsers.add_parser(
        "watch-monitor",
        aliases=["watch-session"],
        help="centrally coordinate recognition and reminder policy",
    )
    add_monitor_args(watch_monitor)
    watch_monitor.set_defaults(func=command_watch_monitor)

    match = subparsers.add_parser(
        "match", help="capture or load one region and compare it to an icon template"
    )
    add_region_args(match)
    match.add_argument("--template", required=True)
    match.add_argument("--threshold", type=float, default=0.90)
    match.add_argument("--source-image")
    match.set_defaults(func=command_match)

    match_villager = subparsers.add_parser(
        "match-villager",
        help="detect whether a villager icon is present in the global queue",
    )
    add_villager_args(match_villager)
    match_villager.set_defaults(func=command_match_villager)

    watch_villager = subparsers.add_parser(
        "watch-villager",
        help="detect villager queue presence repeatedly with immediate false on miss",
    )
    add_villager_args(watch_villager)
    watch_villager.add_argument("--interval", type=float, default=0.33)
    watch_villager.add_argument("--once", action="store_true")
    watch_villager.set_defaults(func=command_watch_villager)

    match_research = subparsers.add_parser(
        "match-research",
        help="classify active common research icons in either globalQueue row",
    )
    add_research_args(match_research)
    match_research.set_defaults(func=command_match_research)

    watch_research = subparsers.add_parser(
        "watch-research",
        help="classify active common research icons repeatedly",
    )
    add_research_args(watch_research)
    watch_research.add_argument("--interval", type=float, default=0.5)
    watch_research.add_argument("--once", action="store_true")
    watch_research.set_defaults(func=command_watch_research)

    test_research_queue = subparsers.add_parser(
        "test-research-queue",
        aliases=["test-research-clipboard"],
        help="capture and classify the calibrated globalQueue with Ctrl+Alt+S",
    )
    add_research_args(test_research_queue)
    test_research_queue.set_defaults(
        region="globalQueue",
        output_dir="captures/research-queue",
        threshold=0.95,
        func=command_test_research_queue,
    )

    watch_resources = subparsers.add_parser(
        "watch-resources",
        help="read resource numbers repeatedly and print parsed values",
    )
    watch_resources.add_argument("--config", default="config/calibration.2560x1440.json")
    watch_resources.add_argument("--interval", type=float, default=3.0)
    watch_resources.add_argument("--scale", type=float, default=3.0)
    watch_resources.add_argument("--psm", type=int, default=6)
    watch_resources.add_argument("--output-dir", default="captures/resources")
    watch_resources.add_argument("--debug-images", action="store_true")
    watch_resources.add_argument("--raw-fields", action="store_true")
    watch_resources.add_argument("--once", action="store_true")
    watch_resources.add_argument("--source-image")
    watch_resources.add_argument(
        "--tesseract-cmd",
        help="path to tesseract.exe if it is not on PATH",
    )
    watch_resources.set_defaults(func=command_watch_resources)

    test_resources = subparsers.add_parser(
        "test-resources",
        help="run resource panel number reading against checked-in fixtures",
    )
    test_resources.add_argument(
        "--fixture-dir",
        default="tests/fixtures/resource_panels",
    )
    test_resources.add_argument("--scale", type=float, default=3.0)
    test_resources.add_argument("--psm", type=int, default=6)
    test_resources.add_argument("--tesseract-cmd")
    test_resources.add_argument("--raw-fields", action="store_true")
    test_resources.set_defaults(func=command_test_resources)

    test_villagers = subparsers.add_parser(
        "test-villagers",
        help="run villager queue detection against checked-in live captures",
    )
    add_villager_args(test_villagers)
    test_villagers.add_argument(
        "--fixture-dir",
        default="tests/fixtures/villager_queue",
    )
    test_villagers.set_defaults(func=command_test_villagers)

    return parser

def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
