#!/usr/bin/env python3
"""Atualiza IDs Pluto quebrados usando grades regionais atuais e preservando jmp2.uk."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

from validate_streams import Entry, parse_playlist, probe_url_and_headers, validate_entry


DEFAULT_SOURCES = {
    "BR": "https://raw.githubusercontent.com/matthuisman/i.mjh.nz/refs/heads/master/PlutoTV/br.xml",
    "US": "https://raw.githubusercontent.com/matthuisman/i.mjh.nz/refs/heads/master/PlutoTV/us.xml",
}
PLUTO_ID_RE = re.compile(r"jmp2\.uk/plu-([0-9a-f]+)\.m3u8", re.IGNORECASE)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def attribute(metadata: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}="([^"]*)"', metadata, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def region_of(entry: Entry) -> str:
    group = attribute(entry.metadata, "group-title").upper()
    return "BR" if group.endswith(" BR") else "US"


def current_id(entry: Entry) -> str:
    _, _, _ = probe_url_and_headers(entry)
    match = PLUTO_ID_RE.search(entry.url or "")
    return match.group(1).lower() if match else ""


def fetch_channel_map(url: str, timeout: int) -> dict[str, list[tuple[str, str]]]:
    request = urllib.request.Request(url, headers={"User-Agent": "Lista-M3U-maintenance/1.0"})
    channels: dict[str, list[tuple[str, str]]] = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for _, element in ET.iterparse(response, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "channel":
                channel_id = element.attrib.get("id", "").strip().lower()
                display = next(
                    (
                        (child.text or "").strip()
                        for child in element
                        if child.tag.rsplit("}", 1)[-1] == "display-name" and (child.text or "").strip()
                    ),
                    "",
                )
                key = normalize(display)
                if channel_id and key:
                    channels.setdefault(key, []).append((channel_id, display))
                element.clear()
            elif tag == "programme":
                break
    return channels


def candidate_for(entry: Entry, channel_map: dict[str, list[tuple[str, str]]]) -> tuple[str, str] | None:
    names = [attribute(entry.metadata, "tvg-name"), entry.title]
    old_id = current_id(entry)
    for name in names:
        for channel_id, display in channel_map.get(normalize(name), []):
            if channel_id != old_id:
                return channel_id, display
    return None


def replace_entry(lines: list[str], entry: Entry, channel_id: str) -> None:
    metadata = lines[entry.start]
    logo = (
        f"https://images.pluto.tv/channels/{channel_id}/thumbnail.jpg"
        "?fill=blur&fit=fill&fm=jpg&h=2080&q=75&w=2080"
    )
    metadata = re.sub(r'tvg-id="[^"]*"', f'tvg-id="{channel_id}"', metadata, count=1, flags=re.I)
    if re.search(r'tvg-logo="[^"]*"', metadata, re.I):
        metadata = re.sub(r'tvg-logo="[^"]*"', f'tvg-logo="{logo}"', metadata, count=1, flags=re.I)
    lines[entry.start] = metadata
    lines[entry.end] = f"https://jmp2.uk/plu-{channel_id}.m3u8"


def write_reports(report_dir: Path, records: list[dict[str, object]], changed: bool) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {"changed": changed, "results": records}
    (report_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Atualizacao de IDs Pluto",
        "",
        f"- IDs substituidos: **{sum(item['status'] == 'updated' for item in records)}**",
        f"- Sem substituto confirmado: **{sum(item['status'] != 'updated' for item in records)}**",
        "",
    ]
    if records:
        lines.extend(["| Canal | Regiao | Resultado | Detalhe |", "|---|---|---|---|"])
        for item in records:
            lines.append(
                f"| {str(item['name']).replace('|', '\\|')} | {item['region']} | "
                f"{item['status']} | {str(item['detail']).replace('|', '\\|')} |"
            )
    else:
        lines.append("Nenhum canal Pluto foi marcado como definitivamente invalido.")
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Substitui IDs Pluto quebrados por IDs regionais atuais")
    parser.add_argument("--playlist", default="srhell02iptv.m3u")
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--report-dir", default="reports/stream-validation/principal-pluto/source-refresh")
    parser.add_argument("--source-br", default=DEFAULT_SOURCES["BR"])
    parser.add_argument("--source-us", default=DEFAULT_SOURCES["US"])
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    playlist = Path(args.playlist)
    raw = playlist.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    entries = parse_playlist(lines)
    by_line = {entry.line: entry for entry in entries}

    report = json.loads(Path(args.validation_report).read_text(encoding="utf-8"))
    if report.get("playlist_sha256") != hashlib.sha256(playlist.read_bytes()).hexdigest():
        raise SystemExit("Relatorio desatualizado: valide novamente esta playlist antes de aplicar reparos")
    failed_lines = {
        int(item["line"])
        for item in report.get("results", [])
        if item.get("status") == "remove" and item.get("host") == "jmp2.uk"
    }
    failed = [by_line[line] for line in sorted(failed_lines) if line in by_line]
    needed_regions = {region_of(entry) for entry in failed}

    source_urls = {"BR": args.source_br, "US": args.source_us}
    maps: dict[str, dict[str, list[tuple[str, str]]]] = {}
    source_errors: dict[str, str] = {}
    for region in sorted(needed_regions):
        try:
            maps[region] = fetch_channel_map(source_urls[region], args.timeout)
        except (OSError, ET.ParseError) as exc:
            source_errors[region] = type(exc).__name__

    records: list[dict[str, object]] = []
    replacements: list[tuple[Entry, str]] = []
    for entry in failed:
        region = region_of(entry)
        base = {"name": entry.title, "region": region}
        if region in source_errors:
            records.append({**base, "status": "source-error", "detail": "fonte regional indisponivel"})
            continue
        candidate = candidate_for(entry, maps.get(region, {}))
        if not candidate:
            records.append({**base, "status": "not-found", "detail": "nenhum ID diferente encontrado"})
            continue

        channel_id, display = candidate
        candidate_entry = replace(
            entry,
            title=display,
            url=f"https://jmp2.uk/plu-{channel_id}.m3u8",
        )
        result = validate_entry(candidate_entry, 2, args.timeout, 4, True)
        if result.status != "healthy":
            records.append(
                {**base, "status": "candidate-rejected", "detail": f"substituto nao passou: {result.reason}"}
            )
            continue

        replacements.append((entry, channel_id))
        records.append({**base, "status": "updated", "detail": "novo ID testado com audio, video e OCR"})

    changed = False
    if args.apply and replacements:
        for entry, channel_id in replacements:
            replace_entry(lines, entry, channel_id)
        new_text = "\n".join(lines) + ("\n" if raw.endswith("\n") else "")
        if new_text != raw:
            playlist.write_text(new_text, encoding="utf-8")
            changed = True

    write_reports(Path(args.report_dir), records, changed)
    print(f"Atualizacao Pluto: candidatos={len(failed)}, substituidos={len(replacements)}, alterado={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
