"""What the shelf holds: files (by reference only), links and text snippets."""
import os
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

KINDS = ("file", "url", "text")
URL_SCHEMES = {"http", "https", "ftp", "mailto"}
HOME = os.path.expanduser("~")


@dataclass
class Item:
    kind: str   # "file", "url" or "text"
    value: str  # a URI for files and links, the text itself for snippets
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    added: float = field(default_factory=time.time)

    @property
    def path(self):
        """Local path of a file:// item, else None."""
        if self.kind == "file" and self.value.startswith("file://"):
            return unquote(urlparse(self.value).path)
        return None

    @property
    def label(self):
        if self.kind == "file":
            p = self.path or unquote(urlparse(self.value).path)
            return os.path.basename(p.rstrip("/")) or p or self.value
        if self.kind == "url":
            return self.value
        first = next((line.strip() for line in self.value.splitlines() if line.strip()), "")
        return first[:120]

    @property
    def detail(self):
        if self.kind == "file":
            p = self.path
            if p is None:
                return urlparse(self.value).netloc or self.value
            folder = os.path.dirname(p.rstrip("/")) or "/"
            if folder == HOME or folder.startswith(HOME + "/"):
                folder = "~" + folder[len(HOME):]
            return folder
        if self.kind == "url":
            return urlparse(self.value).netloc or "Link"
        lines = self.value.count("\n") + 1
        return f"Text · {len(self.value)} characters" + (f", {lines} lines" if lines > 1 else "")

    def as_text(self):
        """What the item becomes when dropped where only text is accepted."""
        return self.path or self.value

    def to_dict(self):
        return {"kind": self.kind, "value": self.value, "id": self.id, "added": self.added}

    @classmethod
    def from_dict(cls, d):
        if d.get("kind") not in KINDS or not isinstance(d.get("value"), str):
            raise ValueError(f"not a shelf item: {d!r}")
        return cls(d["kind"], d["value"], str(d.get("id") or uuid.uuid4().hex),
                   float(d.get("added") or time.time()))


def _uri_item(uri):
    scheme = urlparse(uri).scheme.lower()
    return Item("url" if scheme in URL_SCHEMES else "file", uri)


def from_uris(uris):
    return [_uri_item(u.strip()) for u in uris
            if u and u.strip() and not u.startswith("#")]


def from_paths(paths):
    from gi.repository import Gio
    return [Item("file", Gio.File.new_for_path(p).get_uri()) for p in paths]


def from_copied_files(text):
    """Files copied in a GNOME file manager: "copy" or "cut", then one URI per line.

    Either way the shelf only keeps references, so a "cut" never moves anything.
    """
    lines = (text or "").splitlines()
    if lines and lines[0].strip() in ("copy", "cut"):
        lines = lines[1:]
    return from_uris(lines)


def from_text(text):
    """A dropped/pasted string: one link becomes a link item, anything else a snippet."""
    stripped = (text or "").strip()
    if not stripped:
        return []
    if "\n" not in stripped and " " not in stripped:
        scheme = urlparse(stripped).scheme.lower()
        if scheme in URL_SCHEMES or scheme == "file":
            return [_uri_item(stripped)]
    return [Item("text", text.rstrip("\r\n"))]


def merge(existing, new):
    """Append the new items that aren't on the shelf yet; returns the ones added."""
    seen = {(i.kind, i.value) for i in existing}
    added = []
    for item in new:
        key = (item.kind, item.value)
        if key not in seen:
            seen.add(key)
            existing.append(item)
            added.append(item)
    return added
