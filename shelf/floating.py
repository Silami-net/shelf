"""The floating drop panel: a small drop target that appears beside the pointer
when a drag starts, so things can go on the shelf without a trip to the edge."""
from gi.repository import Gtk

from . import dnd, style

WIDTH, HEIGHT = 112, 84


class FloatingDrop(Gtk.Window):
    def __init__(self, on_drop_in):
        super().__init__(type=Gtk.WindowType.POPUP)
        style.make_overlay(self)
        self.get_style_context().add_class("shelf-window")

        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                             valign=Gtk.Align.FILL)
        self.frame.get_style_context().add_class("shelf")
        self.frame.get_style_context().add_class("shelf-float")
        icon = Gtk.Image.new_from_icon_name("go-down-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        icon.set_pixel_size(24)
        title = Gtk.Label(label="Drop on shelf")
        self.count = Gtk.Label()
        self.count.get_style_context().add_class("shelf-detail")
        self.frame.pack_start(icon, True, True, 0)
        self.frame.pack_start(title, False, False, 0)
        self.frame.pack_start(self.count, False, False, 0)
        self.add(self.frame)
        self.frame.show_all()
        self.drop = dnd.DropTarget(self, on_drop_in, self._hover)

    def _hover(self, on):
        ctx = self.frame.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("drop-hover")

    def show_at(self, rect, count):
        self.count.set_text(f"{count} on the shelf" if count else "")
        self.count.set_visible(bool(count))
        self._hover(False)
        self.move(rect.x, rect.y)
        self.resize(rect.width, rect.height)
        self.frame.set_size_request(rect.width, rect.height)
        self.show()
