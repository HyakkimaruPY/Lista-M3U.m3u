#!/usr/bin/env python3
"""Publica uma saída CGTN Español orientada ao decoder legado Philco.

O erro observado fisicamente na TV acontece depois do manifesto e do primeiro
segmento MPEG-TS terem sido baixados com sucesso. Portanto, apenas validar que o
upstream web é H.264 + AAC não basta: o stream web atual é 1920x1080 (~4 Mb/s)
e já demonstrou não ser aceito pelo decoder da TV.

Política:
  1. tentar primeiro endpoints diretos da CGTN Español;
  2. tentar rebroadcasts conhecidos CCTV/Yangshipin/China Mobile do mesmo canal;
  3. aceitar somente MPEG-TS H.264 + AAC-LC estéreo e altura <= 720;
  4. usar o player web oficial só se ele próprio cair nesse perfil;
  5. nunca promover novamente o 1080p conhecido como incompatível.

A playlist pública continua estável em cgtn-runtime/cgtn-es.m3u8; somente o
upstream interno selecionado pelo workflow muda.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import refresh_cgtn_es_tv as tv
import refresh_cgtn_es_web as web

LEGACY_AUDIO_PROFILE = "LC"
LEGACY_AUDIO_RATE = 48000
LEGACY_AUDIO_CHANNELS = 2
MAX_LEGACY_HEIGHT = 720
MAX_LEGACY_FPS = 60.5

# source, url, family. Os mirrors abaixo são referências conhecidas do mesmo
# CGTN Español; nenhum é publicado sem o probe real H.264/AAC <=720p passar.
DIRECT_CANDIDATES = (
    ("cgtn-news-espanol-576p", "https://news.cgtn.com/resource/live/espanol/cgtn-e.m3u8", "cgtn-direct-tv-safe"),
    ("cgtn-legacy-1000e", "https://livees.cgtn.com/1000e/prog_index.m3u8", "cgtn-direct-tv-safe"),
    ("cgtn-legacy-500e", "https://livees.cgtn.com/500e/prog_index.m3u8", "cgtn-direct-tv-safe"),
    ("cgtn-carrier-ysp-ip", "http://121.51.249.103/tlivecloud-ipv6.ysp.cctv.cn/001/2010152503.m3u8", "cgtn-carrier-tv-safe"),
    ("cgtn-carrier-gz-mobile-6284", "http://cdnrrs.gz.chinamobile.com/PLTV/88888888/224/3221226284/1/index.m3u8?fmt=ts2hls", "cgtn-carrier-tv-safe"),
    ("cgtn-carrier-hz-mobile-1546", "http://117.148.179.176/PLTV/88888888/224/3221231546/index.m3u8", "cgtn-carrier-tv-safe"),
    ("cgtn-carrier-zte-shaanxi", "http://zteres.sn.chinamobile.com:6060/yinhe/2/ch00000090990000002716/index.m3u8?virtualDomain=yinhe.live_hls.zte.com", "cgtn-carrier-tv-safe"),
)

TRUSTED_CARRIER_HOSTS = {
    "121.51.249.103",
    "cdnrrs.gz.chinamobile.com",
    "117.148.179.176",
    "zteres.sn.chinamobile.com",
}


def legacy_audio_ready(probe: dict) -> bool:
    return (
        str(probe.get("audio_codec", "")).lower() == "aac"
        and str(probe.get("audio_profile", "")).upper() == LEGACY_AUDIO_PROFILE
        and int(probe.get("audio_rate") or 0) == LEGACY_AUDIO_RATE
        and int(probe.get("audio_channels") or 0) == LEGACY_AUDIO_CHANNELS
    )


def legacy_video_ready(probe: dict) -> bool:
    height = int(probe.get("height") or 0)
    fps = float(probe.get("fps") or 0)
    return (
        str(probe.get("video_codec", "")).lower() == "h264"
        and 0 < height <= MAX_LEGACY_HEIGHT
        and 0 < fps <= MAX_LEGACY_FPS
    )


def legacy_ready(probe: dict) -> bool:
    return legacy_video_ready(probe) and legacy_audio_ready(probe)


def cgtn_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host == "cgtn.com" or host.endswith(".cgtn.com")


def trusted_final_host(family: str, host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    if family == "cgtn-direct-tv-safe":
        return cgtn_host(host)
    if family == "cgtn-carrier-tv-safe":
        return host in TRUSTED_CARRIER_HOSTS or host.endswith(".chinamobile.com") or host.endswith(".cctv.cn")
    return False


def describe_probe(probe: dict) -> str:
    return (
        f"{probe.get('width')}x{probe.get('height')} "
        f"{probe.get('fps')}fps "
        f"video={probe.get('video_codec')}/{probe.get('video_profile')} "
        f"audio={probe.get('audio_codec')}/{probe.get('audio_profile')} "
        f"{probe.get('audio_rate')}Hz/{probe.get('audio_channels')}ch "
        f"bitrate={probe.get('bitrate_estimate')}"
    )


def resolve_direct_legacy(timeout: int) -> tuple[str, dict, dict, list[str]]:
    errors: list[str] = []
    for source, url, family in DIRECT_CANDIDATES:
        try:
            probe = tv.probe_media(url, {}, timeout)
            if not legacy_ready(probe):
                errors.append(f"{source}: outside legacy profile: {describe_probe(probe)}")
                continue
            final = str(probe.get("url") or url)
            host = (urlparse(final).hostname or "").lower()
            if not trusted_final_host(family, host):
                errors.append(f"{source}: unexpected redirect host {host or '<none>'}")
                continue
            meta = {
                "source": source,
                "source_family": family,
                "no_special_headers": True,
                "fallback_used": family != "cgtn-direct-tv-safe",
                "client_portable": True,
                "legacy_audio_ready": True,
                "legacy_video_ready": True,
                "audio_delivery": "aac-lc-48000-stereo",
                "video_delivery": "h264-max720p",
                "selected_host": host,
            }
            return final, probe, meta, errors
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    raise RuntimeError(" | ".join(errors) if errors else "no direct legacy candidates")


def resolve_web_safe(timeout: int, attempts: int = 3) -> tuple[str, dict, dict, list[str]]:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            signed, capture = web.capture_web_player_url(max(35, timeout + 23))
            final, plain_ok, validation = web.validate_web_url(signed, timeout)
            probe = tv.probe_media(final, web.WEB_HEADERS, timeout)
            if not legacy_ready(probe):
                raise RuntimeError("web representation outside legacy profile: " + describe_probe(probe))
            meta = {
                **capture,
                **validation,
                "source": "cgtn-web-player-legacy-safe",
                "source_family": "cgtn-web-player",
                "no_special_headers": bool(plain_ok),
                "fallback_used": True,
                "client_portable": True,
                "capture_attempt": attempt,
                "legacy_audio_ready": True,
                "legacy_video_ready": True,
                "audio_delivery": "aac-lc-48000-stereo",
                "video_delivery": "h264-max720p",
                "selected_host": (urlparse(final).hostname or "").lower(),
            }
            return final, probe, meta, errors
        except Exception as exc:
            errors.append(f"web attempt {attempt}: {exc}")
            if attempt < attempts:
                time.sleep(2)
    raise RuntimeError(" | ".join(errors))


def resolve_portable(timeout: int) -> tuple[str, dict, dict]:
    diagnostics: list[str] = []
    try:
        media, probe, meta, notes = resolve_direct_legacy(timeout)
        diagnostics.extend(notes)
        meta["diagnostics"] = diagnostics
        return media, probe, meta
    except Exception as exc:
        diagnostics.append("direct/carrier-tv-safe: " + str(exc))

    try:
        media, probe, meta, notes = resolve_web_safe(timeout)
        diagnostics.extend(notes)
        meta["diagnostics"] = diagnostics
        return media, probe, meta
    except Exception as exc:
        diagnostics.append("web-safe: " + str(exc))

    raise RuntimeError(
        "no CGTN Español representation satisfies the legacy decoder contract: "
        + " | ".join(diagnostics)
    )


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
        "delivery_policy": "legacy-tv-safe",
        "legacy_contract": {
            "video": "H.264",
            "max_height": MAX_LEGACY_HEIGHT,
            "max_fps": MAX_LEGACY_FPS,
            "audio_codec": "AAC",
            "audio_profile": LEGACY_AUDIO_PROFILE,
            "audio_rate": LEGACY_AUDIO_RATE,
            "audio_channels": LEGACY_AUDIO_CHANNELS,
        },
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
