#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from validate_streams import Entry, parse_playlist, probe_url_and_headers, validate_entry

URL_RE = re.compile(r'^https?://', re.I)


def attr(meta: str, name: str) -> str:
    m = re.search(rf'\b{re.escape(name)}="([^"]*)"', meta, re.I)
    return m.group(1).strip() if m else ""


def set_attr(meta: str, name: str, value: str) -> str:
    pat = re.compile(rf'\b{re.escape(name)}="[^"]*"', re.I)
    token = f'{name}="{value}"'
    if pat.search(meta):
        return pat.sub(token, meta, count=1)
    comma = meta.find(',')
    return (meta[:comma] + ' ' + token + meta[comma:]) if comma >= 0 else meta + ' ' + token


def cctv_key(entry: Entry) -> str:
    text = ' '.join([attr(entry.metadata, 'tvg-id'), attr(entry.metadata, 'tvg-name'), entry.title]).lower()
    text = text.replace('＋', '+')
    if 'cctv' not in text:
        return ''
    if re.search(r'cctv\s*-?\s*5\s*\+', text) or 'cctv5plus' in text:
        return 'cctv5plus'
    if re.search(r'cctv\s*-?\s*4k', text):
        return 'cctv4'
    if re.search(r'cctv\s*-?\s*8k', text):
        return 'cctv8'
    m = re.search(r'cctv\s*-?\s*(\d{1,2})', text)
    return f'cctv{int(m.group(1))}' if m else ''


def source_rank(entry: Entry) -> int:
    source = attr(entry.metadata, 'x-source').lower()
    group = attr(entry.metadata, 'group-title').lower()
    if source == 'free-tv' or 'free-tv' in group:
        return 0
    if source == 'iptv-org' or 'iptv-org' in group:
        return 1
    return 9


def source_name(entry: Entry) -> str:
    return 'Free-TV' if source_rank(entry) == 0 else 'IPTV-org'


