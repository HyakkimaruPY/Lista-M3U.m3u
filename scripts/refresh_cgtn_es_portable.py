#!/usr/bin/env python3
"""Renova a fonte oficial do CGTN Español para o relay de áudio legado.

O vídeo físico mostrou que o H.264 1080p é renderizado pela TV; portanto o
workflow não deve rejeitar a fonte por resolução. O problema restante está no
caminho de áudio/mux. Esta etapa descobre e mede a fonte oficial, publica seu
estado e deixa a recodificação real para o relay persistente.

GitHub Actions não é um servidor HLS contínuo: reescrever CODECS/metadados não
altera os bytes AAC. O relay usa o `selected.url` publicado aqui, mantém vídeo
em copy e reencoda áudio para AAC-LC 48 kHz estéreo.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import refresh_cgtn_es_tv as tv
import refresh_cgtn_es_web as web


def resolve_source(timeout: int, attempts: int = 3) -> tuple[str, dict, dict]:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            signed, capture = web.capture_web_player_url(max(35, timeout + 23))
            final, plain_ok, validation = web.validate_web_url(signed, timeout)
            probe = tv.probe_media(final, web.WEB_HEADERS, timeout)
            if str(probe.get("video_codec", "")).lower() != "h264":
                raise RuntimeError(f"unexpected video codec: {probe.get('video_codec')}")
            if str(probe.get("audio_codec", "")).lower() != "aac":
                raise RuntimeError(f"unexpected audio codec: {probe.get('audio_codec')}")
            meta = {
                **capture,
                **validation,
                "source": "cgtn-web-player-relay-source",
                "source_family": "cgtn-web-player",
                "no_special_headers": bool(plain_ok),
                "client_portable": True,
                "capture_attempt": attempt,
                "relay_required": True,
                "relay_video_mode": "copy",
                "relay_audio_codec": "aac",
                "relay_audio_profile": "LC",
                "relay_audio_rate": 48000,
                "relay_audio_channels": 2,
                "relay_audio_bitrate": 128000,
                "diagnostics": errors,
            }
            return final, probe, meta
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < attempts:
                time.sleep(2)
    raise RuntimeError("official CGTN source unavailable: " + " | ".join(errors))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="cgtn-es.m3u8")
    ap.add_argument("--state", default="cgtn-es.json")
    ap.add_argument("--patch-playlists", action="store_true")
    ap.add_argument("--timeout", type=int, default=12)
    args = ap.parse_args()

    media_url, probe, meta = resolve_source(args.timeout)
    tv.write_master(Path(args.output), media_url, probe)

    relay_public = os.environ.get("CGTN_RELAY_PUBLIC_URL", "").strip()
    state = {
        "channel": "CGTN Español",
        "generated_at": int(time.time()),
        "delivery_policy": "relay-audio-normalization",
        "selected": probe,
        "relay_public_url": relay_public or None,
        **meta,
    }
    Path(args.state).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.patch_playlists:
        repo = os.environ.get("GITHUB_REPOSITORY", "HyakkimaruPY/Lista-M3U.m3u")
        discovery_url = f"https://raw.githubusercontent.com/{repo}/cgtn-runtime/cgtn-es.m3u8"
        target = relay_public or discovery_url
        need_headers = False if relay_public else not bool(meta.get("no_special_headers", True))
        changed = []
        for name in ("cn.m3u", "srhell02iptv.m3u"):
            if web.patch_playlist(Path(name), target, need_headers):
                changed.append(name)
        print("playlist target:", target)
        print("playlist patch:", ", ".join(changed) if changed else "already current")

    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
