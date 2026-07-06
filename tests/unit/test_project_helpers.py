import unittest

from routers.projects import _json_load


class ProjectHelpersUnitTests(unittest.TestCase):
    def test_json_load_parses_valid_json(self):
        self.assertEqual(_json_load('{"guest_portal": {"token": "abc"}}', {}), {"guest_portal": {"token": "abc"}})

    def test_json_load_returns_default_for_invalid_json(self):
        self.assertEqual(_json_load("{bad json", {"fallback": True}), {"fallback": True})


if __name__ == "__main__":
    unittest.main()
