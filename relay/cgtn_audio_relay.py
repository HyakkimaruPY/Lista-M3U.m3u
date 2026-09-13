#!/usr/bin/env python3
"""Relay leve do CGTN Español para o player Philco legado.

O GitHub Actions publica/renova o upstream assinado em cgtn-runtime/cgtn-es.json.
Este daemon acompanha esse estado e mantém um ffmpeg local com vídeo em copy e
somente o áudio reencodificado para AAC-LC 48 kHz estéreo. O resultado é HLS
MPEG-TS clássico, servido por um web server local (nginx recomendado).

Não há transcode de vídeo: a TV já demonstrou conseguir renderizar o H.264
1920x1080 do CGTN. O objetivo é normalizar AAC + mux/timestamps sem modificar o
player da TV.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

STATE_URL = os.environ.get(
    "CGTN_STATE_URL",
    "https://raw.githubusercontent.com/HyakkimaruPY/Lista-M3U.m3u/cgtn-runtime/cgtn-es.json",
)
OUTPUT_DIR = Path(os.environ.get("CGTN_OUTPUT_DIR", "/var/www/html/cgtn-es"))
POLL_SECONDS = max(15, int(os.environ.get("CGTN_POLL_SECONDS", "30")))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
AUDIO_BITRATE = os.environ.get("CGTN_AUDIO_BITRATE", "128k")
ALLOWED_SOURCE_HOSTS = {
    "espanol-livetx-h5.cgtn.com",
}

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
REFERER = "https://espanol.cgtn.com/en-directo"


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def fetch_state() -> dict:
    # Cache-buster é importante porque o arquivo runtime muda a cada renovação.
    sep = "&" if "?" in STATE_URL else "?"
    url = f"{STATE_URL}{sep}t={int(time.time())}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def source_from_state(state: dict) -> str:
    selected = state.get("selected") or {}
    url = str(selected.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("runtime state has no usable selected.url")
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_SOURCE_HOSTS:
        raise RuntimeError(f"refusing unexpected CGTN source host: {host or '<none>'}")
    return url


def clean_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.ts", "*.m3u8", "*.tmp"):
        for path in OUTPUT_DIR.glob(pattern):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def ffmpeg_command(source: str) -> list[str]:
    playlist = OUTPUT_DIR / "playlist.m3u8"
    segments = OUTPUT_DIR / "seg_%09d.ts"
    return [
        FFMPEG,
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        "-rw_timeout", "15000000",
        "-user_agent", UA,
        "-headers", f"Referer: {REFERER}\r\nAccept: application/vnd.apple.mpegurl,application/x-mpegURL,*/*\r\n",
        "-fflags", "+genpts+discardcorrupt",
        "-i", source,
        "-map", "0:v:0",
        "-map", "0:a:0",
        # Vídeo já é decodificado pela TV: não desperdiçar CPU alterando-o.
        "-c:v", "copy",
        # O áudio é realmente reencodificado, não apenas rotulado/validado.
        "-c:a", "aac",
        "-profile:a", "aac_low",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", AUDIO_BITRATE,
        "-af", "aresample=async=1:first_pts=0",
        # Reescreve cabeçalhos/timestamps TS de forma conservadora.
        "-mpegts_flags", "+resend_headers",
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-max_muxing_queue_size", "1024",
        "-f", "hls",
        "-hls_segment_type", "mpegts",
        "-hls_time", "2",
        "-hls_list_size", "8",
        "-hls_flags", "delete_segments+append_list+program_date_time+independent_segments+temp_file",
        "-hls_segment_filename", str(segments),
        str(playlist),
    ]


def stop_process(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def start_process(source: str) -> subprocess.Popen:
    clean_output()
    cmd = ffmpeg_command(source)
    log("starting ffmpeg audio-normalizing relay")
    return subprocess.Popen(cmd)


def main() -> int:
    proc: subprocess.Popen | None = None
    current_source = ""
    failures = 0

    def shutdown(_signum=None, _frame=None):
        log("stopping relay")
        stop_process(proc)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        try:
            state = fetch_state()
            source = source_from_state(state)
            process_dead = proc is None or proc.poll() is not None
            source_changed = source != current_source

            if process_dead or source_changed:
                if source_changed and current_source:
                    log("CGTN signed source changed; restarting relay")
                elif process_dead and proc is not None:
                    log(f"ffmpeg exited with code {proc.returncode}; restarting")
                stop_process(proc)
                proc = start_process(source)
                current_source = source

            failures = 0
        except Exception as exc:
            failures += 1
            log(f"state/relay refresh failed ({failures}): {exc}")
            # Mantém o ffmpeg atual se a renovação temporariamente falhar.

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
