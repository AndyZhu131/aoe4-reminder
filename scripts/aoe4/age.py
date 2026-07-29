import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .common import (
    capture_region_to_png,
    grab_region_bgr,
    load_json,
    load_region,
    run_windows_hotkey_session,
    wait_before_capture,
)
from .resources import read_text_with_tesseract


AGE_READER = "fixed-position-roman-template"
# Fractions of the captured age/timer region, not fixed screen pixels.
AGE_ROMAN_RECT = (38 / 125, 40 / 288, 50 / 125, 58 / 288)
CALIBRATED_AGE_ROMAN_RECT = (52 / 155, 0.0, 70 / 155, 38 / 146)
AGE_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "age"
AGE_TEMPLATE_THRESHOLD = 0.18
TIMER_RECTS = (
    ("standard", (32 / 125, 142 / 288, 64 / 125, 28 / 288)),
    ("ageUp", (32 / 125, 200 / 288, 64 / 125, 29 / 288)),
)
CALIBRATED_TIMER_RECTS = (
    ("standard", (45 / 155, 60 / 146, 70 / 155, 40 / 146)),
    ("ageUp", (45 / 155, 102 / 146, 70 / 155, 40 / 146)),
)
AGE_ROMAN_TO_LABEL = {
    "I": "age_1",
    "II": "age_2",
    "III": "age_3",
    "IV": "age_4",
}


def load_monitor(monitor_index):
    import mss

    with mss.mss() as screen_capture:
        monitors = screen_capture.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            raise RuntimeError(
                f"monitor {monitor_index} is unavailable. "
                f"mss reported {len(monitors) - 1} physical monitor(s)."
            )
        return dict(monitors[monitor_index])


def auto_age_timer_rect(monitor):
    # At 2048 px width, 100 px covers the age marker and timer with a small margin.
    width = max(1, round(monitor["width"] * (100 / 2048)))
    height = max(1, round(monitor["height"] * 0.2))
    return (
        monitor["left"] + (monitor["width"] - width) // 2,
        monitor["top"],
        width,
        height,
    )


def resolve_age_timer_rect(args):
    if args.rect:
        return args.rect
    if args.use_calibrated_region:
        config_path = Path(args.config)
        config = load_json(config_path) or {}
        monitor_index = args.monitor
        if monitor_index is None:
            monitor_index = int(config.get("monitor", 1))
        return load_region(config_path, "ageAndTimer", load_monitor(monitor_index))

    config = load_json(Path(args.config)) or {}
    monitor_index = args.monitor
    if monitor_index is None:
        monitor_index = int(config.get("monitor", 1))
    return auto_age_timer_rect(load_monitor(monitor_index))


def capture_age_once(args):
    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    rect = resolve_age_timer_rect(args)
    source_path = output_dir / f"ageAndTimer-{timestamp}.png"
    capture_region_to_png(rect, source_path)
    print(f"Captured ageAndTimer {rect} -> {source_path}", file=sys.stderr)
    return {
        "region": "ageAndTimer",
        "source": str(source_path),
    }


def command_capture_age(args):
    if args.once:
        wait_before_capture(args.delay)
        print(json.dumps(capture_age_once(args), indent=2))
        return 0

    print(
        "Age/timer capture session ready. Press Ctrl+Alt+S to save the calibrated "
        "ageAndTimer region. Press Ctrl+C to stop.",
        file=sys.stderr,
    )

    def capture_on_hotkey():
        try:
            print(json.dumps(capture_age_once(args), indent=2))
        except Exception as exc:
            print(f"age/timer capture failed: {exc}", file=sys.stderr)

    try:
        run_windows_hotkey_session(capture_on_hotkey)
    except KeyboardInterrupt:
        print("Stopped age/timer capture session.", file=sys.stderr)
    return 0


def age_capture_layout(frame):
    frame_height, frame_width = frame.shape[:2]
    if frame_width / max(1, frame_height) >= 0.75:
        return CALIBRATED_AGE_ROMAN_RECT, CALIBRATED_TIMER_RECTS
    return AGE_ROMAN_RECT, TIMER_RECTS


def crop_reference_rect(frame, relative_rect):
    frame_height, frame_width = frame.shape[:2]
    relative_x, relative_y, relative_w, relative_h = relative_rect

    x = max(0, min(round(relative_x * frame_width), frame_width - 1))
    y = max(0, min(round(relative_y * frame_height), frame_height - 1))
    width = max(1, min(round(relative_w * frame_width), frame_width - x))
    height = max(1, min(round(relative_h * frame_height), frame_height - y))
    return frame[y : y + height, x : x + width]


def crop_age_roman(frame):
    roman_rect, _timer_rects = age_capture_layout(frame)
    return crop_reference_rect(frame, roman_rect)


