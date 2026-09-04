#!/usr/bin/env python3
"""Procura substitutos saudaveis para streams chineses confirmadamente invalidos.

Somente candidatos das fontes publicas declaradas abaixo sao considerados.
O canal e associado por tvg-id canonico ou, na ausencia dele, pelo nome normalizado.
Uma URL nova so e aplicada depois de passar por ffprobe e ffmpeg.
URLs completas nunca sao gravadas nos relatorios.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from validate_streams import Entry, host_of, parse_playlist, probe_url_and_headers, validate_entry


SOURCES = (
    ("BurningC4", "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u"),
    ("Free-TV", "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_china.m3u8"),
    ("IPTV-org", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u"),
)

TEMPORARY_QUERY_KEYS = {
    "token", "auth", "authid", "username", "password", "mac", "userid",
    "msisdn", "securitykey", "timestamp", "expires", "expire", "expiration",
    "signature", "sign",
}


@dataclass
class Candidate:
    entry: Entry
    source: str


def attribute(metadata: str, name: str) -> str:
    match = re.search(rf'\b{re.escape(name)}="([^"]*)"', metadata, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def canonical_identity(entry: Entry) -> str:
    tvg_id = attribute(entry.metadata, "tvg-id").lower()
    tvg_id = re.sub(r"\.cn(?:@.*)?$", "", tvg_id)
    tvg_id = re.sub(r"@.*$", "", tvg_id)
    tvg_id = re.sub(r"[^a-z0-9\u3400-\u9fff]", "", tvg_id)
    if tvg_id:
        return "id:" + tvg_id

    name = entry.title.lower()
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）", "", name)
    name = re.sub(r"\b(?:1080p|720p|576p|480p|sd|hd|uhd|4k)\b", "", name)
    name = re.sub(r"[^a-z0-9\u3400-\u9fff]", "", name)
    return "name:" + name


def safe_public_url(entry: Entry) -> bool:
    url, _, _ = probe_url_and_headers(entry)
    if not url or re.search(r"geo.?block", entry.metadata + " " + entry.title, re.IGNORECASE):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    return not bool(keys & TEMPORARY_QUERY_KEYS)


def fetch_source(url: str, retries: int = 2) -> str:
    error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Lista-M3U-source-refresh/1.0"},
            )
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.read().decode("utf-8-sig", errors="replace")
        except Exception as exc:
            error = exc
            if attempt + 1 < retries:
                time.sleep(2)
    raise RuntimeError(f"fonte indisponivel: {host_of(url)}: {type(error).__name__}")


def set_source(metadata: str, source: str) -> str:
    if re.search(r'\bx-source="[^"]*"', metadata, re.IGNORECASE):
        return re.sub(
            r'\bx-source="[^"]*"',
            f'x-source="{source}"',
            metadata,
            count=1,
            flags=re.IGNORECASE,
        )
    comma = metadata.find(",")
    if comma < 0:
        return metadata + f' x-source="{source}"'
    return metadata[:comma] + f' x-source="{source}"' + metadata[comma:]


def set_outputs(changed: bool, repaired: int, deduplicated: int, unresolved: int) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if changed else 'false'}\n")
        handle.write(f"repaired={repaired}\n")
        handle.write(f"deduplicated={deduplicated}\n")
        handle.write(f"unresolved={unresolved}\n")


def write_report(report_dir: Path, mode: str, records: list[dict[str, object]]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    repaired = sum(item["action"] == "replace" for item in records)
    deduplicated = sum(item["action"] == "remove_broken_duplicate" for item in records)
    unresolved = sum(item["action"] == "unresolved" for item in records)
    payload = {
        "mode": mode,
        "sources": [url for _, url in SOURCES],
        "repaired": repaired,
        "deduplicated": deduplicated,
        "unresolved": unresolved,
        "results": records,
    }
    (report_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Atualizacao de fontes chinesas",
        "",
        f"- Modo: **{mode}**",
        f"- URLs que podem ser substituidas: **{repaired}**",
        f"- Entradas quebradas com alternativa ja existente: **{deduplicated}**",
        f"- Sem alternativa saudavel confirmada: **{unresolved}**",
        "",
        "| Linha | Canal | Acao | Origem | Host novo |",
        "|---:|---|---|---|---|",
    ]
    for item in records:
        name = str(item["name"]).replace("|", "\\|")
        lines.append(
            f"| {item['line']} | {name} | {item['action']} | "
            f"{item.get('source', '-')} | \`{item.get('new_host', '-')}\` |"
        )
    if not records:
        lines.append("| - | Nenhum stream definitivamente invalido | - | - | - |")
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Atualiza URLs chinesas por fontes rastreaveis")
    parser.add_argument("--playlist", default="cn.m3u")
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--decode-seconds", type=int, default=4)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    playlist = Path(args.playlist)
    validation_path = Path(args.validation_report)
    raw = playlist.read_text(encoding="utf-8-sig")
    trailing_newline = raw.endswith("\n")
    lines = raw.splitlines()
    current_entries = parse_playlist(lines)
    by_line = {entry.line: entry for entry in current_entries}
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    broken_lines = {
        int(item["line"])
        for item in validation.get("results", [])
        if item.get("status") == "remove"
    }

    candidates: dict[str, list[Candidate]] = {}
    source_errors: list[str] = []
    for source, url in SOURCES:
        try:
            source_text = fetch_source(url)
        except RuntimeError as exc:
            source_errors.append(str(exc))
            continue
        for entry in parse_playlist(source_text.splitlines()):
            if not safe_public_url(entry):
                continue
            candidates.setdefault(canonical_identity(entry), []).append(Candidate(entry, source))

    used_urls = {
        (probe_url_and_headers(entry)[0] or "").rstrip("/")
        for entry in current_entries
        if probe_url_and_headers(entry)[0]
    }
    replacements: dict[int, tuple[str, str]] = {}
    drop_starts: set[int] = set()
    records: list[dict[str, object]] = []

    for line_number in sorted(broken_lines):
        current = by_line.get(line_number)
        if current is None:
            continue
        current_url, _, _ = probe_url_and_headers(current)
        current_norm = (current_url or "").rstrip("/")
        preferred_source = attribute(current.metadata, "x-source")
        pool = candidates.get(canonical_identity(current), [])
        pool = sorted(pool, key=lambda item: (item.source != preferred_source, item.source))
        resolved = False

        for candidate in pool[: max(1, args.max_candidates)]:
            url, user_agent, referer = probe_url_and_headers(candidate.entry)
            norm = (url or "").rstrip("/")
            if not url or norm == current_norm or user_agent or referer:
                continue

            probe_entry = Entry(
                number=current.number,
                start=current.start,
                end=current.end,
                line=current.line,
                title=current.title,
                url=url,
                metadata=candidate.entry.metadata,
            )
            result = validate_entry(
                probe_entry,
                max(1, args.retries),
                args.timeout,
                args.decode_seconds,
            )
            if result.status != "healthy":
                continue

            if norm in used_urls:
                drop_starts.add(current.start)
                action = "remove_broken_duplicate"
            else:
                replacements[current.start] = (url, candidate.source)
                used_urls.discard(current_norm)
                used_urls.add(norm)
                action = "replace"

            records.append({
                "line": current.line,
                "name": current.title,
                "action": action,
                "source": candidate.source,
                "old_host": host_of(current_url),
                "new_host": host_of(url),
            })
            resolved = True
            break

        if not resolved:
            records.append({
                "line": current.line,
                "name": current.title,
                "action": "unresolved",
                "source": preferred_source or "-",
                "old_host": host_of(current_url),
                "new_host": "-",
            })

    for start, (url, source) in replacements.items():
        entry = next(item for item in current_entries if item.start == start)
        lines[entry.end] = url
        lines[entry.start] = set_source(lines[entry.start], source)

    if drop_starts:
        mask = [False] * len(lines)
        for entry in current_entries:
            if entry.start in drop_starts:
                for index in range(entry.start, min(entry.end + 1, len(lines))):
                    mask[index] = True
        lines = [line for index, line in enumerate(lines) if not mask[index]]

    repaired = sum(item["action"] == "replace" for item in records)
    deduplicated = sum(item["action"] == "remove_broken_duplicate" for item in records)
    unresolved = sum(item["action"] == "unresolved" for item in records)
    would_change = bool(replacements or drop_starts)
    changed = False
    if args.apply and would_change:
        updated = "\n".join(lines)
        if trailing_newline:
            updated += "\n"
        if updated != raw:
            playlist.write_text(updated, encoding="utf-8")
            changed = True

    mode = "aplicar" if args.apply else "dry-run"
    write_report(Path(args.report_dir), mode, records)
    set_outputs(changed, repaired, deduplicated, unresolved)

    for error in source_errors:
        print(f"[SOURCE-UNCERTAIN] {error}")
    print(
        f"Fontes chinesas: reparaveis={repaired}, duplicatas={deduplicated}, "
        f"sem_alternativa={unresolved}, alterado={'sim' if changed else 'nao'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
