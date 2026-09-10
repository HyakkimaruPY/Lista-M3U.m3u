import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import validate_old_hls as old
import validate_streams as base

class OldHLSTests(unittest.TestCase):
    def test_real_playlist_structure(self):
        self.assertEqual(old.playlist_structure(ROOT/'old_hls.m3u8'),[])
        entries=base.parse_playlist((ROOT/'old_hls.m3u8').read_text().splitlines())
        self.assertGreaterEqual(len(entries),27)
        groups={e.metadata.split('group-title="',1)[1].split('"',1)[0] for e in entries}
        self.assertEqual(groups,{'Variedade','Filmes','Séries','CCTV'})

    def test_plain_query_is_rejected(self):
        e=base.Entry(1,0,1,1,'X','https://example.org/a.m3u8?token=x')
        self.assertIn('query',old.simple_source_policy(e))

    def test_bridge_profile_allows_known_complex_url(self):
        e=base.Entry(1,0,1,1,'X','https://example.org/a.m3u8?token=x',metadata='#EXTINF:-1 group-title="Variedade" x-profile="bridge",X')
        self.assertIsNone(old.simple_source_policy(e))

    def test_headers_are_rejected(self):
        e=base.Entry(1,0,1,1,'X','https://example.org/a.m3u8',user_agent='UA')
        self.assertIn('headers',old.simple_source_policy(e))

    def test_cmaf_is_rejected(self):
        self.assertIn('CMAF',old.media_policy('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\na.m4s\n','https://example.org/a.m3u8'))

    def test_aes_is_rejected(self):
        self.assertIn('criptografado',old.media_policy('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:6,\na.ts\n','https://example.org/a.m3u8'))

    def test_ts_media_is_accepted(self):
        self.assertIsNone(old.media_policy('#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\na.ts\n','https://example.org/a.m3u8'))

    def test_variant_prefers_highest_compatible(self):
        text='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"\n1080.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=3840x2160,CODECS="hvc1.1.6.L120"\n4k.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"\n720.m3u8\n'
        url,why=old.select_variant(text,'https://example.org/master.m3u8')
        self.assertIsNone(why)
        self.assertEqual(url,'https://example.org/1080.m3u8')

if __name__=='__main__': unittest.main()
