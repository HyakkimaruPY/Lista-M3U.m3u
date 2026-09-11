import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import hls_compat as compat
import validate_old_hls as old
import validate_streams as base

class OldHLSTests(unittest.TestCase):
    def test_real_playlist_structure(self):
        self.assertEqual(old.playlist_structure(ROOT/'old_hls.m3u8'),[])
        entries=base.parse_playlist((ROOT/'old_hls.m3u8').read_text(encoding='utf-8-sig').splitlines())
        self.assertGreaterEqual(len(entries),35)
        groups={old.entry_group(e) for e in entries}
        required={'Variedade','Filmes','Séries','CCTV','B • Filmes','B • Séries','B • Animações'}
        self.assertTrue(required.issubset(groups))
        self.assertNotIn('Beta',groups)

    def test_pluto_br_promoted_groups(self):
        entries=base.parse_playlist((ROOT/'old_hls.m3u8').read_text(encoding='utf-8-sig').splitlines())
        by_name={e.title:old.entry_group(e) for e in entries}
        self.assertEqual(by_name.get('P • Pluto TV Cine Clássicos'),'B • Filmes')
        self.assertEqual(by_name.get('P • A Feiticeira'),'B • Séries')
        self.assertEqual(by_name.get('P • MacGyver'),'B • Séries')
        self.assertEqual(by_name.get('P • Pluto TV Desenhos Clássicos'),'B • Animações')
        self.assertEqual(by_name.get('P • Popeye'),'B • Animações')
        self.assertEqual(by_name.get('Novelíssima'),'Variedade')

    def test_categories_are_dynamic_not_whitelisted(self):
        e=base.Entry(1,0,1,1,'X','https://example.org/a.m3u8',metadata='#EXTINF:-1 group-title="Documentários",X')
        self.assertEqual(old.entry_group(e),'Documentários')
        self.assertIsNone(old.simple_source_policy(e))

    def test_query_is_allowed_without_custom_profile_tag(self):
        e=base.Entry(1,0,1,1,'X','https://example.org/a.m3u8?token=x')
        self.assertIsNone(old.simple_source_policy(e))

    def test_external_header_syntax_is_rejected(self):
        e=base.Entry(1,0,1,1,'X','https://example.org/a.m3u8',user_agent='UA')
        self.assertIn('headers',old.simple_source_policy(e))

    def test_simple_profile(self):
        text='#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:1\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\na.ts\n'
        self.assertEqual(compat.classify_media_manifest(text).kind,'simple')

    def test_novelissima_style_detects_normalize_without_hostname(self):
        text='#EXTM3U\n#EXT-X-DISCONTINUITY-SEQUENCE:7\n#EXT-X-MEDIA-SEGMENT-SEQUENCE:11\n#EXT-X-CUE-OUT-CONT:ElapsedTime=1\n#EXT-X-MEDIA-SEQUENCE:20\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\na.ts\n'
        p=compat.classify_media_manifest(text,'https://generic.example/live.m3u8')
        self.assertEqual(p.kind,'normalize')
        out=compat.adapt_media_manifest(text,'https://generic.example/live.m3u8',p)
        self.assertNotIn('DISCONTINUITY-SEQUENCE',out)
        self.assertNotIn('MEDIA-SEGMENT',out)
        self.assertNotIn('CUE-OUT',out)
        self.assertIn('#EXT-X-MEDIA-SEQUENCE:20',out)

    def test_pluto_style_detects_aes_without_hostname(self):
        text='#EXTM3U\n#PLUTO-VERSION:2\n#EXT-X-DISCONTINUITY-SEQUENCE:9\n#EXT-X-MEDIA-SEQUENCE:100\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,KEYFORMAT="identity",URI="https://keys.example/k",IV=0x64\n#EXTINF:6,\na.ts\n'
        p=compat.classify_media_manifest(text,'https://generic.example/live.m3u8')
        self.assertEqual(p.kind,'normalize+aes128')
        out=compat.adapt_media_manifest(text,'https://generic.example/live.m3u8',p)
        self.assertNotIn('#EXT-X-KEY',out)

    def test_pure_aes128_is_supported(self):
        text='#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:5\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:6,\na.ts\n'
        self.assertEqual(compat.classify_media_manifest(text).kind,'aes128')

    def test_sample_aes_and_nonidentity_are_rejected(self):
        a='#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"\n#EXTINF:6,\na.ts\n'
        b='#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,KEYFORMAT="com.example.drm",URI="k"\n#EXTINF:6,\na.ts\n'
        self.assertEqual(compat.classify_media_manifest(a).kind,'unsupported')
        self.assertEqual(compat.classify_media_manifest(b).kind,'unsupported')

    def test_cmaf_and_byterange_are_rejected_until_proven(self):
        cmaf='#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\na.m4s\n'
        br='#EXTM3U\n#EXT-X-BYTERANGE:1000@0\n#EXTINF:6,\na.ts\n'
        self.assertEqual(compat.classify_media_manifest(cmaf).kind,'unsupported')
        self.assertEqual(compat.classify_media_manifest(br).kind,'unsupported')

    def test_variant_prefers_720_then_1080(self):
        text='#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"\n1080.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1800000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"\n720.m3u8\n'
        self.assertEqual(compat.choose_variant_with_fallback(text,'https://example.org/master.m3u8'),'https://example.org/720.m3u8')

if __name__=='__main__': unittest.main()
