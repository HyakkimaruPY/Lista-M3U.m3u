#!/usr/bin/env python3
"""Valida streams de uma playlist M3U usando ffprobe + ffmpeg.

O validador foi desenhado para auto-remocao conservadora e pode restringir a verificacao por host:
- remove URLs malformadas;
- remove 404/410 confirmados em todas as tentativas;
- remove streams que abrem, mas repetidamente nao possuem video e audio;
- mantem erros ambiguos (403/451, timeout, rate limit, bloqueio regional etc.)
  para evitar apagar canais validos por causa da localizacao do runner do GitHub.

Nenhuma URL completa e escrita nos relatorios/logs para evitar republicar tokens.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit


@dataclass
class Entry:
    number: int
    start: int
    end: int
    line: int
    title: str
    url: str | None
    metadata: str = ""
    user_agent: str | None = None
    referer: str | None = None


@dataclass
class Result:
    entry: Entry
    status: str  # healthy | remove | uncertain | skipped
    reason: str
    host: str
    seconds: float


DEFINITE_HTTP_ERRORS = (
    "404 not found",
    "server returned 404",
    "http error 404",
    "410 gone",
    "server returned 410",
    "http error 410",
)

AMBIGUOUS_MARKERS = (
    "401 unauthorized",
    "403 forbidden",
    "429 too many requests",
    "451 unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "network is unreachable",
    "temporary failure",
    "name or service not known",
    "could not resolve",
    "i/o error",
)


def normalize_ocr_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def is_pluto_unavailable_slate(ocr_text: str) -> bool:
    """Reconhece a tela que ainda possui A/V, mas nao entrega o canal pedido."""
    text = normalize_ocr_text(ocr_text)
    words = set(text.split())
    if "pluto" not in words:
        return False
    if "wrap" in words:
        return True
    if {"longer", "available"}.issubset(words) and ("device" in words or "tv" in words):
        return True
    if {"nao", "mais", "disponivel"}.issubset(words):
        return True
    if {"ya", "no", "disponible"}.issubset(words):
        return True
    return False


def extract_title(extinf: str, fallback: str) -> str:
    if "," in extinf:
        title = extinf.split(",", 1)[1].strip()
        if title:
            return title
    match = re.search(r'tvg-name="([^"]+)"', extinf, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return fallback


def parse_playlist(lines: list[str]) -> list[Entry]:
    entries: list[Entry] = []
    i = 0
    number = 0

    while i < len(lines):
        if not lines[i].lstrip().upper().startswith("#EXTINF"):
            i += 1
            continue

        number += 1
        start = i
        next_entry = i + 1
        while next_entry < len(lines) and not lines[next_entry].lstrip().upper().startswith("#EXTINF"):
            next_entry += 1

        user_agent = None
        referer = None
        url = None
        url_index = None

        for j in range(i + 1, next_entry):
            stripped = lines[j].strip()
            lower = stripped.lower()
            if lower.startswith("#extvlcopt:http-user-agent="):
                user_agent = stripped.split("=", 1)[1].strip() or None
            elif lower.startswith("#extvlcopt:http-referrer=") or lower.startswith("#extvlcopt:http-referer="):
                referer = stripped.split("=", 1)[1].strip() or None
            elif stripped and not stripped.startswith("#"):
                url = stripped
                url_index = j
                break

        end = url_index if url_index is not None else max(start, next_entry - 1)
        title = extract_title(lines[start], f"entrada-{number}")
        entries.append(
            Entry(
                number=number,
                start=start,
                end=end,
                line=start + 1,
                title=title,
                url=url,
                metadata=lines[start],
                user_agent=user_agent,
                referer=referer,
            )
        )
        i = max(start + 1, next_entry)

    return entries


def probe_url_and_headers(entry: Entry) -> tuple[str | None, str | None, str | None]:
    """Suporta tambem o formato IPTV URL|User-Agent=...&Referer=..."""
    if not entry.url:
        return None, entry.user_agent, entry.referer

    url = entry.url
    user_agent = entry.user_agent
    referer = entry.referer

    if "|" in url:
        base, suffix = url.split("|", 1)
        lowered = suffix.lower()
        if "user-agent=" in lowered or "referer=" in lowered or "referrer=" in lowered:
            url = base
            for key, value in parse_qsl(suffix, keep_blank_values=True):
                k = key.lower()
                if k == "user-agent" and value:
                    user_agent = value
                elif k in {"referer", "referrer"} and value:
                    referer = value

    return url, user_agent, referer


def host_of(url: str | None) -> str:
    if not url:
        return "-"
    try:
        return urlsplit(url).hostname or "-"
    except ValueError:
        return "-"


def valid_network_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def command_prefix(url: str, user_agent: str | None, referer: str | None) -> list[str]:
    args = [
        "-rw_timeout",
        "15000000",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "2",
    ]
    if user_agent:
        args.extend(["-user_agent", user_agent])
    if referer:
        args.extend(["-headers", f"Referer: {referer}\r\n"])
    return args


def run_command(cmd: list[str], timeout: int) -> tuple[int, str, bool]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        combined = (proc.stderr or "") + "\n" + (proc.stdout or "")
        return proc.returncode, combined, False
    except subprocess.TimeoutExpired:
        return 124, "timeout", True


def is_definite_dead(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(marker in lowered for marker in DEFINITE_HTTP_ERRORS)


def classify_error(error_text: str, timed_out: bool) -> str:
    lowered = error_text.lower()
    if timed_out:
        return "timeout do runner"
    if is_definite_dead(error_text):
        if "410" in lowered:
            return "HTTP 410 confirmado"
        return "HTTP 404 confirmado"
    if any(marker in lowered for marker in AMBIGUOUS_MARKERS):
        return "erro de rede/autorizacao possivelmente regional ou temporario"
    return "falha de leitura nao conclusiva"


def ffprobe_once(entry: Entry, timeout: int) -> tuple[str, str]:
    url, user_agent, referer = probe_url_and_headers(entry)
    if not valid_network_url(url):
        return "definite", "URL ausente ou malformada"

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-hide_banner",
        *command_prefix(url, user_agent, referer),
        "-analyzeduration",
        "8000000",
        "-probesize",
        "8000000",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        url,
    ]
    rc, output, timed_out = run_command(cmd, timeout)
    if rc != 0:
        if is_definite_dead(output):
            return "definite", classify_error(output, timed_out)
        return "uncertain", classify_error(output, timed_out)

    try:
        json_start = output.find("{")
        if json_start < 0:
            raise json.JSONDecodeError("JSON ausente", output, 0)
        payload = json.loads(output[json_start:])
    except json.JSONDecodeError:
        return "uncertain", "ffprobe respondeu, mas o resultado nao pode ser interpretado"

    stream_types = {str(item.get("codec_type", "")).lower() for item in payload.get("streams", [])}
    has_video = "video" in stream_types
    has_audio = "audio" in stream_types

    if not has_video and not has_audio:
        return "missing", "stream sem video e sem audio detectaveis"
    if not has_video:
        return "missing", "stream sem video detectavel"
    if not has_audio:
        return "missing", "stream sem audio detectavel"

    return "av", "video e audio encontrados"


def decode_once(entry: Entry, timeout: int, decode_seconds: int) -> tuple[str, str]:
    url, user_agent, referer = probe_url_and_headers(entry)
    assert url is not None

    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        *command_prefix(url, user_agent, referer),
        "-i",
        url,
        "-t",
        str(decode_seconds),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-f",
        "null",
        "-",
    ]
    rc, output, timed_out = run_command(cmd, timeout)
    if rc == 0:
        return "healthy", f"video e audio decodificados por {decode_seconds}s"
    if is_definite_dead(output):
        return "definite", classify_error(output, timed_out)
    return "uncertain", classify_error(output, timed_out)


def inspect_pluto_frames(entry: Entry, timeout: int, decode_seconds: int) -> tuple[str, str]:
    """Extrai amostras e usa OCR para rejeitar a tela de indisponibilidade da Pluto."""
    url, user_agent, referer = probe_url_and_headers(entry)
    assert url is not None

    with tempfile.TemporaryDirectory(prefix="iptv-pluto-") as temp_dir:
        frame_pattern = str(Path(temp_dir) / "frame-%02d.png")
        sample_seconds = max(6, decode_seconds)
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-hide_banner",
            *command_prefix(url, user_agent, referer),
            "-i",
            url,
            "-t",
            str(sample_seconds),
            "-an",
            "-vf",
            "fps=1/2,scale=960:-2:flags=fast_bilinear",
            "-frames:v",
            "3",
            frame_pattern,
        ]
        rc, output, timed_out = run_command(cmd, max(timeout, sample_seconds + 10))
        if rc != 0:
            if is_definite_dead(output):
                return "definite", classify_error(output, timed_out)
            return "uncertain", "nao foi possivel extrair quadros para a verificacao visual"

        frames = sorted(Path(temp_dir).glob("frame-*.png"))
        if not frames:
            return "uncertain", "nenhum quadro foi gerado para a verificacao visual"

        ocr_parts: list[str] = []
        for frame in frames:
            ocr_cmd = ["tesseract", str(frame), "stdout", "-l", "eng", "--psm", "11"]
            ocr_rc, ocr_output, _ = run_command(ocr_cmd, 15)
            if ocr_rc == 0:
                ocr_parts.append(ocr_output)

        if not ocr_parts:
            return "uncertain", "OCR nao conseguiu analisar os quadros do stream"

        combined = "\n".join(ocr_parts)
        if is_pluto_unavailable_slate(combined):
            return "unavailable", "tela de indisponibilidade da Pluto detectada por OCR"
        return "clear", "conteudo visual sem tela de indisponibilidade conhecida"


def validate_entry(
    entry: Entry,
    retries: int,
    timeout: int,
    decode_seconds: int,
    detect_pluto_slate: bool,
) -> Result:
    started = time.monotonic()
    url, _, _ = probe_url_and_headers(entry)
    host = host_of(url)

    attempt_kinds: list[str] = []
    attempt_reasons: list[str] = []

    for attempt in range(retries):
        kind, reason = ffprobe_once(entry, timeout)
        attempt_kinds.append(kind)
        attempt_reasons.append(reason)

        if kind == "av":
            decode_kind, decode_reason = decode_once(entry, timeout, decode_seconds)
            if decode_kind == "healthy":
                if not detect_pluto_slate:
                    return Result(entry, "healthy", decode_reason, host, time.monotonic() - started)
                content_kind, content_reason = inspect_pluto_frames(entry, timeout, decode_seconds)
                if content_kind == "clear":
                    return Result(
                        entry,
                        "healthy",
                        f"{decode_reason}; {content_reason}",
                        host,
                        time.monotonic() - started,
                    )
                attempt_kinds[-1] = "definite" if content_kind in {"unavailable", "definite"} else "uncertain"
                attempt_reasons[-1] = content_reason
                if attempt + 1 < retries:
                    time.sleep(1.0)
                continue
            attempt_kinds[-1] = decode_kind
            attempt_reasons[-1] = decode_reason

        if attempt + 1 < retries:
            time.sleep(1.0)

    if attempt_kinds and all(kind in {"definite", "missing"} for kind in attempt_kinds):
        # Para erro HTTP definitivo, exigimos repeticao. Para ausencia de A/V,
        # tambem exigimos que todas as tentativas tenham sido conclusivas.
        reason = attempt_reasons[-1]
        return Result(entry, "remove", reason, host, time.monotonic() - started)

    reason = attempt_reasons[-1] if attempt_reasons else "falha nao conclusiva"
    return Result(entry, "uncertain", reason, host, time.monotonic() - started)


def remove_ranges(lines: list[str], results: Iterable[Result]) -> list[str]:
    remove_mask = [False] * len(lines)
    for result in results:
        if result.status != "remove":
            continue
        for idx in range(result.entry.start, min(result.entry.end + 1, len(lines))):
            remove_mask[idx] = True
    return [line for idx, line in enumerate(lines) if not remove_mask[idx]]


def write_reports(report_dir: Path, playlist: Path, results: list[Result], apply: bool, total_entries: int) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    counts = {"healthy": 0, "remove": 0, "uncertain": 0, "skipped": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    data = {
        "playlist": str(playlist),
        "mode": "apply" if apply else "dry-run",
        "entries_total": total_entries,
        "entries_tested": len([r for r in results if r.status != "skipped"]),
        "counts": counts,
        "results": [
            {
                "line": r.entry.line,
                "name": r.entry.title,
                "host": r.host,
                "status": r.status,
                "reason": r.reason,
                "seconds": round(r.seconds, 2),
            }
            for r in results
        ],
    }
    (report_dir / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Validacao de streams IPTV",
        "",
        f"- Playlist: `{playlist}`",
        f"- Modo: **{'aplicar remocoes' if apply else 'somente teste'}**",
        f"- Entradas na lista: **{total_entries}**",
        f"- Testadas: **{data['entries_tested']}**",
        f"- Saudaveis: **{counts['healthy']}**",
        f"- Marcadas para remocao: **{counts['remove']}**",
        f"- Inconclusivas/mantidas: **{counts['uncertain']}**",
        f"- Nao testadas por limite: **{counts['skipped']}**",
        "",
        "## Problemas",
        "",
    ]

    problems = [r for r in results if r.status in {"remove", "uncertain"}]
    if not problems:
        lines.append("Nenhum problema encontrado nas entradas testadas.")
    else:
        lines.append("| Linha | Canal | Host | Resultado | Motivo |")
        lines.append("|---:|---|---|---|---|")
        for r in problems:
            title = r.entry.title.replace("|", "\\|")
            reason = r.reason.replace("|", "\\|")
            lines.append(f"| {r.entry.line} | {title} | `{r.host}` | {r.status} | {reason} |")

    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_github_outputs(changed: bool, removed: int, uncertain: int, healthy: int) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if changed else 'false'}\n")
        handle.write(f"removed={removed}\n")
        handle.write(f"uncertain={uncertain}\n")
        handle.write(f"healthy={healthy}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida video e audio de streams M3U")
    parser.add_argument("--playlist", default="srhell02iptv.m3u")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--decode-seconds", type=int, default=4)
    parser.add_argument(
        "--detect-pluto-slate",
        action="store_true",
        help="Usa OCR para detectar a tela 'Pluto TV is no longer available'",
    )
    parser.add_argument("--limit", type=int, default=0, help="0 = todas as entradas")
    parser.add_argument("--report-dir", default="reports/stream-validation")
    parser.add_argument(
        "--include-host",
        action="append",
        default=[],
        help="Testa somente hosts informados; pode ser repetido",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    required_binaries = ["ffprobe", "ffmpeg"]
    if args.detect_pluto_slate:
        required_binaries.append("tesseract")
    for binary in required_binaries:
        if not shutil.which(binary):
            print(f"ERRO: {binary} nao encontrado no PATH", file=sys.stderr)
            return 2

    playlist = Path(args.playlist)
    if not playlist.exists():
        print(f"ERRO: playlist nao encontrada: {playlist}", file=sys.stderr)
        return 2

    raw = playlist.read_text(encoding="utf-8-sig")
    trailing_newline = raw.endswith("\n")
    lines = raw.splitlines()
    entries = parse_playlist(lines)
    if not entries:
        print("ERRO: nenhuma entrada #EXTINF encontrada", file=sys.stderr)
        return 2

    allowed_hosts = {item.strip().lower() for item in args.include_host if item.strip()}
    eligible: list[Entry] = []
    filtered_out: list[Entry] = []
    for entry in entries:
        url, _, _ = probe_url_and_headers(entry)
        host = host_of(url).lower()
        matches = not allowed_hosts or any(
            host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts
        )
        (eligible if matches else filtered_out).append(entry)

    selected = eligible if args.limit <= 0 else eligible[: args.limit]
    limited_out = eligible[len(selected) :]

    print(
        f"Validando {len(selected)} de {len(eligible)} entradas elegiveis "
        f"({len(entries)} totais) em {playlist}..."
    )
    results: list[Result] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(
                validate_entry,
                entry,
                max(1, args.retries),
                args.timeout,
                args.decode_seconds,
                args.detect_pluto_slate,
            ): entry
            for entry in selected
        }
        for future in concurrent.futures.as_completed(future_map):
            result = future.result()
            results.append(result)
            print(f"[{result.status.upper():9}] linha {result.entry.line}: {result.entry.title} ({result.host}) - {result.reason}")

    for entry in filtered_out:
        results.append(Result(entry, "skipped", "fora do filtro seguro desta playlist", host_of(entry.url), 0.0))
    for entry in limited_out:
        results.append(Result(entry, "skipped", "nao testado por limite desta execucao", host_of(entry.url), 0.0))

    results.sort(key=lambda r: r.entry.number)
    removable = [r for r in results if r.status == "remove"]
    uncertain = [r for r in results if r.status == "uncertain"]
    healthy = [r for r in results if r.status == "healthy"]

    changed = False
    if args.apply and removable:
        new_lines = remove_ranges(lines, removable)
        new_text = "\n".join(new_lines)
        if trailing_newline:
            new_text += "\n"
        if new_text != raw:
            playlist.write_text(new_text, encoding="utf-8")
            changed = True

    write_reports(Path(args.report_dir), playlist, results, args.apply, len(entries))
    set_github_outputs(changed, len(removable), len(uncertain), len(healthy))

    print(
        f"Resumo: saudaveis={len(healthy)}, remover={len(removable)}, "
        f"inconclusivos={len(uncertain)}, alterado={'sim' if changed else 'nao'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
