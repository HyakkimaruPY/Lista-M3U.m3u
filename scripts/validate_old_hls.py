#!/usr/bin/env python3
"""Valida o perfil HLS legado exigido por old_hls.m3u8.

Este check complementa validate_streams.py. Ele nao tenta provar disponibilidade global;
serve para impedir que uma URL tecnicamente complexa/incompativel entre na lista da TV antiga.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

import validate_streams as base

MAX_MANIFEST = 2 * 1024 * 1024
BAD_CODEC = re.compile(r"(?:hvc1|hev1|hevc|h265|av01|av1|vp09|vp9|ac-3|ec-3|eac3)", re.I)


@dataclass
class LegacyResult:
    name: str
    host: str
    status: str
    reason: str
    redirects: int = 0
    final_host: str = ""
    media_url: str = ""


class RedirectCounter(HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > 3:
            raise HTTPError(req.full_url, code, "redirect limit", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_text(url: str, timeout: int) -> tuple[str, str, int, str]:
    counter = RedirectCounter()
    opener = build_opener(counter, HTTPSHandler(context=ssl.create_default_context()))
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Linux; SmartTV) OldHLSValidator/1.0",
        "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*",
        "Accept-Encoding": "identity",
    })
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read(MAX_MANIFEST + 1)
        if len(raw) > MAX_MANIFEST:
            raise ValueError("manifesto maior que 2 MiB")
        final = resp.geturl()
        ctype = resp.headers.get("Content-Type", "")
    return raw.decode("utf-8-sig", "replace"), final, counter.count, ctype


def simple_source_policy(entry: base.Entry) -> str | None:
    url, ua, ref = base.probe_url_and_headers(entry)
    if not base.valid_network_url(url):
        return "URL ausente ou malformada"
    assert url is not None
    p = urlsplit(url)
    if p.query or p.fragment:
        return "URL possui query/fragmento; Old HLS exige endpoint estavel sem token"
    if "|" in (entry.url or "") or ua or ref:
        return "URL depende de headers/opcoes especiais"
    return None


def parse_attrs(line: str) -> dict[str, str]:
    payload = line.split(":", 1)[1] if ":" in line else ""
    out: dict[str, str] = {}
    cur = []
    quoted = False
    parts = []
    for ch in payload:
        if ch == '"':
            quoted = not quoted
        if ch == "," and not quoted:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().upper()] = v.strip().strip('"')
    return out


def select_variant(text: str, base_url: str) -> tuple[str | None, str | None]:
    lines = [x.strip() for x in text.replace("\r\n", "\n").split("\n")]
    variants = []
    for i, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = parse_attrs(line)
        uri = None
        for nxt in lines[i + 1:]:
            if not nxt or nxt.startswith("#"):
                continue
            uri = nxt
            break
        if not uri:
            continue
        codecs = attrs.get("CODECS", "")
        if BAD_CODEC.search(codecs):
            continue
        width = height = 0
        if "RESOLUTION" in attrs and "x" in attrs["RESOLUTION"].lower():
            try:
                width, height = [int(x) for x in attrs["RESOLUTION"].lower().split("x", 1)]
            except ValueError:
                pass
        try:
            fps = float(attrs.get("FRAME-RATE", "0") or 0)
        except ValueError:
            fps = 0
        if width > 1920 or height > 1080 or fps > 60.5:
            continue
        try:
            bw = int(attrs.get("AVERAGE-BANDWIDTH", attrs.get("BANDWIDTH", "0")) or 0)
        except ValueError:
            bw = 0
        variants.append((height, bw, urljoin(base_url, uri), codecs))
    if not variants:
        return None, "master sem variante AVC/AAC <=1080p/60fps identificavel"
    variants.sort(reverse=True)
    return variants[0][2], None


def media_policy(text: str, final_url: str) -> str | None:
    upper = text.upper()
    if "#EXT-X-MAP" in upper:
        return "HLS fMP4/CMAF (#EXT-X-MAP) nao aceito"
    for line in text.splitlines():
        u = line.strip().upper()
        if u.startswith("#EXT-X-KEY:"):
            attrs = parse_attrs(line)
            if attrs.get("METHOD", "NONE").upper() != "NONE":
                return "stream criptografado (#EXT-X-KEY) nao aceito no perfil simples"
    media = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            media.append(urljoin(final_url, s))
    if not media:
        return "playlist de midia sem segmentos"
    sample = media[0].lower().split("?", 1)[0]
    if sample.endswith((".m4s", ".mp4", ".cmfv", ".cmfa")):
        return "segmentos fMP4/CMAF nao aceitos"
    return None


def inspect_entry(entry: base.Entry, timeout: int) -> LegacyResult:
    url, _, _ = base.probe_url_and_headers(entry)
    host = base.host_of(url)
    bad = simple_source_policy(entry)
    if bad:
        return LegacyResult(entry.title, host, "incompatible", bad)
    assert url is not None
    try:
        text, final, redirects, _ = fetch_text(url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return LegacyResult(entry.title, host, "uncertain", f"rede/HTTP inconclusivo: {exc}")
    except ValueError as exc:
        return LegacyResult(entry.title, host, "incompatible", str(exc))
    if not text.lstrip().startswith("#EXTM3U"):
        return LegacyResult(entry.title, host, "incompatible", "resposta nao e manifesto HLS", redirects, base.host_of(final))
    if redirects > 1:
        return LegacyResult(entry.title, host, "incompatible", f"cadeia de redirect longa ({redirects})", redirects, base.host_of(final))

    media_url = final
    if "#EXT-X-STREAM-INF" in text.upper():
        media_url, why = select_variant(text, final)
        if why:
            return LegacyResult(entry.title, host, "incompatible", why, redirects, base.host_of(final))
        assert media_url is not None
        try:
            text, media_final, r2, _ = fetch_text(media_url, timeout)
            redirects += r2
            media_url = media_final
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            return LegacyResult(entry.title, host, "uncertain", f"variante inconclusiva: {exc}", redirects, base.host_of(final), media_url)
        if redirects > 1:
            return LegacyResult(entry.title, host, "incompatible", f"cadeia de redirect longa ({redirects})", redirects, base.host_of(media_url), media_url)
        if not text.lstrip().startswith("#EXTM3U"):
            return LegacyResult(entry.title, host, "incompatible", "variante escolhida nao e HLS", redirects, base.host_of(media_url), media_url)

    bad_media = media_policy(text, media_url)
    if bad_media:
        return LegacyResult(entry.title, host, "incompatible", bad_media, redirects, base.host_of(media_url), media_url)
    return LegacyResult(entry.title, host, "compatible", "HLS simples compativel com o perfil legado", redirects, base.host_of(media_url), media_url)


def playlist_structure(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    errors = []
    if not lines or not lines[0].startswith("#EXTM3U"):
        errors.append("primeira linha deve ser #EXTM3U")
    if sum(1 for x in lines if x.startswith("#EXTM3U")) != 1:
        errors.append("playlist deve conter exatamente um #EXTM3U")
    entries = base.parse_playlist(lines)
    if not entries:
        errors.append("nenhuma entrada #EXTINF")
    allowed = {"Novelas", "Series", "Filmes", "Humor"}
    for e in entries:
        match = re.search(r'group-title="([^"]+)"', e.metadata, re.I)
        if not match:
            errors.append(f"linha {e.line}: group-title ausente")
        elif match.group(1) not in allowed:
            errors.append(f"linha {e.line}: grupo nao permitido: {match.group(1)}")
        bad = simple_source_policy(e)
        if bad:
            errors.append(f"linha {e.line}: {bad}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", default="old_hls.m3u8")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--report-dir", default="reports/old-hls")
    ap.add_argument("--strict", action="store_true", help="retorna erro se houver incompatibilidade comprovada")
    args = ap.parse_args()
    path = Path(args.playlist)
    if not path.exists():
        print(f"ERRO: {path} nao existe", file=sys.stderr)
        return 2
    structure = playlist_structure(path)
    entries = base.parse_playlist(path.read_text(encoding="utf-8-sig").splitlines())
    results = []
    if not structure:
        for e in entries:
            r = inspect_entry(e, max(2, args.timeout))
            results.append(r)
            print(f"[{r.status.upper():12}] {r.name}: {r.reason}")
    report = {
        "playlist": str(path),
        "checked_at_unix": int(time.time()),
        "structure_errors": structure,
        "counts": {
            "compatible": sum(r.status == "compatible" for r in results),
            "incompatible": sum(r.status == "incompatible" for r in results),
            "uncertain": sum(r.status == "uncertain" for r in results),
        },
        "results": [asdict(r) for r in results],
    }
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "legacy-profile.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = ["# Old HLS - perfil legado", "", f"- Estrutura: **{'PASS' if not structure else 'FAIL'}**"]
    if structure:
        summary += ["", "## Erros estruturais"] + [f"- {x}" for x in structure]
    summary += ["", f"- Compativeis: **{report['counts']['compatible']}**", f"- Incompativeis: **{report['counts']['incompatible']}**", f"- Inconclusivos: **{report['counts']['uncertain']}**"]
    (out / "legacy-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    if structure:
        return 1
    if args.strict and report["counts"]["incompatible"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
