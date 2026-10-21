"""Global hotkeys and drag detection, through Xlib and XFixes (via ctypes).

Uses its own X connection, separate from GTK's, and feeds its events into the
GLib main loop. Drags are spotted by watching who owns the XdndSelection: every
X drag-and-drop source takes ownership of it when a drag starts.
"""
import ctypes
import ctypes.util
import logging
from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_ubyte, c_uint, c_ulong, c_void_p

log = logging.getLogger(__name__)

_xlib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
_xfixes = ctypes.CDLL(ctypes.util.find_library("Xfixes") or "libXfixes.so.3")

XID = c_ulong

SHIFT, LOCK, CONTROL, MOD1, MOD2, MOD4 = 1, 2, 4, 8, 16, 64
MODIFIERS = {
    "shift": SHIFT, "ctrl": CONTROL, "control": CONTROL,
    "alt": MOD1, "super": MOD4, "win": MOD4, "meta": MOD4,
}
RELEVANT_MODS = SHIFT | CONTROL | MOD1 | MOD4
# Grab each key with Caps Lock and Num Lock on and off, or it stops working when they are on.
LOCK_VARIANTS = (0, LOCK, MOD2, LOCK | MOD2)
BUTTON_MASKS = 0x1F00  # Button1Mask .. Button5Mask

KEY_PRESS, KEY_RELEASE = 2, 3
XA_WINDOW = 33
# The low bits of an X resource id number it within its client; the rest says which
# client (connection) made it. 0x1FFFFF is the X server's default split.
CLIENT_MASK = 0x1FFFFF
GRAB_MODE_ASYNC = 1
BAD_ACCESS = 10
XFIXES_SELECTION_NOTIFY = 0
XFIXES_SET_SELECTION_OWNER_NOTIFY_MASK = 1


class XKeyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int),
                ("display", c_void_p), ("window", XID), ("root", XID), ("subwindow", XID),
                ("time", c_ulong), ("x", c_int), ("y", c_int), ("x_root", c_int),
                ("y_root", c_int), ("state", c_uint), ("keycode", c_uint),
                ("same_screen", c_int)]


class XFixesSelectionNotifyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int),
                ("display", c_void_p), ("window", XID), ("subtype", c_int),
                ("owner", XID), ("selection", XID), ("timestamp", c_ulong),
                ("selection_timestamp", c_ulong)]


class XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("xkey", XKeyEvent),
                ("xfixes", XFixesSelectionNotifyEvent), ("pad", c_long * 24)]


class XErrorEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("display", c_void_p), ("resourceid", XID),
                ("serial", c_ulong), ("error_code", c_ubyte), ("request_code", c_ubyte),
                ("minor_code", c_ubyte)]


class XClassHint(ctypes.Structure):
    _fields_ = [("res_name", c_void_p), ("res_class", c_void_p)]


_ErrorHandler = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(XErrorEvent))


def _fn(lib, name, restype, *argtypes):
    f = getattr(lib, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


XOpenDisplay = _fn(_xlib, "XOpenDisplay", c_void_p, c_char_p)
XCloseDisplay = _fn(_xlib, "XCloseDisplay", c_int, c_void_p)
XDefaultRootWindow = _fn(_xlib, "XDefaultRootWindow", XID, c_void_p)
XConnectionNumber = _fn(_xlib, "XConnectionNumber", c_int, c_void_p)
XInternAtom = _fn(_xlib, "XInternAtom", XID, c_void_p, c_char_p, c_int)
XStringToKeysym = _fn(_xlib, "XStringToKeysym", c_ulong, c_char_p)
XKeysymToKeycode = _fn(_xlib, "XKeysymToKeycode", c_ubyte, c_void_p, c_ulong)
XGrabKey = _fn(_xlib, "XGrabKey", c_int, c_void_p, c_int, c_uint, XID, c_int, c_int, c_int)
XUngrabKey = _fn(_xlib, "XUngrabKey", c_int, c_void_p, c_int, c_uint, XID)
XSync = _fn(_xlib, "XSync", c_int, c_void_p, c_int)
XFlush = _fn(_xlib, "XFlush", c_int, c_void_p)
XPending = _fn(_xlib, "XPending", c_int, c_void_p)
XNextEvent = _fn(_xlib, "XNextEvent", c_int, c_void_p, POINTER(XEvent))
XQueryPointer = _fn(_xlib, "XQueryPointer", c_int, c_void_p, XID, POINTER(XID), POINTER(XID),
                    POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_int),
                    POINTER(c_uint))
