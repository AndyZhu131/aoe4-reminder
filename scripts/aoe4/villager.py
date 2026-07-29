import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .age import load_monitor
from .common import grab_region_bgr, load_json, load_region, resolution_multiplier


VILLAGER_READER = "masked-template"
DEFAULT_VILLAGER_TEMPLATE = "templates/queue/villager.png"
PRODUCTION_QUEUE_TILE_SIZE = 48
PRODUCTION_QUEUE_LEFT_OFFSET = 10
PRODUCTION_QUEUE_SLOT_PITCH = 58
PRODUCTION_QUEUE_MIN_BLUE_COVERAGE = 0.15
PRODUCTION_QUEUE_MIN_PORTRAIT_COVERAGE = 0.05
PRODUCTION_QUEUE_MIN_HEAD_COVERAGE = 0.05


def queue_geometry(scale):
    if scale <= 0:
        raise RuntimeError("queue scale must be greater than zero")
    return (
        max(1, round(PRODUCTION_QUEUE_TILE_SIZE * scale)),
        max(0, round(PRODUCTION_QUEUE_LEFT_OFFSET * scale)),
        max(1, round(PRODUCTION_QUEUE_SLOT_PITCH * scale)),
    )


def reader_args(args):
    multiplier = resolution_multiplier(getattr(args, "template_resolution", "2560x1440"))
    queue_scale = args.queue_scale if getattr(args, "queue_scale", None) else multiplier
    return SimpleNamespace(
        threshold=args.threshold,
        scales=[scale * multiplier for scale in args.scales],
        queue_scale=queue_scale,
        number_mask_ratio=args.number_mask_ratio,
        border_mask_ratio=args.border_mask_ratio,
    )


def villager_template_mask(template, number_mask_ratio, border_mask_ratio):
    import cv2
    import numpy as np

    height, width = template.shape[:2]
    mask = np.full((height, width), 255, dtype=np.uint8)

    border_x = round(width * border_mask_ratio)
    border_y = round(height * border_mask_ratio)
    if border_x > 0:
        mask[:, :border_x] = 0
        mask[:, width - border_x :] = 0
    if border_y > 0:
        mask[:border_y, :] = 0
        mask[height - border_y :, :] = 0

    number_width = round(width * number_mask_ratio)
    number_height = round(height * number_mask_ratio)
    mask[:number_height, :number_width] = 0

    return cv2.merge([mask, mask, mask])

