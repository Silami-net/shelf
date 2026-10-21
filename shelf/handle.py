"""The drop strip that appears on the screen edge while something is being dragged."""
from gi.repository import Gtk

from . import dnd, style


class EdgeHandle(Gtk.Window):
    def __init__(self, on_drop_in, on_drag_over):
        super().__init__(type=Gtk.WindowType.POPUP)
        style.make_overlay(self)
        self.get_style_context().add_class("shelf-handle-window")
        self.strip = Gtk.Box()
        self.strip.get_style_context().add_class("shelf-handle")
        self.add(self.strip)
        self.strip.show()
        self._on_drag_over = on_drag_over
        self.drop = dnd.DropTarget(self, on_drop_in, self._hover)

    def _hover(self, on):
        ctx = self.strip.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("drop-hover")
        if on:
            self._on_drag_over()

    def place(self, rect):
        self.move(rect.x, rect.y)
        self.resize(rect.width, rect.height)
        self.strip.set_size_request(rect.width, rect.height)
