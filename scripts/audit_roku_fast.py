#!/usr/bin/env python3
"""Read-only CCTV retest and curated FAST H.264 admission report."""
import concurrent.futures
import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
from validate_streams import Entry, parse_playlist, validate_entry, decode_once

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/roku-fast'

def fast(item):
    result = dict(item, rounds=[], dns=[], admitted=False)
    try:
        result['dns'] = sorted({r[4][0] for r in socket.getaddrinfo(urlsplit(item['url']).hostname, 443)})
        with urlopen(item['url'], timeout=20) as response:
            manifest = response.read(200000).decode()
            result['manifest_host'] = urlsplit(response.url).hostname
            result['manifest_codecs'] = [x for x in manifest.splitlines() if x.startswith('#EXT-X-STREAM-INF')]
        entry = Entry(1,0,1,1,item['name'],item['url'])
        for attempt in range(2):
            proc = subprocess.run(['ffprobe','-v','error','-rw_timeout','20000000','-show_streams','-of','json',item['url']], capture_output=True,text=True,timeout=40)
            streams = json.loads(proc.stdout or '{}').get('streams',[])
            video = [s for s in streams if s.get('codec_type')=='video']
            audio = [s for s in streams if s.get('codec_type')=='audio']
            codecs = sorted({s.get('codec_name','') for s in video})
            status, reason = decode_once(entry, 50, 8) if video and audio and codecs == ['h264'] else ('uncertain','H.264 + audio nao confirmados')
            result['rounds'].append({'status':status,'reason':reason,'video_codecs':codecs,'audio_codecs':sorted({s.get('codec_name','') for s in audio}),'video':[{k:s.get(k) for k in ['width','height','profile','pix_fmt']} for s in video]})
        result['admitted'] = all(r['status']=='healthy' for r in result['rounds'])
        if result['admitted']:
            slug = ''.join(c if c.isalnum() else '-' for c in item['name'])
            p = subprocess.run(['ffmpeg','-v','error','-nostdin','-rw_timeout','20000000','-i',item['url'],'-t','24','-an','-vf','fps=1/8,scale=640:-2','-frames:v','3',str(OUT / (slug+'-%02d.jpg'))],capture_output=True,timeout=50)
            result['frames'] = [p.name for p in OUT.glob(slug+'-*.jpg')]
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:250]
    print('FAST_RESULT '+json.dumps(result,ensure_ascii=False),flush=True)
    return result

def china(pair):
    filename, entry = pair
    r = validate_entry(entry, 2, 25, 4, False)
    result = {'playlist':filename,'line':entry.line,'name':entry.title,'url':entry.url,'status':r.status,'reason':r.reason}
    print('CCTV_RESULT '+json.dumps(result,ensure_ascii=False),flush=True)
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    candidates = json.loads((ROOT/'data/roku_fast_candidates.json').read_text())
    entries = [(name,e) for name in ['cn.m3u','srhell02iptv.m3u'] for e in parse_playlist((ROOT/name).read_text().splitlines()) if 'cctv' in (e.metadata+' '+e.title).lower()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        fast_results = list(pool.map(fast,candidates))
        cctv_results = list(pool.map(china,entries))
    report = {'tested_at':datetime.now(timezone.utc).isoformat(),'fast':fast_results,'cctv':cctv_results}
    (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('SUMMARY '+json.dumps({'fast_admitted':sum(x['admitted'] for x in fast_results),'fast_total':len(fast_results),'cctv':{s:sum(x['status']==s for x in cctv_results) for s in ['healthy','uncertain','remove']}}),flush=True)

if __name__ == '__main__':
    main()
