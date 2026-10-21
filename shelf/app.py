"""The shelf application: decides when the panel shows, and owns the item list.

When the panel is visible:
  - always while the shelf holds items, or while Undo is on offer
  - while empty: when opened by the hotkey (until the hotkey or Esc),
    by a drag onto the edge strip (until the drag ends), or by resting the
    pointer on the edge (until the pointer leaves the panel)
While another app drags something, a strip on the shelf's edge and (if turned on,
for that app) a floating drop panel beside the pointer accept the drop.
An empty shelf that is left alone fades away after empty_timeout_seconds.
"""
import dataclasses
import logging

from gi.repository import Gdk, Gio, GLib, Gtk

from . import APP_ID, apps, autostart, config, fetch, geometry, items, store, style
from .floating import HEIGHT as FLOAT_HEIGHT, WIDTH as FLOAT_WIDTH, FloatingDrop
from .handle import EdgeHandle
from .panel import ShelfPanel

log = logging.getLogger(__name__)

POINTER_POLL_MS = 120
DRAG_POLL_MS = 50
AFTER_DRAG_MS = 400       # let a drop that is still arriving land before closing
HOVER_LEAVE_MS = 500
FADE_MS = 400
FADE_STEP_MS = 16


def current_monitors():
    display = Gdk.Display.get_default()
    monitors = []
    for i in range(display.get_n_monitors()):
        m = display.get_monitor(i)
        g, w = m.get_geometry(), m.get_workarea()
        monitors.append(geometry.Monitor(
            i, m.get_model() or str(i),
            geometry.Rect(g.x, g.y, g.width, g.height),
            geometry.Rect(w.x, w.y, w.width, w.height), m.is_primary()))
    return monitors


def pointer_position():
    seat = Gdk.Display.get_default().get_default_seat()
    _screen, x, y = seat.get_pointer().get_position()
    return x, y


class ShelfApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("toggle", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Show or hide the empty shelf (same as the hotkey)", None)
        self.add_main_option("flush", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Take everything off the shelf", None)
        self.add_main_option("add", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING_ARRAY,
                             "Put a file or folder on the shelf (repeatable)", "PATH")
        self.add_main_option("add-text", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING_ARRAY,
                             "Put a text snippet on the shelf (repeatable)", "TEXT")
        self.add_main_option("toggle-float", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Turn the floating drop panel on or off", None)
        self.add_main_option("settings", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Open the settings window", None)
        self.add_main_option("app-settings", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Open the per-app settings of the floating drop panel", None)
        self.add_main_option("quit", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Stop the running shelf", None)

    # --- start-up and command line -----------------------------------------

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        self.config = config.load()
        style.install()
        self.items = store.load()
        fetch.clean([it.path for it in self.items])

        self._open_reason = None   # None, "hotkey", "drag" or "hover"
        self._undo_entries = None  # [(index, item)] that Undo would put back
        self._undo_timer = None
        self._monitor = None       # the monitor the visible panel is on
        self._panel_rect = None
        self._drag_active = False
        self._hover_since = None
        self._outside_since = None
        self._escape = None
        self._hotkeys = {}         # config field name -> grab token
        self._float_timer = None
        self.seen_apps = apps.SeenApps()
        self.last_drag_app = None  # the app the most recent drag came from
        self._idle_since = None    # when the empty panel was last in use
        self._fade_timer = None
        self._fade_started = 0
        self._settings = None
        self._moving = False       # the panel is being dragged by its header

        self.panel = ShelfPanel(self.config.edge, self.add_items, self.remove_items,
                                self._dragged_out, self.flush, self.undo, self.show_settings,
                                self._move_started, self._move_ended,
                                self.set_floating_enabled, self._float_menu)
        self.panel.set_floating(self.config.floating_enabled)
        self.panel.thumbnail_limit = self._thumbnail_limit()
        self.handle = EdgeHandle(self.add_items, self._handle_dragged_over)
        self.floating = FloatingDrop(self.add_items)
        self.handle.realize()  # its window id tells our own drags apart

        self.x11 = None
        try:
            from .x11 import XConnection
            self.x11 = XConnection()
            self.x11.on_drag_start = self._drag_started
        except (OSError, ImportError) as e:
            log.warning("no X11 connection (%s): hotkey and drag strip disabled", e)
        self._grab_hotkeys()

        screen = Gdk.Screen.get_default()
        screen.connect("monitors-changed", self._monitors_changed)
        screen.connect("size-changed", self._monitors_changed)
        GLib.timeout_add(POINTER_POLL_MS, self._poll_pointer)

        from .tray import Tray
        self.tray = Tray(self)

        self.panel.set_items(self.items)
        self._update()

    def do_command_line(self, command_line):
        opts = command_line.get_options_dict().end().unpack()
        if opts.get("quit"):
            self.quit()
            return 0
        if opts.get("flush"):
            self.flush()
        new = []
        for arg in opts.get("add") or []:
            new.append(items.Item("file", command_line.create_file_for_arg(arg).get_uri()))
        for text in opts.get("add-text") or []:
            new += items.from_text(text)
        if new:
            self.add_items(new)
        if opts.get("toggle"):
            self.toggle()
        if opts.get("toggle-float"):
            self.set_floating_enabled(not self.config.floating_enabled)
        if opts.get("settings"):
            self.show_settings()
        if opts.get("app-settings"):
            self.show_settings("apps")
        return 0

    # --- settings ----------------------------------------------------------

    def show_settings(self, page="main"):
        from .settings import SettingsWindow
        if self._settings is None:
            self._settings = SettingsWindow(self)
            self._settings.connect("destroy", lambda w: setattr(self, "_settings", None))
        self._settings.show_page(page)
        self._settings.present()

    def apply_config(self, cfg):
        """Use new settings right away and save them. Returns a problem to show, or None."""
        old, self.config = self.config, cfg
        problem = config.save(cfg)
        keys_changed = (cfg.hotkey, cfg.float_hotkey) != (old.hotkey, old.float_hotkey)
        if keys_changed or self.hotkey_error or len(self._hotkeys) < self._wanted_hotkeys():
            self._grab_hotkeys()
        problem = self.hotkey_error or problem
        self.panel.set_edge(cfg.edge)
        self.panel.set_floating(cfg.floating_enabled)
        if self._thumbnail_limit() != self.panel.thumbnail_limit:
            self.panel.thumbnail_limit = self._thumbnail_limit()
            self.panel.set_items(self.items)
        self.tray.refresh()
        if not cfg.floating_enabled:
            self._hide_floating()
        self._monitor = None
        self._update()
        return problem

    def _thumbnail_limit(self):
        return self.config.thumbnail_max_mb * 1024 * 1024 if self.config.thumbnails else 0

    def set_autostart(self, on):
        """Start at login on or off. Returns an error message, or None."""
        problem = autostart.set_enabled(on)
        self.tray.refresh()
        if self._settings is not None:
            self._settings.sync()
        return problem

    def set_floating_for_app(self, app, on):
        rules = dict(self.config.floating_apps)
        rules[app] = on
        self.apply_config(dataclasses.replace(self.config, floating_apps=rules))
        if self._settings is not None:
            self._settings.sync()

    def _float_menu(self, event):
        """Right-click on the header's floating-panel button: quick per-app switches."""
        cfg = self.config
        menu = Gtk.Menu()
        main = Gtk.CheckMenuItem(label="Floating drop panel", active=cfg.floating_enabled)
        main.connect("toggled", lambda m: self.set_floating_enabled(m.get_active()))
        menu.append(main)
        recent = self.seen_apps.recent()[:8]
        if recent:
            menu.append(Gtk.SeparatorMenuItem())
            title = Gtk.MenuItem(label="Show when dragging from:", sensitive=False)
            menu.append(title)
        for app in recent:
            item = Gtk.CheckMenuItem(label=apps.describe(app)[0], active=cfg.app_allowed(app),
                                     sensitive=cfg.floating_enabled)
            item.set_tooltip_text(app)
            item.connect("toggled", lambda m, a=app: self.set_floating_for_app(a, m.get_active()))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        more = Gtk.MenuItem(label="All Apps…")
        more.connect("activate", lambda m: self.show_settings("apps"))
        menu.append(more)
        menu.show_all()
        menu.attach_to_widget(self.panel, None)
        menu.popup_at_pointer(event)

    def set_floating_enabled(self, on):
        self.apply_config(dataclasses.replace(self.config, floating_enabled=on))
        if self._settings is not None:
            self._settings.sync()

    def suspend_hotkeys(self):
        """Let the settings window record new keys, including the current ones."""
        for token in self._hotkeys.values():
            self.x11.ungrab_key(token)
        self._hotkeys.clear()

    def _wanted_hotkeys(self):
        return sum(1 for key in (self.config.hotkey, self.config.float_hotkey) if key)

    def _grab_hotkeys(self):
        """(Re)grab the configured hotkeys; problems end up in self.hotkey_error."""
        self.suspend_hotkeys()
        problems = []
        actions = (("hotkey", self.toggle),
                   ("float_hotkey", lambda: self.set_floating_enabled(
                       not self.config.floating_enabled)))
        for name, action in actions:
            key = getattr(self.config, name)
            if not key:
                continue
            if self.x11 is None:
                problems.append(f"{key} unavailable: no X11 connection")
                continue
            from .x11 import GrabError
            try:
                self._hotkeys[name] = self.x11.grab_key(key, lambda t, a=action: a())
            except GrabError as e:
                log.warning("hotkey not available: %s", e)
                problems.append(f"Hotkey unavailable: {e}")
        self.hotkey_error = "\n".join(problems) or None
        if "hotkey" in self._hotkeys:
            hint = f"{self.config.hotkey} or Esc to close"
        else:
            hint = self.hotkey_error or ""
        self.panel.set_empty_hint(hint)

    # --- the item list -----------------------------------------------------

    def add_items(self, new):
        if not items.merge(self.items, new):
            return
        self._open_reason = None  # from now on it stays up because it has items
        self._release_escape()
        self._cancel_fade()
        self._items_changed()

    def remove_items(self, ids, message=None):
        ids = set(ids)
        removed = [(i, it) for i, it in enumerate(self.items) if it.id in ids]
        if not removed:
            return
        self.items = [it for it in self.items if it.id not in ids]
        self._offer_undo(message or f"{len(removed)} removed", removed)
        self._items_changed()

    def flush(self):
        if self.items:
            self.remove_items([it.id for it in self.items], f"{len(self.items)} flushed")

    def _dragged_out(self, ids):
        if self.config.remove_after_drop:
            self.remove_items(ids, f"{len(ids)} dropped")

    def undo(self):
        entries = self._undo_entries or []
        self._clear_undo()
        present = {it.id for it in self.items}
        for index, item in sorted(entries, key=lambda e: e[0]):
            if item.id not in present:
                self.items.insert(min(index, len(self.items)), item)
        self._items_changed()

    def _offer_undo(self, message, entries):
        if self._undo_timer:
            GLib.source_remove(self._undo_timer)
        self._undo_entries = entries
        self._undo_timer = GLib.timeout_add_seconds(self.config.undo_seconds, self._undo_expired)
        self.panel.show_undo(message)

    def _undo_expired(self):
        self._undo_timer = None
        self._clear_undo()
        self._update()
        return False

    def _clear_undo(self):
        if self._undo_timer:
            GLib.source_remove(self._undo_timer)
            self._undo_timer = None
        self._undo_entries = None
        self.panel.hide_undo()

    def _items_changed(self):
        store.save(self.items)
        self.panel.set_items(self.items)
        self.tray.refresh()
        self._update()

    # --- showing and hiding ------------------------------------------------

    def toggle(self):
        """The hotkey: open the empty shelf, or close it again."""
        if self.items:
            self._update()  # it is already up
        elif self._open_reason == "hotkey":
            self._close()
        else:
            self._open("hotkey")

    def _open(self, reason):
        self._cancel_fade()
        self._idle_since = None
        self._open_reason = reason
        if reason == "hotkey":
            self._grab_escape()
        self._update()

    def _close(self):
        self._open_reason = None
        self._release_escape()
        self._update()

    def _update(self):
        visible = bool(self.items) or self._undo_entries is not None \
            or self._open_reason is not None
        if not visible:
            self.panel.hide()
            self._monitor = self._panel_rect = None
            self._idle_since = None
            return
        if self._monitor is None:
            self._monitor = self._pick_monitor()
        self.handle.hide()
        self._place_panel()
        self.panel.show()

    def _pick_monitor(self):
        return geometry.choose_monitor(current_monitors(), self.config.monitor,
                                       pointer_position())

    def _place_panel(self):
        cfg, m = self.config, self._monitor
        max_h = geometry.max_panel_height(m, cfg.max_height_percent)
        width = min(cfg.width, m.workarea.width)
        height = self.panel.natural_height(width, max_h, cfg.min_items)
        self._panel_rect = geometry.panel_rect(m, cfg.edge, width, height,
                                               cfg.max_height_percent)
        self.panel.place(self._panel_rect)

    def _monitors_changed(self, screen):
        self._monitor = None
        self._update()

    def _grab_escape(self):
        if self.x11 and self._escape is None:
            from .x11 import GrabError
            try:
                self._escape = self.x11.grab_key("Escape", lambda t: self._close())
            except GrabError as e:
                log.info("Esc not available to close the shelf: %s", e)

    def _release_escape(self):
        if self._escape is not None:
            self.x11.ungrab_key(self._escape)
            self._escape = None

    # --- moving the shelf to another side -----------------------------------

    def _move_started(self):
        self._moving = True
        self._cancel_fade()

    def _move_ended(self, x, y):
        """Snap to the side of the monitor nearest to where the header was let go."""
        self._moving = False
        self._idle_since = None
        m = geometry.monitor_at(current_monitors(), x, y)
        self.apply_config(dataclasses.replace(
            self.config, monitor=m.name, edge=geometry.nearest_side(m, x)))
        if self._settings is not None:
            self._settings.sync()

    # --- drags from other apps ---------------------------------------------

    def _drag_started(self, owner):
        if self._drag_active:
            return
        self._drag_active = True
        self._cancel_fade()
        own = self.panel.dragging_out or self._is_own_window(owner)
        app = None if own else self.x11.drag_source_app(owner)
        if app:
            self.last_drag_app = app
            self.seen_apps.note(app)
            if self._settings is not None:
                self._settings.sync()
        if not own and self.config.floating_for(app):
            self._float_timer = GLib.timeout_add(self.config.floating_delay_ms,
                                                 self._show_floating, pointer_position())
        if not self.panel.get_visible():
            monitors = current_monitors()
            m = geometry.choose_monitor(monitors, self.config.monitor, pointer_position())
            outer = geometry.is_outer_edge(monitors, m, self.config.edge)
            width = self.config.handle_width if outer else self.config.inner_handle_width
            self.handle.place(geometry.handle_rect(m, self.config.edge, width))
            self.handle.show()
        GLib.timeout_add(DRAG_POLL_MS, self._poll_drag)

    def _is_own_window(self, xid):
        from gi.repository import GdkX11
        from .x11 import same_client
        window = self.handle.get_window() or self.panel.get_window()
        return window is not None and same_client(xid, GdkX11.X11Window.get_xid(window))

    def _show_floating(self, start):
        """Put the floating drop panel beside where the pointer was when the drag began."""
        self._float_timer = None
        if not self._drag_active or self.panel.dragging_out:
            return False  # drag already over, or it comes from the shelf itself
        x, y = start
        m = geometry.monitor_at(current_monitors(), x, y)
        rect = geometry.place_near(x, y, FLOAT_WIDTH, FLOAT_HEIGHT, m.workarea,
                                   self.config.floating_offset)
        self.floating.show_at(rect, len(self.items))
        return False

    def _hide_floating(self):
        if self._float_timer:
            GLib.source_remove(self._float_timer)
            self._float_timer = None
        self.floating.hide()

    def _poll_drag(self):
        if self.x11.buttons_down():
            return True
        self._drag_active = False
        if self._float_timer:
            GLib.source_remove(self._float_timer)
            self._float_timer = None
        GLib.timeout_add(AFTER_DRAG_MS, self._after_drag)
        return False

    def _after_drag(self):
        # The strip and floating panel stay up until a drop that is still on its
        # way has landed; hiding them earlier could lose it.
        if self._drag_active:
            return False
        if any(t.drop.receiving for t in (self.panel, self.handle, self.floating)):
            return True  # data still on its way; check again shortly
        self.handle.hide()
        self.floating.hide()
        if self._open_reason == "drag":
            self._close()
        return False

    def _handle_dragged_over(self):
        if self._open_reason in (None, "hover"):
            self._open("drag")

    # --- hover ---------------------------------------------------------------

    def _poll_pointer(self):
        if self._moving:
            return True
        now = GLib.get_monotonic_time() // 1000
        x, y = pointer_position()
        if self._open_reason == "hover":
            if self._panel_rect and self._panel_rect.grow(12).contains(x, y):
                self._outside_since = None
            elif self._outside_since is None:
                self._outside_since = now
            elif now - self._outside_since >= HOVER_LEAVE_MS:
                self._outside_since = None
                self._close()
        elif (self.config.open_on_hover and not self.panel.get_visible()
              and not self._drag_active and self._in_hover_zone(x, y)):
            if self._hover_since is None:
                self._hover_since = now
            elif now - self._hover_since >= self.config.hover_delay_ms:
                self._hover_since = None
                self._open("hover")
        else:
            self._hover_since = None
        self._check_idle(now, x, y)
        return True

    # --- fading away when empty and unused -----------------------------------

    def _check_idle(self, now, x, y):
        in_use = (self.items or not self.panel.get_visible() or self._drag_active
                  or (self._panel_rect and self._panel_rect.grow(12).contains(x, y)))
        if in_use:
            self._idle_since = None
            if self._fade_timer and self.panel.get_visible():
                self._cancel_fade()
        elif self._idle_since is None:
            self._idle_since = now
        elif (now - self._idle_since >= self.config.empty_timeout_seconds * 1000
              and not self._fade_timer):
            self._fade_started = now
            self._fade_timer = GLib.timeout_add(FADE_STEP_MS, self._fade_step)

    def _fade_step(self):
        done = (GLib.get_monotonic_time() // 1000 - self._fade_started) / FADE_MS
        if done < 1:
            self.panel.set_opacity(1 - done)
            return True
        self._fade_timer = None
        self._idle_since = None
        self._clear_undo()
        self._close()
        self.panel.set_opacity(1)
        return False

    def _cancel_fade(self):
        if self._fade_timer:
            GLib.source_remove(self._fade_timer)
            self._fade_timer = None
        self.panel.set_opacity(1)

    def _in_hover_zone(self, x, y):
        if self.x11 and self.x11.buttons_down():
            return False  # e.g. dragging a scrollbar along the edge
        monitors = current_monitors()
        m = geometry.choose_monitor(monitors, self.config.monitor, (x, y))
        # Outer edges: the last pixel column, where the pointer stops by itself.
        outer = geometry.is_outer_edge(monitors, m, self.config.edge)
        width = 1 if outer else self.config.inner_handle_width
        return geometry.handle_rect(m, self.config.edge, width).contains(x, y)
