#!/usr/bin/env python3
"""Renders the README screenshots into docs/images/ from the real widgets, off screen.

Uses sample files in a temporary folder, with its own settings, data and
thumbnail cache, so it never touches a running shelf or your own files.

    python3 docs/screenshots.py
"""
import math
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")
TMP = tempfile.mkdtemp(prefix="shelf-screenshots-")
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(TMP, var.lower())
os.environ.setdefault("GDK_BACKEND", "x11")
sys.path.insert(0, ROOT)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GdkX11", "3.0")
import cairo  # noqa: E402
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from shelf import config, items, settings, style  # noqa: E402
from shelf.apps import SeenApps  # noqa: E402
from shelf.floating import FloatingDrop  # noqa: E402
from shelf.panel import ShelfPanel  # noqa: E402

BACKGROUND = ((0.27, 0.32, 0.42), (0.13, 0.15, 0.20))  # top, bottom
PANEL_WIDTH = 120


# --- sample content -----------------------------------------------------------

def sample_render(path, hue):
    """A colourful stand-in for a render, so thumbnails have something to show."""
    w, h = 640, 360
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    cr = cairo.Context(surface)
    sky = cairo.LinearGradient(0, 0, 0, h)
    sky.add_color_stop_rgb(0, *hue[0])
    sky.add_color_stop_rgb(1, *hue[1])
    cr.set_source(sky)
    cr.paint()
    cr.set_source_rgba(1, 1, 1, 0.85)
    cr.arc(w * 0.7, h * 0.35, h * 0.16, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(*[c * 0.35 for c in hue[1]])
    cr.move_to(0, h)
    for x in range(0, w + 40, 40):
        cr.line_to(x, h * 0.62 + 40 * math.sin(x / 70.0))
    cr.line_to(w, h)
    cr.close_path()
    cr.fill()
    surface.write_to_png(path)


def sample_items():
    folder = os.path.join(TMP, "project")
    os.makedirs(os.path.join(folder, "renders"))
    renders = [("sh010_comp_v003.png", ((0.98, 0.62, 0.35), (0.45, 0.18, 0.42))),
               ("sh020_plate_v001.png", ((0.35, 0.65, 0.95), (0.10, 0.20, 0.45))),
               ("turntable_v002.png", ((0.55, 0.85, 0.65), (0.10, 0.35, 0.30)))]
    uris = []
    for name, hue in renders:
        path = os.path.join(folder, name)
        sample_render(path, hue)
        uris.append(Gio.File.new_for_path(path).get_uri())
    uris.append(Gio.File.new_for_path(os.path.join(folder, "renders")).get_uri())
    return (items.from_uris(uris)
            + items.from_text("Grade notes: lift the shadows a touch on sh020")
            + items.from_text("https://example.com/client-brief"))


# --- rendering -----------------------------------------------------------------

def pump(seconds=0.0, until=None):
    end = time.time() + seconds
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration()
        if until is not None and until():
            return
        if time.time() >= end:
            return
        time.sleep(0.02)


def snapshot(widget, width, height=-1, transparent=True):
    """Draw a widget in an off-screen window; returns a surface.

    transparent: for the shelf's own panels, whose rounded corners show what's
    behind them. Otherwise the window gets the theme's normal background.
    """
    window = Gtk.OffscreenWindow()
    if transparent:
        style.make_overlay(window)
        window.get_style_context().add_class("shelf-window")
    widget.set_size_request(width, height)
    window.add(widget)
    window.show_all()
    pump(0.3)
    source = window.get_surface()
    w, h = window.get_allocated_width(), window.get_allocated_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_surface(source, 0, 0)
    cr.paint()
    window.remove(widget)
    window.destroy()
    return surface


def backdrop(width, height):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    gradient = cairo.LinearGradient(0, 0, 0, height)
    gradient.add_color_stop_rgb(0, *BACKGROUND[0])
    gradient.add_color_stop_rgb(1, *BACKGROUND[1])
    cr.set_source(gradient)
    cr.paint()
    return surface, cr


def save(surface, name):
    os.makedirs(OUT, exist_ok=True)
    surface.write_to_png(os.path.join(OUT, name))
    print("wrote", os.path.join("docs", "images", name))


def on_screen_edge(panel_surface, name, width=300):
    """Place a panel against the right edge of a plain 'desktop', as it sits on screen."""
    h = panel_surface.get_height() + 80
    surface, cr = backdrop(width, h)
    cr.set_source_surface(panel_surface, width - panel_surface.get_width(), 40)
    cr.paint()
    save(surface, name)


def pointer(cr, x, y):
    """A mouse pointer with its tip at (x, y)."""
    cr.save()
    cr.translate(x, y)
    cr.move_to(0, 0)
    for px, py in ((0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12), (12.5, 12)):
        cr.line_to(px, py)
    cr.close_path()
    cr.set_source_rgb(1, 1, 1)
    cr.fill_preserve()
    cr.set_line_width(1.2)
    cr.set_source_rgb(0, 0, 0)
    cr.stroke()
    cr.restore()


def thumbnail_ghost(cr, path, x, y):
    """The semi-transparent file preview that follows the pointer during a drag."""
    image = cairo.ImageSurface.create_from_png(path)
    scale = 72 / image.get_width()
    cr.save()
    cr.translate(x, y)
    cr.scale(scale, scale)
    cr.set_source_surface(image, 0, 0)
    cr.paint_with_alpha(0.75)
    cr.restore()


# --- the screenshots -------------------------------------------------------------

def make_panel(cfg):
    panel = ShelfPanel(cfg.edge, *[lambda *a: None] * 11)
    panel.thumbnail_limit = 1 << 30
    panel.set_floating(cfg.floating_enabled)
    panel.set_empty_hint(f"{cfg.hotkey} or Esc to close")
    panel.remove(panel.frame)
    return panel


def panel_shots(cfg, sample):
    panel = make_panel(cfg)
    panel.set_items(sample)
    rows = panel.list.get_children()
    pump(15, until=lambda: all(r.image.get_storage_type() == Gtk.ImageType.SURFACE
                               for r in rows if r.item.label.endswith(".png")))
    height = panel.natural_height(PANEL_WIDTH, 2000, cfg.min_items)
    on_screen_edge(snapshot(panel.frame, PANEL_WIDTH, height), "shelf.png")

    empty = make_panel(cfg)
    empty.set_items([])
    height = empty.natural_height(PANEL_WIDTH, 2000, cfg.min_items)
    on_screen_edge(snapshot(empty.frame, PANEL_WIDTH, height), "shelf-empty.png")

    flushed = make_panel(cfg)
    flushed.set_items([])
    flushed.show_undo(f"{len(sample)} flushed")
    height = flushed.natural_height(PANEL_WIDTH, 2000, cfg.min_items)
    on_screen_edge(snapshot(flushed.frame, PANEL_WIDTH, height), "shelf-flushed.png")
    return sample[0].path


def floating_shot(dragged_png):
    drop = FloatingDrop(lambda new: None)
    drop.remove(drop.frame)
    drop.count.set_text("6 on the shelf")
    drop._hover(True)
    from shelf.floating import HEIGHT, WIDTH
    panel = snapshot(drop.frame, WIDTH, HEIGHT)

    surface, cr = backdrop(420, 260)
    start = (90, 60)  # where the drag began
    left, top = start[0] + 48, start[1] + 48  # floating_offset
    cr.set_source_surface(panel, left, top)
    cr.paint()
    tip = (left + WIDTH - 14, top + HEIGHT - 10)  # dropping on the panel's corner
    thumbnail_ghost(cr, dragged_png, tip[0] + 10, tip[1] + 16)
    pointer(cr, *tip)
    cr.set_source_rgba(1, 1, 1, 0.45)
    cr.set_line_width(1.5)
    cr.set_dash([3, 3])
    cr.arc(*start, 6, 0, 2 * math.pi)
    cr.stroke()
    cr.set_dash([])
    cr.select_font_face("sans-serif")
    cr.set_font_size(12)
    cr.move_to(start[0] + 12, start[1] + 4)
    cr.show_text("drag started here")
    save(surface, "floating-panel.png")


class ScreenshotApp(Gtk.Application):
    """Just enough of the shelf app for the settings window to draw itself."""

    def __init__(self):
        super().__init__(application_id="app.shelf.Screenshots",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.config = config.Config(floating_apps={"Nuke": False})
        self.hotkey_error = None
        self.seen_apps = SeenApps(os.path.join(TMP, "apps.json"))
        for app in ("Gnome-terminal", "Brave-browser", "Nuke", "Org.gnome.Nautilus"):
            self.seen_apps.note(app)
            time.sleep(0.01)

    def apply_config(self, cfg):
        self.config = cfg

    def set_floating_for_app(self, app, on):
        pass

    def suspend_hotkeys(self):
        pass

    def set_autostart(self, on):
        pass

    def do_activate(self):
        style.install()
        dragged = panel_shots(self.config, sample_items())
        floating_shot(dragged)
        settings_shots(self)
        self.quit()


def settings_shots(app):
    show_all = settings.SettingsWindow.show_all
    settings.SettingsWindow.show_all = lambda self: None  # build it, but never on screen
    try:
        window = settings.SettingsWindow(app)
    finally:
        settings.SettingsWindow.show_all = show_all
    pages = window.pages
    window.remove(pages)
    pages.set_vhomogeneous(False)
    pages.set_transition_type(Gtk.StackTransitionType.NONE)
    window.problem.set_no_show_all(True)
    pages.show_all()
    for page, name in (("main", "settings.png"), ("apps", "settings-apps.png")):
        pages.set_visible_child_name(page)
        height = pages.get_preferred_height_for_width(480)[1]
        if page == "apps":
            height = 360  # the app list would otherwise stretch to the main page's height
        save(snapshot(pages, 480, height, transparent=False), name)
    window.destroy()


if __name__ == "__main__":
    ScreenshotApp().run([])
