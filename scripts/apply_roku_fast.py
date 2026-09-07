#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

PLAYLIST = Path("srhell02iptv.m3u")
START = "# --- Roku FAST BEGIN ---"
END = "# --- Roku FAST END ---"

# Curadoria intencionalmente restrita: nostalgia, séries antigas, animações clássicas
# e filmes. Não preencher a categoria com conteúdo infantil moderno/genérico.
ENTRIES = [
    # Roku • Animações — somente conteúdo antigo/clássico
    {
        "id": "roku-pantera-cor-de-rosa",
        "name": "Pantera Cor-de-Rosa",
        "logo": "https://imgur.com/3wizSOk.png",
        "group": "Roku • Animações",
        "url": "https://jmp2.uk/rok-65f83bbbf7a2eb952b798c96300bb329.m3u8",
        "source": "Roku FAST",
    },
    {
        "id": "roku-retrocrush",
        "name": "RetroCrush",
        "logo": "https://tvpnlogopus.samsungcloud.tv/platform/image/sourcelogo/vc/00/02/34/CABC2300012FY_20250318T021309SQUARE.png",
        "group": "Roku • Animações",
        "url": "https://jmp2.uk/rok-72a54a3c7a3d5381a1baa223a5dc8d23.m3u8",
        "source": "Roku FAST",
    },

    # Roku • Filmes — preferência por catálogo clássico/nostálgico
    {
        "id": "e2e10d08139b56aba73a448f5555b6fd",
        "name": "FilmRise Classic TV",
        "logo": "",
        "group": "Roku • Filmes",
        "url": "https://jmp2.uk/rok-e2e10d08139b56aba73a448f5555b6fd.m3u8",
        "source": "Roku FAST",
    },
    {
        "id": "roku-western-bound-pt",
        "name": "Western Bound em Português",
        "logo": "",
        "group": "Roku • Filmes",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/f5db557dc5ea4552bb723690a52f5aee/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },

    # Roku • Séries — foco em séries antigas e nostalgia
    {
        "id": "8c36c765b4415db78a85078c37df4a5f",
        "name": "Lassie",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://jmp2.uk/rok-8c36c765b4415db78a85078c37df4a5f.m3u8",
        "source": "Roku FAST",
    },
    {
        "id": "dcecb48012b5c99824cb0b1667f4499c",
        "name": "Highway To Heaven",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://jmp2.uk/rok-dcecb48012b5c99824cb0b1667f4499c.m3u8",
        "source": "Roku FAST",
    },
    {
        "id": "roku-mr-bean",
        "name": "Mr. Bean",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://amg00627-banijay-amg00627c35-tcl-us-4282.playouts.now.amagi.tv/playlist/amg00627-banijayfast-mrbeanbr-tclus/playlist.m3u8",
        "source": "Roku FAST via TCL/Amagi",
    },
    {
        "id": "roku-andromeda",
        "name": "Andromeda",
        "logo": "https://d3bd0tgyk368z1.cloudfront.net/feeds/images/andromeda/Andromeda_LGChannel_ChannelLogo_400x200.png",
        "group": "Roku • Séries",
        "url": "https://dotjw4onyd4re.cloudfront.net/v1/master/3fec3e5cac39a52b2132f9c66c83dae043dc17d4/prod-tcl/master.m3u8?ads.xumo_channelId=88884607",
        "source": "Roku FAST via TCL",
    },
    {
        "id": "roku-malhacao-fast",
        "name": "Malhação Fast",
        "logo": "",
        "group": "Roku • Séries",
        "url": "https://ssai2-ads.api.leiniao.com/global-adinsertion-api/hls/live/v2/f46d6f4717bc41758662e8c6700c1d68/playlist.m3u8",
        "source": "Roku FAST via TCL/Leiniao",
    },

    # Roku • Variedades — exceção pedida explicitamente: novelas
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
    print(f"Roku FAST: {len(ENTRIES)} canais nostálgicos aplicados em {PLAYLIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
