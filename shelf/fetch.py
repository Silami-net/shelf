"""Turning a picture dragged out of a web browser into a real file on the shelf.

Browsers drag an image as its address plus a little HTML (<img src=...>), and
sometimes the image data itself. The shelf saves that data, or downloads the
image, into ~/.local/share/shelf/downloads, so dropping it elsewhere gives the
picture rather than a link. Copies no longer on the shelf are cleaned up.
"""
import base64
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser

from .store import DATA_DIR

log = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
MAX_BYTES = 200 * 1024 * 1024
TIMEOUT = 30
KEEP_SECONDS = 24 * 3600
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
              "image/webp": ".webp", "image/svg+xml": ".svg", "image/bmp": ".bmp",
              "image/tiff": ".tif", "image/avif": ".avif", "image/x-icon": ".ico"}


class _ImageFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            src = dict(attrs).get("src")
            if src:
                self.sources.append(src.strip())

    def handle_data(self, data):
        self.text.append(data)


def decode_html(raw):
    """Browsers send dragged HTML as UTF-8 or (Firefox) UTF-16."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if raw[1:2] == b"\x00":
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def image_in_html(markup):
    """The picture's address when the dragged HTML is just an image (perhaps inside a
    link), or None when it is text that happens to contain images."""
    finder = _ImageFinder()
    try:
        finder.feed(markup or "")
    except Exception:
        return None
    if not finder.sources or "".join(finder.text).strip():
        return None
    src = finder.sources[0]
    if urllib.parse.urlparse(src).scheme.lower() in ("http", "https", "data"):
        return src
    return None


def file_name(url, content_type):
    """A sensible file name: the one in the address, with the right extension."""
    content_type = (content_type or "").split(";")[0].strip().lower()
    name = ""
    if not url.startswith("data:"):
        name = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path))
    name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip(" .") or "image"
    stem, ext = os.path.splitext(name)
    wanted = EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ""
    if ext.lower() not in EXTENSIONS.values() and ext.lower() not in (".jpeg", ".tiff"):
        stem, ext = name, wanted
    elif wanted and mimetypes.guess_type("x" + ext)[0] != content_type:
        ext = wanted  # e.g. a .png address that actually serves WebP
    return (stem[:120] or "image") + ext


def decode_data_url(url):
    """(bytes, content type) from a data: address."""
    header, _, payload = url.partition(",")
    content_type = header[5:].split(";")[0] or "text/plain"
    if header.endswith(";base64"):
        return base64.b64decode(payload), content_type
    return urllib.parse.unquote_to_bytes(payload), content_type


def save(data, name, folder=None):
    """Store bytes under a fresh folder in the downloads area; returns the path."""
    target = os.path.join(folder or DOWNLOAD_DIR, uuid.uuid4().hex[:12])
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _download(url):
    if url.startswith("data:"):
        data, content_type = decode_data_url(url)
    else:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Shelf",
            "Accept": "image/*,*/*;q=0.5"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            content_type = resp.headers.get_content_type()
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("larger than 200 MB")
    if not content_type.startswith("image/"):
        raise ValueError(f"not a picture ({content_type})")
    return save(data, file_name(url, content_type))


def download(url, on_done):
    """Fetch a picture in the background; on_done(path or None) runs on the main thread."""
    from gi.repository import GLib

    def work():
        try:
            path = _download(url)
        except Exception as e:
            log.warning("could not get the picture from %s: %s", url[:200], e)
            path = None
        GLib.idle_add(lambda: on_done(path) and False)

    threading.Thread(target=work, name="download", daemon=True).start()


def clean(keep_paths, folder=None, older_than=KEEP_SECONDS):
    """Remove saved pictures that are no longer on the shelf and older than a day."""
    folder = folder or DOWNLOAD_DIR
    keep = {os.path.dirname(p) for p in keep_paths if p}
    try:
        entries = os.listdir(folder)
    except FileNotFoundError:
        return
    now = time.time()
    for entry in entries:
        path = os.path.join(folder, entry)
        try:
            if path not in keep and now - os.path.getmtime(path) > older_than:
                shutil.rmtree(path)
        except OSError as e:
            log.warning("could not clean up %s: %s", path, e)
