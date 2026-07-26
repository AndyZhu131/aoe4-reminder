import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path


REGIONS = ("resources", "ageAndTimer", "globalQueue")
RESOURCE_ORDER = ("food", "wood", "gold", "stone")
RESOURCE_READER = "tesseract-position"
VILLAGER_READER = "masked-template"
MAX_REASONABLE_POPULATION = 250
DEFAULT_VILLAGER_TEMPLATE = "templates/queue/villager.png"
PRODUCTION_QUEUE_TILE_SIZE = 48
PRODUCTION_QUEUE_LEFT_OFFSET = 10
PRODUCTION_QUEUE_SLOT_PITCH = 58
PRODUCTION_QUEUE_MIN_BLUE_COVERAGE = 0.15
PRODUCTION_QUEUE_MIN_PORTRAIT_COVERAGE = 0.05
PRODUCTION_QUEUE_MIN_HEAD_COVERAGE = 0.05
RESOURCE_PANEL_FIELDS = {
    "population": (50, 15, 95, 55),
    "idleVillagers": (190, 15, 40, 50),
    "resources": {
        "food": (50, 85, 90, 55),
        "wood": (50, 137, 90, 55),
        "gold": (50, 189, 90, 55),
        "stone": (50, 242, 90, 55),
    },
    "villagersOnResource": {
        "food": (190, 82, 40, 50),
        "wood": (190, 135, 40, 50),
        "gold": (190, 187, 40, 50),
        "stone": (190, 240, 40, 50),
    },
}
RESOURCE_PANEL_CANONICAL_WIDTH = 258
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


def preprocess_for_number_reader(frame, scale):
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Try both polarities; resource text can be light-on-dark depending on the crop.
    if threshold.mean() > 127:
        threshold = cv2.bitwise_not(threshold)

    return cv2.copyMakeBorder(
        threshold,
        12,
        12,
        12,
        12,
        cv2.BORDER_CONSTANT,
        value=0,
    )


def preprocess_field_for_number_reader(frame, scale, threshold):
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    _, processed = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    return cv2.copyMakeBorder(
        processed,
        10,
        10,
        10,
        10,
        cv2.BORDER_CONSTANT,
        value=0,
    )


def read_text_with_tesseract(image, tesseract_cmd, psm, whitelist):
    import pytesseract
    from PIL import Image

    resolved_tesseract_cmd = resolve_tesseract_cmd(tesseract_cmd)
    if resolved_tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = str(resolved_tesseract_cmd)

    config = (
        f"--psm {psm} "
        f"-c tessedit_char_whitelist={whitelist} "
        "-c classify_bln_numeric_mode=1"
    )
    pil_image = Image.fromarray(image)
    try:
        return pytesseract.image_to_string(pil_image, config=config).strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "tesseract.exe was not found. Install Tesseract OCR and make sure it "
            "is on PATH, or pass --tesseract-cmd \"C:/path/to/tesseract.exe\"."
        ) from exc


def read_numbers_with_tesseract(image, tesseract_cmd, psm):
    return read_text_with_tesseract(image, tesseract_cmd, psm, "0123456789")


def read_positioned_text_with_tesseract(image, tesseract_cmd, psm, whitelist):
    import pytesseract
    from PIL import Image

    resolved_tesseract_cmd = resolve_tesseract_cmd(tesseract_cmd)
    if resolved_tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = str(resolved_tesseract_cmd)

    config = (
        f"--psm {psm} "
        f"-c tessedit_char_whitelist={whitelist} "
        "-c classify_bln_numeric_mode=1"
    )
    pil_image = Image.fromarray(image)
    try:
        return pytesseract.image_to_data(
            pil_image,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "tesseract.exe was not found. Install Tesseract OCR and make sure it "
            "is on PATH, or pass --tesseract-cmd \"C:/path/to/tesseract.exe\"."
        ) from exc


def resolve_tesseract_cmd(tesseract_cmd):
    if tesseract_cmd:
        return Path(tesseract_cmd)

    candidates = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Tesseract-OCR"
        / "tesseract.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def parse_resources(raw_text):
    numbers = [int(value) for value in re.findall(r"\d+", raw_text)]
    parsed = {}

    for index, name in enumerate(RESOURCE_ORDER):
        parsed[name] = numbers[index] if index < len(numbers) else None

    return parsed, numbers