XSetErrorHandler = _fn(_xlib, "XSetErrorHandler", c_void_p, _ErrorHandler)
XkbSetDetectableAutoRepeat = _fn(_xlib, "XkbSetDetectableAutoRepeat", c_int,
                                 c_void_p, c_int, POINTER(c_int))
XGetWindowProperty = _fn(_xlib, "XGetWindowProperty", c_int, c_void_p, XID, XID, c_long, c_long,
                         c_int, XID, POINTER(XID), POINTER(c_int), POINTER(c_ulong),
                         POINTER(c_ulong), POINTER(c_void_p))
XGetClassHint = _fn(_xlib, "XGetClassHint", c_int, c_void_p, XID, POINTER(XClassHint))
XFree = _fn(_xlib, "XFree", c_int, c_void_p)
XFixesQueryExtension = _fn(_xfixes, "XFixesQueryExtension", c_int,
                           c_void_p, POINTER(c_int), POINTER(c_int))
XFixesQueryVersion = _fn(_xfixes, "XFixesQueryVersion", c_int,
                         c_void_p, POINTER(c_int), POINTER(c_int))
XFixesSelectSelectionInput = _fn(_xfixes, "XFixesSelectSelectionInput", None,
                                 c_void_p, XID, XID, c_ulong)


class GrabError(Exception):
    pass


def same_client(a, b):
    """True when two X resource ids were made by the same program's connection."""
    return bool(a) and bool(b) and (a & ~CLIENT_MASK) == (b & ~CLIENT_MASK)


def parse_accel(accel):
    """'Ctrl+Alt+F6' -> (modifier mask, 'F6'). Raises ValueError."""
    parts = [p.strip() for p in (accel or "").split("+")]
    if not parts or not parts[-1]:
        raise ValueError(f"no key in {accel!r}")
    mods = 0
    for p in parts[:-1]:
        try:
            mods |= MODIFIERS[p.lower()]
        except KeyError:
            raise ValueError(f"unknown modifier {p!r} in {accel!r}") from None
    return mods, parts[-1]


def _keysym(name):
    for candidate in (name, name.lower(), name.capitalize(), name.upper()):
        sym = XStringToKeysym(candidate.encode())
        if sym:
            return sym
    return 0


