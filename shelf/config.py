"""Settings, read from ~/.config/shelf/shelf.ini (written with defaults on first run)."""
import configparser
import logging
import os
from dataclasses import dataclass, field, fields

from .geometry import EDGES

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "shelf")
CONFIG_PATH = os.path.join(CONFIG_DIR, "shelf.ini")

TEMPLATE = """\
# Shelf settings. Changes made in the settings window (gear icon) are saved here.
# After editing this file by hand, restart the shelf:  shelf --quit; shelf &

[shelf]
# Which monitor the shelf lives on:
#   primary       the primary monitor
#   follow-mouse  the monitor the pointer is on when the shelf opens
#   DP-2, HDMI-1  a connector name (see: xrandr --listmonitors)
#   0, 1, ...     a monitor number
monitor = {monitor}

# Screen edge: left or right
edge = {edge}

# Panel width in pixels (follows GNOME's display scaling)
width = {width}

# Panel height: never shorter than this many items, and growing with its
# contents up to max_height_percent of the monitor's usable height.
min_items = {min_items}
max_height_percent = {max_height_percent}

# Width of the drop strip that appears on the edge while you drag something.
# Edges that border another monitor get the wider strip, so you can stop on it.
handle_width = {handle_width}
inner_handle_width = {inner_handle_width}

# Open the empty shelf by resting the pointer on the screen edge
open_on_hover = {open_on_hover}
hover_delay_ms = {hover_delay_ms}

# An empty shelf fades away after this many seconds with nothing happening
empty_timeout_seconds = {empty_timeout_seconds}

# Take items off the shelf once they have been dropped somewhere else
remove_after_drop = {remove_after_drop}

# How long the Undo button stays up after a flush or a drop
undo_seconds = {undo_seconds}

# Key that shows/hides the empty shelf. Examples: F6, Super+F6, Ctrl+Alt+S
hotkey = {hotkey}

# Show previews of images, videos and documents. Making one means reading the
# file, so files bigger than thumbnail_max_mb keep their plain icon.
thumbnails = {thumbnails}
thumbnail_max_mb = {thumbnail_max_mb}

# Small icon in the top bar with a menu (needs GNOME's AppIndicator extension)
tray_icon = {tray_icon}

# Floating drop panel: when you start dragging something, a small drop target
# appears next to the pointer, so you don't have to drag all the way to the edge.
floating_enabled = {floating_enabled}
# Distance from the pointer, in pixels
floating_offset = {floating_offset}
# Wait this long after a drag starts, so quick accidental drags don't show it
floating_delay_ms = {floating_delay_ms}
# Optional key that turns the floating drop panel on and off (empty = none)
float_hotkey = {float_hotkey}
# Show it for apps that have no line under [apps] below
floating_new_apps = {floating_new_apps}

[apps]
# Floating drop panel per app, by the app's window class (as listed in the
# settings window): on or off. Example:  Nuke = off
"""


@dataclass
class Config:
    monitor: str = "primary"
    edge: str = "right"
    width: int = 120
    min_items: int = 3
    max_height_percent: int = 70
    handle_width: int = 4
    inner_handle_width: int = 14
    open_on_hover: bool = True
    hover_delay_ms: int = 400
    empty_timeout_seconds: int = 5
    remove_after_drop: bool = True
    undo_seconds: int = 6
    hotkey: str = "F6"
    thumbnails: bool = True
    thumbnail_max_mb: int = 2048
    tray_icon: bool = True
    floating_enabled: bool = True
    floating_offset: int = 48
    floating_delay_ms: int = 150
    float_hotkey: str = ""
    floating_new_apps: bool = True
    floating_apps: dict = field(default_factory=dict)  # app window class -> on/off

    def floating_for(self, app):
        """Whether the floating drop panel shows for drags from this app."""
        return self.floating_enabled and self.app_allowed(app)

    def app_allowed(self, app):
        """The per-app rule alone, ignoring the main on/off switch."""
        if app:
            for name, on in self.floating_apps.items():
                if name.lower() == app.lower():
                    return on
        return self.floating_new_apps


# Allowed ranges for the numeric settings.
_LIMITS = {
    "width": (80, 1000),
    "min_items": (1, 20),
    "max_height_percent": (10, 100),
    "handle_width": (1, 50),
    "inner_handle_width": (1, 80),
    "hover_delay_ms": (0, 5000),
    "undo_seconds": (1, 120),
    "empty_timeout_seconds": (1, 600),
    "thumbnail_max_mb": (1, 1000000),
    "floating_offset": (8, 400),
    "floating_delay_ms": (0, 2000),
}


def parse(text):
    """Build a Config from INI text; bad values fall back to the default."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None)
    parser.optionxform = str  # app names are case-sensitive
    parser.read_string(text)
    section = parser["shelf"] if parser.has_section("shelf") else {}
    cfg = Config()
    for f in fields(Config):
        if f.name not in section or f.type is dict:
            continue
        raw = section[f.name].strip()
        try:
            if f.type is bool:
                value = configparser.ConfigParser.BOOLEAN_STATES[raw.lower()]
            elif f.type is int:
                value = int(raw)
                low, high = _LIMITS[f.name]
                if not low <= value <= high:
                    raise ValueError(f"must be between {low} and {high}")
            else:
                value = raw
        except (KeyError, ValueError) as e:
            log.warning("setting %s = %r ignored (%s), using %r",
                        f.name, raw, e or "not a yes/no value", getattr(cfg, f.name))
            continue
        setattr(cfg, f.name, value)
    if cfg.edge not in EDGES:
        log.warning("setting edge = %r ignored (use left or right)", cfg.edge)
        cfg.edge = Config.edge
    if parser.has_section("apps"):
        for app, raw in parser["apps"].items():
            on = configparser.ConfigParser.BOOLEAN_STATES.get(raw.strip().lower())
            if on is None:
                log.warning("[apps] %s = %r ignored (use on or off)", app, raw)
            else:
                cfg.floating_apps[app] = on
    return cfg


def render(cfg):
    values = {f.name: getattr(cfg, f.name) for f in fields(Config)}
    for name, value in values.items():
        if isinstance(value, bool):
            values[name] = "true" if value else "false"
    apps = "".join(f"{app} = {'on' if on else 'off'}\n"
                   for app, on in sorted(cfg.floating_apps.items(), key=lambda a: a[0].lower()))
    return TEMPLATE.format(**values) + apps


DEFAULT_INI = render(Config())


def save(cfg, path=CONFIG_PATH):
    """Write the settings file; returns an error message, or None."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(render(cfg))
        os.replace(tmp, path)
    except OSError as e:
        log.warning("could not save settings to %s: %s", path, e)
        return str(e)
    return None


def load(path=CONFIG_PATH):
    if not os.path.exists(path):
        save(Config(), path)
        return Config()
    try:
        with open(path) as fh:
            return parse(fh.read())
    except (OSError, configparser.Error) as e:
        log.warning("could not read %s (%s), using defaults", path, e)
        return Config()
