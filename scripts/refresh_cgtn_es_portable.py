#!/usr/bin/env python3
"""Publica CGTN Español usando somente a fonte web portátil para clientes.

A fonte Yangshipin/CCTV pode ser útil para diagnóstico dentro do runner, mas
não é publicada no bridge porque URLs geradas no GitHub Actions podem responder
403 quando abertas pela TV. Este renovador usa o player web oficial da CGTN,
mede o MPEG-TS real e publica um master com RESOLUTION/FRAME-RATE/CODECS e
bitrate estimado, sem inventar parâmetros.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import refresh_cgtn_es_tv as tv
import refresh_cgtn_es_web as web


def resolve_portable(timeout: int, attempts: int = 3) -> tuple[str, dict, dict]:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            signed, capture = web.capture_web_player_url(max(35, timeout + 23))
            final, plain_ok, validation = web.validate_web_url(signed, timeout)
            probe = tv.probe_media(final, web.WEB_HEADERS, timeout)
            meta = {
                **capture,
                **validation,
                "source": "cgtn-web-player-portable",
                "no_special_headers": bool(plain_ok),
                "fallback_used": False,
                "client_portable": True,
                "capture_attempt": attempt,
            }
            return final, probe, meta
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < attempts:
                time.sleep(2)
    raise RuntimeError("official CGTN portable source unavailable: " + " | ".join(errors))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="cgtn-es.m3u8")
    ap.add_argument("--state", default="cgtn-es.json")
    ap.add_argument("--patch-playlists", action="store_true")
    ap.add_argument("--timeout", type=int, default=12)
    args = ap.parse_args()

    media_url, probe, meta = resolve_portable(args.timeout)
    tv.write_master(Path(args.output), media_url, probe)

    state = {
        "channel": "CGTN Español",
        "generated_at": int(time.time()),
        "delivery_policy": "portable-web-only",
        "selected": probe,
        **meta,
    }
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.patch_playlists:
        repo = os.environ.get("GITHUB_REPOSITORY", "HyakkimaruPY/Lista-M3U.m3u")
        stable = f"https://raw.githubusercontent.com/{repo}/cgtn-runtime/cgtn-es.m3u8"
        changed = []
        need_headers = not bool(meta.get("no_special_headers", True))
        for name in ("cn.m3u", "srhell02iptv.m3u"):
            if web.patch_playlist(Path(name), stable, need_headers):
                changed.append(name)
        print("playlist patch:", ", ".join(changed) if changed else "already current")

    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
