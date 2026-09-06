#!/usr/bin/env python3
from pathlib import Path

PLAYLIST = Path('srhell02iptv.m3u')
DEAD_IDS = {'WTV-Classicos', 'Retrô-TV'}

raw = PLAYLIST.read_text(encoding='utf-8-sig')
lines = raw.splitlines()
out = []
i = 0
removed = []
while i < len(lines):
    line = lines[i]
    if line.startswith('#EXTINF:') and any(f'tvg-id="{channel_id}"' in line for channel_id in DEAD_IDS):
        removed.append(line)
        i += 1
        while i < len(lines) and not lines[i].startswith('#EXTINF:'):
            # consume options, URL and blank separator up to next entry
            i += 1
        continue
    out.append(line)
    i += 1

text = '\n'.join(out).rstrip() + '\n'
if text != raw:
    PLAYLIST.write_text(text, encoding='utf-8')
print(f'Removidos: {len(removed)}')
