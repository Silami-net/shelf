import unittest

from shelf.geometry import (
    Monitor, Rect, choose_monitor, handle_rect, is_outer_edge, monitor_at,
    nearest_side, panel_rect, place_near)


def mon(index, x, y, w, h, name=None, primary=False, workarea=None):
    g = Rect(x, y, w, h)
    return Monitor(index, name or f"OUT-{index}", g, workarea or g, primary)


# Layouts the shelf has to cope with.
LAPTOP = [mon(0, 0, 0, 1366, 768, "eDP-1", True, Rect(0, 27, 1366, 741))]
CURRENT = [mon(0, 0, 0, 2560, 1440, "DP-0"),
           mon(1, 2560, 0, 2560, 1440, "DP-2", True, Rect(2560, 27, 2560, 1413))]
MIXED = [mon(0, 0, 0, 1920, 1080, "HDMI-1", True), mon(1, 1920, 0, 3840, 2160, "DP-1")]
PORTRAIT = [mon(0, 0, 0, 2560, 1440, "DP-1", True), mon(1, 2560, -600, 1440, 2560, "DP-2")]
THREE = [mon(0, 0, 360, 1920, 1080, "L"), mon(1, 1920, 0, 2560, 1440, "C", True),
         mon(2, 4480, 360, 1920, 1080, "R")]
NEGATIVE = [mon(0, -1920, 200, 1920, 1080, "LEFT"), mon(1, 0, 0, 2560, 1440, "MAIN", True)]
GAP = [mon(0, 0, 0, 1920, 1080, "A", True), mon(1, 2000, 0, 1920, 1080, "B")]
ALL_LAYOUTS = [LAPTOP, CURRENT, MIXED, PORTRAIT, THREE, NEGATIVE, GAP]


class ChooseMonitorTest(unittest.TestCase):
    def test_primary(self):
        self.assertEqual(choose_monitor(CURRENT, "primary").name, "DP-2")

    def test_by_name_is_case_insensitive(self):
        self.assertEqual(choose_monitor(CURRENT, "dp-0").name, "DP-0")

    def test_by_index(self):
        self.assertEqual(choose_monitor(THREE, "2").name, "R")

    def test_unplugged_name_falls_back_to_primary(self):
        self.assertEqual(choose_monitor(LAPTOP, "DP-2").name, "eDP-1")

    def test_no_primary_uses_first(self):
        self.assertEqual(choose_monitor([mon(0, 0, 0, 800, 600)], "primary").index, 0)

    def test_follow_mouse(self):
        self.assertEqual(choose_monitor(THREE, "follow-mouse", (5000, 900)).name, "R")
        self.assertEqual(choose_monitor(NEGATIVE, "follow-mouse", (-50, 500)).name, "LEFT")

    def test_follow_mouse_in_gap_picks_nearest(self):
        self.assertEqual(monitor_at(GAP, 1990, 10).name, "B")
        self.assertEqual(monitor_at(THREE, 100, 10).name, "L")

    def test_empty(self):
        with self.assertRaises(ValueError):
            choose_monitor([], "primary")


class OuterEdgeTest(unittest.TestCase):
    def test_current_setup(self):
        left, right = CURRENT
        self.assertTrue(is_outer_edge(CURRENT, right, "right"))
        self.assertFalse(is_outer_edge(CURRENT, right, "left"))
        self.assertFalse(is_outer_edge(CURRENT, left, "right"))

    def test_partial_overlap_counts_as_inner(self):
        self.assertFalse(is_outer_edge(PORTRAIT, PORTRAIT[0], "right"))
        self.assertFalse(is_outer_edge(THREE, THREE[1], "right"))

    def test_gap_is_outer(self):
        self.assertTrue(is_outer_edge(GAP, GAP[0], "right"))

    def test_diagonal_neighbour_is_not_a_border(self):
        stacked = [mon(0, 0, 0, 1920, 1080, primary=True), mon(1, 1920, 1080, 1920, 1080)]
        self.assertTrue(is_outer_edge(stacked, stacked[0], "right"))


class PlacementTest(unittest.TestCase):
    def test_panel_and_handle_stay_on_their_monitor(self):
        for layout in ALL_LAYOUTS:
            for m in layout:
                for edge in ("left", "right"):
                    with self.subTest(monitor=m.name, edge=edge):
                        p = panel_rect(m, edge, 260, 5000, 70)
                        self.assertTrue(m.workarea.contains(p.x, p.y))
                        self.assertTrue(m.workarea.contains(p.right - 1, p.bottom - 1))
                        self.assertLessEqual(p.height, m.workarea.height * 70 // 100)
                        h = handle_rect(m, edge, 4)
                        self.assertTrue(m.geometry.contains(h.x, h.y))
                        self.assertTrue(m.geometry.contains(h.right - 1, h.bottom - 1))
                        side = m.geometry.right if edge == "right" else m.geometry.x
                        self.assertIn(side, (h.x, h.right))

    def test_panel_sits_against_the_edge(self):
        m = CURRENT[1]
        self.assertEqual(panel_rect(m, "right", 260, 300, 70).right, m.workarea.right)
        self.assertEqual(panel_rect(m, "left", 260, 300, 70).x, m.workarea.x)

    def test_panel_is_centred_and_fits_content(self):
        m = LAPTOP[0]
        p = panel_rect(m, "right", 260, 200, 70)
        self.assertEqual(p.height, 200)
        self.assertEqual(p.y, m.workarea.y + (m.workarea.height - 200) // 2)

    def test_nearest_side(self):
        left, right = CURRENT
        self.assertEqual(nearest_side(right, 2600), "left")
        self.assertEqual(nearest_side(right, 5000), "right")
        self.assertEqual(nearest_side(left, 1279), "left")
        self.assertEqual(nearest_side(left, 1280), "right")
        self.assertEqual(nearest_side(NEGATIVE[0], -100), "right")

    def test_panel_capped_by_percentage(self):
        m = MIXED[1]
        self.assertEqual(panel_rect(m, "right", 260, 99999, 50).height, 1080)

    def test_panel_never_wider_than_monitor(self):
        tiny = mon(0, 0, 0, 200, 300, primary=True)
        self.assertEqual(panel_rect(tiny, "right", 260, 100, 70).width, 200)

    def test_handle_spans_usable_height(self):
        m = CURRENT[1]
        h = handle_rect(m, "right", 4)
        self.assertEqual((h.x, h.y, h.width, h.height), (5116, 27, 4, 1413))


class PlaceNearTest(unittest.TestCase):
    area = Rect(0, 0, 1920, 1080)

    def test_below_right(self):
        self.assertEqual(place_near(100, 100, 120, 80, self.area, 48), Rect(148, 148, 120, 80))

    def test_flips_at_right_and_bottom(self):
        r = place_near(1900, 1060, 120, 80, self.area, 48)
        self.assertEqual((r.x, r.y), (1900 - 48 - 120, 1060 - 48 - 80))

    def test_never_covers_the_point(self):
        for layout in ALL_LAYOUTS:
            for m in layout:
                wa = m.workarea
                for px, py in [(wa.x, wa.y), (wa.right - 1, wa.bottom - 1),
                               (wa.x + wa.width // 2, wa.y + wa.height // 2)]:
                    r = place_near(px, py, 120, 80, wa, 48)
                    with self.subTest(monitor=m.name, point=(px, py)):
                        self.assertFalse(r.contains(px, py))
                        self.assertTrue(wa.contains(r.x, r.y))
                        self.assertTrue(wa.contains(r.right - 1, r.bottom - 1))


if __name__ == "__main__":
    unittest.main()