def crop_panel_field(frame, field_rect):
    height, width = frame.shape[:2]
    scale = width / RESOURCE_PANEL_CANONICAL_WIDTH
    x_px, y_px, w_px, h_px = field_rect
    x = max(0, min(round(x_px * scale), width - 1))
    y = max(0, min(round(y_px * scale), height - 1))
    w = max(1, min(round(w_px * scale), width - x))
    h = max(1, min(round(h_px * scale), height - y))
    return frame[y : y + h, x : x + w]


def read_field_number(frame, args, *, allow_slash=False, default_zero=False):
    thresholds = [150, 170, 130, 190, 110]
    whitelist = "0123456789/" if allow_slash else "0123456789"
    psm = 7 if allow_slash else 7
    attempts = []

    for threshold in thresholds:
        processed = preprocess_field_for_number_reader(frame, args.scale, threshold)
        raw_text = read_text_with_tesseract(
            processed,
            args.tesseract_cmd,
            psm,
            whitelist,
        )
        numbers = [int(value) for value in re.findall(r"\d+", raw_text)]
        attempts.append(
            {
                "threshold": threshold,
                "rawText": raw_text,
                "numbers": numbers,
            }
        )

        if allow_slash and len(numbers) >= 2:
            return numbers[:2], attempts
        if not allow_slash and numbers:
            return numbers[0], attempts

    if default_zero:
        return 0, attempts

    return None, attempts


def read_resource_panel_fixed_fields(frame, args):
    population_crop = crop_panel_field(frame, RESOURCE_PANEL_FIELDS["population"])
    population_values, population_attempts = read_field_number(
        population_crop,
        args,
        allow_slash=True,
    )
    if population_values:
        current_pop, max_pop = population_values
    else:
        current_pop = None
        max_pop = None

    idle_crop = crop_panel_field(frame, RESOURCE_PANEL_FIELDS["idleVillagers"])
    idle_villagers, idle_attempts = read_field_number(
        idle_crop,
        args,
        default_zero=True,
    )

    resources = {}
    resource_attempts = {}
    for resource in RESOURCE_ORDER:
        crop = crop_panel_field(frame, RESOURCE_PANEL_FIELDS["resources"][resource])
        value, attempts = read_field_number(crop, args)
        resources[resource] = value
        resource_attempts[resource] = attempts

    villagers_on_resource = {}
    villager_attempts = {}
    for resource in RESOURCE_ORDER:
        crop = crop_panel_field(
            frame,
            RESOURCE_PANEL_FIELDS["villagersOnResource"][resource],
        )
        value, attempts = read_field_number(crop, args, default_zero=True)
        villagers_on_resource[resource] = value
        villager_attempts[resource] = attempts

    panel = {
        "population": {
            "current": current_pop,
            "max": max_pop,
        },
        "idleVillagers": idle_villagers,
        "resources": resources,
        "villagersOnResource": villagers_on_resource,
    }

    if args.raw_fields:
        panel["rawFields"] = {
            "population": population_attempts,
            "idleVillagers": idle_attempts,
            "resources": resource_attempts,
            "villagersOnResource": villager_attempts,
        }

    return panel


def preprocess_panel_for_position_reader(frame, scale, threshold):
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    _, processed = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    processed = cv2.morphologyEx(
        processed,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
    )
    return processed