def historical_burning_text() -> str:
    try:
        revs = subprocess.check_output(['git', 'rev-list', 'HEAD', '--', 'cn.m3u'], text=True).splitlines()
    except Exception:
        return ''
    for rev in revs:
        try:
            text = subprocess.check_output(['git', 'show', f'{rev}:cn.m3u'], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        if 'x-source="BurningC4"' in text or 'China • BurningC4' in text:
            return text
    return ''


def norm_ascii(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', value.lower())


def base_station_id(entry: Entry) -> str:
    raw = attr(entry.metadata, 'tvg-id').split('.cn')[0]
    value = norm_ascii(raw)
    aliases = {
        'beijingsatellitetv': 'btv1',
        'brtvkakuchildrenschannel': 'btvchild',
        'shaanxisatellitetv': 'shan3xi',
        'shaanxitv': 'shan3xi',
        'neimonggolsatellitetv': 'neimenggu',
        'neimonggolt': 'neimenggu',
    }
    for prefix, target in aliases.items():
        if value.startswith(prefix):
            return target
    return value


def build_logo_catalog(text: str):
    catalog = []
    if not text:
        return catalog
    for e in parse_playlist(text.splitlines()):
        if attr(e.metadata, 'x-source').lower() != 'burningc4' and 'burningc4' not in attr(e.metadata, 'group-title').lower():
            continue
        logo = attr(e.metadata, 'tvg-logo')
        if not logo:
            continue
        catalog.append({
            'key': cctv_key(e),
            'id': norm_ascii(attr(e.metadata, 'tvg-id')),
            'logo': logo,
        })
    return catalog


def match_logo(entry: Entry, catalog) -> str:
    key = cctv_key(entry)
    if key:
        for item in catalog:
            if item['key'] == key:
                return item['logo']

    eid = base_station_id(entry)
    if not eid:
        return ''
    for item in catalog:
        iid = item['id']
        if not iid or item['key']:
            continue
        if eid == iid:
            return item['logo']
        if len(iid) >= 4 and eid.startswith(iid):
            return item['logo']
        if len(eid) >= 4 and iid.startswith(eid):
            return item['logo']
    return ''


def clean_and_fill_cn(path: Path) -> tuple[int, int]:
    raw = path.read_text(encoding='utf-8-sig')
    lines = raw.splitlines()
    catalog = build_logo_catalog(historical_burning_text())
    remove = set()
    logos = 0
    for e in parse_playlist(lines):
        source = attr(e.metadata, 'x-source').lower()
        group = attr(e.metadata, 'group-title').lower()
        if source == 'burningc4' or 'burningc4' in group:
            remove.update(range(e.start, e.end + 1))
            continue
        if (source == 'iptv-org' or 'iptv-org' in group) and not attr(e.metadata, 'tvg-logo'):
            logo = match_logo(e, catalog)
            if logo:
                lines[e.start] = set_attr(lines[e.start], 'tvg-logo', logo)
                logos += 1
    if remove:
        lines = [line for i, line in enumerate(lines) if i not in remove]
    updated = '\n'.join(lines).rstrip() + '\n'
    if updated != raw:
        path.write_text(updated, encoding='utf-8')
    return len(remove), logos


def validate_candidate(candidate: Entry, retries: int, timeout: int, decode_seconds: int) -> bool:
    url, _, _ = probe_url_and_headers(candidate)
    if not url:
        return False
    result = validate_entry(candidate, retries, timeout, decode_seconds, False)
    print(f'[TEST] {candidate.title}: {result.status} - {result.reason}')
    return result.status == 'healthy'


def sync_main(cn_path: Path, main_path: Path, retries: int, timeout: int, decode_seconds: int) -> tuple[int, list[str]]:
    cn_lines = cn_path.read_text(encoding='utf-8-sig').splitlines()
    candidates: dict[str, list[Entry]] = {}
    for e in parse_playlist(cn_lines):
        key = cctv_key(e)
        if not key or source_rank(e) > 1:
            continue
        candidates.setdefault(key, []).append(e)
    for key in candidates:
        candidates[key].sort(key=lambda e: (source_rank(e), e.line))

    raw = main_path.read_text(encoding='utf-8-sig')
    lines = raw.splitlines()
    main_entries = parse_playlist(lines)
    usage: dict[str, int] = {}
    validated: dict[str, bool] = {}
    changed_urls = 0
    selected = []

    for e in main_entries:
        group = attr(e.metadata, 'group-title').lower()
        key = cctv_key(e)
        if not key or 'china' not in group:
            continue
        pool = candidates.get(key, [])
        if not pool:
            print(f'[MISS] {e.title}: sem equivalente em Free-TV/IPTV-org')
            continue
        start = usage.get(key, 0)
        ordered = pool[start:] + pool[:start]
        choice = None
        for cand in ordered:
            url, _, _ = probe_url_and_headers(cand)
            if not url:
                continue
            if url not in validated:
                validated[url] = validate_candidate(cand, retries, timeout, decode_seconds)
            if validated[url]:
                choice = cand
                break
        if choice is None:
            print(f'[FAIL] {e.title}: nenhum candidato passou ffprobe/ffmpeg')
            continue

        usage[key] = min(start + 1, max(0, len(pool) - 1))
        url, _, _ = probe_url_and_headers(choice)
        old_url, _, _ = probe_url_and_headers(e)
        if url != old_url:
            lines[e.end] = url
            changed_urls += 1

        lines[e.start] = set_attr(lines[e.start], 'x-source', source_name(choice))
        logo = attr(choice.metadata, 'tvg-logo')
        if logo and not attr(lines[e.start], 'tvg-logo'):
            lines[e.start] = set_attr(lines[e.start], 'tvg-logo', logo)
        selected.append(f'{e.title} <- {source_name(choice)} | {url}')

    updated = '\n'.join(lines).rstrip() + '\n'
    if updated != raw:
        main_path.write_text(updated, encoding='utf-8')
    return changed_urls, selected


def structural_check(path: Path) -> None:
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    if not lines or not lines[0].startswith('#EXTM3U'):
        raise SystemExit(f'{path}: cabecalho #EXTM3U ausente')
    entries = parse_playlist(lines)
    if not entries:
        raise SystemExit(f'{path}: nenhuma entrada')
    for e in entries:
        url, _, _ = probe_url_and_headers(e)
        if not url or not URL_RE.match(url):
            raise SystemExit(f'{path}:{e.line}: URL invalida em {e.title}')
    print(f'[M3U] {path}: {len(entries)} entradas estruturalmente validas')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--cn', default='cn.m3u')
    ap.add_argument('--main', default='srhell02iptv.m3u')
    ap.add_argument('--retries', type=int, default=2)
    ap.add_argument('--timeout', type=int, default=25)
    ap.add_argument('--decode-seconds', type=int, default=4)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    cn = Path(args.cn)
    mainp = Path(args.main)
    cn_before = cn.read_text(encoding='utf-8-sig')
    main_before = mainp.read_text(encoding='utf-8-sig')

    removed_lines, logos = clean_and_fill_cn(cn)
    changed, selected = sync_main(cn, mainp, args.retries, args.timeout, args.decode_seconds)
    structural_check(cn)
    structural_check(mainp)

    print(f'[CN] linhas BurningC4 removidas={removed_lines}; logos IPTV-org preenchidas={logos}')
    print(f'[MAIN] URLs CCTV substituidas={changed}; CCTV validados={len(selected)}')
    for item in selected:
        print('[SYNC]', item)

    if not args.apply:
        cn.write_text(cn_before, encoding='utf-8')
        mainp.write_text(main_before, encoding='utf-8')
        print('[DRY-RUN] arquivos restaurados')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
