#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,ssl,sys,time
from dataclasses import asdict,dataclass
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urljoin,urlsplit
from urllib.request import HTTPRedirectHandler,Request,build_opener,HTTPSHandler
import validate_streams as base

MAX_MANIFEST=2*1024*1024
BAD_CODEC=re.compile(r'(?:hvc1|hev1|hevc|h265|av01|av1|vp09|vp9|ac-3|ec-3|eac3)',re.I)
ALLOWED_GROUPS={'Variedade','Filmes','Séries','CCTV','Beta'}

@dataclass
class LegacyResult:
    name:str; host:str; status:str; reason:str; redirects:int=0; final_host:str=''; media_url:str=''

class RedirectCounter(HTTPRedirectHandler):
    def __init__(self): super().__init__(); self.count=0
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        self.count+=1
        if self.count>8: raise HTTPError(req.full_url,code,'redirect limit',headers,fp)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def entry_profile(entry:base.Entry)->str:
    m=re.search(r'x-profile="([^"]+)"',entry.metadata or '',re.I)
    return m.group(1).lower() if m else ''

def bridge_profile(entry:base.Entry)->bool:
    return entry_profile(entry).startswith('bridge')

def entry_group(entry:base.Entry)->str:
    m=re.search(r'group-title="([^"]+)"',entry.metadata or '',re.I)
    return m.group(1) if m else ''

def beta_profile(entry:base.Entry)->bool:
    return entry_group(entry)=='Beta'

def simple_source_policy(entry:base.Entry)->str|None:
    url,ua,ref=base.probe_url_and_headers(entry)
    if not base.valid_network_url(url): return 'URL ausente ou malformada'
    assert url is not None
    p=urlsplit(url)
    if (p.query or p.fragment) and not bridge_profile(entry):
        return 'URL possui query/fragmento; use x-profile="bridge*" apenas para excecao comprovada'
    if '|' in (entry.url or '') or ua or ref: return 'URL depende de headers/opcoes especiais'
    return None

