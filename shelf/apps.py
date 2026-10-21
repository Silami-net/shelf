"""Apps that drags have come from, so their floating-panel switch can be offered.

Kept in ~/.local/share/shelf/apps.json; names and icons come from the
installed .desktop files where one matches.
"""
import json
import logging
import os
import time

from .store import DATA_DIR

log = logging.getLogger(__name__)

APPS_PATH = os.path.join(DATA_DIR, "apps.json")


class SeenApps:
    def __init__(self, path=APPS_PATH):
        self._path = path
        self._seen = {}  # window class -> last time a drag came from it
        try:
            with open(path) as fh:
                self._seen = {str(k): float(v) for k, v in json.load(fh).get("apps", {}).items()}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, TypeError) as e:
            log.warning("could not read %s (%s); starting a new list", path, e)

    def note(self, app):
        self._seen[app] = time.time()
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"apps": self._seen}, fh, indent=1)
            os.replace(tmp, self._path)
        except OSError as e:
            log.warning("could not save %s: %s", self._path, e)

    def recent(self, also=()):
        """Seen apps, most recent first, followed by any in `also` never seen."""
        ordered = sorted(self._seen, key=self._seen.get, reverse=True)
        known = {a.lower() for a in ordered}
        return ordered + sorted((a for a in also if a.lower() not in known), key=str.lower)


_desktop_cache = {}


def describe(app):
    """(display name, Gio icon or None) for a window class."""
    if app in _desktop_cache:
        return _desktop_cache[app]
    from gi.repository import Gio

    key = app.lower()
    found = (app, None)
    for info in Gio.AppInfo.get_all():
        if not isinstance(info, Gio.DesktopAppInfo):
            continue
        stem = (info.get_id() or "").lower()
        stem = stem[:-len(".desktop")] if stem.endswith(".desktop") else stem
        if key in ((info.get_startup_wm_class() or "").lower(), stem):
            found = (info.get_display_name() or info.get_name() or app, info.get_icon())
            break
    _desktop_cache[app] = found
    return found
