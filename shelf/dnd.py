"""Drag-and-drop plumbing shared by the panel and the edge strip.

The shelf only ever copies or links: it never accepts or offers a "move", so a
drop onto or out of the shelf can't take a file away from where it lives.
"""
from gi.repository import Gdk, Gtk

from . import items

INFO_URIS, INFO_TEXT = 1, 2
ACTIONS = Gdk.DragAction.COPY | Gdk.DragAction.LINK


def drop_targets():
    targets = Gtk.TargetList.new([])
    targets.add_uri_targets(INFO_URIS)  # first, so files win over their text form
    targets.add_text_targets(INFO_TEXT)
    return targets


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
        self.receiving = False
        self._on_items = on_items
        self._on_hover = on_hover or (lambda hovering: None)
        widget.drag_dest_set(0, [], ACTIONS)
        widget.drag_dest_set_target_list(drop_targets())
        widget.connect("drag-motion", self._motion)
        widget.connect("drag-leave", self._leave)
        widget.connect("drag-drop", self._drop)
        widget.connect("drag-data-received", self._received)

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
        self.receiving = True
        widget.drag_get_data(context, target, time)
        return True

    def _received(self, widget, context, x, y, data, info, time):
        self.receiving = False
        new = []
        if info == INFO_URIS:
            new = items.from_uris(data.get_uris() or [])
        else:
            new = items.from_text(data.get_text())
        Gtk.drag_finish(context, bool(new), False, time)
        if new:
            self._on_items(new)