def detect_number_groups(frame, args):
    thresholds = [150, 130, 170, 110, 190, 95]
    attempts = []

    for threshold in thresholds:
        processed = preprocess_panel_for_position_reader(
            frame,
            args.scale,
            threshold,
        )
        data = read_positioned_text_with_tesseract(
            processed,
            args.tesseract_cmd,
            args.psm,
            "0123456789/",
        )
        groups = []
        count = len(data.get("text", []))
        for index in range(count):
            raw_text = str(data["text"][index] or "").strip()
            text = re.sub(r"[^0-9/]", "", raw_text)
            if not re.search(r"\d", text):
                continue

            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                confidence = -1.0

            x = float(data["left"][index]) / args.scale
            y = float(data["top"][index]) / args.scale
            width = float(data["width"][index]) / args.scale
            height = float(data["height"][index]) / args.scale
            groups.append(
                {
                    "text": text,
                    "numbers": [int(value) for value in re.findall(r"\d+", text)],
                    "confidence": round(confidence, 2),
                    "rect": [
                        round(x),
                        round(y),
                        max(1, round(width)),
                        max(1, round(height)),
                    ],
                    "center": [
                        round(x + width / 2, 1),
                        round(y + height / 2, 1),
                    ],
                }
            )

        attempts.append(
            {
                "threshold": threshold,
                "groups": groups,
                "panel": classify_number_groups(groups, frame.shape[1], frame.shape[0]),
            }
        )

    panel = classify_number_group_attempts(attempts)
    best_attempt = max(
        attempts,
        key=lambda attempt: score_classified_panel(attempt["panel"]),
    )
    return panel, best_attempt["groups"], attempts


def score_classified_panel(panel):
    score = 0
    if panel["population"]["current"] is not None:
        score += 2
    if panel["population"]["max"] is not None:
        score += 2
    if panel["idleVillagers"] is not None:
        score += 1
    score += sum(value is not None for value in panel["resources"].values())
    score += sum(value is not None for value in panel["villagersOnResource"].values())
    return score


def number_from_group(group):
    numbers = group.get("numbers", [])
    return numbers[0] if numbers else None


def y_center(group):
    return group["center"][1]


def assign_groups_to_rows(groups, row_anchors, max_distance):
    assigned = {}
    sorted_groups = sorted(groups, key=lambda group: group["confidence"], reverse=True)

    for group in sorted_groups:
        value = number_from_group(group)
        if value is None:
            continue

        nearest_index = min(
            range(len(row_anchors)),
            key=lambda index: abs(y_center(group) - row_anchors[index]),
        )
        distance = abs(y_center(group) - row_anchors[nearest_index])
        if distance > max_distance:
            continue
        current = assigned.get(nearest_index)
        if current is None or group["confidence"] > current["confidence"]:
            assigned[nearest_index] = group

    return {
        RESOURCE_ORDER[index]: number_from_group(assigned[index])
        if index in assigned
        else None
        for index in range(len(RESOURCE_ORDER))
    }


def assign_sorted_groups_to_resources(groups):
    values = {resource: None for resource in RESOURCE_ORDER}
    sorted_groups = sorted(groups, key=y_center)[: len(RESOURCE_ORDER)]
    for index, group in enumerate(sorted_groups):
        value = number_from_group(group)
        if value is not None:
            values[RESOURCE_ORDER[index]] = value
    return values


def choose_consensus_value(values, min_votes=1):
    values = [value for value in values if value is not None]
    if not values:
        return None

    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1

    value = sorted(
        counts,
        key=lambda value: (-counts[value], len(str(value)), value),
    )[0]
    if counts[value] < min_votes:
        return None
    return value


def choose_consensus_pair(pairs):
    pairs = [pair for pair in pairs if pair[0] is not None and pair[1] is not None]
    if not pairs:
        return (None, None)

    counts = {}
    for pair in pairs:
        counts[pair] = counts.get(pair, 0) + 1

    return sorted(
        counts,
        key=lambda pair: (-counts[pair], len(str(pair[0])) + len(str(pair[1])), pair),
    )[0]


def classify_number_group_attempts(attempts):
    panels = [attempt["panel"] for attempt in attempts]
    current_pop, max_pop = choose_consensus_pair(
        [
            (panel["population"]["current"], panel["population"]["max"])
            for panel in panels
        ]
    )

    resources = {}
    villagers_on_resource = {}
    for resource in RESOURCE_ORDER:
        resources[resource] = choose_consensus_value(
            [panel["resources"][resource] for panel in panels]
        )
        villagers_on_resource[resource] = choose_consensus_value(
            [panel["villagersOnResource"][resource] for panel in panels],
            min_votes=2,
        )

    return {
        "population": {
            "current": current_pop,
            "max": max_pop,
        },
        "idleVillagers": choose_consensus_value(
            [panel["idleVillagers"] for panel in panels]
        ),
        "resources": resources,
        "villagersOnResource": villagers_on_resource,
    }


