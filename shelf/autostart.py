"""Starting the shelf at login, through ~/.config/autostart."""
import logging
import os

from . import APP_ID

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LAUNCHER = os.path.join(ROOT, "bin", "shelf")
ICON = os.path.join(ROOT, "data", "icons", "shelf.svg")
AUTOSTART_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "autostart", APP_ID + ".desktop")


def _quote(path):
    """Quote a path for a desktop entry's Exec line."""
    if not any(c in path for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return path
    return '"' + "".join("\\" + c if c in '"`$\\' else c for c in path) + '"'


def desktop_entry():
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Shelf\n"
        "Comment=Drop shelf on the edge of the screen\n"
        f"Exec={_quote(LAUNCHER)}\n"
        f"Icon={ICON}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_enabled(path=AUTOSTART_PATH):
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return False
    lines = {line.strip().lower() for line in text.splitlines()}
    return "hidden=true" not in lines and "x-gnome-autostart-enabled=false" not in lines


def set_enabled(on, path=AUTOSTART_PATH):
    """Add or remove the shelf's own autostart entry. Returns an error message, or None."""
    try:
        if on:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(desktop_entry())
        elif os.path.exists(path):
            os.remove(path)
    except OSError as e:
        log.warning("could not change %s: %s", path, e)
        return str(e)
    return None
