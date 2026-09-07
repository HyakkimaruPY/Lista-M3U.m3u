#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

PLAYLIST = Path("srhell02iptv.m3u")
START = "# --- Roku FAST BEGIN ---"
END = "# --- Roku FAST END ---"

ENTRIES = [
    # Roku • Animações
    {
        "id": "roku-turma-da-monica",
        "name": "Turma da Mônica",
        "logo": "https://images.pluto.tv/channels/5f997e44949bc70007a6941e/thumbnail.jpg?fill=blur&fit=fill&fm=jpg&h=2080&q=75&w=2080",
        "group": "Roku • Animações",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/6e5fce0478454ffca133472e1c359f55/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
    {
        "id": "roku-moranguinho",
        "name": "Moranguinho",
        "logo": "https://i.imgur.com/9Vt0vrZ.png",
        "group": "Roku • Animações",
        "url": "https://ssai-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/15d2d4a8f740492cb0f81cbb1feb5123/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
    {
        "id": "roku-toon-goggles-brasil",
        "name": "Toon Goggles Brasil",
        "logo": "",
        "group": "Roku • Animações",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/pipAd/f0b823ee756a475d96c661596195e21e/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },

    # Roku • Filmes
    {
        "id": "roku-western-bound-pt",
        "name": "Western Bound em Português",
        "logo": "",
        "group": "Roku • Filmes",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/f5db557dc5ea4552bb723690a52f5aee/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
    {
        "id": "roku-filmelier-esperanca",
        "name": "Filmelier TV Esperança",
        "logo": "https://d3bd0tgyk368z1.cloudfront.net/feeds/epg/sofa/espca/lgartwork/esperanca_Logo700x200.png",
        "group": "Roku • Filmes",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/d8c82ef3962a4866bbff81317936d8cf/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
    {
        "id": "roku-filmelier-vida-real",
        "name": "Filmelier TV Vida Real",
        "logo": "https://d3bd0tgyk368z1.cloudfront.net/feeds/epg/sofa/fmvirl/vidareal_Logo700x200.png",
        "group": "Roku • Filmes",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/565cfbea4dd84fe9af37cf67e9036de7/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
    {
        "id": "roku-adrenalina-pura-halloween",
        "name": "Adrenalina Pura TV Halloween",
        "logo": "https://d3bd0tgyk368z1.cloudfront.net/feeds/epg/sofa/tvapt/tvapt_logo700x200.png",
        "group": "Roku • Filmes",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/61d31f5ea0524ab392ddf5c3ea37d678/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },

    # Roku • Séries
    {
        "id": "roku-malhacao-fast",
        "name": "Malhação Fast",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/f46d6f4717bc41758662e8c6700c1d68/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
    {
        "id": "roku-filmrise-series",
        "name": "FilmRise Séries Gratuitas",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://dotjw4onyd4re.cloudfront.net/v1/master/3fec3e5cac39a52b2132f9c66c83dae043dc17d4/prod-tcl/master.m3u8?ads.xumo_channelId=88884541",
        "source": "Roku FAST via TCL",
    },
    {
        "id": "roku-highway-to-heaven",
        "name": "Highway To Heaven",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://dotjw4onyd4re.cloudfront.net/v1/master/3fec3e5cac39a52b2132f9c66c83dae043dc17d4/prod-tcl/master.m3u8?ads.xumo_channelId=88884542",
        "source": "Roku FAST via TCL",
    },
    {
        "id": "roku-rookie-blue",
        "name": "Rookie Blue",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://amg00353-amg00353c44-tcl-us-7113.playouts.now.amagi.tv/playlist/amg00353-lionsgatetvfast-rookieblueportuguese-tclus/playlist.m3u8",
        "source": "Roku FAST via TCL/Amagi",
    },
    {
        "id": "roku-mr-bean",
        "name": "Mr. Bean",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://amg00627-banijay-amg00627c35-tcl-us-4282.playouts.now.amagi.tv/playlist/amg00627-banijayfast-mrbeanbr-tclus/playlist.m3u8",
        "source": "Roku FAST via TCL/Amagi",
    },

    # Roku • Variedades
    {
        "id": "roku-novelissima",
        "name": "Novelíssima",
        "logo": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRicsDxtDGrzInNAZnCnZJuGcWCiaAZ9yBOkEnaHaFkytr0FAdNRIpCHcJY&s=10",
        "group": "Roku • Variedades",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/12d72d1a2d184982808da4e7dc859aed/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },
]


def render_entry(item: dict[str, str]) -> str:
    attrs = [
        f'tvg-id="{item["id"]}"',
        f'tvg-name="{item["name"]}"',
    ]
    if item["logo"]:
        attrs.append(f'tvg-logo="{item["logo"]}"')
    attrs.extend([
        f'group-title="{item["group"]}"',
        f'x-source="{item["source"]}"',
    ])
    return f'#EXTINF:-1 {" ".join(attrs)}, {item["name"]}\n{item["url"]}'


def strip_existing_roku_block(text: str) -> str:
    block = re.compile(rf'\n?{re.escape(START)}.*?{re.escape(END)}\n?', re.S)
    return block.sub("\n", text)


def strip_legacy_novelissima(text: str) -> str:
    # Migra a entrada antiga Ottera/Novelissima(ES) para o endpoint TCL/Leiniao de referência.
    pattern = re.compile(
        r'\n?#EXTINF:[^\n]*Novelissima\(ES\)[^\n]*\n'
        r'(?:#EXTVLCOPT:[^\n]*\n)?'
        r'https://stream\.ads\.ottera\.tv/playlist\.m3u8\?network_id=2380\n?',
        re.I,
    )
    return pattern.sub("\n", text)


def main() -> int:
    text = PLAYLIST.read_text(encoding="utf-8-sig")
    trailing = text.endswith("\n")
    text = strip_existing_roku_block(text)
    text = strip_legacy_novelissima(text)

    block = START + "\n" + "\n\n".join(render_entry(e) for e in ENTRIES) + "\n" + END + "\n\n"

    marker = 'group-title="Pluto •'
    pos = text.find(marker)
    if pos >= 0:
        line_start = text.rfind("\n", 0, pos) + 1
        text = text[:line_start].rstrip() + "\n\n" + block + text[line_start:].lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + block

    if trailing or not text.endswith("\n"):
        text = text.rstrip() + "\n"
    PLAYLIST.write_text(text, encoding="utf-8")
    print(f"Roku FAST: {len(ENTRIES)} canais aplicados em {PLAYLIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