def crop_timer_area(frame, reference_rect):
    return crop_reference_rect(frame, reference_rect)


def preprocess_age_roman(frame, scale, minimum_value):
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Roman numerals are gold; the crop excludes the decorative side lines.
    mask = cv2.inRange(hsv, (8, 50, minimum_value), (45, 255, 255))
    mask = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(
        mask,
        16,
        16,
        16,
        16,
        cv2.BORDER_CONSTANT,
        value=0,
    )


def match_inline_age_roman(frame):
    """Classify the inline ``- III -`` marker from its gold vertical glyphs."""
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Bright gold glyph highlights stay distinct even when terrain is gold or brown.
    gold_mask = cv2.inRange(hsv, (5, 40, 180), (55, 255, 255))
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(gold_mask)
    height, width = gold_mask.shape[:2]
    minimum_height = max(6, round(height * 0.42))
    maximum_width = max(5, round(height * 0.95))
    glyphs = []

    for index in range(1, count):
        x, y, component_width, component_height, area = stats[index]
        center_x, _center_y = centroids[index]
        if area < 8 or component_height < minimum_height:
            continue
        # Circular age wrappers can leave a tall arc at the crop edge. It is
        # taller than any Roman glyph and must not be mistaken for a V.
        if component_height >= height * 0.85:
            continue
        # The wrapper dashes are short and horizontal, unlike the Roman glyphs.
        if (
            component_width > maximum_width
            or component_width > component_height * 1.15
        ):
            continue
        if not width * 0.12 <= center_x <= width * 0.88:
            continue
        glyphs.append((int(x), int(component_width), int(component_height)))

    glyphs.sort()
    widths = [component_width for _x, component_width, _height in glyphs]
    if len(widths) == 1:
        # The I and V can touch in the calibrated wide crop. Their merged
        # component is substantially wider than a standalone I glyph.
        _x, component_width, component_height = glyphs[0]
        if component_width / component_height >= 0.58:
            return "age_4", glyphs
        return "age_1", glyphs
    if len(widths) == 2:
        # In IV, V is substantially wider than the preceding I.
        if max(widths) >= min(widths) * 1.45:
            return "age_4", glyphs
        return "age_2", glyphs
    if len(widths) == 3:
        return "age_3", glyphs
    return None, glyphs


