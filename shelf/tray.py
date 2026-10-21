"""Top-bar icon with the shelf's menu (via GNOME's AppIndicator extension)."""
import logging
import os

from gi.repository import Gtk

from . import APP_ID, autostart

log = logging.getLogger(__name__)

ICON = os.path.join(autostart.ROOT, "data", "icons", "shelf-symbolic.svg")


class Tray:
    def __init__(self, app):
        self.app = app
        self.indicator = None
        try:
            import gi
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3
        except (ImportError, ValueError) as e:
            log.info("no tray icon: %s", e)
            return
        self._ai = AppIndicator3
        self.indicator = AppIndicator3.Indicator.new(
            APP_ID, ICON, AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_title("Shelf")

        menu = Gtk.Menu()
        self.count = Gtk.MenuItem(sensitive=False)
        menu.append(self.count)
        show = self._item(menu, "Show/Hide Empty Shelf", app.toggle)
        self.floating = self._check(menu, "Floating Drop Panel", app.set_floating_enabled)
        self._item(menu, "Add Clipboard", app.add_clipboard)
        self.flush = self._item(menu, "Flush", app.flush)
        menu.append(Gtk.SeparatorMenuItem())
        self._item(menu, "Settings…", app.show_settings)
        self.login = self._check(menu, "Start at Login", app.set_autostart)
        menu.append(Gtk.SeparatorMenuItem())
        self._item(menu, "Quit", app.quit)
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_secondary_activate_target(show)  # middle click
        self.refresh()

    @staticmethod
    def _item(menu, label, callback):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda m: callback())
        menu.append(item)
        return item

    @staticmethod
    def _check(menu, label, callback):
        item = Gtk.CheckMenuItem(label=label)
        item.handler = item.connect("toggled", lambda m: callback(m.get_active()))
        menu.append(item)
        return item

    @staticmethod
    def _set_check(item, on):
        with item.handler_block(item.handler):
            item.set_active(on)

    def refresh(self):
        """Bring the menu and icon in line with the app's current state."""
        if self.indicator is None:
            return
        app, n = self.app, len(self.app.items)
        self.indicator.set_status(self._ai.IndicatorStatus.ACTIVE if app.config.tray_icon
                                  else self._ai.IndicatorStatus.PASSIVE)
        self.indicator.set_label(str(n) if n else "", "99")
        self.count.set_label(f"{n} item{'s' if n != 1 else ''} on the shelf" if n
                             else "Shelf is empty")
        self.flush.set_sensitive(bool(n))
        self._set_check(self.floating, app.config.floating_enabled)
        self._set_check(self.login, autostart.is_enabled())
