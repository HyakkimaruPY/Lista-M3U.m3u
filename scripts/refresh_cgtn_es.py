#!/usr/bin/env python3
"""Resolve CGTN Español from the official Yangshipin/CCTV API.

The generated cgtn-es.m3u8 is a tiny master playlist whose variant points at
the current signed official media manifest. GitHub Actions publishes it on a
dedicated runtime branch so main does not receive constant refresh commits.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import struct
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

API_URL = "https://bkliveinfo.ysp.cctv.cn/"
CHANNEL_ID = "2024182101"
LIVE_PID = "600084744"
PLATFORM = 4330403
APP_VERSION = "V8.22.1035.3031"
CKEY_TEA_KEY = bytes.fromhex("59b2f7cf725ef43c34fdd7c123411ed3")
GUARD_TEA_KEY = bytes.fromhex("110DBEC10C23E7D2E56A1CAD6914EF1B")
CKEY_XOR = bytes((0x84, 0x2E, 0xED, 0x08, 0xF0, 0x66, 0xE6, 0xEA, 0x48, 0xB4, 0xCA, 0xA9, 0x91, 0xED, 0x6F, 0xF3))
GUARD_XOR = bytes((0xB3, 0xC9, 0x53, 0xA0, 0x69, 0x13, 0xAD, 0x4D))
H264_CAPABILITY = base64.b64encode(b"H(30:1080,60:1080|30:1080,60:1080)").decode()
FETCH_HEADERS = {
    "Accept": "application/vnd.apple.mpegurl,application/json,*/*",
    "Referer": "https://live.cctv.cn/",
    "User-Agent": "qqlive",
}
MASK32 = 0xFFFFFFFF


def u32(value: int) -> int:
    return value & MASK32


def tea_encrypt_block(block: bytes, key: bytes) -> bytes:
    y, z = struct.unpack(">II", block)
    k0, k1, k2, k3 = struct.unpack(">IIII", key)
    total = 0
    for _ in range(16):
        total = u32(total + 0x9E3779B9)
        y = u32(y + (u32((z << 4) + k0) ^ u32(z + total) ^ u32((z >> 5) + k1)))
        z = u32(z + (u32((y << 4) + k2) ^ u32(y + total) ^ u32((y >> 5) + k3)))
    return struct.pack(">II", y, z)


def checksum(data: bytes) -> int:
    value = 0
    for byte in data:
        value = (0x83 * value + byte) & 0x7FFFFFFF
    return value


def tea_packet_encrypt(payload: bytes, key: bytes) -> bytes:
    pad = (8 - ((len(payload) + 10) % 8)) % 8
    plain = bytes(((secrets.randbits(8) & 0xF8) | pad,)) + secrets.token_bytes(pad) + secrets.token_bytes(2) + payload + bytes(7)
    previous_plain = bytes(8)
    previous_cipher = bytes(8)
    result = bytearray()
    for offset in range(0, len(plain), 8):
        source = plain[offset : offset + 8]
        mixed = bytes(a ^ b for a, b in zip(source, previous_cipher))
        encrypted = tea_encrypt_block(mixed, key)
        cipher = bytes(a ^ b for a, b in zip(encrypted, previous_plain))
        result.extend(cipher)
        previous_plain = mixed
        previous_cipher = cipher
    return bytes(result)


def lp(value: str | bytes) -> bytes:
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def guard_tail(value: str) -> str:
    return value[-5:] if len(value) >= 5 else ""


def make_guard(timestamp: int, guid: str) -> str:
    body = b"".join((
        struct.pack(">I", timestamp),
        lp(guard_tail(guid)),
        lp(guard_tail("null")),
        lp(guard_tail("null")),
        lp("-1"),
    ))
    plain = lp(body)
    encrypted = bytearray(tea_packet_encrypt(plain, GUARD_TEA_KEY) + struct.pack(">I", checksum(plain)))
    for i in range(len(encrypted)):
        encrypted[i] ^= GUARD_XOR[i % len(GUARD_XOR)]
    return encrypted.hex().upper()


def make_ckey(channel_id: str) -> dict[str, str | int]:
    timestamp = int(time.time())
    guid = secrets.token_hex(16)
    guard = make_guard(timestamp, guid)
    uid = secrets.token_hex(4).upper()
    body = b"".join((
        bytes.fromhex("0000004200000004000004d2"),
        struct.pack(">I", PLATFORM),
        struct.pack(">I", 0),
        struct.pack(">I", timestamp),
        lp("dcgh"),
        lp("_zj1A5Gh6QYcxWjIUGos2w=="),
        lp(APP_VERSION),
        lp(channel_id),
        lp(guid),
        struct.pack(">I", 1),
        struct.pack(">I", 1),
        lp(uid),
        lp("nil"),
        lp("57eab0c4-2c58-44c6-8ae9-dd2757525dc5"),
        lp("nil"),
        lp("v0.1.000"),
        lp("com.cctv.yangshipin.app.iphone"),
        lp(str(PLATFORM)),
        lp("ex_json_bus"),
        lp("ex_json_vs"),
        lp(guard),
    ))
    packet = bytearray(struct.pack(">H", len(body)) + body)
    packet[18:22] = struct.pack(">I", checksum(packet))
    encrypted = bytearray(tea_packet_encrypt(bytes(packet), CKEY_TEA_KEY) + struct.pack(">I", checksum(packet)))
    for i in range(len(encrypted)):
        encrypted[i] ^= CKEY_XOR[i % len(CKEY_XOR)]
    encoded = base64.b64encode(encrypted).decode().replace("+", "_").replace("/", "-").rstrip("=")
    return {
        "cKey": "--01" + encoded,
        "guid": guid,
        "timestamp": timestamp,
        "flowid": f"{str(uuid.uuid4()).upper()}_{PLATFORM}",
    }


def official_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == suffix or host.endswith("." + suffix) for suffix in ("cctv.cn", "ysp.cctv.cn", "cctv.com"))


def api_urls(timeout: int = 15) -> tuple[list[str], dict]:
    ticket = make_ckey(CHANNEL_ID)
    params = {
        "atime": "120", "livepid": LIVE_PID, "cnlid": CHANNEL_ID,
        "appVer": APP_VERSION, "app_version": "300090", "caplv": "1",
        "cmd": "2", "defn": "fhd", "device": "iPhone", "encryptVer": "4.2",
        "getpreviewinfo": "0", "hevclv": "0", "lang": "zh-Hans_CN",
        "livequeue": "0", "logintype": "1", "nettype": "1", "newnettype": "1",
        "newplatform": str(PLATFORM), "platform": str(PLATFORM), "sdtfrom": "v3021",
        "spacode": "23", "spaudio": "1", "spdemuxer": "6", "spdrm": "2",
        "spdynamicrange": "1", "spflv": "1", "spflvaudio": "1", "sphdrfps": "60",
        "sphttps": "1", "spvcode": H264_CAPABILITY, "spvideo": "4", "stream": "1",
        "system": "1", "sysver": "ios18.2.1", "uhd_flag": "0",
        "cKey": ticket["cKey"], "guid": ticket["guid"],
        "fntick": str(ticket["timestamp"]), "flowid": ticket["flowid"],
        "playbacktime": "0",
    }
    request = urllib.request.Request(
        API_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "qqlive", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if int(payload.get("iretcode", -1)) != 0:
        raise RuntimeError(f"official API error {payload.get('iretcode')}: {payload.get('errinfo', 'unknown error')}")
    candidates: list[str] = []
    if isinstance(payload.get("playurl"), str):
        candidates.append(payload["playurl"])
    backups = payload.get("backurl_list") or payload.get("backurlList") or payload.get("backurl")
    if isinstance(backups, list):
        for item in backups:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                candidates.append(str(item.get("url") or item.get("playurl") or ""))
    elif isinstance(backups, str):
        candidates.extend(part.strip() for part in backups.replace(";", ",").split(","))
    urls = []
    for value in candidates:
        value = str(value).strip()
        if value and official_url(value) and value not in urls:
            urls.append(value)
    if not urls:
        raise RuntimeError("official API returned no accepted CCTV/Yangshipin HLS URL")
    return urls, payload


def fetch_text(url: str, headers: dict[str, str] | None, timeout: int = 12) -> tuple[str, str]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
        final_url = response.geturl()
    if not text.lstrip().startswith("#EXTM3U"):
        raise RuntimeError("response is not an HLS manifest")
    return text, final_url


def first_variant(text: str, base_url: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]
    for idx, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        for candidate in lines[idx + 1 :]:
            if not candidate or candidate.startswith("#"):
                continue
            resolved = urljoin(base_url, candidate)
            return resolved if official_url(resolved) else None
    return None


def resolve_media_url(urls: list[str], timeout: int = 12) -> tuple[str, dict]:
    errors = []
    for source in urls:
        try:
            text, final_url = fetch_text(source, FETCH_HEADERS, timeout)
            variant = first_variant(text, final_url)
            media_url = variant or final_url
            if not official_url(media_url):
                raise RuntimeError("resolved manifest left official CCTV domains")
            plain_ok = False
            try:
                plain_text, plain_final = fetch_text(media_url, {}, timeout)
                plain_ok = plain_text.lstrip().startswith("#EXTM3U") and official_url(plain_final)
                if plain_ok:
                    media_url = plain_final
            except Exception:
                pass
            checked_text, checked_final = fetch_text(media_url, FETCH_HEADERS, timeout)
            if not checked_text.lstrip().startswith("#EXTM3U"):
                raise RuntimeError("resolved media URL failed HLS verification")
            return checked_final, {"source_url": source, "no_special_headers": plain_ok}
        except Exception as exc:
            errors.append(f"{urlparse(source).hostname}: {exc}")
    raise RuntimeError("all official CDN candidates failed: " + " | ".join(errors))


def write_master(path: Path, media_url: str) -> None:
    body = "\n".join((
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-STREAM-INF:BANDWIDTH=8000000,AVERAGE-BANDWIDTH=6000000",
        media_url,
        "",
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def patch_playlist(path: Path, stable_url: str) -> bool:
    if not path.exists():
        return False
    old_text = path.read_text(encoding="utf-8")
    lines = old_text.splitlines()
    target = None
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF") and 'tvg-id="CGTNSpanish.cn' in line:
            target = i
            break
    if target is None:
        return False
    end = target + 1
    while end < len(lines) and not lines[end].startswith("#EXTINF") and lines[end].strip():
        end += 1
    entry = lines[target:end]
    url_index = None
    for i in range(1, len(entry)):
        if entry[i].startswith(("http://", "https://")):
            url_index = i
            break
    if url_index is None:
        entry.append(stable_url)
        url_index = len(entry) - 1
    else:
        entry[url_index] = stable_url
    opts = [
        "#EXTVLCOPT:http-user-agent=qqlive",
        "#EXTVLCOPT:http-referrer=https://live.cctv.cn/",
    ]
    for opt in reversed(opts):
        if opt not in entry:
            entry.insert(url_index, opt)
    new_text = "\n".join(lines[:target] + entry + lines[end:]) + "\n"
    if new_text == old_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="cgtn-es.m3u8")
    parser.add_argument("--state", default="cgtn-es.json")
    parser.add_argument("--patch-playlists", action="store_true")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    urls, payload = api_urls(args.timeout)
    media_url, probe = resolve_media_url(urls, args.timeout)
    write_master(Path(args.output), media_url)
    state = {
        "channel": "CGTN Español",
        "channel_id": CHANNEL_ID,
        "live_pid": LIVE_PID,
        "definition": "fhd",
        "generated_at": int(time.time()),
        "media_host": urlparse(media_url).hostname,
        "candidate_count": len(urls),
        "no_special_headers": probe["no_special_headers"],
        "vkey_renew_interval": payload.get("vkey_renew_interval"),
    }
    Path(args.state).parent.mkdir(parents=True, exist_ok=True)
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.patch_playlists:
        repo = os.environ.get("GITHUB_REPOSITORY", "HyakkimaruPY/Lista-M3U.m3u")
        stable = f"https://raw.githubusercontent.com/{repo}/cgtn-runtime/cgtn-es.m3u8"
        changed = []
        for name in ("cn.m3u", "srhell02iptv.m3u"):
            if patch_playlist(Path(name), stable):
                changed.append(name)
        print("playlist patch:", ", ".join(changed) if changed else "already current")

    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
