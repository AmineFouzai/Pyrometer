import json
import os
import sys

from .themes import PRESETS, sanitize_custom_themes

DEFAULTS = {
    "x": None, "y": None, "alpha": 0.9, "expanded": False,
    "refresh": 3.0, "click_through": False, "start_hidden": False,
    "hotkey_toggle": "ctrl+alt+t", "hotkey_expand": "ctrl+alt+e",
    "hotkey_lock": "ctrl+alt+l", "hotkey_quit": "ctrl+alt+q",
    "theme": "Default", "custom_themes": {}, "collapsed": [],
    "expanded_width": 320, "expanded_height": None, "psu_watts": None,
    "psu_name": "",
    "text_scale": 1.15,
}


def app_dir():
    """Folder holding the exe, or the project folder when run from source."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir():
    return getattr(sys, "_MEIPASS", app_dir())


def log_error(message):
    """Windowed builds have no console; leave failures on disk instead."""
    try:
        with open(os.path.join(app_dir(), "pyrometer-error.log"), "w",
                  encoding="utf-8") as stream:
            stream.write(message + "\n")
    except OSError:
        pass


class Settings:
    def __init__(self):
        self.path = os.path.join(app_dir(), "widget_config.json")
        self.data = dict(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as stream:
                loaded = json.load(stream)
            self.data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (OSError, ValueError, TypeError):
            pass
        self.data["refresh"] = max(2.0, float(self.data["refresh"]))
        self.data["custom_themes"] = sanitize_custom_themes(self.data.get("custom_themes"))
        collapsed = self.data.get("collapsed")
        if not isinstance(collapsed, list):
            collapsed = []
        self.data["collapsed"] = [item for item in collapsed if isinstance(item, str)]
        theme = self.data.get("theme")
        if theme not in PRESETS and theme not in self.data["custom_themes"]:
            self.data["theme"] = "Default"
        try:
            self.data["expanded_width"] = max(
                280, min(900, int(self.data["expanded_width"])))
        except (TypeError, ValueError):
            self.data["expanded_width"] = 320
        try:
            height = self.data["expanded_height"]
            self.data["expanded_height"] = (
                max(180, min(1400, int(height))) if height is not None else None)
        except (TypeError, ValueError):
            self.data["expanded_height"] = None
        try:
            self.data["text_scale"] = max(0.9, min(2.0, float(self.data["text_scale"])))
        except (TypeError, ValueError):
            self.data["text_scale"] = 1.15
        try:
            watts = self.data["psu_watts"]
            self.data["psu_watts"] = (
                max(100, min(3000, int(watts))) if watts is not None else None)
        except (TypeError, ValueError):
            self.data["psu_watts"] = None
        name = self.data.get("psu_name")
        self.data["psu_name"] = " ".join(name.split())[:40] if isinstance(name, str) else ""

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2)
        except OSError:
            pass
