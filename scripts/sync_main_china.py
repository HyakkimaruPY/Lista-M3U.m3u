#!/usr/bin/env python3
import re
from pathlib import Path
cn=Path('cn.m3u').read_text(encoding='utf-8')
main=Path('srhell02iptv.m3u').read_text(encoding='utf-8')

def candidates(tid):
    out=[]
    parts=re.split(r'(?=^#EXTINF:)',cn,flags=re.M)
    for p in parts:
        if f'tvg-id="{tid}' not in p: continue
        if 'x-source="Free-TV"' not in p and 'x-source="IPTV-org"' not in p: continue
        u=next((x.strip() for x in p.splitlines()[1:] if x.strip() and not x.startswith('#')),None)
        if u and u not in out: out.append(u)
    return out

ids={'CCTV6.cn':'CCTV-6 电影','CCTV8.cn':'CCTV-8 电视剧','CCTV11.cn':'CCTV-11 戏曲','CCTV14.cn':'CCTV-14 少儿'}
lines=main.splitlines()
for tid,name in ids.items():
    cs=candidates(tid)
    if not cs: continue
    for i,line in enumerate(lines):
        if line.startswith('#EXTINF:') and name in line:
            j=i+1
            while j<len(lines) and lines[j].startswith('#'): j+=1
            if j<len(lines): lines[j]=cs[0]
# CCTV-15 entries are rebuilt from all unique Free-TV/IPTV-org alternatives present in cn.m3u.
cs=candidates('CCTV15.cn')
out=[]; i=0; inserted=False
while i<len(lines):
    if lines[i].startswith('#EXTINF:') and 'CCTV-15 音乐' in lines[i]:
        template=lines[i]
        j=i+1
        while j<len(lines) and lines[j].startswith('#'): j+=1
        i=j+1
        if not inserted:
            for n,u in enumerate(cs,1):
                inf=re.sub(r'CCTV-15 音乐(?: [A-D1-9])?',f'CCTV-15 音乐 {n}',template)
                out.extend([inf,u,''])
            inserted=True
        continue
    out.append(lines[i]); i+=1
Path('srhell02iptv.m3u').write_text('\n'.join(out).rstrip()+'\n',encoding='utf-8')
print('CCTV da principal sincronizados com Free-TV/IPTV-org de cn.m3u')
