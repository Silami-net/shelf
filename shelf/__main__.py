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
    import signal

    from gi.repository import GLib

    from .app import ShelfApp

    app = ShelfApp()
    for sig in (signal.SIGINT, signal.SIGTERM):  # Ctrl+C or a normal kill: quit cleanly
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: app.quit() or False)
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
