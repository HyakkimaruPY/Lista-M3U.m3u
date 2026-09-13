#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import refresh_cgtn_es_web as web
import refresh_cgtn_es_tv as tv

HOST = web.STREAM_HOST
PAGE = web.PAGE_URL
URL_RE = re.compile(r"https://" + re.escape(HOST) + r"/[^\s\"'<>]+?\.m3u8(?:\?[^\s\"'<>]+)?", re.I)


def walk(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from walk(x)
    elif isinstance(v, str):
        yield v


def main() -> int:
    chrome = web._chrome_binary()
    with tempfile.TemporaryDirectory(prefix="cgtn-same-cdn-") as tmp:
        netlog = Path(tmp) / "netlog.json"
        cmd = [
            chrome, "--headless", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
            "--autoplay-policy=no-user-gesture-required", "--virtual-time-budget=20000",
            f"--log-net-log={netlog}", "--net-log-capture-mode=IncludeSensitive", "--dump-dom", PAGE,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)
        data = json.loads(netlog.read_text("utf-8", errors="replace"))
        urls = []
        for value in walk(data):
            text = value.replace("\\u0026", "&").replace("\\/", "/")
            for match in URL_RE.findall(text):
                match = match.rstrip(".,);]")
                if urlparse(match).hostname == HOST and match not in urls:
                    urls.append(match)
        print(f"same-cdn m3u8 candidates={len(urls)}")
        for i, url in enumerate(urls, 1):
            redacted = re.sub(r"(wsSecret=)[^&]+", r"\1<redacted>", url)
            print(f"CANDIDATE[{i}] {redacted}")
            try:
                probe = tv.probe_media(url, web.WEB_HEADERS, 12)
                print("PROBE[%d] %sx%s fps=%s profile=%s bitrate=%s segdur=%s segbytes=%s" % (
                    i, probe.get("width"), probe.get("height"), probe.get("fps"), probe.get("video_profile"),
                    probe.get("bitrate_estimate"), probe.get("segment_duration"), probe.get("segment_bytes")))
            except Exception as exc:
                print(f"PROBE[{i}] ERROR {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
