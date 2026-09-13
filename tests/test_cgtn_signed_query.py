from urllib.parse import parse_qs, urlsplit
from scripts.hls_compat import resolve_with_context

def q(url):
    return parse_qs(urlsplit(url).query)

def test_cgtn_relative_child_inherits_signature():
    base = 'https://espanol-livetx-h5.cgtn.com/hls/live/playlist.m3u8?wsSecret=abc123&wsTime=1789310853&quality=debug'
    got = q(resolve_with_context(base, 'segment0001.ts'))
    assert got['wsSecret'] == ['abc123']
    assert got['wsTime'] == ['1789310853']
    assert 'quality' not in got

def test_child_value_wins_and_missing_signed_key_is_inherited():
    base = 'https://espanol-livetx-h5.cgtn.com/hls/live/playlist.m3u8?wsSecret=parent&wsTime=10'
    got = q(resolve_with_context(base, 'segment.ts?wsSecret=child'))
    assert got['wsSecret'] == ['child']
    assert got['wsTime'] == ['10']

def test_cross_host_does_not_receive_signature():
    base = 'https://espanol-livetx-h5.cgtn.com/hls/live/playlist.m3u8?wsSecret=abc123&wsTime=1789310853'
    got = q(resolve_with_context(base, 'https://cdn.example/segment.ts'))
    assert 'wsSecret' not in got
    assert 'wsTime' not in got
