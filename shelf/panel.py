"""The shelf panel: a list of items you can drag out, with Flush and Undo."""
import logging
import re

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from . import dnd, style, thumbnails
from .items import Item

log = logging.getLogger(__name__)

ICON_SIZE = 48
ZWSP = "\u200b"


def breakable(name):
    """Let long file names wrap after _ and - and before the extension, not mid-word."""
    name = re.sub(r"([_\-])", r"\1" + ZWSP, name)
    return re.sub(r"\.(?=[^.]+$)", ZWSP + ".", name)
# Space taken by everything except the item list (header, footer, padding, undo bar).
CHROME_HEIGHT = 150


class ItemRow(Gtk.ListBoxRow):
    def __init__(self, item, thumbnail_limit=0):
        super().__init__()
        self.item = item
        self._thumbnail_limit = thumbnail_limit  # largest file to thumbnail, in bytes
        self.gicon = None
        self._cancel = Gio.Cancellable()

        self.handle = Gtk.EventBox()  # receives the presses that start drags
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.image = Gtk.Image(halign=Gtk.Align.CENTER)
        self.image.set_pixel_size(ICON_SIZE)
        self.image.set_size_request(ICON_SIZE, ICON_SIZE)

        self.remove_button = Gtk.Button.new_from_icon_name("window-close-symbolic",
                                                          Gtk.IconSize.MENU)
        self.remove_button.set_halign(Gtk.Align.END)
        self.remove_button.set_valign(Gtk.Align.START)
        self.remove_button.set_tooltip_text("Remove from the shelf")
        self.remove_button.get_style_context().add_class("shelf-remove")
        icon = Gtk.Overlay()
        icon.add(self.image)
        icon.add_overlay(self.remove_button)
        box.pack_start(icon, False, False, 0)

        title = Gtk.Label(label=breakable(item.label), justify=Gtk.Justification.CENTER,
                          ellipsize=Pango.EllipsizeMode.MIDDLE, lines=2, wrap=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=1)
        no_hyphens = Pango.AttrList()
        no_hyphens.insert(Pango.attr_insert_hyphens_new(False))
        title.set_attributes(no_hyphens)
        title.get_style_context().add_class("shelf-name")
        box.pack_start(title, False, False, 0)

        self.handle.add(box)
        self.add(self.handle)
        tip = item.value if item.kind == "text" else (item.path or item.value)
        self.set_tooltip_text(f"{tip}\n{item.detail}" if item.kind != "file" else tip)
        self.connect("destroy", lambda *a: self._cancel.cancel())
        self._load_icon()

    def _set_icon(self, gicon):
        self.gicon = gicon
        self.image.set_from_gicon(gicon, Gtk.IconSize.DND)
        self.image.set_pixel_size(ICON_SIZE)

    def _load_icon(self):
        if self.item.kind == "text":
            self._set_icon(Gio.ThemedIcon.new("text-x-generic"))
            return
        if self.item.kind == "url":
            self._set_icon(Gio.ThemedIcon.new("text-html"))
            return
        self._set_icon(Gio.ThemedIcon.new("text-x-generic"))
        Gio.File.new_for_uri(self.item.value).query_info_async(
            "standard::icon,standard::content-type,standard::type,standard::size,"
            "time::modified,thumbnail::path", Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_LOW, self._cancel, self._on_info)

    def _on_info(self, file, result):
        try:
            info = file.query_info_finish(result)
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self.get_style_context().add_class("missing")
                self.set_tooltip_text(f"{self.get_tooltip_text()}\n(not found)")
            return
        if info.get_icon():
            self._set_icon(info.get_icon())
        thumb = info.get_attribute_byte_string("thumbnail::path")
        if thumb:
            self._set_thumbnail(thumb)
        elif (info.get_file_type() == Gio.FileType.REGULAR
              and 0 < info.get_size() <= self._thumbnail_limit):
            mtime = info.get_attribute_uint64("time::modified")
            thumbnails.request(self.item.value, info.get_content_type() or "", mtime,
                               self._set_thumbnail)

    def _set_thumbnail(self, path):
        if self._cancel.is_cancelled():
            return False  # row already gone
        try:
            scale = self.get_scale_factor()
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, ICON_SIZE * scale, ICON_SIZE * scale, True)
            self.image.set_from_surface(Gdk.cairo_surface_create_from_pixbuf(pixbuf, scale, None))
        except GLib.Error:
            pass
        return False


