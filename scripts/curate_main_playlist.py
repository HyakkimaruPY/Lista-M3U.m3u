#!/usr/bin/env python3
"""Curadoria idempotente de metadados; nao inventa nem substitui streams."""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from validate_streams import parse_playlist, probe_url_and_headers, extract_title
from sync_cn_to_main import attr, set_attr, cctv_key

PLUTO_GROUPS = {
    'Movies': 'Filmes', 'Westerns': 'Faroeste', 'Sci-Fi': 'Ficção científica',
    'Drama': 'Séries', 'Comedy': 'Comédia', 'Classic TV': 'Séries clássicas',
    'Kids': 'Infantil', 'Anime': 'Anime', 'Gaming + Anime': 'Anime',
    'Reality': 'Reality e variedades', 'Competition Reality': 'Reality e variedades',
    'Daytime + Game Shows': 'Reality e variedades', 'Entertainment': 'Entretenimento',
    'True Crime': 'Investigação', 'History + Science': 'História e ciência',
    'Home + Food': 'Casa e gastronomia', 'Sports': 'Esportes',
    'En Español': 'Em espanhol', "Season's Greetings": 'Sazonais',
    'Test Test Test': 'Experimentais',
}
CCTV_GROUPS = {
    'cctv1': 'Nacionais e variedades', 'cctv2': 'Notícias e economia',
    'cctv3': 'Nacionais e variedades', 'cctv4': 'Internacional',
    'cctv5': 'Esportes', 'cctv5plus': 'Esportes', 'cctv6': 'Cinema e séries',
    'cctv7': 'Documentários e cultura', 'cctv8': 'Cinema e séries',
    'cctv9': 'Documentários e cultura', 'cctv10': 'Documentários e cultura',
    'cctv11': 'Documentários e cultura', 'cctv12': 'Sociedade e educação',
    'cctv13': 'Notícias e economia', 'cctv14': 'Infantil', 'cctv15': 'Música',
    'cctv16': 'Esportes', 'cctv17': 'Sociedade e educação',
    'cctv4k': 'Nacionais e variedades', 'cctv8k': 'Nacionais e variedades',
}

def china_group(entry):
    key = cctv_key(entry)
    if key in CCTV_GROUPS:
        return 'China • ' + CCTV_GROUPS[key]
    text = entry.title.lower() + ' ' + attr(entry.metadata, 'tvg-id').lower()
    rules = [
        (r'少儿|少兒|卡通|炫动|金鹰|child|cartoon|哈哈', 'Infantil'),
        (r'音乐|音樂|music', 'Música'),
        (r'体育|體育|篮球|足球|sport|olympic', 'Esportes'),
        (r'电影|電影|影视|影視|影院|电视剧|cinema|movie|drama', 'Cinema e séries'),
        (r'纪录|紀錄|纪实|紀實|文化|人文|戏曲|documentary|discovering|travel', 'Documentários e cultura'),
        (r'购物|購物|乐购|置业|shopping', 'Compras'),
        (r'财经|財經|理财|財經|经济|經濟|global biz|finance', 'Notícias e economia'),
        (r'科教|教育|法治|农村|農村|乡村|鄉村|education', 'Sociedade e educação'),
        (r'cgtn|国际|國際|international', 'Internacional'),
        (r'卫视|衛視|satellite|星空', 'Nacionais e variedades'),
    ]
    for pattern, group in rules:
        if re.search(pattern, text):
            return 'China • ' + group
    return 'China • Regionais e locais'


def group_for(entry, china):
    group = attr(entry.metadata, 'group-title')
    if china or group.startswith('China •'):
        return china_group(entry)
    if 'jmp2.uk' in (entry.url or ''):
        if group.endswith(' BR'):
            return {'Pluto Desenhos Clássicos BR': 'Pluto • Desenhos clássicos BR',
                    'Pluto Séries Clássicas BR': 'Pluto • Séries clássicas BR',
                    'Pluto Cinema Clássico BR': 'Pluto • Cinema clássico BR'}.get(group, group)
        if group.startswith('Pluto •'):
            return group
        base = re.sub(r' (?:US|S)$', '', group)
        return 'Pluto • ' + PLUTO_GROUPS.get(base, base) + ' S'
    if group == 'Wild Cards temp 01':
        return 'Séries VOD • Wild Cards • Temporada 1'
    return {'Filmes • Ação': 'Filmes', 'Filmes • Clássicos': 'Filmes',
            'Variedades • Latino': 'Variedades', 'Variedades • Gastronomia': 'Variedades'}.get(group, group)


def curate(raw: str, china=False):
    lines = raw.lstrip('\ufeff').splitlines()
    lines = ['#' + x if x.startswith('EXTINF:') else x.rstrip() for x in lines]
    entries = parse_playlist(lines)
    if not entries:
        raise ValueError('Nenhuma entrada encontrada')
    header = next((x for x in lines if x.startswith('#EXTM3U')), '#EXTM3U')
    blocks = []
    seen = {}
    removed = 0
    for e in entries:
        if e.title.casefold() in {'rede-gospel', 'rede gospel', 'renascer', 'rede-renascer', 'rede renascer'}:
            removed += 1
            continue
        # Only identical playback requests are duplicates; names/EPG IDs alone are insufficient.
        identity = probe_url_and_headers(e)
        directives = tuple(x for x in lines[e.start+1:e.end] if x.startswith('#'))
        identity = (*identity, directives)
        meta = set_attr(e.metadata, 'group-title', group_for(e, china))
        meta = set_attr(meta, 'tvg-name', e.title)
        if identity in seen:
            previous = blocks[seen[identity]][1]
            for name in ('tvg-id', 'tvg-logo'):
                if not attr(previous[0], name) and attr(meta, name):
                    previous[0] = set_attr(previous[0], name, attr(meta, name))
            removed += 1
            continue
        seen[identity] = len(blocks)
        block = [meta] + [x for x in lines[e.start+1:e.end+1] if x.strip()]
        blocks.append((group_for(e, china), block))
    # Group contiguous channels without changing provider order inside each group.
    order = list(dict.fromkeys(group for group, _ in blocks))
    out = [header, '# Categorias por conteúdo; x-source preserva a origem dos streams.',
           '# Links alternativos distintos são preservados; duplicatas exatas são removidas.', '']
    for group in order:
        for current, block in blocks:
            if group == current:
                out.extend(block + [''])
    return '\n'.join(out).rstrip() + '\n', removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--playlist', action='append')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    different = False
    for name in args.playlist or ['cn.m3u', 'srhell02iptv.m3u']:
        path = Path(name)
        raw = path.read_text(encoding='utf-8-sig')
        updated, removed = curate(raw, path.name == 'cn.m3u')
        different |= raw != updated
        if not args.check:
            path.write_text(updated, encoding='utf-8')
        print(f'{name}: removidas={removed}; alterada={raw != updated}')
    return int(args.check and different)

if __name__ == '__main__':
    raise SystemExit(main())
