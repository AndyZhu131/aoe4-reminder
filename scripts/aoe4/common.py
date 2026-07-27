import argparse
import json
import sys
import time
from pathlib import Path


REGIONS = ("resources", "ageAndTimer", "globalQueue")
COLORS = {
    "resources": "#37d67a",
    "ageAndTimer": "#3aa0ff",
    "globalQueue": "#ffb020",
}


def parse_rect(value):
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be x,y,width,height")

    try:
        rect = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rect values must be integers") from exc

    if rect[2] <= 0 or rect[3] <= 0:
        raise argparse.ArgumentTypeError("rect width and height must be positive")

    return rect

def load_json(path):
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

def load_region(config_path, region_name):
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    try:
        values = config["regions"][region_name]
    except KeyError as exc:
        raise RuntimeError(f"region '{region_name}' not found in {config_path}") from exc

    if len(values) != 4:
        raise RuntimeError(f"region '{region_name}' must be [x, y, width, height]")

    rect = tuple(int(value) for value in values)
    if rect[2] <= 0 or rect[3] <= 0:
        raise RuntimeError(f"region '{region_name}' has invalid width/height: {values}")

    return rect

def resolve_rect(args):
    if args.rect:
        return args.rect

    config_path = Path(args.config)
    if not config_path.exists():
        raise RuntimeError(
            f"config file not found: {config_path}. "
            "Pass --rect x,y,w,h or run the calibrate command first."
        )

    return load_region(config_path, args.region)

def default_regions(width, height):
    return {
        "resources": [0, 0, min(700, width), 90],
        "ageAndTimer": [max(0, (width // 2) - 160), 0, 320, 120],
        "globalQueue": [max(0, (width // 2) - 520), max(0, height - 250), 1040, 190],
    }

def rect_from_config(config, region, monitor):
    values = config.get("regions", {}).get(region)
    if not values or len(values) != 4:
        return None

    x, y, width, height = (int(value) for value in values)
    return [x - monitor["left"], y - monitor["top"], width, height]

def clamp_rect(rect, width, height):
    x, y, w, h = rect
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    return [x, y, w, h]

def capture_monitor_to_png(monitor, output_path):
    import mss
    import mss.tools

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with mss.mss() as screen_capture:
            image = screen_capture.grab(monitor)
            mss.tools.to_png(image.rgb, image.size, output=str(output_path))
    except Exception as exc:
        raise RuntimeError(
            "screen capture failed. Run this from a normal interactive terminal "
            "with the AoE4 window visible."
        ) from exc

def get_image_size(image_path):
    import cv2

    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"could not read image: {image_path}")

    height, width = image.shape[:2]
    return width, height

def wait_before_capture(delay):
    if delay <= 0:
        return

    print(
        f"Capturing screen in {delay:g} seconds. Switch to AoE4 now...",
        file=sys.stderr,
    )

    remaining = delay
    while remaining > 0:
        sleep_for = min(1.0, remaining)
        time.sleep(sleep_for)
        remaining -= sleep_for
        if remaining > 0:
            print(f"{remaining:.0f}...", file=sys.stderr)


def run_windows_hotkey_session(callback):
    import ctypes
    import os
    from ctypes import wintypes

    if os.name != "nt":
        raise RuntimeError("the Ctrl+Alt+S capture session is supported on Windows only")

    hotkey_id = 1
    modifiers = 0x0001 | 0x0002  # MOD_ALT | MOD_CONTROL
    virtual_key_s = 0x53
    wm_hotkey = 0x0312
    wm_quit = 0x0012
    pm_remove = 0x0001
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    if not user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key_s):
        error_code = ctypes.get_last_error()
        raise RuntimeError(
            "could not register Ctrl+Alt+S. It may already be assigned by another app "
            f"(Windows error {error_code})."
        )

    message = wintypes.MSG()
    try:
        while True:
            while user32.PeekMessageW(
                ctypes.byref(message),
                None,
                0,
                0,
                pm_remove,
            ):
                if message.message == wm_quit:
                    return
                if message.message == wm_hotkey and message.wParam == hotkey_id:
                    callback()
            # A non-blocking loop lets the interpreter process Ctrl+C reliably.
            time.sleep(0.05)
    finally:
        user32.UnregisterHotKey(None, hotkey_id)

def capture_region_to_png(rect, output_path):
    import cv2

    frame = grab_region_bgr(rect)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), frame)


def grab_region_bgr(rect):
    import cv2
    import mss
    import numpy as np

    x, y, width, height = rect
    monitor = {"left": x, "top": y, "width": width, "height": height}

    with mss.mss() as screen_capture:
        frame = np.array(screen_capture.grab(monitor))

    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

def match_template(source_path, template_path, threshold, output_path):
    import cv2

    source = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)

    if source is None:
        raise RuntimeError(f"could not read source image: {source_path}")
    if template is None:
        raise RuntimeError(f"could not read template image: {template_path}")

    source_height, source_width = source.shape[:2]
    template_height, template_width = template.shape[:2]

    if template_width > source_width or template_height > source_height:
        raise RuntimeError("template image is larger than source image")

    result = cv2.matchTemplate(source, template, cv2.TM_SQDIFF_NORMED)
    min_value, _, min_location, _ = cv2.minMaxLoc(result)
    score = 1.0 - float(min_value)
    matched = score >= threshold

    debug = source.copy()
    x, y = min_location
    cv2.rectangle(
        debug,
        (x, y),
        (x + template_width, y + template_height),
        (0, 255, 0) if matched else (0, 0, 255),
        2,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), debug)

    return {
        "threshold": threshold,
        "matched": matched,
        "score": round(score, 4),
        "match": {
            "x": x,
            "y": y,
            "width": template_width,
            "height": template_height,
        },
        "sourceSize": {
            "width": source_width,
            "height": source_height,
        },
        "debugImage": str(output_path),
    }

def parse_scales(value):
    try:
        scales = [float(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scales must be comma-separated numbers") from exc

    if not scales:
        raise argparse.ArgumentTypeError("at least one scale is required")
    if any(scale <= 0 for scale in scales):
        raise argparse.ArgumentTypeError("scales must be positive")

    return scales

def command_monitors(_args):
    import mss

    with mss.mss() as screen_capture:
        monitors = []
        for index, monitor in enumerate(screen_capture.monitors):
            monitors.append(
                {
                    "index": index,
                    "left": monitor["left"],
                    "top": monitor["top"],
                    "width": monitor["width"],
                    "height": monitor["height"],
                    "note": "all monitors" if index == 0 else "physical monitor",
                }
            )

    print(json.dumps(monitors, indent=2))
    return 0