def fetch_text(url:str,timeout:int):
    c=RedirectCounter(); op=build_opener(c,HTTPSHandler(context=ssl.create_default_context()))
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (Linux; SmartTV) OldHLSValidator/1.3','Accept':'application/vnd.apple.mpegurl,application/x-mpegURL,*/*','Accept-Encoding':'identity'})
    with op.open(req,timeout=timeout) as r:
        raw=r.read(MAX_MANIFEST+1)
        if len(raw)>MAX_MANIFEST: raise ValueError('manifesto maior que 2 MiB')
        return raw.decode('utf-8-sig','replace'),r.geturl(),c.count,r.headers.get('Content-Type','')

def parse_attrs(line:str)->dict[str,str]:
    payload=line.split(':',1)[1] if ':' in line else ''; out={}; cur=[]; quoted=False; parts=[]
    for ch in payload:
        if ch=='"': quoted=not quoted
        if ch==',' and not quoted: parts.append(''.join(cur)); cur=[]
        else: cur.append(ch)
    parts.append(''.join(cur))
    for p in parts:
        if '=' in p:
            k,v=p.split('=',1); out[k.strip().upper()]=v.strip().strip('"')
    return out

def select_variant(text:str,base_url:str):
    lines=[x.strip() for x in text.replace('\r\n','\n').split('\n')]; variants=[]
    for i,line in enumerate(lines):
        if not line.upper().startswith('#EXT-X-STREAM-INF:'): continue
        a=parse_attrs(line); uri=None
        for nxt in lines[i+1:]:
            if nxt and not nxt.startswith('#'): uri=nxt; break
        if not uri or BAD_CODEC.search(a.get('CODECS','')): continue
        w=h=0
        try:
            if 'x' in a.get('RESOLUTION','').lower(): w,h=[int(x) for x in a['RESOLUTION'].lower().split('x',1)]
        except: pass
        try: fps=float(a.get('FRAME-RATE','0') or 0)
        except: fps=0
        if w>1920 or h>1080 or fps>60.5: continue
        try: bw=int(a.get('AVERAGE-BANDWIDTH',a.get('BANDWIDTH','0')) or 0)
        except: bw=0
        variants.append((h,bw,urljoin(base_url,uri)))
    if not variants: return None,'master sem variante AVC/AAC <=1080p/60fps identificavel'
    variants.sort(reverse=True); return variants[0][2],None

def media_policy(text:str,final_url:str,profile:str='')->str|None:
    up=text.upper()
    if '#EXT-X-MAP' in up: return 'HLS fMP4/CMAF (#EXT-X-MAP) nao aceito'
    for line in text.splitlines():
        if not line.strip().upper().startswith('#EXT-X-KEY:'): continue
        a=parse_attrs(line); method=a.get('METHOD','NONE').upper(); keyformat=a.get('KEYFORMAT','identity') or 'identity'
        if method=='NONE': continue
        if profile=='bridge-aes' and method=='AES-128' and keyformat.lower()=='identity' and a.get('URI'):
            continue
        return 'stream criptografado (#EXT-X-KEY) fora do perfil bridge-aes suportado'
    media=[urljoin(final_url,s.strip()) for s in text.splitlines() if s.strip() and not s.strip().startswith('#')]
    if not media: return 'playlist de midia sem segmentos'
    sample=media[0].lower().split('?',1)[0]
    if sample.endswith(('.m4s','.mp4','.cmfv','.cmfa')): return 'segmentos fMP4/CMAF nao aceitos'
    return None

def inspect_entry(entry:base.Entry,timeout:int)->LegacyResult:
    url,_,_=base.probe_url_and_headers(entry); host=base.host_of(url); bad=simple_source_policy(entry); profile=entry_profile(entry)
    if bad: return LegacyResult(entry.title,host,'incompatible',bad)
    assert url is not None
    try: text,final,redirects,_=fetch_text(url,timeout)
    except (HTTPError,URLError,TimeoutError,OSError) as e: return LegacyResult(entry.title,host,'uncertain',f'rede/HTTP inconclusivo: {e}')
    except ValueError as e: return LegacyResult(entry.title,host,'incompatible',str(e))
    if not text.lstrip().startswith('#EXTM3U'): return LegacyResult(entry.title,host,'incompatible','resposta nao e manifesto HLS',redirects,base.host_of(final))
    max_redirects=8 if bridge_profile(entry) else (3 if entry_group(entry)=='CCTV' else 1)
    if redirects>max_redirects: return LegacyResult(entry.title,host,'incompatible',f'cadeia de redirect longa ({redirects})',redirects,base.host_of(final))
    media_url=final
    if '#EXT-X-STREAM-INF' in text.upper():
        media_url,why=select_variant(text,final)
        if why: return LegacyResult(entry.title,host,'incompatible',why,redirects,base.host_of(final))
        try: text,media_final,r2,_=fetch_text(media_url,timeout); redirects+=r2; media_url=media_final
        except (HTTPError,URLError,TimeoutError,OSError) as e: return LegacyResult(entry.title,host,'uncertain',f'variante inconclusiva: {e}',redirects,base.host_of(final),media_url)
        if redirects>max_redirects: return LegacyResult(entry.title,host,'incompatible',f'cadeia de redirect longa ({redirects})',redirects,base.host_of(media_url),media_url)
    bad=media_policy(text,media_url,profile)
    if bad: return LegacyResult(entry.title,host,'incompatible',bad,redirects,base.host_of(media_url),media_url)
    detail='HLS compativel com o perfil legado'
    if profile=='bridge-normalize': detail+=' via normalizacao HLS v3 na bridge'
    if profile=='bridge-aes': detail+=' via AES-128 descriptografado na bridge'
    return LegacyResult(entry.title,host,'compatible',detail,redirects,base.host_of(media_url),media_url)

def playlist_structure(path:Path)->list[str]:
    lines=path.read_text(encoding='utf-8-sig').splitlines(); errors=[]
    if not lines or not lines[0].startswith('#EXTM3U'): errors.append('primeira linha deve ser #EXTM3U')
    if sum(x.startswith('#EXTM3U') for x in lines)!=1: errors.append('playlist deve conter exatamente um #EXTM3U')
    entries=base.parse_playlist(lines)
    if not entries: errors.append('nenhuma entrada #EXTINF')
    for e in entries:
        m=re.search(r'group-title="([^"]+)"',e.metadata,re.I)
        if not m: errors.append(f'linha {e.line}: group-title ausente')
        elif m.group(1) not in ALLOWED_GROUPS: errors.append(f'linha {e.line}: grupo nao permitido: {m.group(1)}')
        bad=simple_source_policy(e)
        if bad: errors.append(f'linha {e.line}: {bad}')
    return errors

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--playlist',default='old_hls.m3u8'); ap.add_argument('--timeout',type=int,default=12); ap.add_argument('--report-dir',default='reports/old-hls'); ap.add_argument('--strict',action='store_true'); a=ap.parse_args()
    p=Path(a.playlist)
    if not p.exists(): print(f'ERRO: {p} nao existe',file=sys.stderr); return 2
    structure=playlist_structure(p); entries=base.parse_playlist(p.read_text(encoding='utf-8-sig').splitlines()); results=[]
    if not structure:
        for e in entries:
            r=inspect_entry(e,max(2,a.timeout))
            if beta_profile(e) and r.status=='incompatible': r.status='uncertain'; r.reason='BETA experimental: '+r.reason
            results.append(r); print(f'[{r.status.upper():12}] {r.name}: {r.reason}')
    report={'playlist':str(p),'checked_at_unix':int(time.time()),'structure_errors':structure,'counts':{k:sum(r.status==k for r in results) for k in ('compatible','incompatible','uncertain')},'results':[asdict(r) for r in results]}
    out=Path(a.report_dir); out.mkdir(parents=True,exist_ok=True); (out/'legacy-profile.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    s=['# Old HLS - perfil legado','',f"- Estrutura: **{'PASS' if not structure else 'FAIL'}**",'',f"- Compativeis: **{report['counts']['compatible']}**",f"- Incompativeis: **{report['counts']['incompatible']}**",f"- Inconclusivos/Beta: **{report['counts']['uncertain']}**"]
    if structure: s+=['','## Erros estruturais']+[f'- {x}' for x in structure]
    (out/'legacy-summary.md').write_text('\n'.join(s)+'\n',encoding='utf-8')
    return 1 if structure or (a.strict and report['counts']['incompatible']) else 0
if __name__=='__main__': raise SystemExit(main())