class ShelfPanel(Gtk.Window):
    """Calls back into the app; never changes the item list itself."""

    def __init__(self, edge, on_drop_in, on_remove, on_dragged_out, on_flush, on_undo,
                 on_settings, on_move_start, on_move_end, on_float_toggle, on_float_menu,
                 on_paste):
        super().__init__(type=Gtk.WindowType.POPUP)
        style.make_overlay(self)
        self.get_style_context().add_class("shelf-window")
        self._on_remove = on_remove
        self._on_dragged_out = on_dragged_out
        self._dragging = []
        self._drag_failed = False
        self._on_move_start = on_move_start
        self._on_move_end = on_move_end
        self._move = None  # while the header is being dragged
        self.dragging_out = False  # a drag from the shelf to another app is in progress
        self.thumbnail_limit = 0     # largest file to make a thumbnail of, in bytes

        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.get_style_context().add_class("shelf")
        self.set_edge(edge)

        header = Gtk.Box(spacing=4)
        header.get_style_context().add_class("shelf-header")
        self.count = Gtk.Label(xalign=1)
        self.count.get_style_context().add_class("shelf-dim")
        self.flush_button = self._icon_button("edit-clear-all-symbolic",
                                              "Flush: take everything off the shelf", on_flush)
        settings_button = self._icon_button("emblem-system-symbolic", "Settings", on_settings)
        self.float_button = Gtk.ToggleButton()
        self.float_button.add(Gtk.Image.new_from_icon_name("window-new-symbolic",
                                                           Gtk.IconSize.MENU))
        self.float_button.get_style_context().add_class("shelf-icon-button")
        self._float_handler = self.float_button.connect(
            "toggled", lambda b: on_float_toggle(b.get_active()))
        self.float_button.connect(
            "button-press-event",
            lambda b, e: e.button == Gdk.BUTTON_SECONDARY and (on_float_menu(e) or True))
        paste_button = self._icon_button("edit-paste-symbolic",
                                         "Add the clipboard to the shelf", on_paste)
        header.pack_start(paste_button, False, False, 0)
        header.pack_start(Gtk.Box(), True, True, 0)  # the empty grip space
        header.pack_end(settings_button, False, False, 0)
        header.pack_end(self.float_button, False, False, 0)
        # The header's empty space is the grip for moving the shelf to another side.
        self.header = Gtk.EventBox(visible_window=False)
        self.header.add(header)
        self.header.set_tooltip_text("Drag to move the shelf to another screen side")
        self.header.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                               | Gdk.EventMask.BUTTON1_MOTION_MASK
                               | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.header.connect("button-press-event", self._grip_press)
        self.header.connect("motion-notify-event", self._grip_motion)
        self.header.connect("button-release-event", self._grip_release)
        self.header.connect("enter-notify-event", lambda w, e: self._set_cursor("grab"))
        self.header.connect("leave-notify-event",
                            lambda w, e: self._move or self._set_cursor(None))
        self.frame.pack_start(self.header, False, False, 0)

        self.empty = Gtk.Label(justify=Gtk.Justification.CENTER, wrap=True,
                               max_width_chars=1, vexpand=True)
        self.empty.get_style_context().add_class("shelf-empty")
        self.empty.get_style_context().add_class("shelf-dim")
        self.set_empty_hint("")

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.list.set_activate_on_single_click(False)
        self.list.connect("row-activated", lambda lb, row: self._open(row.item))
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.add(self.list)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(self.scroller, "list")
        self.stack.set_vhomogeneous(False)
        self.stack.set_hhomogeneous(False)
        self.frame.pack_start(self.stack, True, True, 0)

        undo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        undo_box.get_style_context().add_class("shelf-undo")
        self.undo_label = Gtk.Label(justify=Gtk.Justification.CENTER, wrap=True,
                                    max_width_chars=1)
        self.undo_label.get_style_context().add_class("shelf-dim")
        self.undo_button = undo_button = Gtk.Button(label="Undo")
        undo_button.connect("clicked", lambda b: on_undo())
        self._notice_timer = None
        undo_box.pack_start(self.undo_label, False, False, 0)
        undo_box.pack_start(undo_button, False, False, 0)
        self.undo = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.NONE)
        self.undo.add(undo_box)

        # Flush and the item count sit in the bottom-right corner.
        self.footer = Gtk.Box()
        self.footer.get_style_context().add_class("shelf-footer")
        self.footer.pack_end(self.flush_button, False, False, 0)
        self.footer.pack_end(self.count, False, False, 6)  # count right beside Flush
        self.frame.pack_end(self.footer, False, False, 0)
        self.frame.pack_end(self.undo, False, False, 0)

        # Never shown: a sample row in the panel's styling, to measure the minimum height.
        self._probe = Gtk.ListBox(no_show_all=True)
        self._probe.add(ItemRow(Item("text", "Item")))
        self._probe.get_children()[0].show_all()
        self.frame.pack_start(self._probe, False, False, 0)

        self.add(self.frame)
        self.frame.show_all()
        self.drop = dnd.DropTarget(self, on_drop_in, self.set_drop_highlight)

    @staticmethod
    def _icon_button(icon, tooltip, callback):
        button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
        button.set_tooltip_text(tooltip)
        button.get_style_context().add_class("shelf-icon-button")
        button.connect("clicked", lambda b: callback())
        return button

    # --- state from the app -------------------------------------------------

    def set_edge(self, edge):
        ctx = self.frame.get_style_context()
        for e in ("left", "right"):
            ctx.remove_class(f"edge-{e}")
        ctx.add_class(f"edge-{edge}")

    def set_items(self, items):
        for row in self.list.get_children():
            row.destroy()
        for item in items:
            row = ItemRow(item, self.thumbnail_limit)
            self._wire_row(row)
            self.list.add(row)
            row.show_all()
        n = len(items)
        self.count.set_text(str(n) if n else "")
        self.count.set_tooltip_text(f"{n} item{'s' if n != 1 else ''} on the shelf")
        self.flush_button.set_sensitive(bool(n))
        self.stack.set_visible_child_name("list" if n else "empty")

    def set_floating(self, on):
        """Show whether the floating drop panel is on, without reporting it back."""
        with self.float_button.handler_block(self._float_handler):
            self.float_button.set_active(on)
        self.float_button.set_tooltip_text(
            "Floating drop panel is " + ("on: it appears beside the pointer when you drag"
                                         if on else "off") + ". Click to turn it "
            + ("off" if on else "on") + ".\nRight-click to choose apps.")

    def set_empty_hint(self, extra):
        text = "Drop here"
        self.empty.set_text(f"{text}\n\n{extra}" if extra else text)

    def show_undo(self, message):
        self._end_notice()
        self.undo_label.set_text(message)
        self.undo_button.show()
        self.undo.set_reveal_child(True)

    def hide_undo(self):
        self.undo.set_reveal_child(False)

    def show_notice(self, message, seconds=2.5):
        """A short message in the bottom bar, without an Undo button."""
        if self.undo.get_reveal_child() and self.undo_button.get_visible():
            return  # an Undo is on offer; don't hide it
        self._end_notice()
        self.undo_label.set_text(message)
        self.undo_button.hide()
        self.undo.set_reveal_child(True)
        self._notice_timer = GLib.timeout_add(int(seconds * 1000), self._notice_done)

    def _notice_done(self):
        self._notice_timer = None
        self.undo.set_reveal_child(False)
        self.undo_button.show()
        return False

    def _end_notice(self):
        if self._notice_timer:
            GLib.source_remove(self._notice_timer)
            self._notice_timer = None

    def set_drop_highlight(self, on):
        ctx = self.frame.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("drop-hover")

    def natural_height(self, width, max_height, min_items):
        """Height the panel wants: its content, but at least min_items rows tall."""
        self.scroller.set_max_content_height(max(60, max_height - CHROME_HEIGHT))
        self.frame.set_size_request(width, -1)
        content = self.frame.get_preferred_height_for_width(width)[1]
        row = self._probe.get_children()[0].get_preferred_height_for_width(width)[1]
        chrome = (self.header.get_preferred_height_for_width(width)[1]
                  + self.footer.get_preferred_height_for_width(width)[1] + 8)
        if self.undo.get_reveal_child():
            chrome += self.undo.get_preferred_height_for_width(width)[1]
        return max(content, chrome + min_items * row)

    def place(self, rect):
        self.move(rect.x, rect.y)
        self.resize(rect.width, rect.height)
        self.frame.set_size_request(rect.width, rect.height)

    # --- moving the shelf by its header ---------------------------------------

    def _set_cursor(self, name):
        window = self.get_window()
        if window is not None:
            window.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name)
                              if name else None)
        return False

    def _grip_press(self, widget, event):
        if event.button != Gdk.BUTTON_PRIMARY or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        self._move = {"start": (event.x_root, event.y_root),
                      "origin": self.get_position(), "moving": False}
        return True

    def _grip_motion(self, widget, event):
        m = self._move
        if m is None:
            return False
        dx, dy = event.x_root - m["start"][0], event.y_root - m["start"][1]
        if not m["moving"]:
            if abs(dx) + abs(dy) < 6:
                return True  # still a click, not a drag
            m["moving"] = True
            self._set_cursor("grabbing")
            self._on_move_start()
        self.move(int(m["origin"][0] + dx), int(m["origin"][1] + dy))
        return True

    def _grip_release(self, widget, event):
        m, self._move = self._move, None
        if m is None:
            return False
        self._set_cursor("grab")
        if m["moving"]:
            self._on_move_end(int(event.x_root), int(event.y_root))
        return True

    # --- rows: drag out, context menu ----------------------------------------

    def _wire_row(self, row):
        row.remove_button.connect("clicked", lambda b: self._on_remove([row.item.id]))
        h = row.handle
        h.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [], dnd.ACTIONS)
        h.connect("button-press-event", self._on_press, row)
        h.connect("drag-begin", self._on_drag_begin, row)
        h.connect("drag-data-get", self._on_drag_data_get)
        h.connect("drag-failed", self._on_drag_failed)
        h.connect("drag-end", self._on_drag_end)

    def _on_press(self, widget, event, row):
        if event.button == Gdk.BUTTON_SECONDARY:
            self._menu(row, event)
            return True
        if event.button == Gdk.BUTTON_PRIMARY:
            # Pressing a selected row drags the whole selection; otherwise just this row.
            rows = self.list.get_selected_rows() if row.is_selected() else [row]
            self._dragging = [r.item for r in rows]
            widget.drag_source_set_target_list(dnd.drag_targets(self._dragging))
        return False

    def _on_drag_begin(self, widget, context, row):
        self._drag_failed = False
        self.dragging_out = True
        if len(self._dragging) == 1 and row.gicon is not None:
            Gtk.drag_set_icon_gicon(context, row.gicon, 0, 0)
        else:
            Gtk.drag_set_icon_name(context, "edit-copy", 0, 0)

    def _on_drag_data_get(self, widget, context, data, info, time):
        dnd.fill_selection(data, info, self._dragging)

    def _on_drag_failed(self, widget, context, result):
        self._drag_failed = True
        return False

    def _on_drag_end(self, widget, context):
        self.dragging_out = False
        dropped = not self._drag_failed and bool(context.get_selected_action())
        ids = [i.id for i in self._dragging]
        self._dragging = []
        if dropped and ids:
            # Leave the row alone until GTK has finished with this drag.
            GLib.idle_add(lambda: self._on_dragged_out(ids) and False)

    def _menu(self, row, event):
        if not row.is_selected():
            self.list.unselect_all()
            self.list.select_row(row)
        chosen = [r.item for r in self.list.get_selected_rows()]
        item = row.item
        menu = Gtk.Menu()

        def add(label, callback, sensitive=True):
            mi = Gtk.MenuItem(label=label)
            mi.set_sensitive(sensitive)
            mi.connect("activate", lambda m: callback())
            menu.append(mi)

        if item.kind != "text":
            add("Open", lambda: self._open(item))
        if item.kind == "file":
            add("Show in Folder", lambda: self._show_in_folder(item))
        add("Copy", lambda: self._copy(chosen))
        menu.append(Gtk.SeparatorMenuItem())
        add("Remove" if len(chosen) == 1 else f"Remove {len(chosen)} Items",
            lambda: self._on_remove([i.id for i in chosen]))
        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_pointer(event)

    # --- item actions -------------------------------------------------------

    def _open(self, item):
        if item.kind == "text":
            self._copy([item])
            return
        try:
            Gio.AppInfo.launch_default_for_uri(item.value, None)
        except GLib.Error as e:
            log.warning("could not open %s: %s", item.value, e.message)

    @staticmethod
    def _show_in_folder(item):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                     "org.freedesktop.FileManager1", "ShowItems",
                     GLib.Variant("(ass)", ([item.value], "")), None,
                     Gio.DBusCallFlags.NONE, -1, None, None, None)
        except GLib.Error as e:
            log.warning("could not show %s in the file manager: %s", item.value, e.message)

    @staticmethod
    def _copy(chosen):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text("\n".join(i.as_text() for i in chosen), -1)
