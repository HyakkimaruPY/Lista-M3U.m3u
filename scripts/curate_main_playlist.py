#!/usr/bin/env python3
"""Curadoria estrutural da playlist principal.

- mantem exatamente um cabecalho #EXTM3U;
- corrige linhas EXTINF sem '#';
- remove Rede-Gospel/Renascer, preservando Rede-Super;
- normaliza categorias dos canais principais nao-Pluto;
- substitui a secao China inicial por uma selecao curta e rastreavel.

Nao altera entradas Pluto, exceto correcoes puramente sintaticas.
"""

from __future__ import annotations

import re
from pathlib import Path

PLAYLIST = Path("srhell02iptv.m3u")

CHINA_BLOCK = '''#EXTINF:-1 tvg-id="CGTNSpanish.cn" tvg-name="CGTN Español" tvg-logo="https://i.imgur.com/Poz3xfi.png" group-title="China • Internacional", CGTN Español
https://livees.cgtn.com/1000e/prog_index.m3u8

#EXTINF:-1 tvg-id="CCTV15.cn" tvg-name="CCTV-15 音乐 A" tvg-logo="https://i.imgur.com/CCV0eRG.png" group-title="China • Música", CCTV-15 音乐 A
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226476/index.m3u8

#EXTINF:-1 tvg-id="CCTV15.cn@alt1" tvg-name="CCTV-15 音乐 B" tvg-logo="https://i.imgur.com/CCV0eRG.png" group-title="China • Música", CCTV-15 音乐 B
https://xykt-fix.github.io/play/a02e/index.m3u8

#EXTINF:-1 tvg-id="CCTV15.cn@alt2" tvg-name="CCTV-15 音乐 C" tvg-logo="https://i.imgur.com/CCV0eRG.png" group-title="China • Música", CCTV-15 音乐 C
http://183.196.25.171:808/hls/15/index.m3u8

#EXTINF:-1 tvg-id="CCTV15.cn@alt3" tvg-name="CCTV-15 音乐 D" tvg-logo="https://i.imgur.com/CCV0eRG.png" group-title="China • Música", CCTV-15 音乐 D
https://stream1.freetv.fun/cb3c72e7254e40411c7136bafb32bd8e1b6f4739c265c52851cff323a6a22b77.m3u8

#EXTINF:-1 tvg-id="CCTV6.cn" tvg-name="CCTV-6 电影" tvg-logo="https://iptv.burningc4.com/tvg-logo/cctv6.png" group-title="China • Cinema", CCTV-6 电影
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226010/index.m3u8

#EXTINF:-1 tvg-id="CCTV8.cn" tvg-name="CCTV-8 电视剧" tvg-logo="https://iptv.burningc4.com/tvg-logo/cctv8.png" group-title="China • Séries", CCTV-8 电视剧
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226008/index.m3u8

#EXTINF:-1 tvg-id="CCTV11.cn" tvg-name="CCTV-11 戏曲" tvg-logo="https://iptv.burningc4.com/tvg-logo/cctv11.png" group-title="China • Cultura", CCTV-11 戏曲
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226565/index.m3u8

#EXTINF:-1 tvg-id="CCTV14.cn" tvg-name="CCTV-14 少儿" tvg-logo="https://iptv.burningc4.com/tvg-logo/cctvchild.png" group-title="China • Infantil", CCTV-14 少儿
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226591/index.m3u8

#EXTINF:-1 tvg-id="HunanSatelliteTV.cn" tvg-name="湖南卫视" tvg-logo="https://iptv.burningc4.com/tvg-logo/hunan.png" group-title="China • Variedades", 湖南卫视
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226307/index.m3u8

#EXTINF:-1 tvg-id="ZhejiangSatelliteTV.cn" tvg-name="浙江卫视" tvg-logo="https://iptv.burningc4.com/tvg-logo/zhejiang.png" group-title="China • Variedades", 浙江卫视
http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226404/index.m3u8
'''

CATEGORY_MAP = {
    "Tv-Series": "Séries",
    "Run-Ação": "Filmes • Ação",
    "Run-Ação 4k": "Filmes • Ação",
    "WTV-Classicos": "Filmes • Clássicos",
    "Sony-One": "Filmes • Clássicos",
    "On-Filmes": "Filmes",
    "Novelissima(ES)": "Novelas",
    "Retrô-TV": "Desenhos • Retrô",
    "Loading": "Anime",
    "Telemundo": "Variedades • Latino",
    "Master-Chef": "Variedades • Gastronomia",
    "Rede-Super": "TV • Brasil",
}


def get_name(extinf: str) -> str:
    m = re.search(r'tvg-name="([^"]+)"', extinf)
    if m:
        return m.group(1)
    return extinf.split(",", 1)[-1].strip()


def set_group(extinf: str, group: str) -> str:
    if 'group-title="' in extinf:
        return re.sub(r'group-title="[^"]*"', f'group-title="{group}"', extinf, count=1)
    comma = extinf.find(",")
    if comma == -1:
        return extinf + f' group-title="{group}"'
    return extinf[:comma] + f' group-title="{group}"' + extinf[comma:]


def main() -> int:
    raw = PLAYLIST.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()

    # Corrige sintaxe global e remove cabecalhos duplicados.
    out: list[str] = []
    header_seen = False
    for line in lines:
        stripped = line.strip()
        if stripped == "#EXTM3U":
            if header_seen:
                continue
            header_seen = True
            out.append("#EXTM3U")
            continue
        if line.startswith("EXTINF:"):
            line = "#" + line
        out.append(line)
    lines = out

    # Substitui a secao China inicial, terminando antes de Tv-Series.
    first_entry = next((i for i, line in enumerate(lines) if line.startswith("#EXTINF")), None)
    first_non_china = next((i for i, line in enumerate(lines) if 'tvg-id="Tv-Series"' in line), None)
    if first_entry is not None and first_non_china is not None and first_entry < first_non_china:
        lines = lines[:first_entry] + CHINA_BLOCK.strip().splitlines() + [""] + lines[first_non_china:]

    # Percorre blocos EXTINF para remover Rede-Gospel e normalizar categorias nao-Pluto.
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("#EXTINF"):
            result.append(line)
            i += 1
            continue

        start = i
        j = i + 1
        while j < len(lines) and not lines[j].startswith("#EXTINF"):
            j += 1
        block = lines[start:j]
        name = get_name(block[0])
        url = next((x.strip() for x in block[1:] if x.strip() and not x.lstrip().startswith("#")), "")

        if name in {"Rede-Gospel", "Rede Gospel", "Renascer", "Rede-Renascer", "Rede Renascer"}:
            i = j
            continue

        if "jmp2.uk" not in url and name in CATEGORY_MAP:
            block[0] = set_group(block[0], CATEGORY_MAP[name])

        result.extend(block)
        i = j

    text = "\n".join(result).rstrip() + "\n"
    PLAYLIST.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
