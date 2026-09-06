#!/usr/bin/env python3
"""Valida todos os canais nao-Pluto da playlist principal sem altera-la."""

from __future__ import annotations

import argparse
import concurrent.futures
from pathlib import Path

from validate_streams import Result, host_of, parse_playlist, probe_url_and_headers, validate_entry, write_reports


def is_pluto(entry) -> bool:
    url, _, _ = probe_url_and_headers(entry)
    host = host_of(url).lower()
    return host == "jmp2.uk" or host.endswith(".jmp2.uk")


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida canais nao-Pluto da playlist principal")
    parser.add_argument("--playlist", default="srhell02iptv.m3u")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--decode-seconds", type=int, default=4)
    parser.add_argument("--report-dir", default="reports/stream-validation/principal-non-pluto")
    args = parser.parse_args()

    playlist = Path(args.playlist)
    raw = playlist.read_text(encoding="utf-8-sig")
    entries = parse_playlist(raw.splitlines())
    selected = [entry for entry in entries if not is_pluto(entry)]

    print(f"Validando {len(selected)} canais nao-Pluto de {len(entries)} entradas totais em {playlist}...")
    results: list[Result] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(
                validate_entry,
                entry,
                max(1, args.retries),
                args.timeout,
                args.decode_seconds,
                False,
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
    write_reports(Path(args.report_dir), playlist, results, False, len(entries))

    healthy = sum(r.status == "healthy" for r in results)
    removable = sum(r.status == "remove" for r in results)
    uncertain = sum(r.status == "uncertain" for r in results)
    print(f"Resumo nao-Pluto: saudaveis={healthy}, remover={removable}, inconclusivos={uncertain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
