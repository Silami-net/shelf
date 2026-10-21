import logging
import os
import sys


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="shelf: %(levelname)s: %(message)s")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        logging.warning("running under Wayland via XWayland: the hotkey and drag strip "
                        "only see X11 apps")
    os.environ.setdefault("GDK_BACKEND", "x11")

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("GdkX11", "3.0")
    from .app import ShelfApp

    return ShelfApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
