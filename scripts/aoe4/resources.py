import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .common import grab_region_bgr, load_json, load_region
from .paths import bundled_path


RESOURCE_ORDER = ("food", "wood", "gold", "stone")
RESOURCE_READER = "tesseract-position"
MAX_REASONABLE_POPULATION = 250
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
        bundled_path("tesseract", "tesseract.exe"),
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