class XConnection:
    """One private X connection for key grabs and drag-start notifications."""

    def __init__(self):
        from gi.repository import GLib

        self._dpy = XOpenDisplay(None)
        if not self._dpy:
            raise OSError("cannot open the X display")
        self._root = XDefaultRootWindow(self._dpy)
        self._errors = []
        self._keys = {}       # (keycode, mods) -> callback(time)
        self._down = set()    # keys held, to ignore auto-repeat
        self.on_drag_start = None

        # Xlib has one process-wide error handler. Ours only handles errors on our own
        # connection and passes everything else (GTK's) to the handler it replaces.
        self._handler = _ErrorHandler(self._on_error)
        old = XSetErrorHandler(self._handler)
        self._old_handler = _ErrorHandler(old) if old else None

        XkbSetDetectableAutoRepeat(self._dpy, 1, None)

        base, err = c_int(), c_int()
        if XFixesQueryExtension(self._dpy, byref(base), byref(err)):
            major, minor = c_int(5), c_int(0)
            XFixesQueryVersion(self._dpy, byref(major), byref(minor))
            self._selection_notify = base.value + XFIXES_SELECTION_NOTIFY
            self._xdnd = XInternAtom(self._dpy, b"XdndSelection", 0)
            XFixesSelectSelectionInput(self._dpy, self._root, self._xdnd,
                                       XFIXES_SET_SELECTION_OWNER_NOTIFY_MASK)
        else:
            log.warning("XFixes is not available; the drop strip will not appear during drags")
            self._selection_notify = None
        XFlush(self._dpy)

        self._watch = GLib.io_add_watch(XConnectionNumber(self._dpy), GLib.PRIORITY_DEFAULT,
                                        GLib.IO_IN, self._on_readable)

    def _on_error(self, dpy, event):
        if dpy == self._dpy:
            self._errors.append(event.contents.error_code)
            return 0
        return self._old_handler(dpy, event) if self._old_handler else 0

    def grab_key(self, accel, callback):
        """Grab a key combination on the whole desktop. Returns a token for ungrab_key."""
        try:
            mods, name = parse_accel(accel)
        except ValueError as e:
            raise GrabError(str(e)) from None
        keysym = _keysym(name)
        keycode = XKeysymToKeycode(self._dpy, keysym) if keysym else 0
        if not keycode:
            raise GrabError(f"unknown key {name!r}")
        del self._errors[:]
        for extra in LOCK_VARIANTS:
            XGrabKey(self._dpy, keycode, mods | extra, self._root, 0,
                     GRAB_MODE_ASYNC, GRAB_MODE_ASYNC)
        XSync(self._dpy, 0)
        failed = list(self._errors)
        if failed:
            for extra in LOCK_VARIANTS:
                XUngrabKey(self._dpy, keycode, mods | extra, self._root)
            XSync(self._dpy, 0)
            del self._errors[:]
            if BAD_ACCESS in failed:
                raise GrabError(f"{accel} is already taken by another program")
            raise GrabError(f"could not grab {accel} (X error {failed[0]})")
        token = (keycode, mods)
        self._keys[token] = callback
        self._drain()
        return token

    def ungrab_key(self, token):
        if self._keys.pop(token, None) is None:
            return
        keycode, mods = token
        for extra in LOCK_VARIANTS:
            XUngrabKey(self._dpy, keycode, mods | extra, self._root)
        XFlush(self._dpy)
        self._down.discard(token)

    def _window_list(self, window, prop):
        """A window-list property such as _NET_CLIENT_LIST, as a list of ids."""
        atom = XInternAtom(self._dpy, prop.encode(), 0)
        actual_type, actual_format = XID(), c_int()
        nitems, after, data = c_ulong(), c_ulong(), c_void_p()
        status = XGetWindowProperty(self._dpy, window, atom, 0, 4096, 0, XA_WINDOW,
                                    byref(actual_type), byref(actual_format), byref(nitems),
                                    byref(after), byref(data))
        if status != 0 or not data.value:
            return []
        try:
            if actual_format.value != 32:
                return []
            return list((c_ulong * nitems.value).from_address(data.value))  # Xlib uses longs
        finally:
            XFree(data)

    def app_class(self, window):
        """The WM_CLASS class of a window (e.g. 'Org.gnome.Nautilus'), or None."""
        hint = XClassHint()
        if not XGetClassHint(self._dpy, window, byref(hint)):
            return None
        try:
            return ctypes.string_at(hint.res_class).decode("utf-8", "replace") \
                if hint.res_class else None
        finally:
            for p in (hint.res_name, hint.res_class):
                if p:
                    XFree(p)

    def drag_source_app(self, owner):
        """Which app a drag comes from, given the window that started it.

        Drag sources usually start drags from a hidden helper window with no name,
        so the answer comes from that program's own top-level window: normally the
        active window, otherwise any listed window made by the same program.
        """
        del self._errors[:]  # a window may be gone already; that is not a problem
        active = next(iter(self._window_list(self._root, "_NET_ACTIVE_WINDOW")), 0)
        clients = self._window_list(self._root, "_NET_CLIENT_LIST")
        candidates = [w for w in [active] + clients if same_client(w, owner)]
        for window in candidates + [owner]:
            name = self.app_class(window)
            if name:
                return name
        return None

    def buttons_down(self):
        root, child = XID(), XID()
        rx, ry, wx, wy = c_int(), c_int(), c_int(), c_int()
        mask = c_uint()
        XQueryPointer(self._dpy, self._root, byref(root), byref(child), byref(rx), byref(ry),
                      byref(wx), byref(wy), byref(mask))
        return bool(mask.value & BUTTON_MASKS)

    def _on_readable(self, fd, condition):
        self._drain()
        return True

    def _drain(self):
        event = XEvent()
        while XPending(self._dpy):
            XNextEvent(self._dpy, byref(event))
            try:
                self._dispatch(event)
            except Exception:
                log.exception("error handling X event")

    def _dispatch(self, event):
        if event.type in (KEY_PRESS, KEY_RELEASE):
            key = (event.xkey.keycode, event.xkey.state & RELEVANT_MODS)
            if event.type == KEY_RELEASE:
                # Match on keycode only: the modifier may have been let go first.
                self._down = {k for k in self._down if k[0] != key[0]}
            elif key in self._keys and key not in self._down:
                self._down.add(key)
                self._keys[key](event.xkey.time)
        elif event.type == self._selection_notify:
            sel = event.xfixes
            if sel.selection == self._xdnd and sel.owner and self.on_drag_start:
                self.on_drag_start(sel.owner)