def match_age_template(frame):
    import cv2

    roman_crop = crop_age_roman(frame)
    source = cv2.Canny(
        cv2.cvtColor(roman_crop, cv2.COLOR_BGR2GRAY),
        60,
        140,
    )
    attempts = []
    for age, filename in AGE_ROMAN_TO_LABEL.items():
        template_path = AGE_TEMPLATE_DIR / f"{filename}.png"
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None:
            continue
        template_edges = cv2.Canny(
            cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
            60,
            140,
        )
        if template_edges.shape != source.shape:
            template_edges = cv2.resize(
                template_edges,
                (source.shape[1], source.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        score = float(cv2.matchTemplate(source, template_edges, cv2.TM_CCOEFF_NORMED)[0, 0])
        attempts.append(
            {
                "template": filename,
                "score": round(score, 4),
            }
        )

    if not attempts:
        return None, attempts
    best = max(attempts, key=lambda attempt: attempt["score"])
    return (
        best["template"] if best["score"] >= AGE_TEMPLATE_THRESHOLD else None,
        attempts,
    )


def parse_age_roman(raw_text):
    roman = "".join(character for character in raw_text.upper() if character in "IV")
    return AGE_ROMAN_TO_LABEL.get(roman)


def read_age_roman(frame, args):
    roman_crop = crop_age_roman(frame)
    if frame.shape[1] / max(1, frame.shape[0]) >= 0.75:
        inline_age, glyphs = match_inline_age_roman(roman_crop)
        inline_attempt = {
            "method": "normalized-inline-glyphs",
            "glyphWidths": [width for _x, width, _height in glyphs],
            "age": inline_age,
        }
        if inline_age:
            return inline_age, [inline_attempt]

    matched_age, template_attempts = match_age_template(frame)
    attempts = [{"method": "template", **attempt} for attempt in template_attempts]
    if frame.shape[1] / max(1, frame.shape[0]) >= 0.75:
        attempts.insert(0, inline_attempt)
    if matched_age:
        return matched_age, attempts

    for minimum_value in (95, 125, 70, 155):
        processed = preprocess_age_roman(
            roman_crop,
            args.age_scale,
            minimum_value,
        )
        raw_text = read_text_with_tesseract(processed, args.tesseract_cmd, 7, "IV")
        age = parse_age_roman(raw_text)
        attempts.append(
            {
                "method": "ocr",
                "minimumValue": minimum_value,
                "rawText": raw_text,
                "age": age,
            }
        )
        if age:
            return age, attempts
    return None, attempts


def preprocess_timer_area(frame, scale, minimum_value):
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Timer digits are neutral white/gray; this rejects terrain and gold HUD art.
    processed = cv2.inRange(hsv, (0, 0, minimum_value), (180, 55, 255))
    processed = cv2.resize(
        processed,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )
    return cv2.copyMakeBorder(
        processed,
        12,
        12,
        12,
        12,
        cv2.BORDER_CONSTANT,
        value=0,
    )


def parse_timer(raw_text):
    match = re.search(r"(\d{1,3})\s*:\s*(\d{2})", raw_text)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    if seconds >= 60:
        return None
    return f"{minutes:02d}:{seconds:02d}"


def read_game_timer(frame, args):
    attempts = []
    _roman_rect, timer_rects = age_capture_layout(frame)
    for position, timer_rect in timer_rects:
        timer_area = crop_timer_area(frame, timer_rect)
        raw_text = read_text_with_tesseract(
            timer_area,
            args.tesseract_cmd,
            13,
            "0123456789:",
        )
        timer = parse_timer(raw_text)
        attempts.append(
            {
                "position": position,
                "method": "raw",
                "psm": 13,
                "rawText": raw_text,
                "timer": timer,
            }
        )
        if timer:
            return timer, attempts
        for minimum_value in (100, 80):
            processed = preprocess_timer_area(
                timer_area,
                args.timer_scale,
                minimum_value,
            )
            for page_segmentation_mode in (13, 7):
                raw_text = read_text_with_tesseract(
                    processed,
                    args.tesseract_cmd,
                    page_segmentation_mode,
                    "0123456789:",
                )
                timer = parse_timer(raw_text)
                attempts.append(
                    {
                        "position": position,
                        "minimumValue": minimum_value,
                        "psm": page_segmentation_mode,
                        "rawText": raw_text,
                        "timer": timer,
                    }
                )
                if timer:
                    return timer, attempts
    return None, attempts


def read_age_and_timer(frame, args):
    started = time.perf_counter()
    age, age_attempts = read_age_roman(frame, args)
    timer, timer_attempts = read_game_timer(frame, args)
    return {
        "reader": AGE_READER,
        "age": age,
        "ageAttempts": age_attempts,
        "timer": timer,
        "timerAttempts": timer_attempts,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
    }


def parse_age_fixture_name(path):
    match = re.fullmatch(r"(\d{2})-(\d{2})-([1-4])\.png", path.name)
    if match:
        return {"timer": f"{match.group(1)}:{match.group(2)}", "age": f"age_{match.group(3)}"}
    age_only_match = re.fullmatch(r".+-age-([1-4])\.png", path.name)
    if age_only_match:
        return {"timer": None, "age": f"age_{age_only_match.group(1)}"}
    return None


def command_test_age(args):
    import cv2

    fixture_dir = Path(args.fixture_dir)
    fixtures = sorted(fixture_dir.glob("*.png"))
    if not fixtures:
        raise RuntimeError(f"no age/timer fixtures found in {fixture_dir}")

    results = []
    for fixture_path in fixtures:
        expected = parse_age_fixture_name(fixture_path)
        if expected is None:
            continue
        frame = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"could not read fixture: {fixture_path}")
        actual = read_age_and_timer(frame, args)
        timer_matches = (
            expected["timer"] is None or actual["timer"] == expected["timer"]
        )
        passed = timer_matches and actual["age"] == expected["age"]
        results.append(
            {
                "fixture": fixture_path.name,
                "expected": expected,
                "actual": {"timer": actual["timer"], "age": actual["age"]},
                "passed": passed,
            }
        )

    passed_count = sum(item["passed"] for item in results)
    print(
        json.dumps(
            {
                "fixtureDir": str(fixture_dir),
                "passed": passed_count,
                "total": len(results),
                "results": results,
            },
            indent=2,
        )
    )
    return 0 if passed_count == len(results) else 1


def command_watch_age(args):
    import cv2

    source_path = Path(args.source_image) if args.source_image else None
    if source_path:
        if not source_path.exists():
            raise RuntimeError(f"source image not found: {source_path}")
        rect = None
        print(f"Reading age/timer from image {source_path}.", file=sys.stderr)
    else:
        rect = resolve_age_timer_rect(args)
        print(f"Watching age/timer region {rect}. Press Ctrl+C to stop.", file=sys.stderr)

    try:
        while True:
            if source_path:
                frame = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
                if frame is None:
                    raise RuntimeError(f"could not read source image: {source_path}")
            else:
                frame = grab_region_bgr(rect)

            payload = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **read_age_and_timer(frame, args),
            }
            if source_path:
                payload["source"] = str(source_path)
            else:
                payload["region"] = rect
            print(json.dumps(payload), flush=True)

            if args.once or source_path:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped age/timer watcher.", file=sys.stderr)
        return 0
