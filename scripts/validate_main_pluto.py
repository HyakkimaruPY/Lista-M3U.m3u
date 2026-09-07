#!/usr/bin/env python3
"""Valida e, opcionalmente, remove somente canais Pluto da playlist principal."""

from __future__ import annotations

import argparse
import concurrent.futures
from pathlib import Path

from validate_main_non_pluto import is_pluto
from validate_streams import (
    Result,
    parse_playlist,
    remove_ranges,
    validate_entry,
    write_reports,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida somente canais Pluto da playlist principal")
    parser.add_argument("--playlist", default="srhell02iptv.m3u")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--decode-seconds", type=int, default=4)
    parser.add_argument("--report-dir", default="reports/stream-validation/principal-pluto")
    parser.add_argument("--apply", action="store_true", help="Remove apenas falhas Pluto definitivas confirmadas")
    args = parser.parse_args()

    playlist = Path(args.playlist)
    raw = playlist.read_text(encoding="utf-8-sig")
    trailing_newline = raw.endswith("\n")
    lines = raw.splitlines()
    entries = parse_playlist(lines)
    selected = [entry for entry in entries if is_pluto(entry)]

    print(f"Validando {len(selected)} canais Pluto de {len(entries)} entradas totais em {playlist}...")
    results: list[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(
                validate_entry,
                entry,
                max(1, args.retries),
                args.timeout,
                args.decode_seconds,
                True,
            ): entry
            for entry in selected
        }
        for future in concurrent.futures.as_completed(future_map):
            result = future.result()
            results.append(result)
            print(
                f"[{result.status.upper():9}] linha {result.entry.line}: "
                f"{result.entry.title} ({result.host}) - {result.reason}"
            )

    results.sort(key=lambda r: r.entry.number)
    removable = [r for r in results if r.status == "remove"]
    write_reports(Path(args.report_dir), playlist, results, args.apply, len(entries))

    if args.apply and removable:
        new_lines = remove_ranges(lines, removable)
        updated = "\n".join(new_lines)
        if trailing_newline:
            updated += "\n"
        if updated != raw:
            playlist.write_text(updated, encoding="utf-8")
            print(f"Aplicado: {len(removable)} canais Pluto definitivamente inválidos removidos.")

    healthy = sum(r.status == "healthy" for r in results)
    uncertain = sum(r.status == "uncertain" for r in results)
    print(f"Resumo Pluto: saudaveis={healthy}, remover={len(removable)}, inconclusivos={uncertain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