def classify_number_groups(groups, width, height):
    top_cutoff = height * 0.24
    lower_top = height * 0.22
    left_column_max = width * 0.64
    right_column_min = width * 0.55
    fallback_row_anchors = [
        height * 0.35,
        height * 0.515,
        height * 0.675,
        height * 0.835,
    ]
    max_row_distance = height * 0.095

    top_groups = [group for group in groups if y_center(group) < top_cutoff]
    lower_groups = [group for group in groups if y_center(group) >= lower_top]

    population_group = None
    population_candidates = [
        group
        for group in top_groups
        if group["center"][0] < left_column_max and len(group["numbers"]) >= 2
    ]
    if population_candidates:
        population_group = min(
            population_candidates,
            key=lambda group: ("/" not in group["text"], group["center"][0]),
        )

    if population_group:
        current_pop, max_pop = population_group["numbers"][:2]
        if max_pop > MAX_REASONABLE_POPULATION or current_pop > max_pop:
            current_pop = None
            max_pop = None
    else:
        current_pop = None
        max_pop = None

    idle_candidates = [
        group
        for group in top_groups
        if group["center"][0] >= right_column_min and group.get("numbers")
    ]
    idle_villagers = (
        number_from_group(max(idle_candidates, key=lambda group: group["confidence"]))
        if idle_candidates
        else None
    )

    resource_groups = [
        group
        for group in lower_groups
        if group["center"][0] < left_column_max and group.get("numbers")
    ]
    worker_groups = [
        group
        for group in lower_groups
        if group["center"][0] >= right_column_min and group.get("numbers")
    ]

    resources = assign_sorted_groups_to_resources(resource_groups)
    detected_resource_anchors = [
        y_center(group)
        for group in sorted(resource_groups, key=y_center)
        if number_from_group(group) is not None
    ]
    if len(detected_resource_anchors) >= 4:
        row_anchors = detected_resource_anchors[:4]
    else:
        row_anchors = fallback_row_anchors

    villagers_on_resource = assign_groups_to_rows(
        worker_groups,
        row_anchors,
        max_row_distance,
    )
    return {
        "population": {
            "current": current_pop,
            "max": max_pop,
        },
        "idleVillagers": idle_villagers,
        "resources": resources,
        "villagersOnResource": villagers_on_resource,
    }


def merge_panels(primary, fallback):
    merged = {
        "population": dict(primary["population"]),
        "idleVillagers": primary["idleVillagers"],
        "resources": dict(primary["resources"]),
        "villagersOnResource": dict(primary["villagersOnResource"]),
    }

    for key in ("current", "max"):
        if merged["population"][key] is None:
            merged["population"][key] = fallback["population"][key]

    if merged["idleVillagers"] is None:
        merged["idleVillagers"] = fallback["idleVillagers"]

    for resource in RESOURCE_ORDER:
        if merged["resources"][resource] is None:
            merged["resources"][resource] = fallback["resources"][resource]
        if merged["villagersOnResource"][resource] is None:
            merged["villagersOnResource"][resource] = fallback["villagersOnResource"][
                resource
            ]

    return merged


def read_resource_panel(frame, args):
    dynamic_panel, detected_groups, detection_attempts = detect_number_groups(frame, args)
    fixed_panel = read_resource_panel_fixed_fields(frame, args)
    panel = merge_panels(dynamic_panel, fixed_panel)

    if args.raw_fields:
        panel["rawFields"] = {
            "detectedGroups": detected_groups,
            "detectionAttempts": detection_attempts,
            "fixedFieldFallback": fixed_panel.get("rawFields"),
        }

    return panel


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


