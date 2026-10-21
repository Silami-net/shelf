"""Screen geometry: which monitor the shelf uses and where on it things go.

Plain functions on plain rectangles, so they can be tested against any monitor
layout without a display. All values are in GDK's logical pixels.
"""
from dataclasses import dataclass

EDGES = ("left", "right")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    def contains(self, px, py):
        return self.x <= px < self.right and self.y <= py < self.bottom

    def grow(self, n):
        return Rect(self.x - n, self.y - n, self.width + 2 * n, self.height + 2 * n)

    def distance_to(self, px, py):
        dx = max(self.x - px, 0, px - (self.right - 1))
        dy = max(self.y - py, 0, py - (self.bottom - 1))
        return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True)
class Monitor:
    index: int
    name: str
    geometry: Rect
    workarea: Rect
    primary: bool = False


def monitor_at(monitors, x, y):
    """The monitor containing (x, y), or the nearest one if it falls in a gap."""
    for m in monitors:
        if m.geometry.contains(x, y):
            return m
    return min(monitors, key=lambda m: m.geometry.distance_to(x, y))


def choose_monitor(monitors, setting="primary", pointer=None):
    """Resolve the `monitor` setting; anything unknown or unplugged falls back to primary."""
    if not monitors:
        raise ValueError("no monitors")
    setting = (setting or "primary").strip().lower()
    if setting == "follow-mouse":
        if pointer is not None:
            return monitor_at(monitors, *pointer)
    elif setting != "primary":
        for m in monitors:
            if m.name.lower() == setting:
                return m
        if setting.isdigit():
            for m in monitors:
                if m.index == int(setting):
                    return m
    for m in monitors:
        if m.primary:
            return m
    return monitors[0]


def is_outer_edge(monitors, monitor, edge):
    """False when another monitor borders this edge, so the pointer can cross it."""
    g = monitor.geometry
    for other in monitors:
        if other.index == monitor.index:
            continue
        o = other.geometry
        if min(g.bottom, o.bottom) <= max(g.y, o.y):
            continue  # no vertical overlap
        if edge == "right" and o.x == g.right:
            return False
        if edge == "left" and o.right == g.x:
            return False
    return True


def handle_rect(monitor, edge, thickness):
    """The drop strip: flush against the screen edge, as tall as the usable area."""
    g, wa = monitor.geometry, monitor.workarea
    thickness = max(1, min(thickness, g.width))
    x = g.right - thickness if edge == "right" else g.x
    return Rect(x, wa.y, thickness, wa.height)


def panel_rect(monitor, edge, width, content_height, max_height_percent):
    """The shelf panel: against the edge of the usable area, vertically centred."""
    wa = monitor.workarea
    width = max(1, min(width, wa.width))
    height = max(1, min(content_height, max_panel_height(monitor, max_height_percent)))
    x = wa.right - width if edge == "right" else wa.x
    y = wa.y + (wa.height - height) // 2
    return Rect(x, y, width, height)


def max_panel_height(monitor, max_height_percent):
    percent = max(1, min(max_height_percent, 100))
    return max(1, monitor.workarea.height * percent // 100)


def nearest_side(monitor, x):
    """The edge of the monitor that x is closer to."""
    g = monitor.geometry
    return "left" if x < g.x + g.width / 2 else "right"


def place_near(px, py, width, height, area, offset):
    """A width x height box beside (px, py): below-right, flipped to stay inside area."""
    x = px + offset
    if x + width > area.right:
        x = px - offset - width
    y = py + offset
    if y + height > area.bottom:
        y = py - offset - height
    x = max(area.x, min(x, area.right - width))
    y = max(area.y, min(y, area.bottom - height))
    return Rect(x, y, width, height)