def find_economy_queue_tiles(frame, queue_scale=1.0):
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(
        hsv,
        np.array((100, 20, 10)),
        np.array((130, 255, 170)),
    )
    portrait_mask = cv2.inRange(
        hsv,
        np.array((5, 60, 80)),
        np.array((24, 255, 255)),
    )
    tiles = []
    expected_tile_size, left_offset, slot_pitch = queue_geometry(queue_scale)
    tile_size = min(expected_tile_size, frame.shape[0], frame.shape[1])
    row_y = frame.shape[0] - tile_size
    if tile_size < expected_tile_size:
        return tiles

    tile_area = tile_size * tile_size
    for x in range(
        left_offset,
        frame.shape[1] - tile_size + 1,
        slot_pitch,
    ):
        blue_coverage = (
            cv2.countNonZero(blue_mask[row_y : row_y + tile_size, x : x + tile_size])
            / tile_area
        )
        if blue_coverage < PRODUCTION_QUEUE_MIN_BLUE_COVERAGE:
            continue

        portrait = portrait_mask[row_y : row_y + tile_size, x : x + tile_size]
        portrait_coverage = cv2.countNonZero(portrait) / tile_area
        if portrait_coverage < PRODUCTION_QUEUE_MIN_PORTRAIT_COVERAGE:
            continue

        top_half = portrait[: tile_size // 2, :]
        left_head_coverage = cv2.countNonZero(top_half[:, : tile_size // 2]) / (
            tile_size * tile_size / 4
        )
        right_head_coverage = cv2.countNonZero(top_half[:, tile_size // 2 :]) / (
            tile_size * tile_size / 4
        )
        if min(left_head_coverage, right_head_coverage) < PRODUCTION_QUEUE_MIN_HEAD_COVERAGE:
            continue

        tiles.append(
            {
                "x": x,
                "y": row_y,
                "width": tile_size,
                "height": tile_size,
                "blueCoverage": round(blue_coverage, 3),
                "portraitCoverage": round(portrait_coverage, 3),
                "leftHeadCoverage": round(left_head_coverage, 3),
                "rightHeadCoverage": round(right_head_coverage, 3),
            }
        )

    return tiles

def crop_production_queue(frame, queue_scale=1.0):
    # Debug captures already contain the lower production half.
    expected_tile_size, _left_offset, _slot_pitch = queue_geometry(queue_scale)
    if frame.shape[0] <= expected_tile_size * 1.25:
        return frame
    return frame[frame.shape[0] // 2 :, :]

def match_villager_icon(frame, template_path, args):
    import cv2
    import numpy as np

    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"could not read villager template: {template_path}")

    queue_tiles = find_economy_queue_tiles(
        frame,
        getattr(args, "queue_scale", 1.0),
    )
    best = None

    for tile in queue_tiles:
        x = tile["x"]
        y = tile["y"]
        source = frame[y : y + tile["height"], x : x + tile["width"]]

        for scale in args.scales:
            if scale == 1.0:
                scaled_template = template
            else:
                scaled_template = cv2.resize(
                    template,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
                )

            height, width = scaled_template.shape[:2]
            source_height, source_width = source.shape[:2]
            if width > source_width or height > source_height:
                continue

            mask = villager_template_mask(
                scaled_template,
                args.number_mask_ratio,
                args.border_mask_ratio,
            )
            result = cv2.matchTemplate(
                source,
                scaled_template,
                cv2.TM_CCORR_NORMED,
                mask=mask,
            )
            result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
            _, max_value, _, max_location = cv2.minMaxLoc(result)
            candidate = {
                "score": float(max_value),
                "scale": scale,
                "queueTile": tile,
                "match": {
                    "x": x + int(max_location[0]),
                    "y": y + int(max_location[1]),
                    "width": int(width),
                    "height": int(height),
                },
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate

    if best is None:
        best = {
            "score": 0.0,
            "scale": None,
            "match": None,
        }

    best["queueTileCount"] = len(queue_tiles)
    best["queueTiles"] = queue_tiles
    best["villagerQueued"] = best["score"] >= args.threshold
    best["threshold"] = args.threshold
    return best

def save_villager_debug_image(frame, result, output_path, y_offset=0):
    import cv2

    debug = frame.copy()
    for tile in result.get("queueTiles", []):
        x = tile["x"]
        y = tile["y"] + y_offset
        width = tile["width"]
        height = tile["height"]
        cv2.rectangle(debug, (x, y), (x + width, y + height), (255, 255, 0), 1)

    match = result.get("match")
    color = (0, 255, 0) if result["villagerQueued"] else (0, 0, 255)
    if match:
        x = match["x"]
        y = match["y"] + y_offset
        width = match["width"]
        height = match["height"]
        cv2.rectangle(debug, (x, y), (x + width, y + height), color, 2)
        cv2.putText(
            debug,
            f"{result['score']:.3f}",
            (x, max(12, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), debug)

def read_global_queue_frame(args):
    import cv2

    if args.source_image:
        frame = cv2.imread(str(Path(args.source_image)), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"could not read source image: {args.source_image}")
        return frame

    rect = queue_rect(args)
    return grab_region_bgr(rect)


def read_queue_frame(args):
    return crop_production_queue(
        read_global_queue_frame(args),
        reader_args(args).queue_scale,
    )


def queue_rect(args):
    monitor_index = getattr(args, "monitor", None)
    monitor = load_monitor(monitor_index) if monitor_index is not None else None
    return args.rect or load_region(Path(args.config), "globalQueue", monitor)

def villager_payload(result, elapsed_ms, state_changed=None):
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reader": VILLAGER_READER,
        "villagerQueued": result["villagerQueued"],
        "score": round(result["score"], 4),
        "threshold": result["threshold"],
        "match": result["match"],
        "scale": result["scale"],
        "queueTileCount": result["queueTileCount"],
        "elapsedMs": round(elapsed_ms, 2),
    }
    if state_changed is not None:
        payload["stateChanged"] = state_changed
    return payload

def command_match_villager(args):
    import cv2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    started = time.perf_counter()
    frame = read_queue_frame(args)
    result = match_villager_icon(frame, Path(args.template), reader_args(args))
    elapsed_ms = (time.perf_counter() - started) * 1000

    if args.debug_images:
        raw_path = output_dir / f"queue-{timestamp}.png"
        debug_path = output_dir / f"queue-{timestamp}-villager.png"
        cv2.imwrite(str(raw_path), frame)
        save_villager_debug_image(frame, result, debug_path)
        result["sourceImage"] = str(raw_path)
        result["debugImage"] = str(debug_path)

    print(json.dumps(villager_payload(result, elapsed_ms), indent=2))
    return 0

def command_watch_villager(args):
    import cv2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_queued = None

    if args.source_image:
        print(f"Reading queue from image {args.source_image}.", file=sys.stderr)
    else:
        rect = queue_rect(args)
        print(
            f"Watching globalQueue region {rect}. Press Ctrl+C to stop.",
            file=sys.stderr,
        )

    try:
        while True:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            started = time.perf_counter()
            global_queue_frame = read_global_queue_frame(args)
            match_args = reader_args(args)
            frame = crop_production_queue(global_queue_frame, match_args.queue_scale)
            result = match_villager_icon(frame, Path(args.template), match_args)
            elapsed_ms = (time.perf_counter() - started) * 1000
            state_changed = (
                previous_queued is not None
                and previous_queued != result["villagerQueued"]
            )
            previous_queued = result["villagerQueued"]

            if args.debug_images:
                raw_path = output_dir / f"globalQueue-{timestamp}.png"
                debug_path = output_dir / f"queue-{timestamp}-villager.png"
                cv2.imwrite(str(raw_path), global_queue_frame)
                save_villager_debug_image(
                    global_queue_frame,
                    result,
                    debug_path,
                    global_queue_frame.shape[0] - frame.shape[0],
                )

            print(
                json.dumps(villager_payload(result, elapsed_ms, state_changed)),
                flush=True,
            )
            if args.once or args.source_image:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped villager watcher.", file=sys.stderr)
        return 0

def command_test_villagers(args):
    import cv2

    fixture_dir = Path(args.fixture_dir)
    expected_path = fixture_dir / "expected.json"
    expected = load_json(expected_path)
    if expected is None:
        raise RuntimeError(f"expected fixture data not found: {expected_path}")

    template_path = Path(args.template)
    results = {}
    failures = []

    for image_name, expected_queued in expected.items():
        image_path = fixture_dir / image_name
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            failure = {"image": image_name, "error": "could not read image"}
            results[image_name] = failure
            failures.append(failure)
            continue

        match_args = reader_args(args)
        result = match_villager_icon(
            crop_production_queue(frame, match_args.queue_scale),
            template_path,
            match_args,
        )
        actual_queued = result["villagerQueued"]
        passed = actual_queued == expected_queued
        results[image_name] = {
            "passed": passed,
            "actual": {
                "villagerQueued": actual_queued,
                "score": round(result["score"], 4),
                "queueTileCount": result["queueTileCount"],
            },
            "expected": {"villagerQueued": expected_queued},
        }
        if not passed:
            failures.append(results[image_name])

    print(json.dumps(results, indent=2))
    return 1 if failures else 0
