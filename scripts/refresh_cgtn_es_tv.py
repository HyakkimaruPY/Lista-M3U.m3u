#!/usr/bin/env python3
"""Publica um bridge CGTN Español orientado ao player legado Philco.

O player web oficial da CGTN continua sendo a fonte primaria de descoberta. O
stream real e sondado antes da publicacao. Se vier acima de 720p, tentamos as
representacoes oficiais Yangshipin/CCTV `hd` e `sd` e escolhemos a primeira
H.264/AAC de ate 720p. A sonda e Python puro: PAT/PMT + SPS H.264 + ADTS AAC.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

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


def iter_ts(data: bytes):
    for off in range(0, len(data) - 187, 188):
        packet = data[off : off + 188]
        if packet[0] != 0x47:
            continue
        b1, b2, b3 = packet[1], packet[2], packet[3]
        pusi = bool(b1 & 0x40)
        pid = ((b1 & 0x1F) << 8) | b2
        afc = (b3 >> 4) & 0x03
        pos = 4
        if afc in (2, 3):
            if pos >= 188:
                continue
            pos = 5 + packet[4]
        if afc in (1, 3) and pos < 188:
            yield pid, pusi, packet[pos:]


def ts_streams(data: bytes) -> dict[int, int]:
    pmt_pid = None
    for pid, pusi, payload in iter_ts(data):
        if pid != 0 or not pusi or not payload:
            continue
        ptr = payload[0]
        sec = payload[1 + ptr :]
        if len(sec) < 12 or sec[0] != 0x00:
            continue
        section_length = ((sec[1] & 0x0F) << 8) | sec[2]
        end = min(len(sec), 3 + section_length - 4)
        pos = 8
        while pos + 4 <= end:
            program = (sec[pos] << 8) | sec[pos + 1]
            candidate = ((sec[pos + 2] & 0x1F) << 8) | sec[pos + 3]
            if program:
                pmt_pid = candidate
                break
            pos += 4
        if pmt_pid is not None:
            break
    if pmt_pid is None:
        raise RuntimeError("MPEG-TS PAT has no PMT")

    streams: dict[int, int] = {}
    for pid, pusi, payload in iter_ts(data):
        if pid != pmt_pid or not pusi or not payload:
            continue
        ptr = payload[0]
        sec = payload[1 + ptr :]
        if len(sec) < 16 or sec[0] != 0x02:
            continue
        section_length = ((sec[1] & 0x0F) << 8) | sec[2]
        end = min(len(sec), 3 + section_length - 4)
        program_info_length = ((sec[10] & 0x0F) << 8) | sec[11]
        pos = 12 + program_info_length
        while pos + 5 <= end:
            stream_type = sec[pos]
            elementary_pid = ((sec[pos + 1] & 0x1F) << 8) | sec[pos + 2]
            es_info_length = ((sec[pos + 3] & 0x0F) << 8) | sec[pos + 4]
            streams[elementary_pid] = stream_type
            pos += 5 + es_info_length
        if streams:
            break
    if not streams:
        raise RuntimeError("MPEG-TS PMT has no elementary streams")
    return streams


def collect_es(data: bytes, target_pid: int, limit: int = 2 * 1024 * 1024) -> bytes:
    out = bytearray()
    started = False
    for pid, pusi, payload in iter_ts(data):
        if pid != target_pid:
            continue
        if pusi and payload.startswith(b"\x00\x00\x01") and len(payload) >= 9:
            header_len = payload[8]
            pos = 9 + header_len
            if pos < len(payload):
                out.extend(payload[pos:])
            started = True
        elif started:
            out.extend(payload)
        if len(out) >= limit:
            break
    return bytes(out)


def nal_units(es: bytes):
    starts: list[tuple[int, int]] = []
    i = 0
    while i + 3 < len(es):
        if es[i : i + 4] == b"\x00\x00\x00\x01":
            starts.append((i, 4)); i += 4
        elif es[i : i + 3] == b"\x00\x00\x01":
            starts.append((i, 3)); i += 3
        else:
            i += 1
    for idx, (pos, size) in enumerate(starts):
        begin = pos + size
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(es)
        if begin < end:
            yield es[begin:end]


def rbsp(raw: bytes) -> bytes:
    out = bytearray(); zeros = 0
    for value in raw:
        if zeros >= 2 and value == 0x03:
            zeros = 0
            continue
        out.append(value)
        zeros = zeros + 1 if value == 0 else 0
    return bytes(out)


class Bits:
    def __init__(self, data: bytes):
        self.data = data; self.pos = 0
    def bit(self) -> int:
        if self.pos >= len(self.data) * 8:
            raise ValueError("short SPS")
        value = (self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return value
    def bits(self, count: int) -> int:
        value = 0
        for _ in range(count): value = (value << 1) | self.bit()
        return value
    def ue(self) -> int:
        zeros = 0
        while self.bit() == 0:
            zeros += 1
            if zeros > 31: raise ValueError("invalid Exp-Golomb")
        return (1 << zeros) - 1 + (self.bits(zeros) if zeros else 0)
    def se(self) -> int:
        value = self.ue()
        return (value + 1) // 2 if value & 1 else -(value // 2)


def skip_scaling(br: Bits, size: int) -> None:
    last = 8; nxt = 8
    for _ in range(size):
        if nxt:
            nxt = (last + br.se() + 256) % 256
        last = last if nxt == 0 else nxt


def parse_sps(nal: bytes) -> dict:
    br = Bits(rbsp(nal[1:]))
    profile_idc = br.bits(8)
    constraints = br.bits(8)
    level_idc = br.bits(8)
    br.ue()
    chroma = 1
    if profile_idc in {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}:
        chroma = br.ue()
        if chroma == 3: br.bit()
        br.ue(); br.ue(); br.bit()
        if br.bit():
            for idx in range(8 if chroma != 3 else 12):
                if br.bit(): skip_scaling(br, 16 if idx < 6 else 64)
    br.ue()
    poc = br.ue()
    if poc == 0:
        br.ue()
    elif poc == 1:
        br.bit(); br.se(); br.se()
        for _ in range(br.ue()): br.se()
    br.ue(); br.bit()
    width_mbs = br.ue() + 1
    height_map = br.ue() + 1
    frame_mbs_only = br.bit()
    if not frame_mbs_only: br.bit()
    br.bit()
    crop_left = crop_right = crop_top = crop_bottom = 0
    if br.bit():
        crop_left, crop_right, crop_top, crop_bottom = br.ue(), br.ue(), br.ue(), br.ue()
    if chroma == 0: sub_x, sub_y = 1, 1
    elif chroma == 1: sub_x, sub_y = 2, 2
    elif chroma == 2: sub_x, sub_y = 2, 1
    else: sub_x, sub_y = 1, 1
    width = width_mbs * 16 - (crop_left + crop_right) * sub_x
    height = (2 - frame_mbs_only) * height_map * 16 - (crop_top + crop_bottom) * sub_y * (2 - frame_mbs_only)
    fps = 0.0
    if br.bit():
        if br.bit():
            aspect = br.bits(8)
            if aspect == 255: br.bits(16); br.bits(16)
        if br.bit(): br.bit()
        if br.bit():
            br.bits(3); br.bit()
            if br.bit(): br.bits(8); br.bits(8); br.bits(8)
        if br.bit(): br.ue(); br.ue()
        if br.bit():
            units = br.bits(32); scale = br.bits(32); br.bit()
            if units: fps = scale / (2.0 * units)
    names = {66: "Baseline", 77: "Main", 88: "Extended", 100: "High", 110: "High 10", 122: "High 4:2:2", 244: "High 4:4:4"}
    return {
        "width": width, "height": height,
        "fps": round(fps or 25.0, 3),
        "video_codec": "h264",
        "video_profile": names.get(profile_idc, str(profile_idc)),
        "video_profile_idc": profile_idc,
        "video_constraints": constraints,
        "video_level": level_idc,
    }


def parse_adts(es: bytes) -> dict:
    rates = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350]
    for pos in range(max(0, len(es) - 7)):
        if es[pos] == 0xFF and (es[pos + 1] & 0xF6) == 0xF0:
            aot = ((es[pos + 2] >> 6) & 0x03) + 1
            rate_idx = (es[pos + 2] >> 2) & 0x0F
            channels = ((es[pos + 2] & 0x01) << 2) | ((es[pos + 3] >> 6) & 0x03)
            return {
                "audio_codec": "aac",
                "audio_profile": "LC" if aot == 2 else f"AOT{aot}",
                "audio_rate": rates[rate_idx] if rate_idx < len(rates) else 0,
                "audio_channels": channels,
            }
    raise RuntimeError("AAC ADTS header not found")


def probe_ts(segment: bytes) -> dict:
    streams = ts_streams(segment)
    video_pid = next((pid for pid, st in streams.items() if st == 0x1B), None)
    audio_pid = next((pid for pid, st in streams.items() if st in (0x0F, 0x11)), None)
    if video_pid is None: raise RuntimeError(f"H.264 stream not found in PMT: {streams}")
    if audio_pid is None: raise RuntimeError(f"AAC stream not found in PMT: {streams}")
    video_es = collect_es(segment, video_pid)
    sps = next((nal for nal in nal_units(video_es) if nal and (nal[0] & 0x1F) == 7), None)
    if not sps: raise RuntimeError("H.264 SPS not found")
    info = parse_sps(sps)
    if streams[audio_pid] == 0x0F:
        info.update(parse_adts(collect_es(segment, audio_pid, 512 * 1024)))
    else:
        info.update({"audio_codec": "aac", "audio_profile": "LATM", "audio_rate": 0, "audio_channels": 0})
    info.update({"video_pid": video_pid, "audio_pid": audio_pid})
    return info


def probe_media(url: str, headers: dict[str, str] | None, timeout: int) -> dict:
    text, final = web.fetch_manifest(url, headers, timeout)
    seg_url, seg_duration = first_segment(text, final)
    if not seg_url: raise RuntimeError("media playlist has no segment")
    segment, _ = fetch_bytes(seg_url, headers, timeout)
    info = probe_ts(segment)
    bitrate = int((len(segment) * 8 / seg_duration) if seg_duration > 0 else 0)
    return {
        "url": final,
        "manifest_bytes": len(text.encode("utf-8")),
        "segment_bytes": len(segment),
        "segment_duration": seg_duration,
        "bitrate_estimate": bitrate,
        **info,
    }


def compatible(p: dict) -> bool:
    return p.get("video_codec") == "h264" and p.get("audio_codec") == "aac" and 0 < int(p.get("height") or 0) <= MAX_HEIGHT and float(p.get("fps") or 0) <= MAX_FPS


def ysp_urls(defn: str, timeout: int) -> tuple[list[str], dict]:
    ticket = ysp.make_ckey(ysp.CHANNEL_ID)
    params = {
        "atime": "120", "livepid": ysp.LIVE_PID, "cnlid": ysp.CHANNEL_ID,
        "appVer": ysp.APP_VERSION, "app_version": "300090", "caplv": "1",
        "cmd": "2", "defn": defn, "device": "iPhone", "encryptVer": "4.2",
        "getpreviewinfo": "0", "hevclv": "0", "lang": "zh-Hans_CN", "livequeue": "0",
        "logintype": "1", "nettype": "1", "newnettype": "1", "newplatform": str(ysp.PLATFORM),
        "platform": str(ysp.PLATFORM), "sdtfrom": "v3021", "spacode": "23", "spaudio": "1",
        "spdemuxer": "6", "spdrm": "2", "spdynamicrange": "1", "spflv": "1", "spflvaudio": "1",
        "sphdrfps": "60", "sphttps": "1", "spvcode": ysp.H264_CAPABILITY, "spvideo": "4", "stream": "1",
        "system": "1", "sysver": "ios18.2.1", "uhd_flag": "0", "cKey": ticket["cKey"],
        "guid": ticket["guid"], "fntick": str(ticket["timestamp"]), "flowid": ticket["flowid"], "playbacktime": "0",
    }
    req = urllib.request.Request(ysp.API_URL + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "qqlive", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response: payload = json.load(response)
    if int(payload.get("iretcode", -1)) != 0: raise RuntimeError(f"Yangshipin {defn} error {payload.get('iretcode')}: {payload.get('errinfo', '')}")
    raw = []
    if isinstance(payload.get("playurl"), str): raw.append(payload["playurl"])
    backups = payload.get("backurl_list") or payload.get("backurlList") or payload.get("backurl")
    if isinstance(backups, list):
        for item in backups: raw.append(item if isinstance(item, str) else str(item.get("url") or item.get("playurl") or ""))
    urls = []
    for value in raw:
        value = str(value).strip()
        if value and ysp.official_url(value) and value not in urls: urls.append(value)
    if not urls: raise RuntimeError(f"Yangshipin {defn} returned no accepted HLS URL")
    return urls, payload


def resolve_ysp_quality(defn: str, timeout: int) -> tuple[str, dict, dict]:
    urls, payload = ysp_urls(defn, timeout)
    media, base = ysp.resolve_media_url(urls, timeout)
    probe = probe_media(media, ysp.FETCH_HEADERS, timeout)
    return media, probe, {"source": f"yangshipin-{defn}", "candidate_count": len(urls), "no_special_headers": bool(base.get("no_special_headers")), "vkey_renew_interval": payload.get("vkey_renew_interval")}


def codec_string(p: dict) -> str:
    profile = int(p.get("video_profile_idc") or 77)
    constraints = int(p.get("video_constraints") or 0)
    level = int(p.get("video_level") or 31)
    return f"avc1.{profile:02x}{constraints:02x}{level:02x},mp4a.40.2"


def write_master(path: Path, media_url: str, p: dict) -> None:
    bw = int(p.get("bitrate_estimate") or 0) or 3500000
    peak = max(int(bw * 1.30), bw + 500000)
    attrs = [f"BANDWIDTH={peak}", f"AVERAGE-BANDWIDTH={bw}"]
    w, h = int(p.get("width") or 0), int(p.get("height") or 0)
    if w and h: attrs.append(f"RESOLUTION={w}x{h}")
    fps = float(p.get("fps") or 0)
    if fps: attrs.append(f"FRAME-RATE={fps:.3f}")
    attrs.append(f'CODECS="{codec_string(p)}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(("#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-STREAM-INF:" + ",".join(attrs), media_url, "")), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="cgtn-es.m3u8")
    ap.add_argument("--state", default="cgtn-es.json")
    ap.add_argument("--patch-playlists", action="store_true")
    ap.add_argument("--timeout", type=int, default=12)
    args = ap.parse_args()
    errors: list[str] = []; selected_url = ""; selected_probe: dict = {}; meta: dict = {}; web_probe: dict = {}

    try:
        web_url, web_meta = web.capture_web_player_url(max(30, args.timeout + 18))
        web_final, plain_ok, web_validation = web.validate_web_url(web_url, args.timeout)
        web_probe = probe_media(web_final, web.WEB_HEADERS, args.timeout)
        if compatible(web_probe):
            selected_url, selected_probe = web_final, web_probe
            meta = {**web_meta, **web_validation, "source": "cgtn-web-player", "no_special_headers": plain_ok, "fallback_used": False}
        else:
            errors.append(f"web stream not TV-safe: {web_probe.get('width')}x{web_probe.get('height')} {web_probe.get('fps')}fps {web_probe.get('video_profile')}")
    except Exception as exc:
        errors.append(f"web probe: {exc}")

    if not selected_url:
        for defn in ("hd", "sd"):
            try:
                media, probe, ymeta = resolve_ysp_quality(defn, args.timeout)
                if compatible(probe):
                    selected_url, selected_probe, meta = media, probe, {**ymeta, "fallback_used": True, "fallback_reason": errors[-1] if errors else "web stream incompatible"}
                    break
                errors.append(f"{defn} not TV-safe: {probe.get('width')}x{probe.get('height')} {probe.get('fps')}fps {probe.get('video_profile')}")
            except Exception as exc:
                errors.append(f"{defn}: {exc}")

    if not selected_url:
        if web_probe.get("url"):
            selected_url, selected_probe = str(web_probe["url"]), web_probe
            meta = {"source": "cgtn-web-player-last-resort", "fallback_used": True, "fallback_reason": " | ".join(errors)}
        else:
            raise RuntimeError("no usable CGTN Español source: " + " | ".join(errors))

    write_master(Path(args.output), selected_url, selected_probe)
    state = {"channel": "CGTN Español", "generated_at": int(time.time()), "tv_safe_target_height": MAX_HEIGHT, "selected": selected_probe, "web_probe": web_probe, "diagnostics": errors, **meta}
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.patch_playlists:
        repo = os.environ.get("GITHUB_REPOSITORY", "HyakkimaruPY/Lista-M3U.m3u")
        stable = f"https://raw.githubusercontent.com/{repo}/cgtn-runtime/cgtn-es.m3u8"
        changed = []; need_headers = not bool(meta.get("no_special_headers", True))
        for name in ("cn.m3u", "srhell02iptv.m3u"):
            if web.patch_playlist(Path(name), stable, need_headers): changed.append(name)
        print("playlist patch:", ", ".join(changed) if changed else "already current")

    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
