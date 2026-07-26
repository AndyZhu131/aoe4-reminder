import json
import sys
from pathlib import Path

from .common import (
    COLORS,
    REGIONS,
    capture_monitor_to_png,
    clamp_rect,
    default_regions,
    get_image_size,
    load_json,
    rect_from_config,
    wait_before_capture,
)


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
