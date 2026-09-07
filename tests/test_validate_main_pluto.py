import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validate_streams as v
from validate_main_non_pluto import is_pluto


class MainPlutoIsolationTests(unittest.TestCase):
    def test_only_plu_namespace_is_pluto(self):
        entries = [
            v.Entry(1, 0, 1, 1, "Pluto", "https://jmp2.uk/plu-abc.m3u8"),
            v.Entry(2, 2, 3, 3, "Roku", "https://jmp2.uk/rok-abc.m3u8"),
            v.Entry(3, 4, 5, 5, "Outro", "https://example.org/live.m3u8"),
        ]
        self.assertEqual([entry.title for entry in entries if is_pluto(entry)], ["Pluto"])


if __name__ == "__main__":
    unittest.main()
