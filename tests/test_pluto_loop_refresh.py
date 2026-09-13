import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from refresh_pluto_sources import needs_source_refresh, current_id
from validate_streams import Entry, Result, remove_ranges


class LoopRefreshTests(unittest.TestCase):
    def test_loop_is_investigated_not_removed(self):
        item = dict(host="jmp2.uk", status="uncertain", reason="logo Pluto persistente: programacao nao confirmada")
        self.assertTrue(needs_source_refresh(item))
        entry = Entry(1, 0, 1, 1, "Nick", "https://jmp2.uk/plu-abc.m3u8")
        lines = ["#EXTINF:-1,Nick", entry.url]
        result = Result(entry, "uncertain", item["reason"], "jmp2.uk", 30)
        self.assertEqual(remove_ranges(lines, [result]), lines)

    def test_other_uncertainties_are_preserved(self):
        for reason in ("timeout", "HTTP 403", "HTTP 451", "amostra visual incompleta", ""):
            self.assertFalse(needs_source_refresh(dict(host="jmp2.uk", status="uncertain", reason=reason)))

    def test_healthy_and_other_hosts_are_excluded(self):
        self.assertFalse(needs_source_refresh(dict(host="jmp2.uk", status="healthy")))
        self.assertFalse(needs_source_refresh(dict(host="example.org", status="remove")))
        self.assertTrue(needs_source_refresh(dict(host="jmp2.uk", status="remove")))

    def test_roku_is_not_a_pluto_candidate(self):
        self.assertEqual(current_id(Entry(1, 0, 1, 1, "Roku", "https://jmp2.uk/rok-abc.m3u8")), "")


if __name__ == "__main__":
    unittest.main()
