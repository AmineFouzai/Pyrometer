"""Color themes for the overlay. Magenta is reserved for window transparency."""

import re

TRANSPARENT = "#ff00ff"
ROLES = ("panel", "border", "text", "dim", "accent", "cold", "warm", "hot")

PRESETS = {
    "Default": {
        "panel": "#161b22", "border": "#2a3441", "text": "#c9d1d9", "dim": "#6e7681",
        "accent": "#39d0d8", "cold": "#3fd17f", "warm": "#e3b341", "hot": "#f85149",
    },
    "Nord": {
        "panel": "#2e3440", "border": "#3b4252", "text": "#eceff4", "dim": "#7b88a1",
        "accent": "#88c0d0", "cold": "#a3be8c", "warm": "#ebcb8b", "hot": "#bf616a",
    },
    "Dracula": {
        "panel": "#282a36", "border": "#44475a", "text": "#f8f8f2", "dim": "#6272a4",
        "accent": "#bd93f9", "cold": "#50fa7b", "warm": "#f1fa8c", "hot": "#ff5555",
    },
    "Catppuccin": {
        "panel": "#1e1e2e", "border": "#313244", "text": "#cdd6f4", "dim": "#6c7086",
        "accent": "#89dceb", "cold": "#a6e3a1", "warm": "#f9e2af", "hot": "#f38ba8",
    },
    "Rose Pine": {
        "panel": "#191724", "border": "#26233a", "text": "#e0def4", "dim": "#6e6a86",
        "accent": "#c4a7e7", "cold": "#9ccfd8", "warm": "#f6c177", "hot": "#eb6f92",
    },
    "Gruvbox": {
        "panel": "#282828", "border": "#3c3836", "text": "#ebdbb2", "dim": "#a89984",
        "accent": "#83a598", "cold": "#b8bb26", "warm": "#fabd2f", "hot": "#fb4934",
    },
    "Solarized": {
        "panel": "#002b36", "border": "#073642", "text": "#eee8d5", "dim": "#586e75",
        "accent": "#2aa198", "cold": "#859900", "warm": "#b58900", "hot": "#dc322f",
    },
    "Tokyo Night": {
        "panel": "#1a1b26", "border": "#24283b", "text": "#c0caf5", "dim": "#565f89",
        "accent": "#7aa2f7", "cold": "#9ece6a", "warm": "#e0af68", "hot": "#f7768e",
    },
    "OLED": {
        "panel": "#000000", "border": "#222222", "text": "#eeeeee", "dim": "#777777",
        "accent": "#00e5ff", "cold": "#00e676", "warm": "#ffea00", "hot": "#ff1744",
    },
    "Amber": {
        "panel": "#140e08", "border": "#3a2a16", "text": "#ffcc80", "dim": "#a68456",
        "accent": "#ffb000", "cold": "#c6d67a", "warm": "#ffb000", "hot": "#ff5d3a",
    },
    "Matrix": {
        "panel": "#050a05", "border": "#163316", "text": "#b8f5b8", "dim": "#3e7a45",
        "accent": "#39ff14", "cold": "#7dff6a", "warm": "#d2ff4d", "hot": "#ff4d3a",
    },
    "Light": {
        "panel": "#f6f8fa", "border": "#d0d7de", "text": "#1f2328", "dim": "#656d76",
        "accent": "#0969da", "cold": "#1a7f37", "warm": "#9a6700", "hot": "#cf222e",
    },
}

_HEX = re.compile(r"^#[0-9a-f]{6}$")


def normalize_hex(value):
    """Return #rrggbb, or None when the text is not a color."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text.startswith("#"):
        text = "#" + text
    if re.fullmatch(r"#[0-9a-f]{3}", text):
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if not _HEX.match(text) or text == TRANSPARENT:
        return None
    return text


def sanitize_theme(raw, fallback=None):
    """Fill any missing or invalid roles from the fallback theme."""
    base = dict(fallback or PRESETS["Default"])
    if not isinstance(raw, dict):
        return base
    for role in ROLES:
        color = normalize_hex(raw.get(role))
        if color:
            base[role] = color
    return base


def sanitize_custom_themes(raw):
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for name, colors in raw.items():
        if not isinstance(name, str):
            continue
        title = " ".join(name.split())[:40]
        if not title or title in PRESETS or not isinstance(colors, dict):
            continue
        cleaned[title] = sanitize_theme(colors)
    return cleaned


def resolve_theme(name, custom_themes):
    if name in custom_themes:
        return custom_themes[name]
    return PRESETS.get(name, PRESETS["Default"])
