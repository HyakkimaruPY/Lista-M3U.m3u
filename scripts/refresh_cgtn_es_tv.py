#!/usr/bin/env python3
"""Publica um bridge CGTN Español orientado ao player legado Philco.

O player web oficial da CGTN continua sendo a fonte primaria de descoberta. O
stream real e sondado antes da publicacao. Se vier acima de 720p, tentamos as
representacoes oficiais Yangshipin/CCTV `hd` e `sd` e escolhemos a primeira
H.264/AAC de ate 720p. O master publicado inclui metadados explicitos para o
AUTOHLS nao enxergar a variante como 0x0/fps=0/audio vazio.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import refresh_cgtn_es as ysp
import refresh_cgtn_es_web as web

MAX_HEIGHT = 720
MAX_FPS = 60.5


def fetch_bytes(url: str, headers: dict[str, str] | None, timeout: int, limit: int = 8 * 1024 * 1024) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(limit + 1)
        final = resp.geturl()
    if len(data) > limit:
        raise RuntimeError(f"object larger than {limit} bytes")
    return data, final


def first_segment(text: str, base_url: str) -> tuple[str, float]:
    duration = 0.0
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            try:
                duration = float(line.split(":", 1)[1].split(",", 1)[0])
            except Exception:
                duration = 0.0
            continue
        if line and not line.startswith("#"):
            return urljoin(base_url, line), duration
    return "", 0.0


def _rate(value: str) -> float:
    try:
        if "/" in value:
            a, b = value.split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(value)
    except Exception:
        return 0.0


def probe_media(url: str, headers: dict[str, str] | None, timeout: int) -> dict:
    text, final = web.fetch_manifest(url, headers, timeout)
    seg_url, seg_duration = first_segment(text, final)
    if not seg_url:
        raise RuntimeError("media playlist has no segment")
    seg, _ = fetch_bytes(seg_url, headers, timeout)
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is not available on runner")
    with tempfile.NamedTemporaryFile(prefix="cgtn-es-", suffix=".ts") as fh:
        fh.write(seg); fh.flush()
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", fh.name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(10, timeout), check=False,
        )
    if p.returncode:
        raise RuntimeError((p.stderr or b"ffprobe failed").decode("utf-8", "replace")[-400:])
    obj = json.loads(p.stdout.decode("utf-8", "replace"))
    video = next((s for s in obj.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in obj.get("streams", []) if s.get("codec_type") == "audio"), {})
    fps = _rate(str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0"))
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    vcodec = str(video.get("codec_name") or "")
    acodec = str(audio.get("codec_name") or "")
    bitrate = int((len(seg) * 8 / seg_duration) if seg_duration > 0 else 0)
    return {
        "url": final,
        "manifest_bytes": len(text.encode("utf-8")),
        "segment_bytes": len(seg),
        "segment_duration": seg_duration,
        "bitrate_estimate": bitrate,
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "video_codec": vcodec,
        "video_profile": str(video.get("profile") or ""),
        "video_level": int(video.get("level") or 0),
        "audio_codec": acodec,
        "audio_profile": str(audio.get("profile") or ""),
        "audio_rate": int(audio.get("sample_rate") or 0),
        "audio_channels": int(audio.get("channels") or 0),
    }


def compatible(p: dict) -> bool:
    return (
        p.get("video_codec") == "h264"
        and p.get("audio_codec") == "aac"
        and 0 < int(p.get("height") or 0) <= MAX_HEIGHT
        and float(p.get("fps") or 0) <= MAX_FPS
    )


def ysp_urls(defn: str, timeout: int) -> tuple[list[str], dict]:
    ticket = ysp.make_ckey(ysp.CHANNEL_ID)
    params = {
        "atime": "120", "livepid": ysp.LIVE_PID, "cnlid": ysp.CHANNEL_ID,
        "appVer": ysp.APP_VERSION, "app_version": "300090", "caplv": "1",
        "cmd": "2", "defn": defn, "device": "iPhone", "encryptVer": "4.2",
        "getpreviewinfo": "0", "hevclv": "0", "lang": "zh-Hans_CN",
        "livequeue": "0", "logintype": "1", "nettype": "1", "newnettype": "1",
        "newplatform": str(ysp.PLATFORM), "platform": str(ysp.PLATFORM), "sdtfrom": "v3021",
        "spacode": "23", "spaudio": "1", "spdemuxer": "6", "spdrm": "2",
        "spdynamicrange": "1", "spflv": "1", "spflvaudio": "1", "sphdrfps": "60",
        "sphttps": "1", "spvcode": ysp.H264_CAPABILITY, "spvideo": "4", "stream": "1",
        "system": "1", "sysver": "ios18.2.1", "uhd_flag": "0",
        "cKey": ticket["cKey"], "guid": ticket["guid"],
        "fntick": str(ticket["timestamp"]), "flowid": ticket["flowid"], "playbacktime": "0",
    }
    req = urllib.request.Request(
        ysp.API_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "qqlive", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    if int(payload.get("iretcode", -1)) != 0:
        raise RuntimeError(f"Yangshipin {defn} error {payload.get('iretcode')}: {payload.get('errinfo', '')}")
    raw = []
    if isinstance(payload.get("playurl"), str): raw.append(payload["playurl"])
    backups = payload.get("backurl_list") or payload.get("backurlList") or payload.get("backurl")
    if isinstance(backups, list):
        for item in backups:
            raw.append(item if isinstance(item, str) else str(item.get("url") or item.get("playurl") or ""))
    urls = []
    for value in raw:
        value = str(value).strip()
        if value and ysp.official_url(value) and value not in urls: urls.append(value)
    if not urls:
        raise RuntimeError(f"Yangshipin {defn} returned no accepted HLS URL")
    return urls, payload


def resolve_ysp_quality(defn: str, timeout: int) -> tuple[str, dict, dict]:
    urls, payload = ysp_urls(defn, timeout)
    media, base = ysp.resolve_media_url(urls, timeout)
    probe = probe_media(media, ysp.FETCH_HEADERS, timeout)
    return media, probe, {
        "source": f"yangshipin-{defn}",
        "candidate_count": len(urls),
        "no_special_headers": bool(base.get("no_special_headers")),
        "vkey_renew_interval": payload.get("vkey_renew_interval"),
    }


def codec_string(p: dict) -> str:
    # H.264 Main/High on this legacy path + AAC-LC.
    profile = str(p.get("video_profile") or "").lower()
    avc = "avc1.4d401f" if "main" in profile else "avc1.640028" if "high" in profile else "avc1.4d401f"
    return f'{avc},mp4a.40.2'


def write_master(path: Path, media_url: str, p: dict) -> None:
    bw = int(p.get("bitrate_estimate") or 0)
    if bw <= 0: bw = 3500000
    peak = max(int(bw * 1.30), bw + 500000)
    attrs = [f"BANDWIDTH={peak}", f"AVERAGE-BANDWIDTH={bw}"]
    w, h = int(p.get("width") or 0), int(p.get("height") or 0)
    if w and h: attrs.append(f"RESOLUTION={w}x{h}")
    fps = float(p.get("fps") or 0)
    if fps: attrs.append(f"FRAME-RATE={fps:.3f}")
    attrs.append(f'CODECS="{codec_string(p)}"')
    body = "\n".join(("#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS", "#EXT-X-STREAM-INF:" + ",".join(attrs), media_url, ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="cgtn-es.m3u8")
    ap.add_argument("--state", default="cgtn-es.json")
    ap.add_argument("--patch-playlists", action="store_true")
    ap.add_argument("--timeout", type=int, default=12)
    args = ap.parse_args()

    errors = []
    selected_url = ""
    selected_probe = {}
    meta = {}
    web_probe = {}

    try:
        web_url, web_meta = web.capture_web_player_url(max(30, args.timeout + 18))
        web_final, plain_ok, web_validation = web.validate_web_url(web_url, args.timeout)
        web_probe = probe_media(web_final, web.WEB_HEADERS, args.timeout)
        if compatible(web_probe):
            selected_url, selected_probe = web_final, web_probe
            meta = {**web_meta, **web_validation, "source": "cgtn-web-player", "no_special_headers": plain_ok, "fallback_used": False}
        else:
            errors.append(f"web stream not TV-safe: {web_probe.get('width')}x{web_probe.get('height')} {web_probe.get('fps')}fps {web_probe.get('video_codec')}/{web_probe.get('audio_codec')}")
    except Exception as exc:
        errors.append(f"web probe: {exc}")

    if not selected_url:
        for defn in ("hd", "sd"):
            try:
                media, probe, ymeta = resolve_ysp_quality(defn, args.timeout)
                if compatible(probe):
                    selected_url, selected_probe, meta = media, probe, {**ymeta, "fallback_used": True, "fallback_reason": errors[-1] if errors else "web stream incompatible"}
                    break
                errors.append(f"{defn} not TV-safe: {probe.get('width')}x{probe.get('height')} {probe.get('fps')}fps")
            except Exception as exc:
                errors.append(f"{defn}: {exc}")

    if not selected_url:
        # Last resort: keep the working web source rather than publish nothing.
        if web_probe.get("url"):
            selected_url, selected_probe = str(web_probe["url"]), web_probe
            meta = {"source": "cgtn-web-player-last-resort", "fallback_used": True, "fallback_reason": " | ".join(errors)}
        else:
            media, old_meta = web.resolve(args.timeout)
            selected_url = media
            selected_probe = probe_media(media, web.WEB_HEADERS if old_meta.get("source") == "cgtn-web-player" else ysp.FETCH_HEADERS, args.timeout)
            meta = {**old_meta, "fallback_reason": " | ".join(errors)}

    write_master(Path(args.output), selected_url, selected_probe)
    state = {
        "channel": "CGTN Español",
        "generated_at": int(time.time()),
        "tv_safe_target_height": MAX_HEIGHT,
        "selected": selected_probe,
        "web_probe": web_probe,
        "diagnostics": errors,
        **meta,
    }
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.patch_playlists:
        repo = os.environ.get("GITHUB_REPOSITORY", "HyakkimaruPY/Lista-M3U.m3u")
        stable = f"https://raw.githubusercontent.com/{repo}/cgtn-runtime/cgtn-es.m3u8"
        changed = []
        need_headers = not bool(meta.get("no_special_headers", True))
        for name in ("cn.m3u", "srhell02iptv.m3u"):
            if web.patch_playlist(Path(name), stable, need_headers): changed.append(name)
        print("playlist patch:", ", ".join(changed) if changed else "already current")

    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
