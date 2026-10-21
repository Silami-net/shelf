"""Keeps the shelf's contents across restarts in ~/.local/share/shelf/state.json."""
import json
import logging
import os
import tempfile

from .items import Item

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "shelf")
STATE_PATH = os.path.join(DATA_DIR, "state.json")


def load(path=STATE_PATH):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return [Item.from_dict(d) for d in data.get("items", [])]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, AttributeError, TypeError) as e:
        log.warning("could not read %s (%s); starting with an empty shelf", path, e)
        try:
            os.replace(path, path + ".bad")
        except OSError:
            pass
        return []


def save(items, path=STATE_PATH):
    """Write atomically, so a crash never leaves a half-written file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".state-")
        with os.fdopen(fd, "w") as fh:
            json.dump({"version": 1, "items": [i.to_dict() for i in items]}, fh, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("could not save the shelf to %s: %s", path, e)
