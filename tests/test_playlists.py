import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import validate_streams as v
from curate_main_playlist import curate, group_for
from sync_cn_to_main import cctv_key
from refresh_cn_sources import SOURCES

ROOT = Path(__file__).resolve().parents[1]

class ValidationTests(unittest.TestCase):
    def entry(self):
        return v.Entry(1,0,1,1,'TV','https://example.org/live.m3u8')

    def test_title_with_quoted_comma(self):
        self.assertEqual(v.extract_title('#EXTINF:-1 tvg-name="Foo, Bar",Channel', ''), 'Channel')

    def test_single_failure_never_removes(self):
        with patch.object(v, 'ffprobe_once', return_value=('definite','HTTP 404')):
            self.assertEqual(v.validate_entry(self.entry(),1,1,1).status,'uncertain')

    def test_repeated_404_removes(self):
        with patch.object(v, 'ffprobe_once', return_value=('definite','HTTP 404')), patch.object(v.time,'sleep'):
            self.assertEqual(v.validate_entry(self.entry(),2,1,1).status,'remove')

    def test_mixed_failure_preserves(self):
        with patch.object(v, 'ffprobe_once', side_effect=[('definite','404'),('uncertain','403')]), patch.object(v.time,'sleep'):
            self.assertEqual(v.validate_entry(self.entry(),2,1,1).status,'uncertain')

    def test_missing_av_preserves(self):
        with patch.object(v, 'ffprobe_once', return_value=('missing','missing')), patch.object(v.time,'sleep'):
            self.assertEqual(v.validate_entry(self.entry(),2,1,1).status,'uncertain')

    def test_successful_process_without_media_is_not_healthy(self):
        with patch.object(v,'run_command',return_value=(0,'',False)):
            self.assertEqual(v.decode_once(self.entry(),5,4)[0],'uncertain')

    def test_decoded_packets_both_tracks_and_duration(self):
        packets = '#tb 0: 1/25\n#tb 1: 1/48000\n0, 0, 0, 100, 1000, hash\n1, 0, 0, 192000, 1000, hash\n'
        self.assertTrue(v.decoded_av(packets,4))
        self.assertFalse(v.decoded_av(packets,8))
        self.assertFalse(v.decoded_av(packets.split('1, 0')[0],4))

    def test_segment_404_is_not_channel_dead(self):
        with patch.object(v,'run_command',return_value=(1,'Failed segment a.ts: HTTP error 404',False)):
            self.assertEqual(v.ffprobe_once(self.entry(),5)[0],'uncertain')

    def test_uhd_is_distinct(self):
        for name, key in [('CCTV-4K','cctv4k'),('CCTV-8K','cctv8k'),('CCTV-4','cctv4'),('CCTV-8','cctv8'),('CCTV-5+','cctv5plus')]:
            e=self.entry();e.title=name
            self.assertEqual(cctv_key(e),key)

    def test_slate_not_generic_wrap(self):
        self.assertFalse(v.is_pluto_unavailable_slate('Pluto TV cooking wrap'))
        self.assertTrue(v.is_pluto_unavailable_slate('Pluto TV is no longer available on this device'))

    def test_burning_not_stream_source(self):
        self.assertEqual([x[0] for x in SOURCES],['Free-TV','IPTV-org'])

    def test_curate_preserves_alternatives_and_headers(self):
        raw='#EXTM3U\n#EXTINF:-1 group-title="Kids US",Foo\n#EXTVLCOPT:http-user-agent=UA\nhttps://example.org/a\n#EXTINF:-1 group-title="Kids US",Foo\nhttps://example.org/b\n'
        out,removed=curate(raw)
        self.assertEqual(removed,0)
        self.assertIn('#EXTVLCOPT:http-user-agent=UA',out)
        self.assertEqual(len(v.parse_playlist(out.splitlines())),2)
        self.assertEqual(curate(out)[0],out)

    def test_real_playlist_structure(self):
        for name in ['cn.m3u','srhell02iptv.m3u']:
            lines=(ROOT/name).read_text().splitlines()
            self.assertTrue(lines[0].startswith('#EXTM3U'))
            self.assertEqual(sum(x.startswith('#EXTM3U') for x in lines),1)
            entries=v.parse_playlist(lines)
            urls=[i for i,x in enumerate(lines) if x.strip() and not x.startswith('#')]
            self.assertEqual(urls, [e.end for e in entries])
            self.assertGreater(len(entries),0)
            for e in entries:
                self.assertTrue(v.valid_network_url(v.probe_url_and_headers(e)[0]),(name,e.line))
                self.assertIn('group-title="',e.metadata)
            self.assertFalse(any(e.title in ['Rede-Gospel','Renascer'] for e in entries))
        self.assertTrue(any(e.title=='Rede-Super' for e in v.parse_playlist((ROOT/'srhell02iptv.m3u').read_text().splitlines())))

if __name__=='__main__':
    unittest.main()
