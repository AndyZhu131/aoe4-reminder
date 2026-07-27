import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .common import (
    grab_region_bgr,
    load_json,
    load_region,
    run_windows_hotkey_session,
)


RESEARCH_READER = "tech-template-catalog"
DEFAULT_TECH_CATALOG = "data/technologies.json"
DEFAULT_TECH_TEMPLATE_ROOT = "templates/tech"
RESEARCH_CAPTURE_RECTS = {
    "top": (10, 10, 48, 46),
    "bottom": (10, 66, 48, 46),
}


def extract_research_capture(source_path, output_path, row):
    import cv2

    frame = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"could not read queue capture: {source_path}")

    x, y, width, height = RESEARCH_CAPTURE_RECTS[row]
    if x + width > frame.shape[1] or y + height > frame.shape[0]:
        raise RuntimeError(
            f"queue capture is too small for the {row} research slot: {source_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame[y : y + height, x : x + width]):
        raise RuntimeError(f"could not write research icon capture: {output_path}")

    return {"x": x, "y": y, "width": width, "height": height}


def crop_research_queue(frame):
    # Research moves into the lower production row when no units are queued.
    # Search the complete calibrated queue regardless of the current layout.
    return frame

def load_technology_catalog(catalog_path, template_root, categories, civilizations=None):
    catalog = load_json(catalog_path)
    if catalog is None:
        raise RuntimeError(f"technology catalog not found: {catalog_path}")

    root = Path(template_root or catalog.get("templatesRoot") or DEFAULT_TECH_TEMPLATE_ROOT)
    if not root.is_absolute():
        root = catalog_path.parent.parent / root

    category_filter = set(categories or [])
    civilization_filter = {civilization.lower() for civilization in civilizations or []}
    technologies = []
    missing_templates = []

    for entry in catalog.get("technologies", []):
        if not entry.get("enabled", True):
            continue
        if category_filter and entry.get("category") not in category_filter:
            continue
        entry_civilization = entry.get("civilization", "sis").lower()
        if civilization_filter and entry_civilization not in civilization_filter:
            continue

        templates = []
        for template_name in entry.get("templates", []):
            template_path = root / template_name
            if template_path.exists():
                templates.append(template_path)
            else:
                missing_templates.append(
                    {
                        "key": entry.get("key"),
                        "template": str(template_path),
                    }
                )

        technologies.append(
            {
                "key": entry["key"],
                "displayName": entry.get("displayName", entry["key"]),
                "category": entry.get("category", "unknown"),
                "civilization": entry_civilization,
                "ageAvailable": entry.get("ageAvailable"),
                "building": entry.get("building"),
                "templates": templates,
            }
        )

    return technologies, missing_templates

def parse_categories(value):
    categories = [part.strip() for part in value.split(",") if part.strip()]
    if not categories:
        raise argparse.ArgumentTypeError("at least one category is required")
    return categories

def research_template_mask(template, border_mask_ratio):
    import cv2
    import numpy as np

    height, width = template.shape[:2]
    # The teal queue tile is common to every icon. Mask it out so matches are
    # driven by the technology artwork rather than a mostly identical backdrop.
    background = np.median(template.reshape(-1, 3), axis=0)
    difference = np.max(
        np.abs(template.astype(np.int16) - background.astype(np.int16)),
        axis=2,
    )
    mask = np.where(difference >= 32, 255, 0).astype(np.uint8)
    border_x = round(width * border_mask_ratio)
    border_y = round(height * border_mask_ratio)
    if border_x > 0:
        mask[:, :border_x] = 0
        mask[:, width - border_x :] = 0
    if border_y > 0:
        mask[:border_y, :] = 0
        mask[height - border_y :, :] = 0
    # Queue progress pips vary by research state and are not part of the icon.
    mask[: round(height * 0.28), round(width * 0.58) :] = 0
    return cv2.merge([mask, mask, mask])


def rect_center(rect):
    return (rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)

def rect_iou(left, right):
    left_x2 = left["x"] + left["width"]
    left_y2 = left["y"] + left["height"]
    right_x2 = right["x"] + right["width"]
    right_y2 = right["y"] + right["height"]

    overlap_x1 = max(left["x"], right["x"])
    overlap_y1 = max(left["y"], right["y"])
    overlap_x2 = min(left_x2, right_x2)
    overlap_y2 = min(left_y2, right_y2)
    if overlap_x2 <= overlap_x1 or overlap_y2 <= overlap_y1:
        return 0.0

    overlap_area = (overlap_x2 - overlap_x1) * (overlap_y2 - overlap_y1)
    left_area = left["width"] * left["height"]
    right_area = right["width"] * right["height"]
    return overlap_area / (left_area + right_area - overlap_area)

def is_duplicate_detection(candidate, accepted, min_distance):
    candidate_center = rect_center(candidate["match"])
    accepted_center = rect_center(accepted["match"])
    distance = (
        (candidate_center[0] - accepted_center[0]) ** 2
        + (candidate_center[1] - accepted_center[1]) ** 2
    ) ** 0.5
    return distance < min_distance or rect_iou(candidate["match"], accepted["match"]) > 0.35

def suppress_research_detections(candidates, min_distance, max_detections):
    accepted = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if any(is_duplicate_detection(candidate, existing, min_distance) for existing in accepted):
            continue
        accepted.append(candidate)
        if max_detections and len(accepted) >= max_detections:
            break
    return sorted(accepted, key=lambda item: (item["match"]["y"], item["match"]["x"]))

def match_research_technologies(frame, technologies, args):
    import cv2
    import numpy as np

    candidates = []
    loaded_template_count = 0

    for technology in technologies:
        for template_path in technology["templates"]:
            template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
            if template is None:
                continue
            loaded_template_count += 1

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
                if width > frame.shape[1] or height > frame.shape[0]:
                    continue

                mask = research_template_mask(scaled_template, args.border_mask_ratio)
                result = cv2.matchTemplate(
                    frame,
                    scaled_template,
                    cv2.TM_CCORR_NORMED,
                    mask=mask,
                )
                result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
                ys, xs = np.where(result >= args.threshold)
                for x, y in zip(xs, ys):
                    candidates.append(
                        {
                            "key": technology["key"],
                            "displayName": technology["displayName"],
                            "category": technology["category"],
                            "ageAvailable": technology["ageAvailable"],
                            "building": technology["building"],
                            "score": float(result[y, x]),
                            "scale": scale,
                            "template": str(template_path),
                            "match": {
                                "x": int(x),
                                "y": int(y),
                                "width": int(width),
                                "height": int(height),
                            },
                        }
                    )

    detections = suppress_research_detections(
        candidates,
        args.min_distance,
        args.max_detections,
    )
    return {
        "researching": [
            {
                **detection,
                "score": round(detection["score"], 4),
            }
            for detection in detections
        ],
        "candidateCount": len(candidates),
        "loadedTemplateCount": loaded_template_count,
        "threshold": args.threshold,
    }

def save_research_debug_image(frame, result, output_path):
    import cv2

    debug = frame.copy()
    for detection in result.get("researching", []):
        match = detection["match"]
        x = match["x"]
        y = match["y"]
        width = match["width"]
        height = match["height"]
        cv2.rectangle(debug, (x, y), (x + width, y + height), (0, 255, 0), 2)
        label = f"{detection['key']} {detection['score']:.3f}"
        cv2.putText(
            debug,
            label,
            (x, max(12, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), debug)

def read_research_frame(args):
    import cv2

    if args.source_image:
        frame = cv2.imread(str(Path(args.source_image)), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"could not read source image: {args.source_image}")
        return crop_research_queue(frame)

    rect = args.rect or load_region(Path(args.config), "globalQueue")
    return crop_research_queue(grab_region_bgr(rect))

def research_payload(result, elapsed_ms, missing_templates, state_changed=None):
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reader": RESEARCH_READER,
        "researching": result["researching"],
        "detectedKeys": [detection["key"] for detection in result["researching"]],
        "candidateCount": result["candidateCount"],
        "loadedTemplateCount": result["loadedTemplateCount"],
        "threshold": result["threshold"],
        "elapsedMs": round(elapsed_ms, 2),
    }
    if missing_templates:
        payload["missingTemplates"] = missing_templates
    if state_changed is not None:
        payload["stateChanged"] = state_changed
    return payload

def command_match_research(args):
    import cv2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    technologies, missing_templates = load_technology_catalog(
        Path(args.catalog),
        args.template_root,
        args.categories,
        [args.civilization],
    )

    started = time.perf_counter()
    frame = read_research_frame(args)
    result = match_research_technologies(frame, technologies, args)
    elapsed_ms = (time.perf_counter() - started) * 1000

    if args.debug_images:
        raw_path = output_dir / f"research-{timestamp}.png"
        debug_path = output_dir / f"research-{timestamp}-matches.png"
        cv2.imwrite(str(raw_path), frame)
        save_research_debug_image(frame, result, debug_path)
        result["sourceImage"] = str(raw_path)
        result["debugImage"] = str(debug_path)

    if not args.show_missing_templates:
        missing_templates = []

    print(json.dumps(research_payload(result, elapsed_ms, missing_templates), indent=2))
    return 0

def command_watch_research(args):
    import cv2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_keys = None
    technologies, missing_templates = load_technology_catalog(
        Path(args.catalog),
        args.template_root,
        args.categories,
        [args.civilization],
    )

    if args.source_image:
        print(f"Reading research queue from image {args.source_image}.", file=sys.stderr)
    else:
        rect = args.rect or load_region(Path(args.config), "globalQueue")
        print(
            f"Watching both rows of globalQueue region {rect}. Press Ctrl+C to stop.",
            file=sys.stderr,
        )

    if not args.show_missing_templates:
        missing_templates = []

    try:
        while True:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            started = time.perf_counter()
            frame = read_research_frame(args)
            result = match_research_technologies(frame, technologies, args)
            elapsed_ms = (time.perf_counter() - started) * 1000
            detected_keys = tuple(detection["key"] for detection in result["researching"])
            state_changed = previous_keys is not None and previous_keys != detected_keys
            previous_keys = detected_keys

            if args.debug_images:
                raw_path = output_dir / f"research-{timestamp}.png"
                debug_path = output_dir / f"research-{timestamp}-matches.png"
                cv2.imwrite(str(raw_path), frame)
                save_research_debug_image(frame, result, debug_path)

            print(
                json.dumps(
                    research_payload(result, elapsed_ms, missing_templates, state_changed)
                ),
                flush=True,
            )
            if args.once or args.source_image:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped research watcher.", file=sys.stderr)
        return 0


def command_test_research_queue(args):
    import cv2

    output_dir = Path(args.output_dir)
    technologies, missing_templates = load_technology_catalog(
        Path(args.catalog),
        args.template_root,
        args.categories,
        [args.civilization],
    )
    if not args.show_missing_templates:
        missing_templates = []

    rect = args.rect or load_region(Path(args.config), "globalQueue")

    print(
        f"Research queue test ready for globalQueue region {rect}. Press Ctrl+Alt+S "
        "to capture and classify it. Press Ctrl+C to stop.",
        file=sys.stderr,
    )

    def identify_queue_capture():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        source_path = output_dir / f"globalQueue-{timestamp}.png"
        debug_path = output_dir / f"globalQueue-{timestamp}-matches.png"
        frame = crop_research_queue(grab_region_bgr(rect))
        output_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(source_path), frame)

        started = time.perf_counter()
        result = match_research_technologies(frame, technologies, args)
        elapsed_ms = (time.perf_counter() - started) * 1000
        save_research_debug_image(frame, result, debug_path)

        payload = research_payload(result, elapsed_ms, missing_templates)
        payload["capture"] = "globalQueue"
        payload["region"] = rect
        payload["sourceImage"] = str(source_path)
        payload["debugImage"] = str(debug_path)
        print(json.dumps(payload, indent=2), flush=True)

    def identify_on_hotkey():
        try:
            identify_queue_capture()
        except Exception as exc:
            print(f"research queue test failed: {exc}", file=sys.stderr)

    try:
        run_windows_hotkey_session(identify_on_hotkey)
    except KeyboardInterrupt:
        print("Stopped research queue test.", file=sys.stderr)
    return 0
