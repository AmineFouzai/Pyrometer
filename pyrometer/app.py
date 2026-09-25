import ctypes
import math
import os
import time
import tkinter as tk
from tkinter import colorchooser, messagebox

from .hotkeys import HotkeyListener
from .performance import ResourceGovernor
from .screens import virtual_bounds, work_area_at
from .sensors import NAMES, SensorReader, primary
from .settings import Settings, resource_dir
from .themes import PRESETS, ROLES, TRANSPARENT, normalize_hex, resolve_theme

KEY = TRANSPARENT
PAD, ROW, HEADER, FOOTER = 10, 25, 27, 15
GROUP_HEADER = 18
COMPACT_WIDTH, EXPANDED_WIDTH = 208, 286
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
        self._moved = False
        self._last_header_click = 0.0
        self._last_header_name = None

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
            x, y = self.root.winfo_screenwidth() - COMPACT_WIDTH - 24, 48
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
        self.canvas.bind("<Button-3>", self._show_menu)
        self.root.bind("<Escape>", lambda _event: self.toggle_visible())
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    def _menu_style(self):
        return dict(tearoff=0, bg=self.colors["panel"], fg=self.colors["text"],
                    activebackground=self.colors["accent"],
                    activeforeground=self.colors["panel"], bd=0,
                    font=("Segoe UI", 9))

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
        width = EXPANDED_WIDTH if expanded else COMPACT_WIDTH
        self._header_hits = []
        self._scroll_track = None
        self._max_scroll = 0
        if self.reader.error or not groups:
            body = ROW * 2
        elif expanded:
            content = self._expanded_content_height(groups)
            # The extra 5px is the gap already subtracted from the viewport,
            # so a list that fits does not grow a scrollbar.
            body = min(content + 5, self._max_body())
        else:
            body = ROW * len(groups)
        self.size = (width, HEADER + body + FOOTER + 8)
        self._place()

        canvas = self.canvas
        canvas.delete("all")
        self._panel(width, self.size[1])
        canvas.create_text(PAD, 14, text="PYROMETER", anchor="w",
                           fill=self.colors["accent"], font=("Segoe UI Semibold", 9))
        hottest = max((s[1] for g in groups for s in g["sensors"] if s[1] is not None),
                      default=None)
        if hottest is not None:
            canvas.create_text(width - PAD, 14, text=f"{hottest:.0f}°", anchor="e",
                               fill=self._temp_color(hottest), font=("Consolas", 11, "bold"))
        canvas.create_line(PAD, HEADER, width - PAD, HEADER, fill=self.colors["border"])

        y = HEADER + 8
        if self.reader.error:
            canvas.create_text(PAD, y, text=("⚠ " + self.reader.error)[:42],
                               anchor="nw", fill=self.colors["hot"], font=("Segoe UI", 8))
        elif not groups:
            canvas.create_text(PAD, y, text="reading sensors…", anchor="nw",
                               fill=self.colors["dim"], font=("Segoe UI", 9))
        elif expanded:
            self._expanded(groups, width)
        else:
            self._compact(groups, y, width)
        self._footer(width)

    def _max_body(self):
        """Tallest list that still ends inside the monitor work area."""
        _left, top, _width, work_h = work_area_at(*self.position)
        room = top + work_h - self.position[1] - 12
        chrome = HEADER + FOOTER + 8
        return max(GROUP_HEADER * 3, min(work_h - chrome - 12, room - chrome))

    def _expanded_content_height(self, groups):
        collapsed = set(self.settings["collapsed"])
        height = 0
        for group in groups:
            height += GROUP_HEADER
            if group["name"] not in collapsed:
                height += ROW * len(group["sensors"])
        return height

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
            self._row(PAD, y, width - PAD * 2, label, sensor, True)
            y += ROW
        return y

    def _expanded(self, groups, width):
        view_top = HEADER + 8
        view_bottom = self.size[1] - FOOTER - 5
        content = self._expanded_content_height(groups)
        visible = max(1, view_bottom - view_top)
        self._max_scroll = max(0, content - visible)
        self.scroll = max(0, min(self.scroll, self._max_scroll))
        collapsed = set(self.settings["collapsed"])
        inset = 16 if self._max_scroll else 4
        cursor = view_top - self.scroll
        for group in groups:
            header_y = cursor
            cursor += GROUP_HEADER
            if view_top <= header_y and header_y + GROUP_HEADER <= view_bottom:
                self._group_header(header_y, width, group, group["name"] in collapsed)
                self._header_hits.append((header_y, header_y + GROUP_HEADER, group["name"]))
            if group["name"] in collapsed:
                continue
            for sensor in group["sensors"]:
                row_y = cursor
                cursor += ROW
                if view_top <= row_y and row_y + ROW <= view_bottom:
                    self._row(PAD + 4, row_y, width - PAD * 2 - inset,
                              sensor[0][:21], sensor)
        if self._max_scroll:
            self._scrollbar(width, view_top, view_bottom, visible, content)

    def _group_header(self, y, width, group, folded):
        mark = "▶" if folded else "▼"
        title = group["name"].upper()
        if folded:
            title = f"{title[:26]}  {len(group['sensors'])}"
        else:
            title = title[:32]
        self.canvas.create_text(PAD, y + 7, text=mark, anchor="w",
                                fill=self.colors["dim"], font=("Segoe UI", 7))
        self.canvas.create_text(PAD + 14, y + 7, text=title, anchor="w",
                                fill=self.colors["accent"], font=("Segoe UI", 7))
        gutter = 12 if self._max_scroll else 0
        self.canvas.create_line(PAD, y + GROUP_HEADER - 2, width - PAD - gutter,
                                y + GROUP_HEADER - 2, fill=self.colors["border"])

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
        font = ("Segoe UI Semibold", 9) if bold else ("Segoe UI", 8)
        number = ("Consolas", 10, "bold") if bold else ("Segoe UI", 8)
        self.canvas.create_text(x, y + 8, text=label, anchor="w",
                                fill=self.colors["text"] if bold else self.colors["dim"],
                                font=font)
        self.canvas.create_text(x + width, y + 8,
                                text="n/a" if value is None else f"{value:.0f}°C",
                                anchor="e", fill=self._temp_color(value), font=number)
        self.canvas.create_line(x, y + 19, x + width, y + 19, fill=self.colors["border"])
        if value is not None:
            end = x + max(2, int(min(value, 100) * width / 100))
            self.canvas.create_line(x, y + 19, end, y + 19,
                                    fill=self._temp_color(value), width=2)

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

    def _footer(self, width):
        if not is_admin():
            note, warn = "no admin — limited sensors", True
        elif self.reader.missing:
            note, warn = "no " + "/".join(self.reader.missing) + " sensors", True
        elif self.settings["expanded"]:
            note, warn = "click header to fold  ·  wheel to scroll", False
        else:
            note, warn = "Ctrl+Alt+T hide  ·  Ctrl+Alt+E expand", False
        self.canvas.create_text(PAD, self.size[1] - 8, text=note, anchor="w",
                                fill=self.colors["warm"] if warn else self.colors["dim"],
                                font=("Segoe UI", 7))
        if self.settings["click_through"]:
            self.canvas.create_text(width - PAD, self.size[1] - 8, text="LOCKED",
                                    anchor="e", fill=self.colors["warm"],
                                    font=("Segoe UI", 7))

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

    def _drag_start(self, event):
        self.root.focus_set()
        self._press_root = (event.x_root, event.y_root)
        self._moved = False
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
        if self._header_at(event.x, event.y) and event.y > HEADER:
            return
        self.toggle_expanded()

    def _wheel(self, event):
        if not self.settings["expanded"] or self._max_scroll <= 0 or not event.delta:
            return
        step = ROW if event.delta < 0 else -ROW
        self.scroll = max(0, min(self._max_scroll, self.scroll + step))
        self._refresh()

    def _scrollbar_hit(self, event):
        track = self._scroll_track
        if not track or not self.settings["expanded"]:
            return False
        x0, top, bottom, _thumb_h = track
        return event.x >= x0 and top <= event.y <= bottom

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

    def toggle_click_through(self):
        enabled = not self.settings["click_through"]
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, -20, (style | 0x00080020) if enabled else (style & ~0x20))
        self.settings["click_through"] = enabled
        self.dirty = True

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
