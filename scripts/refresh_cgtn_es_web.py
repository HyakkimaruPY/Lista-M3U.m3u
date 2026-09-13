#!/usr/bin/env python3
"""Resolve CGTN Español from its official web player.

Primary path:
  https://espanol.cgtn.com/en-directo
  -> Chrome network log
  -> signed espanol-livetx-h5.cgtn.com HLS URL

If the official web player cannot be resolved, the existing Yangshipin/CCTV
resolver is used as a fallback. The output is a tiny stable master playlist
published by GitHub Actions on the cgtn-runtime branch.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import refresh_cgtn_es as ysp

PAGE_URL = "https://espanol.cgtn.com/en-directo"
STREAM_TOKEN = "LSveOGBaBw41Ea7ukkVAUdKQ220802LSTexu6xAuFH8VZNBLE1ZNEa220802cd"
STREAM_HOST = "espanol-livetx-h5.cgtn.com"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
WEB_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Referer": PAGE_URL,
    "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*",
}
URL_RE = re.compile(
    rf"https://{re.escape(STREAM_HOST)}/hls/{re.escape(STREAM_TOKEN)}/"
    r"playlist\.m3u8\?[^\s\"'<>]+",
    re.I,
)


def _chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("Chrome/Chromium is not available on this runner")


def _walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, str):
        yield value


def _candidate_score(url: str) -> int:
    try:
        query = parse_qs(urlparse(url).query)
        return int((query.get("wsTime") or ["0"])[0])
    except Exception:
        return 0


def capture_web_player_url(timeout: int = 35) -> tuple[str, dict]:
    chrome = _chrome_binary()
    with tempfile.TemporaryDirectory(prefix="cgtn-es-") as tmp:
        netlog = Path(tmp) / "netlog.json"
        dom = Path(tmp) / "dom.html"
        cmd = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--autoplay-policy=no-user-gesture-required",
            "--virtual-time-budget=15000",
            f"--log-net-log={netlog}",
            "--net-log-capture-mode=IncludeSensitive",
            "--dump-dom",
            PAGE_URL,
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            dom.write_bytes(result.stdout or b"")
        except subprocess.TimeoutExpired as exc:
            if exc.stdout:
                dom.write_bytes(exc.stdout)

        if not netlog.exists() or netlog.stat().st_size < 100:
            raise RuntimeError("official CGTN player produced no usable Chrome network log")

        data = json.loads(netlog.read_text("utf-8", errors="replace"))
        candidates: list[str] = []
        for value in _walk_strings(data):
            text = value.replace("\\u0026", "&").replace("\\/", "/")
            for match in URL_RE.findall(text):
                match = match.rstrip(".,);]")
                parsed = urlparse(match)
                query = parse_qs(parsed.query)
                if parsed.hostname != STREAM_HOST:
                    continue
                if "wsSecret" not in query or "wsTime" not in query:
                    continue
                if len((query.get("wsSecret") or [""])[0]) < 16:
                    continue
                if match not in candidates:
                    candidates.append(match)

        if not candidates:
            raise RuntimeError("official CGTN player did not request the signed Español HLS URL")

        candidates.sort(key=_candidate_score, reverse=True)
        chosen = candidates[0]
        query = parse_qs(urlparse(chosen).query)
        return chosen, {
            "source": "cgtn-web-player",
            "page": PAGE_URL,
            "candidate_count": len(candidates),
            "ws_time": int((query.get("wsTime") or ["0"])[0] or 0),
            "chrome": Path(chrome).name,
        }


def fetch_manifest(url: str, headers: dict[str, str] | None, timeout: int) -> tuple[str, str]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
        final_url = response.geturl()
    if not text.lstrip().startswith("#EXTM3U"):
        raise RuntimeError("CGTN web-player URL did not return an HLS manifest")
    return text, final_url


def validate_web_url(url: str, timeout: int) -> tuple[str, bool, dict]:
    text, final_url = fetch_manifest(url, WEB_HEADERS, timeout)
    if STREAM_TOKEN not in text:
        # Media sequence names can change, so this is informational rather than fatal.
        token_seen = False
    else:
        token_seen = True

    plain_ok = False
    try:
        plain_text, plain_final = fetch_manifest(final_url, {}, timeout)
        plain_ok = plain_text.lstrip().startswith("#EXTM3U")
        if plain_ok:
            final_url = plain_final
    except Exception:
        pass

    segments = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ".ts" in line:
            segments.append(line)

    return final_url, plain_ok, {
        "manifest_bytes": len(text.encode("utf-8")),
        "segment_count": len(segments),
        "stream_token_seen": token_seen,
    }


def patch_playlist(path: Path, stable_url: str, need_headers: bool) -> bool:
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
    entry = [
        line for line in entry
        if not line.startswith("#EXTVLCOPT:http-user-agent=")
        and not line.startswith("#EXTVLCOPT:http-referrer=")
        and not line.startswith("#EXTVLCOPT:http-origin=")
    ]

    url_index = next((i for i in range(1, len(entry)) if entry[i].startswith(("http://", "https://"))), None)
    if url_index is None:
        entry.append(stable_url)
        url_index = len(entry) - 1
    else:
        entry[url_index] = stable_url

    if need_headers:
        entry.insert(url_index, "#EXTVLCOPT:http-referrer=https://espanol.cgtn.com/en-directo")
        entry.insert(url_index, f"#EXTVLCOPT:http-user-agent={BROWSER_UA}")

    new_text = "\n".join(lines[:target] + entry + lines[end:]) + "\n"
    if new_text == old_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def resolve(timeout: int) -> tuple[str, dict]:
    web_error = None
    try:
        signed_url, meta = capture_web_player_url(max(30, timeout + 18))
        final_url, plain_ok, probe = validate_web_url(signed_url, timeout)
        return final_url, {
            **meta,
            **probe,
            "media_host": urlparse(final_url).hostname,
            "no_special_headers": plain_ok,
            "fallback_used": False,
        }
    except Exception as exc:
        web_error = str(exc)

    urls, payload = ysp.api_urls(timeout)
    media_url, probe = ysp.resolve_media_url(urls, timeout)
    return media_url, {
        "source": "yangshipin-fallback",
        "media_host": urlparse(media_url).hostname,
        "candidate_count": len(urls),
        "no_special_headers": probe["no_special_headers"],
        "vkey_renew_interval": payload.get("vkey_renew_interval"),
        "fallback_used": True,
        "web_error": web_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="cgtn-es.m3u8")
    parser.add_argument("--state", default="cgtn-es.json")
    parser.add_argument("--patch-playlists", action="store_true")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    media_url, meta = resolve(args.timeout)
    ysp.write_master(Path(args.output), media_url)

    state = {
        "channel": "CGTN Español",
        "generated_at": int(time.time()),
        **meta,
    }
    Path(args.state).parent.mkdir(parents=True, exist_ok=True)
    Path(args.state).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.patch_playlists:
        repo = os.environ.get("GITHUB_REPOSITORY", "HyakkimaruPY/Lista-M3U.m3u")
        stable = f"https://raw.githubusercontent.com/{repo}/cgtn-runtime/cgtn-es.m3u8"
        changed = []
        need_headers = not bool(meta.get("no_special_headers"))
        for name in ("cn.m3u", "srhell02iptv.m3u"):
            if patch_playlist(Path(name), stable, need_headers):
                changed.append(name)
        print("playlist patch:", ", ".join(changed) if changed else "already current")

    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
