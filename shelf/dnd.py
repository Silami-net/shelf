"""Drag-and-drop plumbing shared by the panel and the edge strip.

The shelf only ever copies or links: it never accepts or offers a "move", so a
drop onto or out of the shelf can't take a file away from where it lives.

A picture dragged out of a web browser lands as the picture itself (see fetch.py),
not as a link to it.
"""
from gi.repository import Gdk, Gtk

from . import fetch, items

INFO_URIS, INFO_TEXT, INFO_HTML, INFO_IMAGE = 1, 2, 3, 4
ACTIONS = Gdk.DragAction.COPY | Gdk.DragAction.LINK
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp", "image/tiff")


def drop_targets():
    targets = Gtk.TargetList.new([])
    targets.add_uri_targets(INFO_URIS)  # first, so files win over their text form
    targets.add_text_targets(INFO_TEXT)
    targets.add(Gdk.Atom.intern("text/html", False), 0, INFO_HTML)
    for mime in IMAGE_TYPES:
        targets.add(Gdk.Atom.intern(mime, False), 0, INFO_IMAGE)
    return targets


def first_request(offered):
    """Which form of a drop to ask for first, from the formats the source offers.

    A browser drag (a link or image, which comes with both an address and HTML)
    starts with the HTML, to see whether it is a picture. Other picture data (an
    image editor) is asked for directly. Anything else (files, links, text) is
    asked for as before, via the target list.
    """
    if "text/html" in offered and ("text/uri-list" in offered or "text/x-moz-url" in offered):
        return "text/html"
    for mime in IMAGE_TYPES:
        if mime in offered:
            return mime
    return None


def drag_targets(dragged):
    targets = Gtk.TargetList.new([])
    if any(i.kind != "text" for i in dragged):
        targets.add_uri_targets(INFO_URIS)
    targets.add_text_targets(INFO_TEXT)
    return targets


def fill_selection(data, info, dragged):
    """Hand the dragged items to the app they are dropped on."""
    if info == INFO_URIS:
        data.set_uris([i.value for i in dragged if i.kind != "text"])
    else:
        data.set_text("\n".join(i.as_text() for i in dragged), -1)


def _action(context):
    offered = context.get_actions()
    if offered & Gdk.DragAction.COPY:
        return Gdk.DragAction.COPY
    if offered & Gdk.DragAction.LINK:
        return Gdk.DragAction.LINK
    return 0


class DropTarget:
    """Makes a widget accept files, links and text from other apps."""

    def __init__(self, widget, on_items, on_hover=None):
        self._receiving = False
        self._downloads = 0
        self._image_src = None  # the picture's address, for naming its data
        self._on_items = on_items
        self._on_hover = on_hover or (lambda hovering: None)
        widget.drag_dest_set(0, [], ACTIONS)
        widget.drag_dest_set_target_list(drop_targets())
        widget.connect("drag-motion", self._motion)
        widget.connect("drag-leave", self._leave)
        widget.connect("drag-drop", self._drop)
        widget.connect("drag-data-received", self._received)

    @property
    def receiving(self):
        """True while a drop is still arriving, including a picture being downloaded."""
        return self._receiving or self._downloads > 0

    @staticmethod
    def _acceptable(widget, context):
        """The target to fetch, or None. Drags from the shelf itself are refused."""
        if Gtk.drag_get_source_widget(context) is not None or not _action(context):
            return None
        target = widget.drag_dest_find_target(context, None)
        return None if target is None or target.name() == "NONE" else target

    def _motion(self, widget, context, x, y, time):
        if self._acceptable(widget, context) is None:
            Gdk.drag_status(context, 0, time)
            return True
        Gdk.drag_status(context, _action(context), time)
        self._on_hover(True)
        return True

    def _leave(self, widget, context, time):
        self._on_hover(False)

    def _drop(self, widget, context, x, y, time):
        target = self._acceptable(widget, context)
        if target is None:
            Gtk.drag_finish(context, False, False, time)
            return True
        self._receiving = True
        self._image_src = None
        offered = {t.name() for t in context.list_targets()}
        special = first_request(offered)
        if special:
            target = Gdk.Atom.intern(special, False)
        widget.drag_get_data(context, target, time)
        return True

    def _received(self, widget, context, x, y, data, info, time):
        if info == INFO_IMAGE:
            self._save_image(context, data, time)
            return
        if info == INFO_HTML:
            self._picture_from_html(widget, context, data, time)
            return
        self._receiving = False
        new = []
        if info == INFO_URIS:
            new = items.from_uris(data.get_uris() or [])
        else:
            new = items.from_text(data.get_text())
        Gtk.drag_finish(context, bool(new), False, time)
        if new:
            self._on_items(new)

    def _save_image(self, context, data, time):
        """Raw picture data, e.g. from an image editor: store it as a file."""
        self._receiving = False
        raw = data.get_data()
        mime = data.get_data_type().name()
        path = None
        if raw:
            try:
                path = fetch.save(raw, fetch.file_name(self._image_src or "", mime))
            except OSError as e:
                fetch.log.warning("could not save the dropped picture: %s", e)
        Gtk.drag_finish(context, path is not None, False, time)
        if path:
            self._on_items(items.from_paths([path]))

    def _picture_from_html(self, widget, context, data, time):
        """A browser drag: if it is a picture, download that; otherwise fall back to
        the address or text, as before."""
        src = fetch.image_in_html(fetch.decode_html(data.get_data() or b""))
        if src is None:
            target = widget.drag_dest_find_target(context, None)  # the address or text
            widget.drag_get_data(context, target, time)
            return
        offered = {t.name() for t in context.list_targets()}
        image_data = next((m for m in IMAGE_TYPES if m in offered), None)
        if image_data:
            # The browser hands over the picture itself: no download, real name kept.
            self._image_src = src
            widget.drag_get_data(context, Gdk.Atom.intern(image_data, False), time)
            return
        self._receiving = False
        self._downloads += 1
        Gtk.drag_finish(context, True, False, time)

        def done(path):
            self._downloads -= 1
            # If the picture can't be fetched, keep at least its address.
            self._on_items(items.from_paths([path]) if path else items.from_uris([src])
                           if not src.startswith("data:") else [])

        fetch.download(src, done)
