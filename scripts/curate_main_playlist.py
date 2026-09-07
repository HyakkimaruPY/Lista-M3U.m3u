#!/usr/bin/env python3
"""Curadoria idempotente da playlist principal por categorias-pai de conteúdo."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from validate_streams import parse_playlist, probe_url_and_headers
from sync_cn_to_main import attr, set_attr, cctv_key

PARENT_ORDER = ["Filmes", "Séries", "Animações", "Variedades", "Esportes", "Séries VOD"]

LANG_MARKERS = {
    "pt": "",
    "cn": " • [CN]",
    "es": " • [ES]",
    "en": " • [S]",
}
LANG_RANK = {"pt": 0, "cn": 1, "es": 2, "other": 2, "en": 3}

ROKU_PT = {
    "western bound em português",
    "western bound em portugues",
    "mr. bean",
    "malhação fast",
    "malhacao fast",
    "novelíssima",
    "novelissima",
}

SPANISH_TITLES = {
    "el reino infantil",
}

TITLE_DECORATION_RE = re.compile(
    r"^(?:(?P<platform>[RP])\s*•\s*)?(?P<name>.*?)(?:\s*•\s*\[(?P<lang>S|ES|CN)\])?$",
    re.IGNORECASE,
)


def base_title(title: str) -> str:
    match = TITLE_DECORATION_RE.match(title.strip())
    return (match.group("name") if match else title).strip()


def title_platform(title: str) -> str:
    match = TITLE_DECORATION_RE.match(title.strip())
    return (match.group("platform") or "").upper() if match else ""


def title_language(title: str) -> str:
    match = TITLE_DECORATION_RE.match(title.strip())
    marker = (match.group("lang") or "").upper() if match else ""
    return {"S": "en", "ES": "es", "CN": "cn"}.get(marker, "")


def platform_for(entry) -> str:
    titled = title_platform(entry.title)
    if titled:
        return titled
    group = attr(entry.metadata, "group-title").lower()
    source = attr(entry.metadata, "x-source").lower()
    url = entry.url or ""
    if group.startswith("roku •") or "roku fast" in source or "/rok-" in url:
        return "R"
    if group.startswith("pluto •") or "/plu-" in url:
        return "P"
    return ""


def language_for(entry) -> str:
    tagged = attr(entry.metadata, "x-lang").lower()
    if tagged:
        if tagged.startswith("pt"):
            return "pt"
        if tagged.startswith("zh") or tagged.startswith("cn"):
            return "cn"
        if tagged.startswith("es"):
            return "es"
        if tagged.startswith("en"):
            return "en"

    decorated = title_language(entry.title)
    if decorated:
        return decorated

    name = base_title(entry.title)
    folded = name.casefold()
    group = attr(entry.metadata, "group-title")
    group_folded = group.casefold()
    tvg_id = attr(entry.metadata, "tvg-id").casefold()

    # Espanhol precisa ser detectado antes dos marcadores genéricos de China/US.
    if (
        "em espanhol" in group_folded
        or "en español" in folded
        or "en espanol" in folded
        or folded in SPANISH_TITLES
        or folded == "telemundo"
    ):
        return "es"

    if group.endswith(" BR") or attr(entry.metadata, "x-region").upper() == "BR":
        return "pt"

    if group.startswith("China •") or tvg_id.endswith(".cn") or re.search(r"[\u3400-\u9fff]", name):
        return "cn"

    if platform_for(entry) == "R":
        return "pt" if folded in ROKU_PT else "en"

    if group.endswith(" S") or " US" in group:
        return "en"

    return "pt"


def language_attr(language: str) -> str:
    return {
        "pt": "pt-BR",
        "cn": "zh-CN",
        "es": "es",
        "en": "en",
    }.get(language, language or "und")


def display_title(entry, language: str) -> str:
    name = base_title(entry.title)
    platform = platform_for(entry)
    prefix = f"{platform} • " if platform else ""
    return f"{prefix}{name}{LANG_MARKERS.get(language, '')}"


def china_parent(entry) -> str:
    key = cctv_key(entry)
    if key == "cctv6":
        return "Filmes"
    if key == "cctv8":
        return "Séries"
    if key == "cctv14":
        return "Animações"
    if key in {"cctv5", "cctv5plus", "cctv16"}:
        return "Esportes"

    text = " ".join(
        [
            base_title(entry.title),
            attr(entry.metadata, "tvg-id"),
            attr(entry.metadata, "tvg-name"),
        ]
    ).casefold()
    if re.search(r"少儿|少兒|卡通|动漫|動畫|动画|child|cartoon|anime", text):
        return "Animações"
    if re.search(r"体育|體育|篮球|足球|sport|olympic", text):
        return "Esportes"
    if re.search(r"电影|電影|影院|cinema|movie|film", text):
        return "Filmes"
    if re.search(r"电视剧|電視劇|drama|series", text):
        return "Séries"
    return "Variedades"


def spanish_parent(name: str) -> str:
    text = name.casefold()
    if re.search(r"\bcine\b|pel[ií]cul|movie|m[aá]s adrenalina", text):
        return "Filmes"
    if re.search(r"novela|telenovela|\bcsi\b|familia del barrio", text):
        return "Séries"
    if re.search(r"nickelodeon|infantil|cartoon|anime", text):
        return "Animações"
    return "Variedades"


def parent_group(entry, china: bool = False) -> str:
    group = attr(entry.metadata, "group-title")
    folded = group.casefold()
    name = base_title(entry.title)

    if group == "Wild Cards temp 01" or folded.startswith("séries vod") or folded.startswith("series vod"):
        return "Séries VOD"

    if china or group.startswith("China •") or attr(entry.metadata, "tvg-id").casefold().endswith(".cn"):
        # CGTN Español é um canal internacional em espanhol, não em mandarim.
        if language_for(entry) == "es":
            return "Variedades"
        return china_parent(entry)

    if "desenho" in folded or "infantil" in folded or "anime" in folded or folded == "anime":
        return "Animações"

    if "cinema clássico" in folded or "cinema classico" in folded or "filme" in folded:
        return "Filmes"

    if "séries clássicas" in folded or "series classicas" in folded or folded == "séries" or folded == "series":
        return "Séries"

    if "ficção científica" in folded or "ficcao cientifica" in folded:
        return "Séries"

    if "comédia" in folded or "comedia" in folded:
        return "Séries"

    if "esporte" in folded:
        return "Esportes"

    if "faroeste" in folded or "western" in folded:
        return "Filmes" if "movie" in name.casefold() else "Séries"

    if "em espanhol" in folded:
        return spanish_parent(name)

    if folded in {"filmes", "filmes • ação", "filmes • clássicos"}:
        return "Filmes"
    if folded in {"anime", "animações", "animacoes"}:
        return "Animações"
    if folded in {"séries", "series"}:
        return "Séries"
    if folded in {"esportes", "sport", "sports"}:
        return "Esportes"

    # Reality, música, TV geral, casa/gastronomia, história/ciência,
    # investigação, entretenimento, notícias e demais grades generalistas.
    return "Variedades"


# Compatibilidade com os testes/imports existentes.
def group_for(entry, china=False):
    return parent_group(entry, china)


def pluto_region(entry, language: str) -> str:
    current = attr(entry.metadata, "x-region").upper()
    if current in {"BR", "US"}:
        return current
    group = attr(entry.metadata, "group-title")
    if group.endswith(" BR"):
        return "BR"
    # Os antigos grupos com " S" (inclusive "Em espanhol S") vieram da grade US.
    if group.endswith(" S"):
        return "US"
    return "BR" if language == "pt" else "US"


def curate(raw: str, china=False):
    lines = raw.lstrip("\ufeff").splitlines()
    lines = ["#" + x if x.startswith("EXTINF:") else x.rstrip() for x in lines]
    entries = parse_playlist(lines)
    if not entries:
        raise ValueError("Nenhuma entrada encontrada")

    header = next((x for x in lines if x.startswith("#EXTM3U")), "#EXTM3U")
    blocks = []
    seen = {}
    removed = 0

    for position, entry in enumerate(entries):
        if base_title(entry.title).casefold() in {
            "rede-gospel",
            "rede gospel",
            "renascer",
            "rede-renascer",
            "rede renascer",
        }:
            removed += 1
            continue

        identity = probe_url_and_headers(entry)
        directives = tuple(x for x in lines[entry.start + 1 : entry.end] if x.startswith("#"))
        identity = (*identity, directives)

        language = language_for(entry)
        group = parent_group(entry, china)
        final_title = display_title(entry, language)

        meta = set_attr(entry.metadata, "group-title", group)
        meta = set_attr(meta, "tvg-name", final_title)
        meta = set_attr(meta, "x-lang", language_attr(language))
        if platform_for(entry) == "P":
            meta = set_attr(meta, "x-region", pluto_region(entry, language))

        # Troca somente o título visível após a vírgula do EXTINF.
        comma = meta.rfind(",")
        if comma >= 0:
            meta = meta[: comma + 1] + final_title

        if identity in seen:
            previous = blocks[seen[identity]]["block"]
            for attr_name in ("tvg-id", "tvg-logo"):
                if not attr(previous[0], attr_name) and attr(meta, attr_name):
                    previous[0] = set_attr(previous[0], attr_name, attr(meta, attr_name))
            removed += 1
            continue

        block = [meta] + [x for x in lines[entry.start + 1 : entry.end + 1] if x.strip()]
        seen[identity] = len(blocks)
        blocks.append(
            {
                "group": group,
                "language": language,
                "position": position,
                "block": block,
            }
        )

    order_index = {name: index for index, name in enumerate(PARENT_ORDER)}
    blocks.sort(
        key=lambda item: (
            order_index.get(item["group"], len(PARENT_ORDER)),
            LANG_RANK.get(item["language"], LANG_RANK["other"]),
            item["position"],
        )
    )

    out = [
        header,
        "# Categorias-pai por conteúdo; a plataforma fica no nome (R = Roku, P = Pluto).",
        "# Ordem por idioma dentro de cada categoria: PT-BR, chinês, outros idiomas; inglês por último.",
        "# x-source preserva a origem do stream; x-lang e x-region sustentam a manutenção automática.",
        "",
    ]
    last_group = None
    for item in blocks:
        if last_group is not None and item["group"] != last_group and out[-1] != "":
            out.append("")
        out.extend(item["block"] + [""])
        last_group = item["group"]

    return "\n".join(out).rstrip() + "\n", removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist", action="append")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    different = False
    for name in args.playlist or ["srhell02iptv.m3u"]:
        path = Path(name)
        raw = path.read_text(encoding="utf-8-sig")
        updated, removed = curate(raw, False)
        different |= raw != updated
        if not args.check:
            path.write_text(updated, encoding="utf-8")
        print(f"{name}: removidas={removed}; alterada={raw != updated}")
    return int(args.check and different)


if __name__ == "__main__":
    raise SystemExit(main())
