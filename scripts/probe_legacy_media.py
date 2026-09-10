#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,subprocess,time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,urlopen

UA='Mozilla/5.0 (Linux; SmartTV) OldHLSProbe/1.0'
TARGETS=('Fora Tédio TV','Novelíssima','Pluto · Desenhos Clássicos','Pluto · Cine Clássicos')

def parse_playlist(path:Path):
    out=[]; meta=''; name=''
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        s=raw.strip()
        if s.startswith('#EXTINF:'):
            meta=s; name=s.rsplit(',',1)[-1].strip()
        elif s and not s.startswith('#') and name:
            out.append((name,meta,s)); meta=''; name=''
    return out

def safe_url(u:str)->str:
    p=urlsplit(u)
    return f'{p.scheme}://{p.netloc}{p.path}'

def fetch_text(u:str,timeout=12):
    req=Request(u,headers={'User-Agent':UA,'Accept':'application/vnd.apple.mpegurl,application/x-mpegURL,*/*','Accept-Encoding':'identity'})
    with urlopen(req,timeout=timeout) as r:
        b=r.read(2*1024*1024)
        return b.decode('utf-8-sig','replace'),r.geturl(),r.headers.get('Content-Type','')

def attrs(line:str):
    payload=line.split(':',1)[1] if ':' in line else ''
    out={}; cur=''; q=False; parts=[]
    for ch in payload:
        if ch=='"': q=not q
        if ch==',' and not q: parts.append(cur); cur=''
        else: cur+=ch
    parts.append(cur)
    for p in parts:
        if '=' in p:
            k,v=p.split('=',1); out[k.strip().upper()]=v.strip().strip('"')
    return out

def manifest_summary(text:str,final:str):
    lines=[x.strip() for x in text.replace('\r\n','\n').split('\n') if x.strip()]
    tags=Counter()
    variants=[]; media=[]; keys=[]; segs=[]
    for i,l in enumerate(lines):
        if l.startswith('#'):
            tag=l.split(':',1)[0]
            tags[tag]+=1
            if l.startswith('#EXT-X-STREAM-INF:'):
                a=attrs(l); uri=''
                for n in lines[i+1:]:
                    if not n.startswith('#'):
                        uri=n; break
                variants.append({'resolution':a.get('RESOLUTION',''),'codecs':a.get('CODECS',''),'fps':a.get('FRAME-RATE',''),'bandwidth':a.get('AVERAGE-BANDWIDTH') or a.get('BANDWIDTH',''),'audio':a.get('AUDIO',''),'uri':safe_url(urljoin(final,uri)) if uri else ''})
            elif l.startswith('#EXT-X-MEDIA:'):
                a=attrs(l); media.append({'type':a.get('TYPE',''),'group':a.get('GROUP-ID',''),'name':a.get('NAME',''),'default':a.get('DEFAULT',''),'autoselect':a.get('AUTOSELECT',''),'uri':safe_url(urljoin(final,a.get('URI',''))) if a.get('URI') else ''})
            elif l.startswith('#EXT-X-KEY:'):
                a=attrs(l); keys.append({'method':a.get('METHOD',''),'keyformat':a.get('KEYFORMAT','identity'),'iv':bool(a.get('IV')),'uri_host':urlsplit(urljoin(final,a.get('URI',''))).hostname if a.get('URI') else ''})
        else:
            segs.append(safe_url(urljoin(final,l)))
    return {
        'final':safe_url(final),'tags':dict(sorted(tags.items())),'variants':variants[:8],'media':media[:8],'keys':keys[:8],
        'segment_examples':segs[:3], 'has_map':'#EXT-X-MAP' in tags,'has_byterange':'#EXT-X-BYTERANGE' in tags,
        'discontinuities':tags.get('#EXT-X-DISCONTINUITY',0),'discontinuity_sequence':tags.get('#EXT-X-DISCONTINUITY-SEQUENCE',0),
        'targetduration':[l.split(':',1)[1] for l in lines if l.startswith('#EXT-X-TARGETDURATION:')][:1],
        'version':[l.split(':',1)[1] for l in lines if l.startswith('#EXT-X-VERSION:')][:1],
    }

def choose_child(text,final):
    lines=[x.strip() for x in text.replace('\r\n','\n').split('\n') if x.strip()]
    cand=[]
    for i,l in enumerate(lines):
        if not l.startswith('#EXT-X-STREAM-INF:'): continue
        a=attrs(l); uri=''
        for n in lines[i+1:]:
            if not n.startswith('#'): uri=n; break
        if not uri: continue
        c=(a.get('CODECS','') or '').lower()
        if any(x in c for x in ('hvc1','hev1','av01','vp09','ac-3','ec-3')): continue
        res=a.get('RESOLUTION',''); h=0
        try: h=int(res.lower().split('x')[1]) if 'x' in res else 0
        except: pass
        if h and h>720: continue
        bw=0
        try: bw=int(a.get('AVERAGE-BANDWIDTH') or a.get('BANDWIDTH') or 0)
        except: pass
        cand.append((h or 1,bw,urljoin(final,uri)))
    if not cand: return None
    cand.sort(reverse=True)
    return cand[0][2]

def ffprobe(u:str):
    fields='stream=index,codec_type,codec_name,codec_long_name,profile,level,width,height,pix_fmt,r_frame_rate,avg_frame_rate,field_order,has_b_frames,refs,sample_rate,channels,channel_layout,codec_tag_string'
    cmd=['ffprobe','-v','error','-rw_timeout','12000000','-user_agent',UA,'-probesize','12000000','-analyzeduration','12000000','-show_entries',fields,'-of','json',u]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
    except subprocess.TimeoutExpired:
        return {'error':'timeout'}
    if p.returncode:
        return {'error':(p.stderr or '').strip()[-500:]}
    try: return json.loads(p.stdout)
    except: return {'error':'json','raw':p.stdout[-500:]}

def inspect(name,u):
    r={'name':name,'source':safe_url(u),'manifests':[],'ffprobe':ffprobe(u)}
    cur=u
    for depth in range(3):
        try: text,final,ct=fetch_text(cur)
        except Exception as e:
            r['manifest_error']=f'{type(e).__name__}: {e}'; break
        s=manifest_summary(text,final); s['depth']=depth; s['content_type']=ct; r['manifests'].append(s)
        nxt=choose_child(text,final)
        if not nxt: break
        cur=nxt
    return r

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--playlist',default='old_hls.m3u8'); ap.add_argument('--out',default='reports/old-hls/deep-profile.json'); a=ap.parse_args()
    entries={n:u for n,m,u in parse_playlist(Path(a.playlist))}
    result={'generated_unix':int(time.time()),'targets':[]}
    for n in TARGETS:
        if n in entries:
            print('probe',n,flush=True); result['targets'].append(inspect(n,entries[n]))
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out)
if __name__=='__main__': main()