def find_economy_queue_tiles(frame):
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
    tile_size = min(PRODUCTION_QUEUE_TILE_SIZE, frame.shape[0], frame.shape[1])
    row_y = frame.shape[0] - tile_size
    if tile_size < PRODUCTION_QUEUE_TILE_SIZE:
        return tiles

    tile_area = tile_size * tile_size
    for x in range(
        PRODUCTION_QUEUE_LEFT_OFFSET,
        frame.shape[1] - tile_size + 1,
        PRODUCTION_QUEUE_SLOT_PITCH,
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


def crop_production_queue(frame):
    # Debug captures already contain the lower production half.
    if frame.shape[0] <= PRODUCTION_QUEUE_TILE_SIZE * 1.25:
        return frame
    return frame[frame.shape[0] // 2 :, :]


def match_villager_icon(frame, template_path, args):
    import cv2
    import numpy as np

    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"could not read villager template: {template_path}")

    queue_tiles = find_economy_queue_tiles(frame)
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
    best["shouldRemindVillager"] = not best["villagerQueued"]
    best["threshold"] = args.threshold
    return best


def save_villager_debug_image(frame, result, output_path):
    import cv2

    debug = frame.copy()
    for tile in result.get("queueTiles", []):
        x = tile["x"]
        y = tile["y"]
        width = tile["width"]
        height = tile["height"]
        cv2.rectangle(debug, (x, y), (x + width, y + height), (255, 255, 0), 1)

    match = result.get("match")
    color = (0, 255, 0) if result["villagerQueued"] else (0, 0, 255)
    if match:
        x = match["x"]
        y = match["y"]
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


class CalibrationApp:
    def __init__(self, args, monitor, screenshot_path, initial_rects):
        import tkinter as tk

        self.args = args
        self.monitor = monitor
        self.width = monitor["width"]
        self.height = monitor["height"]
        self.active = "resources"
        self.rects = {
            region: clamp_rect(initial_rects[region], self.width, self.height)
            for region in REGIONS
        }
        self.items = {}
        self.labels = {}
        self.handles = {}
        self.action = None
        self.start = None
        self.original_rect = None

        self.root = tk.Tk()
        self.root.title("AoE4 Reminder Calibration")
        self.root.geometry(
            f"{self.width}x{self.height}{monitor['left']:+d}{monitor['top']:+d}"
        )
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        self.background = tk.PhotoImage(file=str(screenshot_path))
        self.canvas.create_image(0, 0, image=self.background, anchor="nw")

        self.status = self.canvas.create_text(
            16,
            16,
            anchor="nw",
            fill="white",
            font=("Segoe UI", 14, "bold"),
            text="1 resources | 2 age+timer | 3 queue | drag move | corner resize | blank redraw | s save | q quit",
        )

        self.draw_all()
        self.bind_events()

    def bind_events(self):
        self.root.bind("1", lambda _event: self.select("resources"))
        self.root.bind("2", lambda _event: self.select("ageAndTimer"))
        self.root.bind("3", lambda _event: self.select("globalQueue"))
        self.root.bind("s", lambda _event: self.save())
        self.root.bind("S", lambda _event: self.save())
        self.root.bind("q", lambda _event: self.root.destroy())
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def select(self, region):
        self.active = region
        self.draw_all()

    def draw_all(self):
        for item_id in list(self.items.values()):
            self.canvas.delete(item_id)
        for item_id in list(self.labels.values()):
            self.canvas.delete(item_id)
        for item_id in list(self.handles.values()):
            self.canvas.delete(item_id)

        self.items.clear()
        self.labels.clear()
        self.handles.clear()

        for region in REGIONS:
            self.draw_region(region)

        self.canvas.tag_raise(self.status)

    def draw_region(self, region):
        x, y, width, height = self.rects[region]
        color = COLORS[region]
        line_width = 4 if region == self.active else 2
        dash = "" if region == self.active else (4, 4)

        self.items[region] = self.canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            outline=color,
            width=line_width,
            dash=dash,
        )
        self.labels[region] = self.canvas.create_text(
            x + 8,
            y + 8,
            anchor="nw",
            fill=color,
            font=("Segoe UI", 13, "bold"),
            text=f"{region} [{x},{y},{width},{height}]",
        )
        self.handles[region] = self.canvas.create_rectangle(
            x + width - 10,
            y + height - 10,
            x + width + 2,
            y + height + 2,
            fill=color,
            outline="black",
        )

    def hit_handle(self, px, py, region):
        x, y, width, height = self.rects[region]
        return abs(px - (x + width)) <= 14 and abs(py - (y + height)) <= 14

    def hit_rect(self, px, py, region):
        x, y, width, height = self.rects[region]
        return x <= px <= x + width and y <= py <= y + height

    def on_press(self, event):
        px = max(0, min(event.x, self.width - 1))
        py = max(0, min(event.y, self.height - 1))

        for region in REGIONS:
            if self.hit_handle(px, py, region):
                self.select(region)
                self.action = "resize"
                self.start = (px, py)
                self.original_rect = list(self.rects[region])
                return

        for region in REGIONS:
            if self.hit_rect(px, py, region):
                self.select(region)
                self.action = "move"
                self.start = (px, py)
                self.original_rect = list(self.rects[region])
                return

        self.action = "draw"
        self.start = (px, py)
        self.original_rect = [px, py, 1, 1]
        self.rects[self.active] = list(self.original_rect)
        self.draw_all()

    def on_drag(self, event):
        if not self.action:
            return

        px = max(0, min(event.x, self.width - 1))
        py = max(0, min(event.y, self.height - 1))
        start_x, start_y = self.start
        x, y, width, height = self.original_rect

        if self.action == "move":
            dx = px - start_x
            dy = py - start_y
            self.rects[self.active] = clamp_rect(
                [x + dx, y + dy, width, height], self.width, self.height
            )
        elif self.action == "resize":
            self.rects[self.active] = clamp_rect(
                [x, y, max(1, width + px - start_x), max(1, height + py - start_y)],
                self.width,
                self.height,
            )
        elif self.action == "draw":
            left = min(start_x, px)
            top = min(start_y, py)
            right = max(start_x, px)
            bottom = max(start_y, py)
            self.rects[self.active] = clamp_rect(
                [left, top, max(1, right - left), max(1, bottom - top)],
                self.width,
                self.height,
            )

        self.draw_all()

    def on_release(self, _event):
        self.action = None
        self.start = None
        self.original_rect = None

    def save(self):
        output_path = Path(self.args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        regions = {}
        for region, rect in self.rects.items():
            x, y, width, height = rect
            regions[region] = [
                int(x + self.monitor["left"]),
                int(y + self.monitor["top"]),
                int(width),
                int(height),
            ]

        payload = {
            "resolution": f"{self.width}x{self.height}",
            "uiScale": self.args.ui_scale,
            "monitor": self.args.monitor,
            "regions": regions,
        }

        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

        print(f"Saved calibration -> {output_path}", file=sys.stderr)
        print(json.dumps(payload, indent=2))
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def command_calibrate(args):
    import mss

    screenshot_path = Path(args.screenshot)

    if args.source_image:
        screenshot_path = Path(args.source_image)
        if not screenshot_path.exists():
            raise RuntimeError(f"source image not found: {screenshot_path}")
        width, height = get_image_size(screenshot_path)
        monitor = {
            "left": 0,
            "top": 0,
            "width": width,
            "height": height,
        }
        print(f"Using calibration image: {screenshot_path}", file=sys.stderr)
    else:
        with mss.mss() as screen_capture:
            monitors = screen_capture.monitors
            if args.monitor < 0 or args.monitor >= len(monitors):
                raise RuntimeError(
                    f"monitor {args.monitor} is unavailable. "
                    f"mss reported {len(monitors) - 1} monitor(s)."
                )
            monitor = dict(monitors[args.monitor])

        wait_before_capture(args.delay)
        capture_monitor_to_png(monitor, screenshot_path)
        print(f"Captured calibration screenshot -> {screenshot_path}", file=sys.stderr)

    config = load_json(Path(args.output)) or load_json(Path(args.seed)) or {}
    fallback = default_regions(monitor["width"], monitor["height"])
    initial_rects = {}

    for region in REGIONS:
        initial_rects[region] = rect_from_config(config, region, monitor) or fallback[region]

    app = CalibrationApp(args, monitor, screenshot_path, initial_rects)
    app.run()
    return 0


def command_capture(args):
    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rect = resolve_rect(args)
    source_path = output_dir / f"{args.region}-{timestamp}.png"
    capture_region_to_png(rect, source_path)
    print(f"Captured {args.region} {rect} -> {source_path}", file=sys.stderr)
    print(json.dumps({"region": args.region, "source": str(source_path)}, indent=2))
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


def read_queue_frame(args):
    import cv2

    if args.source_image:
        frame = cv2.imread(str(Path(args.source_image)), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"could not read source image: {args.source_image}")
        return crop_production_queue(frame)

    rect = args.rect or load_region(Path(args.config), "globalQueue")
    return crop_production_queue(grab_region_bgr(rect))


def villager_payload(result, elapsed_ms, state_changed=None):
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reader": VILLAGER_READER,
        "villagerQueued": result["villagerQueued"],
        "shouldRemindVillager": result["shouldRemindVillager"],
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
    result = match_villager_icon(frame, Path(args.template), args)
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
        rect = args.rect or load_region(Path(args.config), "globalQueue")
        print(
            f"Watching globalQueue region {rect}. Press Ctrl+C to stop.",
            file=sys.stderr,
        )

    try:
        while True:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            started = time.perf_counter()
            frame = read_queue_frame(args)
            result = match_villager_icon(frame, Path(args.template), args)
            elapsed_ms = (time.perf_counter() - started) * 1000
            state_changed = (
                previous_queued is not None
                and previous_queued != result["villagerQueued"]
            )
            previous_queued = result["villagerQueued"]

            if args.debug_images:
                raw_path = output_dir / f"queue-{timestamp}.png"
                debug_path = output_dir / f"queue-{timestamp}-villager.png"
                cv2.imwrite(str(raw_path), frame)
                save_villager_debug_image(frame, result, debug_path)

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


def command_watch_resources(args):
    import cv2

    rect = load_region(Path(args.config), "resources")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.source_image:
        print(f"Reading resource panel from image {args.source_image}.", file=sys.stderr)
    else:
        print(
            f"Watching resources region {rect}. Press Ctrl+C to stop.",
            file=sys.stderr,
        )

    try:
        while True:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            file_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            if args.source_image:
                frame = cv2.imread(str(Path(args.source_image)), cv2.IMREAD_COLOR)
                if frame is None:
                    raise RuntimeError(f"could not read source image: {args.source_image}")
            else:
                frame = grab_region_bgr(rect)

            panel = read_resource_panel(frame, args)

            if args.debug_images:
                raw_path = output_dir / f"resources-{file_timestamp}.png"
                cv2.imwrite(str(raw_path), frame)

            payload = {
                "timestamp": timestamp,
                "reader": RESOURCE_READER,
                "resourceOrder": list(RESOURCE_ORDER),
                **panel,
            }
            print(json.dumps(payload), flush=True)
            if args.once or args.source_image:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped resource watcher.", file=sys.stderr)
        return 0


def comparable_panel(panel):
    return {
        "population": panel["population"],
        "idleVillagers": panel["idleVillagers"],
        "resources": panel["resources"],
        "villagersOnResource": panel["villagersOnResource"],
    }


def command_test_resources(args):
    import cv2

    fixture_dir = Path(args.fixture_dir)
    expected_path = fixture_dir / "expected.json"
    expected = load_json(expected_path)
    if expected is None:
        raise RuntimeError(f"expected fixture data not found: {expected_path}")

    failures = []
    results = {}

    for image_name, expected_panel in expected.items():
        image_path = fixture_dir / image_name
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            failures.append({"image": image_name, "error": "could not read image"})
            continue

        panel = comparable_panel(read_resource_panel(frame, args))
        passed = panel == expected_panel
        results[image_name] = {
            "passed": passed,
            "actual": panel,
            "expected": expected_panel,
        }
        if not passed:
            failures.append(results[image_name])

    print(json.dumps(results, indent=2))
    if failures:
        return 1

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

        result = match_villager_icon(crop_production_queue(frame), template_path, args)
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
