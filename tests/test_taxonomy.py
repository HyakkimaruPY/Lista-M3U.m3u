import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validate_streams as v
from curate_main_playlist import curate
from refresh_pluto_sources import region_of
from validate_main_non_pluto import is_pluto


class TaxonomyTests(unittest.TestCase):
    def test_parent_groups_platform_labels_and_language_order(self):
        raw = """#EXTM3U
#EXTINF:-1 tvg-id="usmovie" group-title="Pluto • Filmes S",Classic Movies
https://jmp2.uk/plu-aaaaaaaa.m3u8
#EXTINF:-1 tvg-id="CCTV6.cn" group-title="China • Cinema e séries",CCTV-6 电影
https://example.org/cctv6.m3u8
#EXTINF:-1 tvg-id="roku-western-bound-pt" group-title="Roku • Filmes" x-source="Roku FAST via TCL/Leiniao",Western Bound em Português
https://example.org/roku-western.m3u8
#EXTINF:-1 tvg-id="esmovie" group-title="Pluto • Em espanhol S",Cine en español
https://jmp2.uk/plu-bbbbbbbb.m3u8
#EXTINF:-1 tvg-id="run" group-title="Filmes",Run-Ação
https://example.org/run.m3u8
"""
        out, removed = curate(raw)
        self.assertEqual(removed, 0)
        entries = v.parse_playlist(out.splitlines())
        self.assertEqual([e.title for e in entries], [
            "R • Western Bound em Português",
            "Run-Ação",
            "CCTV-6 电影 • [CN]",
            "P • Cine en español • [ES]",
            "P • Classic Movies • [S]",
        ])
        self.assertTrue(all('group-title="Filmes"' in e.metadata for e in entries))
        self.assertIn('x-region="US"', entries[-1].metadata)
        self.assertIn('x-lang="zh-CN"', entries[2].metadata)
        self.assertEqual(curate(out)[0], out)

    def test_roku_jmp_is_not_pluto(self):
        roku = v.Entry(1, 0, 1, 1, "Roku", "https://jmp2.uk/rok-1234.m3u8")
        pluto = v.Entry(1, 0, 1, 1, "Pluto", "https://jmp2.uk/plu-1234.m3u8")
        self.assertFalse(is_pluto(roku))
        self.assertTrue(is_pluto(pluto))

    def test_pluto_region_uses_metadata_after_parent_grouping(self):
        entry = v.Entry(
            1,
            0,
            1,
            1,
            "P • Canal • [S]",
            "https://jmp2.uk/plu-1234.m3u8",
            metadata='#EXTINF:-1 group-title="Filmes" x-region="US",P • Canal • [S]',
        )
        self.assertEqual(region_of(entry), "US")


if __name__ == "__main__":
    unittest.main()
