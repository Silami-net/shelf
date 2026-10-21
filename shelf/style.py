"""Look of the shelf: a dark panel, the same on light and dark desktop themes."""
from gi.repository import Gdk, Gtk

CSS = b"""
.shelf-window, .shelf-handle-window { background-color: transparent; }

.shelf {
  background-color: rgba(28, 29, 33, 0.96);
  color: #e8e8ea;
  border: 1px solid rgba(255, 255, 255, 0.10);
}
.shelf.edge-right { border-radius: 14px 0 0 14px; border-right-width: 0; }
.shelf.edge-left  { border-radius: 0 14px 14px 0; border-left-width: 0; }
.shelf.drop-hover { border-color: #5294e2; box-shadow: inset 0 0 0 2px rgba(82, 148, 226, 0.85); }

.shelf label { color: #e8e8ea; text-shadow: none; }
.shelf-header { padding: 8px 6px 4px 10px; }
.shelf .shelf-name { font-size: smaller; }
.shelf .shelf-dim { color: rgba(232, 232, 234, 0.55); }
.shelf .shelf-detail { color: rgba(232, 232, 234, 0.55); font-size: smaller; }

.shelf button {
  background-image: none; background-color: rgba(255, 255, 255, 0.08);
  color: #e8e8ea; border: none; box-shadow: none; text-shadow: none;
  -gtk-icon-shadow: none; padding: 3px 10px; min-height: 22px; border-radius: 6px;
}
.shelf button:hover { background-color: rgba(255, 255, 255, 0.16); }
.shelf button:disabled { background-color: transparent; }
.shelf button:disabled label { color: rgba(232, 232, 234, 0.3); }
.shelf button.shelf-icon-button { padding: 4px; min-height: 0; min-width: 0; }
.shelf button.shelf-remove {
  background-color: rgba(28, 29, 33, 0.85); padding: 1px; min-height: 0; min-width: 0;
  border-radius: 10px; opacity: 0;
}
.shelf row:hover button.shelf-remove { opacity: 1; }
.shelf button.shelf-remove:hover { background-color: rgba(90, 90, 96, 0.95); }

.shelf list, .shelf scrolledwindow, .shelf viewport { background-color: transparent; }
.shelf row { padding: 6px 4px; margin: 1px 5px; border-radius: 8px; background-color: transparent; }
.shelf row:hover { background-color: rgba(255, 255, 255, 0.07); }
.shelf row:selected { background-color: rgba(82, 148, 226, 0.40); }
.shelf row.missing { opacity: 0.45; }

.shelf-empty {
  padding: 16px 6px; margin: 4px 8px 10px 8px; font-size: smaller;
  border: 2px dashed rgba(255, 255, 255, 0.18); border-radius: 10px;
}
.shelf-undo { padding: 8px 8px 10px 8px; font-size: smaller; border-top: 1px solid rgba(255, 255, 255, 0.08); }

.shelf.shelf-float { border-radius: 14px; border-width: 1px; padding: 8px 6px; font-size: smaller; }

.shelf button.shelf-icon-button:checked { background-color: rgba(82, 148, 226, 0.55); }

.shelf-handle { background-color: rgba(82, 148, 226, 0.55); }
.shelf-handle.drop-hover { background-color: rgba(82, 148, 226, 0.95); }
"""


def install():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def make_overlay(window):
    """Give a popup window an alpha channel, so its rounded corners show through."""
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None and screen.is_composited():
        window.set_visual(visual)
    window.set_app_paintable(True)
