import ctypes
import math
import os
import time
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog
from tkinter import font as tkfont

from .hotkeys import HotkeyListener
from .performance import ResourceGovernor
from .screens import virtual_bounds, work_area_at
from .sensors import NAMES, SensorReader, estimated_component_power, primary
from .settings import Settings, resource_dir
from .themes import PRESETS, ROLES, TRANSPARENT, normalize_hex, resolve_theme

KEY = TRANSPARENT
# Layout sizes at 100% text size; the widget multiplies them by text_scale.
PAD, ROW, GAUGE_ROW, HEADER, FOOTER = 10, 25, 30, 27, 15
GROUP_HEADER, SUMMARY, GAUGE = 18, 44, 22
CELL_W, CELL_H = 132, 50
COMPACT_WIDTH = 208
MIN_EXPANDED_WIDTH, MIN_EXPANDED_HEIGHT = 280, 180
TEXT_SIZES = (0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)
TRIMS_PER_RECLAIM = 10   # redraws between working-set reclaims (~30s)
ROLE_LABELS = {
    "panel": "Panel", "border": "Border", "text": "Text", "dim": "Muted",
    "accent": "Accent", "cold": "Cool", "warm": "Warm", "hot": "Hot",
}


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class Widget:
    """UI redraws only when sensor data or state changes (normally every 3s)."""

    def __init__(self):
        ResourceGovernor.enable()
        self.settings = Settings()
        self.colors = resolve_theme(self.settings["theme"], self.settings["custom_themes"])
        self.visible = not self.settings["start_hidden"]
        self.dirty = True
        self.last_revision = -1
        self.size = (0, 0)
        self._trims_due = 1
        self.scroll = 0
        self._max_scroll = 0
        self._header_hits = []
        self._scroll_track = None
        self._scroll_drag = False
        self._scroll_grab = None
        self._resize_drag = False
        self._moved = False
        self._last_header_click = 0.0
        self._last_header_name = None
        self._font_cache = {}
        self._grid = (1, 1, 1)
        self._click_applied = False
        self._apply_scale()

        self.reader = SensorReader(self.settings["refresh"])
        if self.reader.open():
            self.reader.start()

        self.root = tk.Tk()
        self.root.title("Pyrometer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.settings["alpha"])
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        icon = os.path.join(resource_dir(), "icon.ico")
        if os.path.exists(icon):
            try:
                self.root.iconbitmap(icon)
            except tk.TclError:
                pass
        self.canvas = tk.Canvas(self.root, bg=KEY, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        x, y = self.settings["x"], self.settings["y"]
        if x is None or y is None:
            x, y = self.root.winfo_screenwidth() - self.compact_width - 24, 48
        self.position = [int(x), int(y)]
        self._bind_ui()
        self._build_menu()
        self._start_hotkeys()
        self.reader.set_paused(not self.visible)
        if not self.visible:
            self.root.withdraw()
        self._loop()

    def _bind_ui(self):
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Control-MouseWheel>", self._zoom_wheel)
        self.canvas.bind("<Motion>", self._update_cursor)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.root.bind("<Escape>", lambda _event: self.toggle_visible())
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    def _menu_style(self):
        return dict(tearoff=0, bg=self.colors["panel"], fg=self.colors["text"],
                    activebackground=self.colors["accent"],
                    activeforeground=self.colors["panel"], bd=0,
                    font=self._font("Segoe UI", 9))

    def _build_menu(self):
        if getattr(self, "menu", None) is not None:
            self.menu.destroy()
        style = self._menu_style()
        self.menu = tk.Menu(self.root, **style)
        self.menu.add_command(label="Expand / collapse   Ctrl+Alt+E",
                              command=self.toggle_expanded)
        self.menu.add_command(label="Hide                Ctrl+Alt+T",
                              command=self.toggle_visible)
        self.menu.add_command(label="Click-through       Ctrl+Alt+L",
                              command=self.toggle_click_through)
        self.menu.add_separator()
        opacity = tk.Menu(self.menu, **style)
        for percent in (100, 90, 75, 60):
            opacity.add_command(label=f"{percent}%",
                                command=lambda p=percent: self.set_alpha(p / 100))
        self.menu.add_cascade(label="Opacity", menu=opacity)
        text_size = tk.Menu(self.menu, **style)
        for scale in TEXT_SIZES:
            mark = "●  " if abs(scale - self.scale) < 0.01 else "    "
            text_size.add_command(label=f"{mark}{scale * 100:.0f}%",
                                  command=lambda s=scale: self.set_text_scale(s))
        text_size.add_separator()
        text_size.add_command(label="Ctrl + mouse wheel to adjust", state="disabled")
        self.menu.add_cascade(label="Text size", menu=text_size)
        power = tk.Menu(self.menu, **style)
        watts = self.settings["psu_watts"]
        psu_name = self.settings["psu_name"]
        label = (f"{psu_name} · {watts} W" if watts and psu_name
                 else f"PSU capacity: {watts} W" if watts else "Set PSU capacity…")
        power.add_command(label=label, command=self._set_psu_capacity)
        if watts:
            power.add_command(label="Clear PSU capacity", command=self._clear_psu_capacity)
        power.add_separator()
        power.add_command(label="About power estimates", command=self._power_info)
        self.menu.add_cascade(label="Power", menu=power)
        themes = tk.Menu(self.menu, **style)
        customs = self.settings["custom_themes"]
        for name in PRESETS:
            themes.add_command(label=self._theme_label(name),
                               command=lambda n=name: self.apply_theme(n))
        if customs:
            themes.add_separator()
            for name in customs:
                themes.add_command(label=self._theme_label(name),
                                   command=lambda n=name: self.apply_theme(n))
        themes.add_separator()
        themes.add_command(label="New custom theme…", command=self._new_theme)
        if self.settings["theme"] in customs:
            themes.add_command(label="Edit theme…", command=self._edit_theme)
            themes.add_command(label="Delete theme…", command=self._delete_theme)
        self.menu.add_cascade(label="Themes", menu=themes)
        self.menu.add_separator()
        self.menu.add_command(label="Quit                 Ctrl+Alt+Q", command=self.quit)

    def _start_hotkeys(self):
        bindings = {
            "toggle": self.settings["hotkey_toggle"],
            "expand": self.settings["hotkey_expand"],
            "lock": self.settings["hotkey_lock"],
            "quit": self.settings["hotkey_quit"],
        }
        self.hotkeys = HotkeyListener(bindings)
        self.hotkeys.start()

    def _loop(self):
        action = self.hotkeys.pop()
        while action:
            {"toggle": self.toggle_visible, "expand": self.toggle_expanded,
             "lock": self.toggle_click_through, "quit": self.quit}[action]()
            if action == "quit":
                return
            action = self.hotkeys.pop()
        if self.visible and (self.dirty or self.last_revision != self.reader.revision):
            self.last_revision = self.reader.revision
            self._draw()
            self.dirty = False
            self._trims_due -= 1
            if self._trims_due <= 0:
                # Startup and hardware scans leave pages resident that are never
                # touched again; hand them back between redraws.
                self._trims_due = TRIMS_PER_RECLAIM
                ResourceGovernor.trim()
        self.root.after(200, self._loop)

    def _apply_scale(self):
        self.scale = self.settings["text_scale"]
        s = self._s
        self.pad, self.row, self.gauge_row = s(PAD), s(ROW), s(GAUGE_ROW)
        self.header, self.footer = s(HEADER), s(FOOTER)
        self.group_header, self.summary_h = s(GROUP_HEADER), s(SUMMARY)
        self.gauge = s(GAUGE)
        self.compact_width = s(COMPACT_WIDTH)
        self.min_width, self.min_height = s(MIN_EXPANDED_WIDTH), s(MIN_EXPANDED_HEIGHT)

    def _s(self, pixels):
        return int(round(pixels * self.scale))

    def _font(self, family, size, *styles):
        return (family, max(6, int(round(size * self.scale))), *styles)

    def _fit(self, text, font, width):
        """Trim text with an ellipsis so it never runs into the reading."""
        if self._fit_width(text, font) <= width:
            return text
        while text and self._fit_width(text + "…", font) > width:
            text = text[:-1]
        return text + "…" if text else ""

    def _expanded_width(self):
        return max(self.min_width, self.settings["expanded_width"])

    def set_text_scale(self, scale):
        scale = max(TEXT_SIZES[0], min(TEXT_SIZES[-1], round(scale, 2)))
        if abs(scale - self.scale) < 0.001:
            return
        self.settings["text_scale"] = scale
        self._apply_scale()
        self._font_cache.clear()
        self._persist()
        self._refresh()
        self.root.after_idle(self._build_menu)

    def _zoom_wheel(self, event):
        if not event.delta:
            return
        index = min(range(len(TEXT_SIZES)), key=lambda i: abs(TEXT_SIZES[i] - self.scale))
        index += 1 if event.delta > 0 else -1
        self.set_text_scale(TEXT_SIZES[max(0, min(len(TEXT_SIZES) - 1, index))])

    def _temp_color(self, value):
        if value is None:
            return self.colors["dim"]
        if value < 50:
            return self.colors["cold"]
        if value < 75:
            return self.colors["warm"]
        return self.colors["hot"]

    def _draw(self):
        groups = self.reader.snapshot
        expanded = self.settings["expanded"]
        width = self._expanded_width() if expanded else self.compact_width
        self._header_hits = []
        self._scroll_track = None
        self._max_scroll = 0
        chrome = self.header + self.footer + 8
        saved_height = self.settings["expanded_height"] if expanded else None
        if self.reader.error or not groups:
            body = self.row * 2
        elif expanded:
            content = self._expanded_content_height(groups, width)
            # The extra 5px is the gap already subtracted from the viewport,
            # so a list that fits does not grow a scrollbar.
            body = min(content + 5, self._max_body())
        else:
            body = self.row * self._compact_rows(groups)
        if saved_height is not None:
            body = min(self._max_body(), max(self.min_height, saved_height) - chrome)
        self.size = (width, chrome + body)
        self._place()

        pad = self.pad
        canvas = self.canvas
        canvas.delete("all")
        self._panel(width, self.size[1])
        title_y = self.header // 2
        canvas.create_text(pad, title_y, text="PYROMETER", anchor="w",
                           fill=self.colors["accent"],
                           font=self._font("Segoe UI Semibold", 9))
        hottest = max((s[1] for g in groups for s in g["sensors"]
                       if s[2] == "Temperature" and s[1] is not None),
                      default=None)
        if hottest is not None:
            canvas.create_text(width - pad, title_y, text=f"{hottest:.0f}°", anchor="e",
                               fill=self._temp_color(hottest),
                               font=self._font("Consolas", 11, "bold"))
        canvas.create_line(pad, self.header, width - pad, self.header,
                           fill=self.colors["border"])

        y = self.header + 8
        if self.reader.error:
            font = self._font("Segoe UI", 8)
            canvas.create_text(pad, y, text=self._fit("⚠ " + self.reader.error, font,
                                                      width - pad * 2),
                               anchor="nw", fill=self.colors["hot"], font=font)
        elif not groups:
            canvas.create_text(pad, y, text="reading sensors…", anchor="nw",
                               fill=self.colors["dim"], font=self._font("Segoe UI", 9))
        elif expanded:
            self._expanded(groups, width)
        else:
            self._compact(groups, y, width)
        self._footer(width)
        if expanded:
            self._resize_grip(width)

    def _max_body(self):
        """Tallest list that still ends inside the monitor work area."""
        _left, top, _width, work_h = work_area_at(*self.position)
        room = top + work_h - self.position[1] - 12
        chrome = self.header + self.footer + 8
        return max(self.group_header * 3, min(work_h - chrome - 12, room - chrome))

    def _grid_layout(self, width, inset):
        inner = max(1, width - self.pad * 2 - inset)
        cols = max(1, inner // max(1, self._s(CELL_W)))
        return cols, inner / cols, self._s(CELL_H)

    def _expanded_content_height(self, groups, width):
        collapsed = set(self.settings["collapsed"])

        def measure(inset):
            cols, cell_w, cell_h = self._grid_layout(width, inset)
            height = self.summary_h
            for group in groups:
                height += self.group_header
                if group["name"] not in collapsed and group["sensors"]:
                    height += math.ceil(len(group["sensors"]) / cols) * cell_h
            return height, (cols, cell_w, cell_h)

        height, layout = measure(4)
        if height + 5 > self._max_body():
            height, layout = measure(16)
        self._grid = layout
        return height

    def _compact_rows(self, groups):
        rows = sum(1 for group in groups if primary(group))
        if estimated_component_power(groups)[0] is not None or self.settings["psu_watts"]:
            rows += 1
        return rows

    def _compact(self, groups, y, width):
        disks = 0
        for group in groups:
            sensor = primary(group)
            if not sensor:
                continue
            label = NAMES.get(group["type"], group["type"][:4].upper())
            if label == "DISK":
                disks += 1
                label = f"DISK{disks}" if disks > 1 else label
            self._row(self.pad, y, width - self.pad * 2, label, sensor, True)
            y += self.row
        estimated, _parts = estimated_component_power(groups)
        if estimated is not None or self.settings["psu_watts"]:
            self._power_bar(self.pad, y, width - self.pad * 2, estimated)
        return y

    def _expanded(self, groups, width):
        pad = self.pad
        view_top = self.header + 8
        view_bottom = self.size[1] - self.footer - 5
        content = self._expanded_content_height(groups, width)
        visible = max(1, view_bottom - view_top)
        self._max_scroll = max(0, content - visible)
        self.scroll = max(0, min(self.scroll, self._max_scroll))
        collapsed = set(self.settings["collapsed"])
        inset = 16 if self._max_scroll else 4
        cols, cell_w, cell_h = self._grid
        cursor = view_top - self.scroll
        if view_top <= cursor and cursor + self.summary_h <= view_bottom:
            self._power_summary(groups, pad, cursor, width - pad * 2 - inset)
        cursor += self.summary_h
        for group in groups:
            header_y = cursor
            cursor += self.group_header
            if view_top <= header_y and header_y + self.group_header <= view_bottom:
                self._group_header(header_y, width, group, group["name"] in collapsed)
                self._header_hits.append(
                    (header_y, header_y + self.group_header, group["name"]))
            if group["name"] in collapsed:
                continue
            sensors = group["sensors"]
            for index, sensor in enumerate(sensors):
                row, col = divmod(index, cols)
                cell_x = pad + col * cell_w
                cell_y = cursor + row * cell_h
                if view_top <= cell_y and cell_y + cell_h <= view_bottom:
                    self._grid_cell(cell_x, cell_y, cell_w, cell_h, sensor)
            if sensors:
                cursor += math.ceil(len(sensors) / cols) * cell_h
        if self._max_scroll:
            self._scrollbar(width, view_top, view_bottom, visible, content)

    def _group_header(self, y, width, group, folded):
        pad, mid = self.pad, y + self.group_header // 2 - 1
        gutter = 12 if self._max_scroll else 0
        font = self._font("Segoe UI Semibold", 7)
        self.canvas.create_text(pad, mid, text="▶" if folded else "▼", anchor="w",
                                fill=self.colors["dim"], font=self._font("Segoe UI", 7))
        count = f"  {len(group['sensors'])}" if folded else ""
        room = width - pad * 2 - gutter - self._s(14)
        title = self._fit(group["name"].upper(), font, room - self._s(24)) + count
        self.canvas.create_text(pad + self._s(14), mid, text=title, anchor="w",
                                fill=self.colors["accent"], font=font)
        line_y = y + self.group_header - 2
        self.canvas.create_line(pad, line_y, width - pad - gutter, line_y,
                                fill=self.colors["border"])

    def _scrollbar(self, width, view_top, view_bottom, visible, content):
        track_h = view_bottom - view_top
        thumb_h = max(18, int(track_h * visible / content))
        thumb_h = min(thumb_h, track_h)
        travel = max(1, track_h - thumb_h)
        thumb_y = view_top + travel * (self.scroll / self._max_scroll)
        x = width - 8
        self.canvas.create_line(x, view_top + 2, x, view_bottom - 2,
                                fill=self.colors["border"], width=3)
        self.canvas.create_line(x, thumb_y, x, thumb_y + thumb_h,
                                fill=self.colors["accent"], width=3)
        self._scroll_track = (width - 16, view_top, view_bottom, thumb_h)

    def _row(self, x, y, width, label, sensor, bold=False):
        value = sensor[1]
        font = self._font("Segoe UI Semibold", 9) if bold else self._font("Segoe UI", 8)
        number = self._font("Consolas", 10, "bold") if bold else self._font("Segoe UI", 8)
        text_y, bar_y = y + self._s(8), y + self._s(19)
        self.canvas.create_text(x, text_y, text=label, anchor="w",
                                fill=self.colors["text"] if bold else self.colors["dim"],
                                font=font)
        self.canvas.create_text(x + width, text_y,
                                text="n/a" if value is None else f"{value:.0f}°C",
                                anchor="e", fill=self._temp_color(value), font=number)
        self.canvas.create_line(x, bar_y, x + width, bar_y, fill=self.colors["border"])
        if value is not None:
            end = x + max(2, int(min(value, 100) * width / 100))
            self.canvas.create_line(x, bar_y, end, bar_y,
                                    fill=self._temp_color(value), width=2)

    def _power_bar(self, x, y, width, estimated):
        """Compact-mode load bar for the CPU + GPU estimate against PSU capacity."""
        capacity = self.settings["psu_watts"]
        font = self._font("Segoe UI Semibold", 9)
        number = self._font("Consolas", 10, "bold")
        text_y, bar_y = y + self._s(8), y + self._s(19)
        if estimated is None:
            reading, color, ratio = "n/a", self.colors["dim"], 0
        elif capacity:
            ratio = estimated / capacity
            reading = f"{estimated:.0f}W"
            color = self._power_color(ratio)
        else:
            reading, color, ratio = f"{estimated:.0f}W", self.colors["accent"], 0
        self.canvas.create_text(x, text_y, text="PWR", anchor="w",
                                fill=self.colors["text"], font=font)
        self.canvas.create_text(x + width, text_y, text=reading, anchor="e",
                                fill=color, font=number)
        self.canvas.create_line(x, bar_y, x + width, bar_y, fill=self.colors["border"])
        if ratio > 0:
            end = x + max(2, int(min(ratio, 1) * width))
            self.canvas.create_line(x, bar_y, end, bar_y, fill=color, width=2)

    def _sensor_meter(self, sensor):
        name, value, kind = sensor
        unit = "°C" if kind == "Temperature" else "W"
        capacity = self.settings["psu_watts"]
        if kind == "Temperature":
            maximum = 100.0
        elif capacity:
            maximum = float(capacity)
        else:
            maximum = max(300.0, math.ceil((value or 0) / 50) * 50.0)
        ratio = 0.0 if value is None else max(0.0, min(1.0, value / maximum))
        if value is None:
            color = self.colors["dim"]
        elif kind == "Temperature":
            color = self._temp_color(value)
        elif capacity:
            color = self._power_color(ratio)
        else:
            color = self.colors["accent"]
        reading = "n/a" if value is None else f"{value:.0f}{unit}"
        return name, reading, ratio, color

    def _grid_cell(self, x, y, width, height, sensor):
        """Card: sensor name above, reading and dial on one line."""
        name, reading, ratio, color = self._sensor_meter(sensor)
        gap = self._s(4)
        self.canvas.create_rectangle(
            x + gap, y + gap, x + width - gap, y + height - gap,
            outline=self.colors["border"])
        name_font = self._font("Segoe UI", 8)
        value_font = self._font("Consolas", 10, "bold")
        size = min(self.gauge, height - self._s(18))
        inner_left = x + self._s(8)
        inner_right = x + width - self._s(8)
        dial_x = inner_right - size / 2
        name_y = y + self._s(14)
        value_y = y + height - self._s(16)
        self.canvas.create_text(
            inner_left, name_y,
            text=self._fit(name, name_font, width - self._s(16)),
            anchor="w", fill=self.colors["text"], font=name_font)
        self.canvas.create_text(
            dial_x - size / 2 - self._s(4), value_y, text=reading, anchor="e",
            fill=color, font=value_font)
        self._dial(dial_x, value_y, size, ratio, color)

    def _fit_width(self, text, font):
        measure = self._font_cache.get(font)
        if measure is None:
            measure = self._font_cache[font] = tkfont.Font(root=self.root, font=font)
        return measure.measure(text)

    def _dial(self, cx, cy, size, ratio, color):
        """270° dial that sweeps clockwise from the lower-left, like a speedometer."""
        radius = size / 2
        thickness = max(2, self._s(3))
        inset = thickness / 2
        box = (cx - radius + inset, cy - radius + inset,
               cx + radius - inset, cy + radius - inset)
        self.canvas.create_arc(*box, start=225, extent=-270, style="arc",
                               outline=self.colors["border"], width=thickness)
        if ratio > 0:
            self.canvas.create_arc(*box, start=225, extent=-270 * ratio, style="arc",
                                   outline=color, width=thickness)
        angle = math.radians(225 - 270 * ratio)
        needle = radius - thickness - self._s(2)
        self.canvas.create_line(cx, cy, cx + needle * math.cos(angle),
                                cy - needle * math.sin(angle),
                                fill=color, width=max(1, self._s(1.5)))
        hub = max(1.5, self._s(2))
        self.canvas.create_oval(cx - hub, cy - hub, cx + hub, cy + hub,
                                fill=color, outline="")

    def _power_color(self, ratio):
        if ratio < 0.70:
            return self.colors["cold"]
        if ratio < 0.85:
            return self.colors["warm"]
        return self.colors["hot"]

    def _power_summary(self, groups, x, y, width):
        estimated, _readings = estimated_component_power(groups)
        capacity = self.settings["psu_watts"]
        psu_name = self.settings["psu_name"]
        if estimated is None:
            title = "POWER TELEMETRY UNAVAILABLE"
            detail = (f"{psu_name} · {capacity}W · DRAW UNKNOWN" if capacity and psu_name
                      else f"PSU CAPACITY {capacity}W · DRAW UNKNOWN" if capacity
                      else "SET PSU CAPACITY FROM RIGHT-CLICK MENU")
            color = self.colors["dim"]
        elif capacity:
            ratio = estimated / capacity
            status = "NORMAL" if ratio < 0.70 else "ELEVATED" if ratio < 0.85 else "HIGH"
            title = f"EST. COMPONENT DRAW  {estimated:.0f}W / {capacity}W"
            headroom = capacity - estimated
            lead = f"{psu_name} · " if psu_name else ""
            detail = (f"{lead}{ratio * 100:.0f}% · {status} · "
                      f"EST. RATING HEADROOM {headroom:.0f}W")
            color = self._power_color(ratio)
        else:
            title = f"EST. COMPONENT DRAW  {estimated:.0f}W"
            detail = "CPU/GPU ESTIMATE · SET PSU CAPACITY FOR LOAD BAND"
            color = self.colors["accent"]
        s, inner = self._s, width - self._s(14)
        title_font = self._font("Segoe UI Semibold", 8)
        detail_font = self._font("Segoe UI", 7)
        self.canvas.create_rectangle(
            x, y + s(2), x + width, y + self.summary_h - s(5),
            fill=self.colors["panel"], outline=self.colors["border"])
        self.canvas.create_text(x + s(7), y + s(14), text=self._fit(title, title_font, inner),
                                anchor="w", fill=color, font=title_font)
        self.canvas.create_text(x + s(7), y + s(29),
                                text=self._fit(detail, detail_font, inner),
                                anchor="w", fill=self.colors["dim"], font=detail_font)

    def _panel(self, width, height):
        radius, points = 9, []
        for cx, cy, start in ((width - 9, 9, 0), (9, 9, 90),
                              (9, height - 9, 180), (width - 9, height - 9, 270)):
            for step in range(5):
                angle = math.radians(start + step * 22.5)
                points.extend((cx + radius * math.cos(angle),
                               cy - radius * math.sin(angle)))
        self.canvas.create_polygon(points, fill=self.colors["panel"],
                                   outline=self.colors["border"])

    def _grip_box(self):
        """Opaque corner inside the rounded edge. The outer pixels are transparent."""
        grip = self._s(26)
        inset = 10
        right, bottom = self.size
        return right - inset - grip, bottom - inset - grip, right - inset, bottom - inset

    def _resize_grip(self, width):
        x0, y0, x1, y1 = self._grip_box()
        color = self.colors["accent"]
        for step in range(3):
            offset = self._s(4 + step * 5)
            self.canvas.create_line(x1 - offset, y1 - self._s(3), x1 - self._s(3),
                                    y1 - offset, fill=color, width=2)

    def _footer(self, width):
        if not is_admin():
            note, warn = "no admin — limited sensors", True
        elif self.reader.missing:
            note, warn = "no " + "/".join(self.reader.missing) + " sensors", True
        elif self.settings["click_through"]:
            note, warn = "LOCKED · Ctrl+Alt+L to unlock", True
        elif self.settings["expanded"]:
            note, warn = "drag the corner lines to resize", False
        else:
            note, warn = "Ctrl+Alt+T hide  ·  Ctrl+Alt+E expand", False
        font = self._font("Segoe UI", 7)
        text_y = self.size[1] - self.footer // 2 - 1
        locked = self.settings["click_through"]
        room = width - self.pad * 2 - (self._s(50) if locked else self._s(14))
        self.canvas.create_text(self.pad, text_y, text=self._fit(note, font, room),
                                anchor="w",
                                fill=self.colors["warm"] if warn else self.colors["dim"],
                                font=font)
        if locked:
            self.canvas.create_text(width - self.pad, text_y, text="LOCKED",
                                    anchor="e", fill=self.colors["warm"], font=font)

    def _place(self):
        """Position against the whole virtual desktop so the widget can sit on
        any monitor, including ones at negative coordinates."""
        width, height = self.size
        left, top, span_x, span_y = virtual_bounds()
        x = max(left, min(self.position[0], left + span_x - width))
        y = max(top, min(self.position[1], top + span_y - height))
        self.position[:] = x, y
        self.canvas.config(width=width, height=height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        if not self._click_applied:
            self._click_applied = True
            if self.settings["click_through"]:
                self._apply_click_through(True)

    def _drag_start(self, event):
        self.root.focus_set()
        self._press_root = (event.x_root, event.y_root)
        self._moved = False
        self._resize_drag = self._resize_hit(event)
        if self._resize_drag:
            self._resize_origin = (
                event.x_root, event.y_root, self.size[0], self.size[1])
            return
        self._scroll_drag = self._scrollbar_hit(event)
        if self._scroll_drag:
            span = self._thumb_span()
            if span and span[0] <= event.y <= span[1]:
                self._scroll_grab = event.y - span[0]
            else:
                self._scroll_grab = None
                self._jump_scroll(event.y)
                self._refresh()
            return
        self.drag_offset = (event.x_root - self.position[0],
                            event.y_root - self.position[1])

    def _drag(self, event):
        if self._resize_drag:
            start_x, start_y, start_w, start_h = self._resize_origin
            _left, top, work_w, work_h = work_area_at(*self.position)
            max_h = max(self.min_height, top + work_h - self.position[1] - 8)
            self.settings["expanded_width"] = max(
                self.min_width,
                min(work_w - 8, start_w + event.x_root - start_x))
            self.settings["expanded_height"] = max(
                self.min_height,
                min(max_h, start_h + event.y_root - start_y))
            self._refresh()
            return
        if self._scroll_drag:
            if self._scroll_grab is None:
                self._jump_scroll(event.y)
            else:
                _x0, _top, _bottom, thumb_h = self._scroll_track
                self._jump_scroll(event.y - self._scroll_grab + thumb_h / 2)
            self._refresh()
            return
        if not self._moved:
            if (abs(event.x_root - self._press_root[0]) < 4
                    and abs(event.y_root - self._press_root[1]) < 4):
                return
            self._moved = True
        self.position[:] = (event.x_root - self.drag_offset[0],
                            event.y_root - self.drag_offset[1])
        self._place()

    def _release(self, event):
        if self._resize_drag:
            self._resize_drag = False
            self._persist()
            return
        if self._scroll_drag:
            self._scroll_drag = False
            return
        if self._moved:
            return
        name = self._header_at(event.x, event.y)
        if not name:
            return
        now = time.monotonic()
        if now - self._last_header_click < 0.45 and self._last_header_name == name:
            return
        self._last_header_click = now
        self._last_header_name = name
        self._toggle_group(name)

    def _on_double(self, event):
        # A double-click on a device header folds that device; it should not
        # also collapse the whole panel, even if the list jumps under the cursor.
        if time.monotonic() - self._last_header_click < 0.45:
            return
        if self._header_at(event.x, event.y) and event.y > self.header:
            return
        self.toggle_expanded()

    def _wheel(self, event):
        if not self.settings["expanded"] or self._max_scroll <= 0 or not event.delta:
            return
        step = self.gauge_row if event.delta < 0 else -self.gauge_row
        self.scroll = max(0, min(self._max_scroll, self.scroll + step))
        self._refresh()

    def _scrollbar_hit(self, event):
        track = self._scroll_track
        if not track or not self.settings["expanded"]:
            return False
        x0, top, bottom, _thumb_h = track
        return event.x >= x0 and top <= event.y <= bottom

    def _resize_hit(self, event):
        if not self.settings["expanded"] or self.size[0] <= 0:
            return False
        x0, y0, x1, y1 = self._grip_box()
        return x0 <= event.x <= x1 and y0 <= event.y <= y1

    def _update_cursor(self, event):
        self.canvas.configure(cursor="size_nw_se" if self._resize_hit(event) else "")

    def _jump_scroll(self, y):
        track = self._scroll_track
        if not track or self._max_scroll <= 0:
            return
        _x0, top, bottom, thumb_h = track
        usable = max(1, (bottom - top) - thumb_h)
        ratio = (y - top - thumb_h / 2) / usable
        self.scroll = max(0, min(self._max_scroll, ratio * self._max_scroll))

    def _header_at(self, x, y):
        if not self.settings["expanded"]:
            return None
        if self._scroll_track and x >= self._scroll_track[0]:
            return None
        for top, bottom, name in self._header_hits:
            if top <= y < bottom:
                return name
        return None

    def _toggle_group(self, name):
        collapsed = list(self.settings["collapsed"])
        if name in collapsed:
            collapsed.remove(name)
        else:
            collapsed.append(name)
        self.settings["collapsed"] = collapsed
        self._persist()
        self._refresh()

    def _refresh(self):
        if not self.visible:
            self.dirty = True
            return
        self._draw()
        self.last_revision = self.reader.revision
        self.dirty = False

    def _show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def toggle_visible(self):
        self.visible = not self.visible
        self.reader.set_paused(not self.visible)
        if self.visible:
            self.root.deiconify()
            self.root.lift()
            self.dirty = True
        else:
            self.root.withdraw()
            self.root.after(300, ResourceGovernor.trim)

    def toggle_expanded(self):
        self.settings["expanded"] = not self.settings["expanded"]
        if not self.settings["expanded"]:
            self.scroll = 0
        self.dirty = True

    def set_alpha(self, value):
        self.settings["alpha"] = value
        self.root.attributes("-alpha", value)

    def _set_psu_capacity(self):
        current = self.settings["psu_watts"] or 650
        self.root.attributes("-topmost", False)
        try:
            watts = simpledialog.askinteger(
                "PSU capacity",
                "Enter the rated wattage printed on the PSU label.\n"
                "This cannot be detected reliably by software:",
                parent=self.root, initialvalue=current, minvalue=100, maxvalue=3000)
        finally:
            self.root.attributes("-topmost", True)
            self.root.lift()
        if watts is None:
            return
        if watts != self.settings["psu_watts"]:
            self.settings["psu_name"] = ""
        self.settings["psu_watts"] = watts
        self._persist()
        self._refresh()
        self.root.after_idle(self._build_menu)

    def _clear_psu_capacity(self):
        self.settings["psu_watts"] = None
        self.settings["psu_name"] = ""
        self._persist()
        self._refresh()
        self.root.after_idle(self._build_menu)

    def _power_info(self):
        self.root.attributes("-topmost", False)
        try:
            messagebox.showinfo(
                "Power estimates",
                "Pyrometer can show power sensors reported by the CPU, GPU, "
                "motherboard, and other hardware.\n\n"
                "The summary adds one CPU package reading and one GPU board "
                "reading when available. It is not total wall power and may "
                "exclude the motherboard, drives, fans, conversion losses, "
                "and unsupported devices.\n\n"
                "A normal desktop PSU does not report its rated capacity. "
                "Enter the wattage printed on its physical label. For accurate "
                "whole-system draw, use a plug-in wall power meter.",
                parent=self.root)
        finally:
            self.root.attributes("-topmost", True)
            self.root.lift()

    def toggle_click_through(self):
        enabled = not self.settings["click_through"]
        self._apply_click_through(enabled)
        self.settings["click_through"] = enabled
        self.dirty = True

    def _apply_click_through(self, enabled):
        """64-bit Windows ignores the 32-bit style call, which left the lock stuck."""
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = user32.GetWindowLongPtrW(hwnd, -20)
        style = (style | 0x00080020) if enabled else (style & ~0x20)
        user32.SetWindowLongPtrW(hwnd, -20, style)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)

    def _theme_label(self, name):
        return ("●  " if name == self.settings["theme"] else "    ") + name

    def _thumb_span(self):
        track = self._scroll_track
        if not track or self._max_scroll <= 0:
            return None
        _x0, top, bottom, thumb_h = track
        travel = max(1, (bottom - top) - thumb_h)
        thumb_y = top + travel * (self.scroll / self._max_scroll)
        return thumb_y, thumb_y + thumb_h

    def apply_theme(self, name):
        if name not in PRESETS and name not in self.settings["custom_themes"]:
            name = "Default"
        self.settings["theme"] = name
        self.colors = resolve_theme(name, self.settings["custom_themes"])
        self._persist()
        self._refresh()
        # Rebuilding now would destroy the menu while its command is still running.
        self.root.after_idle(self._build_menu)

    def _theme_names(self):
        return set(PRESETS) | set(self.settings["custom_themes"])

    def _fresh_theme_name(self):
        taken = self._theme_names()
        if "Custom" not in taken:
            return "Custom"
        number = 2
        while f"Custom {number}" in taken:
            number += 1
        return f"Custom {number}"

    def _new_theme(self):
        result = ask_custom_theme(
            self.root, name=self._fresh_theme_name(), colors=self.colors,
            taken=self._theme_names(), title="New theme")
        if result:
            self._store_theme(None, *result)

    def _edit_theme(self):
        name = self.settings["theme"]
        colors = self.settings["custom_themes"].get(name)
        if not colors:
            return
        taken = self._theme_names() - {name}
        result = ask_custom_theme(self.root, name=name, colors=colors,
                                  taken=taken, title="Edit theme")
        if result:
            self._store_theme(name, *result)

    def _delete_theme(self):
        name = self.settings["theme"]
        customs = dict(self.settings["custom_themes"])
        if name not in customs:
            return
        self.root.attributes("-topmost", False)
        try:
            confirmed = messagebox.askyesno("Delete theme", f"Delete “{name}”?",
                                            parent=self.root)
        finally:
            self.root.attributes("-topmost", True)
            self.root.lift()
        if not confirmed:
            return
        del customs[name]
        self.settings["custom_themes"] = customs
        self.apply_theme("Default")

    def _store_theme(self, previous, name, colors):
        customs = dict(self.settings["custom_themes"])
        if previous and previous != name:
            customs.pop(previous, None)
        customs[name] = colors
        self.settings["custom_themes"] = customs
        self.apply_theme(name)

    def _persist(self):
        self.settings["x"], self.settings["y"] = self.position
        self.settings.save()

    def quit(self):
        self._persist()
        self.reader.close()
        self.hotkeys.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def ask_custom_theme(master, name, colors, taken, title):
    """Modal editor. Returns (name, colors) or None when cancelled."""
    dialog = tk.Toplevel(master)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.transient(master)
    dialog.configure(bg="#161b22")
    result = {"value": None}
    vars_ = {role: tk.StringVar(master=dialog, value=colors[role]) for role in ROLES}
    swatches = {}

    def paint(*_args):
        current = {}
        for role, var in vars_.items():
            parsed = normalize_hex(var.get())
            current[role] = parsed or colors[role]
            swatch = swatches.get(role)
            if swatch is not None:
                swatch.configure(bg=current[role])
        preview.delete("all")
        preview.create_rectangle(0, 0, 300, 72, fill=current["panel"],
                                 outline=current["border"])
        preview.create_text(12, 16, text="PYROMETER", anchor="w", fill=current["accent"],
                            font=("Segoe UI Semibold", 9))
        preview.create_text(288, 16, text="72°", anchor="e", fill=current["warm"],
                            font=("Consolas", 11, "bold"))
        preview.create_text(12, 40, text="CPU", anchor="w", fill=current["text"],
                            font=("Segoe UI", 8))
        preview.create_text(70, 40, text="42°", anchor="w", fill=current["cold"],
                            font=("Segoe UI", 8))
        preview.create_text(120, 40, text="81°", anchor="w", fill=current["hot"],
                            font=("Segoe UI", 8))
        preview.create_text(12, 58, text="sensor label", anchor="w", fill=current["dim"],
                            font=("Segoe UI", 7))

    def pick(role):
        initial = normalize_hex(vars_[role].get()) or colors[role]
        chosen = colorchooser.askcolor(color=initial, parent=dialog, title=ROLE_LABELS[role])
        if chosen and chosen[1]:
            vars_[role].set(chosen[1].lower())

    def save(_event=None):
        title_text = " ".join(name_var.get().split())[:40]
        if not title_text:
            messagebox.showerror(title, "Give the theme a name.", parent=dialog)
            return
        if title_text in taken:
            messagebox.showerror(title, f"“{title_text}” is already used.", parent=dialog)
            return
        parsed = {}
        for role, var in vars_.items():
            color = normalize_hex(var.get())
            if not color:
                messagebox.showerror(
                    title, f"{ROLE_LABELS[role]} needs a color like #39d0d8.\n"
                    "Magenta (#ff00ff) is reserved for the transparent edge.",
                    parent=dialog)
                return
            parsed[role] = color
        result["value"] = (title_text, parsed)
        dialog.destroy()

    frame = tk.Frame(dialog, bg="#161b22", padx=12, pady=10)
    frame.pack(fill="both")
    tk.Label(frame, text="Name", bg="#161b22", fg="#c9d1d9",
             font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=2)
    name_var = tk.StringVar(master=dialog, value=name)
    name_entry = tk.Entry(frame, textvariable=name_var, width=22, font=("Segoe UI", 9))
    name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
    for row, role in enumerate(ROLES, start=1):
        tk.Label(frame, text=ROLE_LABELS[role], bg="#161b22", fg="#c9d1d9",
                 font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", pady=2)
        swatch = tk.Label(frame, text="", width=3, bg=colors[role], relief="solid", bd=1)
        swatch.grid(row=row, column=1, padx=6)
        swatches[role] = swatch
        tk.Entry(frame, textvariable=vars_[role], width=12,
                 font=("Consolas", 9)).grid(row=row, column=2, sticky="w")
        tk.Button(frame, text="Pick", font=("Segoe UI", 8),
                  command=lambda role=role: pick(role)).grid(row=row, column=3, padx=(6, 0))
        vars_[role].trace_add("write", paint)
    preview = tk.Canvas(frame, width=300, height=72, bd=0, highlightthickness=0,
                        bg="#161b22")
    preview.grid(row=len(ROLES) + 1, column=0, columnspan=4, pady=(10, 6))
    buttons = tk.Frame(frame, bg="#161b22")
    buttons.grid(row=len(ROLES) + 2, column=0, columnspan=4, sticky="e")
    tk.Button(buttons, text="Cancel", font=("Segoe UI", 9),
              command=dialog.destroy).pack(side="right")
    tk.Button(buttons, text="Save", font=("Segoe UI", 9),
              command=save).pack(side="right", padx=(0, 6))
    paint()
    dialog.bind("<Return>", save)
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    dialog.update_idletasks()
    dialog.geometry(f"+{master.winfo_rootx() + 24}+{master.winfo_rooty() + 24}")
    name_entry.focus_set()
    dialog.lift()
    dialog.grab_set()
    master.attributes("-topmost", False)
    try:
        master.wait_window(dialog)
    finally:
        try:
            master.attributes("-topmost", True)
            master.lift()
        except tk.TclError:
            pass
    return result["value"]
