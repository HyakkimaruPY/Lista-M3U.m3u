#!/usr/bin/env python3
import re
from pathlib import Path
p=Path('cn.m3u')
s=p.read_text(encoding='utf-8')
parts=re.split(r'(?=^#EXTINF:)',s,flags=re.M)
logos={}
keep=[]
for part in parts:
    if 'x-source="BurningC4"' in part:
        m=re.search(r'tvg-id="([^"]+)".*?tvg-logo="([^"]+)"',part)
        if m: logos[m.group(1).lower()]=m.group(2)
        continue
    keep.append(part)
# Reuse the BurningC4 logo catalogue for IPTV-org entries that lack logos.
for i,part in enumerate(keep):
    if 'x-source="IPTV-org"' not in part or 'tvg-logo=' in part: continue
    m=re.search(r'tvg-id="([^"]+)"',part)
    if not m: continue
    tid=m.group(1).split('@')[0].lower().replace('.cn','')
    aliases={'cctv9':'cctvjilu','cctv14':'cctvchild'}
    logo=logos.get(aliases.get(tid,tid))
    if logo:
        keep[i]=part.replace(' group-title=',f' tvg-logo="{logo}" group-title=',1)
s=''.join(keep)
s=re.sub(r'# Fonte: BurningC4\s*','',s)
s=s.replace('# Fonte: Free-TV','# BurningC4 removido como provedor; logos reaproveitadas abaixo.\n# Fonte: Free-TV',1)
p.write_text(s,encoding='utf-8')
print('cn.m3u: BurningC4 removido e logos reaproveitadas')
