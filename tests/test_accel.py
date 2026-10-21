import unittest

from shelf.x11 import CONTROL, MOD1, MOD4, SHIFT, parse_accel


class ParseAccelTest(unittest.TestCase):
    def test_plain_key(self):
        self.assertEqual(parse_accel("F6"), (0, "F6"))

    def test_modifiers(self):
        self.assertEqual(parse_accel("Ctrl+Alt+S"), (CONTROL | MOD1, "S"))
        self.assertEqual(parse_accel("super + shift + F6"), (MOD4 | SHIFT, "F6"))

    def test_errors(self):
        for bad in ("", "Ctrl+", "Hyper+F6"):
            with self.subTest(accel=bad), self.assertRaises(ValueError):
                parse_accel(bad)


if __name__ == "__main__":
    unittest.main()
