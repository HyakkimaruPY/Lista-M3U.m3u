#!/usr/bin/env python3
"""Publica uma saída CGTN Español orientada ao decoder legado Philco.

O erro observado fisicamente na TV acontece depois do manifesto e do primeiro
segmento MPEG-TS terem sido baixados com sucesso. Portanto, apenas validar que o
upstream web é H.264 + AAC não basta: o stream web atual é 1920x1080 (~4 Mb/s)
e já demonstrou não ser aceito pelo decoder da TV.

Política:
  1. tentar primeiro endpoints diretos da CGTN Español;
  2. tentar rebroadcasts conhecidos CCTV/Yangshipin/China Mobile do mesmo canal;
  3. resolver masters HLS e descer para uma variante <= 720p antes do probe TS;
  4. aceitar somente MPEG-TS H.264 + AAC-LC estéreo e altura <= 720;
  5. usar o player web oficial só se ele próprio cair nesse perfil;
  6. nunca promover novamente o 1080p conhecido como incompatível.

A playlist pública continua estável em cgtn-runtime/cgtn-es.m3u8; somente o
upstream interno selecionado pelo workflow muda.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

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


def _attr_int(attrs: str, key: str) -> int:
    match = re.search(r"(?:^|,)" + re.escape(key) + r"=(\d+)", attrs, re.I)
    return int(match.group(1)) if match else 0


def _attr_resolution(attrs: str) -> tuple[int, int]:
    match = re.search(r"(?:^|,)RESOLUTION=(\d+)x(\d+)", attrs, re.I)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def master_variants(text: str, base_url: str) -> tuple[list[dict], list[str]]:
    """Extrai variantes de um master HLS e prioriza a melhor <=720p.

    Variantes declaradamente acima de 720p são descartadas antes de baixar
    segmentos. Variantes sem RESOLUTION permanecem como candidatas e só são
    aceitas depois do probe SPS real.
    """
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    variants: list[dict] = []
    skipped: list[str] = []
    for idx, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = line.split(":", 1)[1]
        width, height = _attr_resolution(attrs)
        bandwidth = _attr_int(attrs, "BANDWIDTH")
        uri = ""
        for nxt in lines[idx + 1 :]:
            if not nxt:
                continue
            if nxt.startswith("#"):
                continue
            uri = urljoin(base_url, nxt)
            break
        if not uri:
            continue
        item = {
            "url": uri,
            "declared_width": width,
            "declared_height": height,
            "declared_bandwidth": bandwidth,
        }
        if height and height > MAX_LEGACY_HEIGHT:
            skipped.append(f"skip master variant {width}x{height} bw={bandwidth}")
            continue
        variants.append(item)

    # Conhecidas <=720p: maior resolução primeiro; sem resolução: depois.
    variants.sort(
        key=lambda item: (
            1 if int(item.get("declared_height") or 0) > 0 else 0,
            int(item.get("declared_height") or 0),
            int(item.get("declared_bandwidth") or 0),
        ),
        reverse=True,
    )
    return variants, skipped


def probe_hls_candidate(url: str, headers: dict[str, str] | None, timeout: int) -> tuple[dict, list[str]]:
    """Sonda media playlist ou resolve master -> media playlist -> MPEG-TS."""
    text, final = web.fetch_manifest(url, headers, timeout)
    if "#EXT-X-STREAM-INF:" not in text:
        return tv.probe_media(final, headers, timeout), []

    variants, notes = master_variants(text, final)
    if not variants:
        detail = "; ".join(notes) if notes else "master has no usable variants"
        raise RuntimeError("master HLS has no <=720p candidate: " + detail)

    errors = list(notes)
    first_probe: dict | None = None
    for item in variants:
        variant_url = str(item["url"])
        try:
            probe = tv.probe_media(variant_url, headers, timeout)
            probe["master_url"] = final
            probe["master_declared_width"] = item.get("declared_width", 0)
            probe["master_declared_height"] = item.get("declared_height", 0)
            probe["master_declared_bandwidth"] = item.get("declared_bandwidth", 0)
            if first_probe is None:
                first_probe = probe
            if legacy_ready(probe):
                return probe, errors
            errors.append("variant outside legacy profile: " + describe_probe(probe))
        except Exception as exc:
            errors.append(f"variant {variant_url}: {exc}")

    if first_probe is not None:
        raise RuntimeError("master variants probed but none TV-safe: " + " | ".join(errors))
    raise RuntimeError("master variants unavailable: " + " | ".join(errors))


def resolve_direct_legacy(timeout: int) -> tuple[str, dict, dict, list[str]]:
    errors: list[str] = []
    for source, url, family in DIRECT_CANDIDATES:
        try:
            probe, probe_notes = probe_hls_candidate(url, {}, timeout)
            errors.extend(f"{source}: {note}" for note in probe_notes)
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
                "master_resolved": bool(probe.get("master_url")),
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
            probe, probe_notes = probe_hls_candidate(final, web.WEB_HEADERS, timeout)
            errors.extend(f"web attempt {attempt}: {note}" for note in probe_notes)
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
                "selected_host": (urlparse(str(probe.get("url") or final)).hostname or "").lower(),
                "master_resolved": bool(probe.get("master_url")),
            }
            return str(probe.get("url") or final), probe, meta, errors
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
