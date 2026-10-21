"""Thumbnails for shelf items, made by GNOME's own thumbnailers.

Thumbnails go into the shared ~/.cache/thumbnails, so Files and the shelf reuse
each other's. Making one can mean reading a big file from a network share, so
it happens one file at a time on a background thread, never on the UI thread.
"""
import logging
import queue
import threading

from gi.repository import GLib

log = logging.getLogger(__name__)

_queue = None
_factory = None


def _worker():
    while True:
        uri, mime, mtime, callback = _queue.get()
        path = None
        try:
            if not _factory.has_valid_failed_thumbnail(uri, mtime):
                pixbuf = _factory.generate_thumbnail(uri, mime)
                if pixbuf is not None:
                    _factory.save_thumbnail(pixbuf, uri, mtime)
                    path = _factory.lookup(uri, mtime)
                else:
                    _factory.create_failed_thumbnail(uri, mtime)
        except GLib.Error as e:
            log.info("no thumbnail for %s: %s", uri, e.message)
            _factory.create_failed_thumbnail(uri, mtime)
        except Exception:
            log.exception("thumbnailer failed for %s", uri)
        if path:
            GLib.idle_add(callback, path)


def request(uri, mime, mtime, callback):
    """Call callback(path) on the main thread once a thumbnail exists, if one can be made."""
    global _queue, _factory
    if _factory is None:
        try:
            import gi
            gi.require_version("GnomeDesktop", "3.0")
            from gi.repository import GnomeDesktop
        except (ImportError, ValueError) as e:
            log.info("thumbnails unavailable: %s", e)
            _factory = False
            return
        _factory = GnomeDesktop.DesktopThumbnailFactory.new(
            GnomeDesktop.DesktopThumbnailSize.NORMAL)
        _queue = queue.Queue()
        threading.Thread(target=_worker, name="thumbnails", daemon=True).start()
    if not _factory:
        return
    existing = _factory.lookup(uri, mtime)
    if existing:
        callback(existing)
    elif _factory.can_thumbnail(uri, mime, mtime):
        _queue.put((uri, mime, mtime, callback))
