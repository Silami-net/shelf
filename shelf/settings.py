"""Settings window (the gear icon). Every change applies straight away and is saved."""
import dataclasses

from gi.repository import Gdk, GLib, Gtk, Pango

from . import apps, autostart
from .app import current_monitors

MODIFIER_NAMES = [
    (Gdk.ModifierType.CONTROL_MASK, "Ctrl"),
    (Gdk.ModifierType.MOD1_MASK, "Alt"),
    (Gdk.ModifierType.SHIFT_MASK, "Shift"),
    (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK, "Super"),
]


def accel_from_event(event):
    """'Ctrl+Alt+S' for a key press, or None for a lone modifier key."""
    if event.is_modifier:
        return None
    name = Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval))
    if not name:
        return None
    if len(name) == 1:
        name = name.upper()
    mods = [label for mask, label in MODIFIER_NAMES if event.state & mask]
    return "+".join(mods + [name])


class SettingsWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="Shelf Settings", application=app)
        self.app = app
        self.set_default_size(420, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self._recording = None  # the hotkey setting being recorded
        self._syncing = False
        self._key_buttons = {}
        self._app_switches = {}  # app -> (switch, handler id)

        grid = Gtk.Grid(column_spacing=16, row_spacing=10, margin=18)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_propagate_natural_height(True)
        workarea = Gdk.Display.get_default().get_primary_monitor() or \
            Gdk.Display.get_default().get_monitor(0)
        scroller.set_max_content_height(int(workarea.get_workarea().height * 0.85))
        scroller.add(grid)
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.pages.add_named(scroller, "main")
        self.add(self.pages)
        self._row = 0
        cfg = app.config

        self._heading(grid, "Position")
        self.monitor = Gtk.ComboBoxText()
        self.monitor.append("primary", "Primary monitor")
        self.monitor.append("follow-mouse", "Monitor with the pointer")
        for m in current_monitors():
            g = m.geometry
            self.monitor.append(m.name, f"{m.name} ({g.width}×{g.height})")
        if not self.monitor.set_active_id(cfg.monitor):
            self.monitor.append(cfg.monitor, f"{cfg.monitor} (not connected)")
            self.monitor.set_active_id(cfg.monitor)
        self.monitor.connect("changed", self._changed)
        self._add(grid, "Monitor", self.monitor)

        self.edge = Gtk.ComboBoxText()
        self.edge.append("right", "Right")
        self.edge.append("left", "Left")
        self.edge.set_active_id(cfg.edge)
        self.edge.connect("changed", self._changed)
        self._add(grid, "Screen edge", self.edge)

        self._heading(grid, "Size")
        self.width = self._spin(cfg.width, 80, 1000, 4)
        self._add(grid, "Width (pixels)", self.width)
        self.min_items = self._spin(cfg.min_items, 1, 20, 1)
        self._add(grid, "Minimum height (items)", self.min_items)
        self.max_height = self._spin(cfg.max_height_percent, 10, 100, 1)
        self._add(grid, "Grows up to (% of screen)", self.max_height)

        self._heading(grid, "Behaviour")
        self._add(grid, "Show/hide hotkey", self._key_button("hotkey"))
        self.problem = Gtk.Label(xalign=0, wrap=True)
        self.problem.get_style_context().add_class("error")
        grid.attach(self.problem, 1, self._row, 1, 1)
        self._row += 1

        self.hover = self._switch(cfg.open_on_hover)
        self._add(grid, "Open on edge hover", self.hover)
        self.hover_delay = self._spin(cfg.hover_delay_ms, 0, 5000, 50)
        self._add(grid, "Hover delay (ms)", self.hover_delay)
        self.timeout = self._spin(cfg.empty_timeout_seconds, 1, 600, 1)
        self._add(grid, "Hide empty shelf after (s)", self.timeout)
        self.remove_after = self._switch(cfg.remove_after_drop)
        self._add(grid, "Remove items once dropped", self.remove_after)
        self.undo = self._spin(cfg.undo_seconds, 1, 120, 1)
        self._add(grid, "Undo time (s)", self.undo)
        self.thumbnails = self._switch(cfg.thumbnails)
        self._add(grid, "Thumbnails", self.thumbnails)
        self.thumb_max = self._spin(cfg.thumbnail_max_mb, 1, 1000000, 64)
        self._add(grid, "Thumbnail files up to (MB)", self.thumb_max)
        self.tray = self._switch(cfg.tray_icon)
        self._add(grid, "Icon in the top bar", self.tray)
        self.login = Gtk.Switch(active=autostart.is_enabled())
        self._login_handler = self.login.connect(
            "notify::active", lambda sw, _p: self._show_problem(
                self.app.set_autostart(sw.get_active())))
        self._add(grid, "Start at login", self.login)

        self._heading(grid, "Floating drop panel")
        self.floating = self._switch(cfg.floating_enabled)
        self._add(grid, "Show beside the pointer when dragging", self.floating)
        self.float_offset = self._spin(cfg.floating_offset, 8, 400, 4)
        self._add(grid, "Distance from pointer (pixels)", self.float_offset)
        self.float_delay = self._spin(cfg.floating_delay_ms, 0, 2000, 50)
        self._add(grid, "Appear after (ms)", self.float_delay)
        self._add(grid, "On/off hotkey", self._key_button("float_hotkey"))

        apps_button = Gtk.Button()
        inner = Gtk.Box(spacing=6)
        self.apps_summary = Gtk.Label(xalign=0, hexpand=True)
        inner.pack_start(self.apps_summary, True, True, 0)
        inner.pack_end(Gtk.Image.new_from_icon_name("go-next-symbolic", Gtk.IconSize.MENU),
                       False, False, 0)
        apps_button.add(inner)
        apps_button.connect("clicked", lambda b: self.show_page("apps"))
        self._add(grid, "Per-app settings", apps_button)

        self.pages.add_named(self._apps_page(cfg), "apps")
        self._fill_app_list()

        self.connect("key-press-event", self._on_key)
        self.connect("destroy", lambda w: self._stop_recording())
        self.show_all()
        self._show_problem(app.hotkey_error)

    def show_page(self, name):
        self.pages.set_visible_child_name(name)

    def _apps_page(self, cfg):
        """Sub panel: the floating drop panel switched on/off per app."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=18)
        top = Gtk.Box(spacing=10)
        back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        back.set_tooltip_text("Back")
        back.connect("clicked", lambda b: self.show_page("main"))
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Floating drop panel per app</b>")
        top.pack_start(back, False, False, 0)
        top.pack_start(title, True, True, 0)
        page.pack_start(top, False, False, 0)

        row = Gtk.Box(spacing=16)
        row.pack_start(Gtk.Label(label="Show for apps not listed below", xalign=0),
                       True, True, 0)
        self.new_apps = self._switch(cfg.floating_new_apps)
        row.pack_end(self.new_apps, False, False, 0)
        page.pack_start(row, False, False, 0)

        self.app_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        placeholder = Gtk.Label(
            label="Apps show up here once you have dragged something from them.",
            wrap=True, margin=12)
        placeholder.show()
        self.app_list.set_placeholder(placeholder)
        list_scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           vexpand=True)
        list_scroller.get_style_context().add_class("frame")
        list_scroller.add(self.app_list)
        page.pack_start(list_scroller, True, True, 0)
        return page

    def _update_apps_summary(self):
        cfg = self.app.config
        off = sum(1 for on in cfg.floating_apps.values() if not on)
        on = sum(1 for on in cfg.floating_apps.values() if on)
        parts = [f"{on} on"] if on else []
        parts += [f"{off} off"] if off else []
        self.apps_summary.set_text(", ".join(parts) or
                                   ("All apps" if cfg.floating_new_apps else "No apps"))

    # --- building blocks ----------------------------------------------------

    def _heading(self, grid, text):
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{text}</b>")
        if self._row:
            label.set_margin_top(8)
        grid.attach(label, 0, self._row, 2, 1)
        self._row += 1

    def _add(self, grid, text, widget):
        grid.attach(Gtk.Label(label=text, xalign=0, hexpand=True), 0, self._row, 1, 1)
        widget.set_halign(Gtk.Align.END if isinstance(widget, Gtk.Switch) else Gtk.Align.FILL)
        grid.attach(widget, 1, self._row, 1, 1)
        self._row += 1

    def _spin(self, value, low, high, step):
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_value(value)
        spin.connect("value-changed", self._changed)
        return spin

    def _switch(self, active):
        switch = Gtk.Switch(active=active)
        switch.connect("notify::active", self._changed)
        return switch

    def _key_button(self, name):
        button = Gtk.Button(label=getattr(self.app.config, name) or "None")
        button.set_tooltip_text("Click, then press the new key combination")
        button.connect("clicked", self._start_recording, name)
        self._key_buttons[name] = button
        return button

    def _show_problem(self, text):
        self.problem.set_text(text or "")
        self.problem.set_visible(bool(text))

    # --- applying -----------------------------------------------------------

    def sync(self):
        """Show settings that were changed elsewhere (e.g. by dragging the shelf)."""
        cfg = self.app.config
        self._syncing = True
        if not self.monitor.set_active_id(cfg.monitor):
            self.monitor.append(cfg.monitor, f"{cfg.monitor} (not connected)")
            self.monitor.set_active_id(cfg.monitor)
        self.edge.set_active_id(cfg.edge)
        self.floating.set_active(cfg.floating_enabled)
        self.new_apps.set_active(cfg.floating_new_apps)
        with self.login.handler_block(self._login_handler):
            self.login.set_active(autostart.is_enabled())
        if list(self._app_switches) != self._app_names():
            GLib.idle_add(self._fill_app_list)  # not from inside a switch's own signal
        for app, (switch, handler) in self._app_switches.items():
            with switch.handler_block(handler):
                switch.set_active(cfg.app_allowed(app))
        self._update_apps_summary()
        self._syncing = False

    def _app_names(self):
        return self.app.seen_apps.recent(also=self.app.config.floating_apps)

    def _fill_app_list(self):
        if self.app_list.in_destruction():
            return False
        for row in self.app_list.get_children():
            row.destroy()
        self._app_switches = {}
        cfg = self.app.config
        for app in self._app_names():
            name, icon = apps.describe(app)
            box = Gtk.Box(spacing=10, margin=8)
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.LARGE_TOOLBAR) if icon \
                else Gtk.Image.new_from_icon_name("application-x-executable",
                                                  Gtk.IconSize.LARGE_TOOLBAR)
            box.pack_start(image, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            text.pack_start(Gtk.Label(label=name, xalign=0,
                                      ellipsize=Pango.EllipsizeMode.END), False, False, 0)
            if name != app:
                detail = Gtk.Label(label=app, xalign=0, ellipsize=Pango.EllipsizeMode.END)
                detail.get_style_context().add_class("dim-label")
                text.pack_start(detail, False, False, 0)
            box.pack_start(text, True, True, 0)
            switch = Gtk.Switch(active=cfg.app_allowed(app), valign=Gtk.Align.CENTER)
            handler = switch.connect(
                "notify::active",
                lambda sw, _p, a=app: self.app.set_floating_for_app(a, sw.get_active()))
            box.pack_end(switch, False, False, 0)
            self._app_switches[app] = (switch, handler)
            self.app_list.add(box)
        self.app_list.show_all()
        self._update_apps_summary()
        return False

    def _changed(self, *args):
        if not self._syncing:
            self._apply()

    def _apply(self, **keys):
        cfg = dataclasses.replace(
            self.app.config,
            monitor=self.monitor.get_active_id(),
            edge=self.edge.get_active_id(),
            width=self.width.get_value_as_int(),
            min_items=self.min_items.get_value_as_int(),
            max_height_percent=self.max_height.get_value_as_int(),
            open_on_hover=self.hover.get_active(),
            hover_delay_ms=self.hover_delay.get_value_as_int(),
            empty_timeout_seconds=self.timeout.get_value_as_int(),
            remove_after_drop=self.remove_after.get_active(),
            undo_seconds=self.undo.get_value_as_int(),
            floating_enabled=self.floating.get_active(),
            floating_offset=self.float_offset.get_value_as_int(),
            floating_delay_ms=self.float_delay.get_value_as_int(),
            floating_new_apps=self.new_apps.get_active(),
            thumbnails=self.thumbnails.get_active(),
            thumbnail_max_mb=self.thumb_max.get_value_as_int(),
            tray_icon=self.tray.get_active(),
            **keys,
        )
        self._show_problem(self.app.apply_config(cfg))
        self.sync()  # unlisted apps' switches follow "Show for apps not listed"

    # --- recording a hotkey -------------------------------------------------

    def _start_recording(self, button, name):
        if self._recording:
            self._stop_recording()
        self._recording = name
        self.app.suspend_hotkeys()  # so the current keys can be pressed too
        button.set_label("Press keys… (Esc cancels, Backspace clears)")

    def _stop_recording(self, accel=None):
        """Save the recorded key ("" clears it); None keeps the old one."""
        name, self._recording = self._recording, None
        if not name:
            return
        self._apply(**({name: accel} if accel is not None else {}))  # re-grabs the keys
        self._key_buttons[name].set_label(getattr(self.app.config, name) or "None")

    def _on_key(self, widget, event):
        if not self._recording:
            return False
        plain = not event.state & Gtk.accelerator_get_default_mod_mask()
        if event.keyval == Gdk.KEY_Escape and plain:
            self._stop_recording()
        elif event.keyval == Gdk.KEY_BackSpace and plain:
            self._stop_recording("")
        else:
            accel = accel_from_event(event)
            if accel:
                self._stop_recording(accel)
        return True
