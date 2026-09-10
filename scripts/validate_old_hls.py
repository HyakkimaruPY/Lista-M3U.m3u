#!/usr/bin/env python3
"""Valida old_hls.m3u8 usando o mesmo modelo por recursos do firmware AUTOHLS.

O validador nao depende de nome de provedor nem de tag tecnica no M3U. Ele segue o
manifesto, escolhe uma variante compativel, classifica o HLS de midia pelos recursos
e simula o mesmo tratamento da bridge. AES-128/identity e realmente descriptografado
e precisa resultar em MPEG-TS valido para ser aceito.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import hls_compat as compat
import validate_streams as base

@dataclass
class LegacyResult:
    name: str
    host: str
    status: str
    reason: str
    redirects: int = 0
    final_host: str = ""
    media_url: str = ""
    auto_profile: str = ""
    aes_decrypt_ok: bool = False
    ts_sync_ok: bool = False

def entry_group(entry: base.Entry) -> str:
    m = re.search(r'group-title="([^"]+)"', entry.metadata or "", re.I)
    return m.group(1).strip() if m else ""

def simple_source_policy(entry: base.Entry) -> str | None:
    """Rejeita apenas sintaxe que a propria bridge nao consegue consumir.

    Query strings sao permitidas. A bridge ja preserva a URL e herda de modo
    controlado parametros de autenticacao no mesmo host; query nao e incompatibilidade.
    """
    url, ua, ref = base.probe_url_and_headers(entry)
    if not base.valid_network_url(url):
        return "URL ausente ou malformada"
    assert url is not None
    if "|" in (entry.url or "") or ua or ref:
        return "URL depende de headers/opcoes externas; Old HLS deve ser autocontido"
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "somente HTTP/HTTPS e aceito"
    return None

def inspect_entry(entry: base.Entry, timeout: int) -> LegacyResult:
    url, _, _ = base.probe_url_and_headers(entry)
    host = base.host_of(url)
    bad = simple_source_policy(entry)
    if bad:
        return LegacyResult(entry.title, host, "incompatible", bad)
    assert url is not None

    session = compat.Session()
    current = url
    redirects = 0
    media_text = ""
    media_url = ""
    try:
        for _depth in range(4):
            text, final, rcount, _ = session.fetch_text(current, timeout=timeout)
            redirects += rcount
            if redirects > 8:
                return LegacyResult(entry.title, host, "incompatible", f"mais de 8 redirects ({redirects})", redirects, base.host_of(final))
            if "#EXT-X-STREAM-INF" not in text.upper():
                media_text, media_url = text, final
                break
            child = compat.choose_variant_with_fallback(text, final)
            if not child:
                return LegacyResult(entry.title, host, "incompatible", "master sem variante H.264/AAC <=1080p/60fps", redirects, base.host_of(final))
            current = child
        else:
            return LegacyResult(entry.title, host, "incompatible", "profundidade de playlist >3", redirects, base.host_of(current))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return LegacyResult(entry.title, host, "uncertain", f"rede/manifesto inconclusivo: {type(exc).__name__}: {exc}", redirects)

    probe = compat.probe_media_profile(session, media_text, media_url, timeout=timeout)
    p = probe.profile
    final_host = base.host_of(media_url)
    if p.kind == "unsupported":
        return LegacyResult(entry.title, host, "incompatible", f"AUTOHLS nao suporta: {p.unsupported}", redirects,
                            final_host, media_url, p.kind, probe.aes_decrypt_ok, probe.ts_sync_ok)

    # AES so entra se a CI reproduzir a mesma operacao da bridge e o resultado
    # descriptografado apresentar sincronismo MPEG-TS. Isso separa AES-128 HLS
    # classico de DRM/SAMPLE-AES que o hardware atual nao trata.
    if p.aes128 and not (probe.aes_decrypt_ok and probe.ts_sync_ok):
        status = "uncertain" if probe.detail.startswith("probe de segmento inconclusivo") else "incompatible"
        return LegacyResult(entry.title, host, status, f"AUTOHLS {p.kind}: {probe.detail}", redirects,
                            final_host, media_url, p.kind, probe.aes_decrypt_ok, probe.ts_sync_ok)

    # Em TS claro, ffprobe/ffmpeg da etapa seguinte e o teste A/V autoritativo.
    # Uma amostra curta sem sync fica inconclusiva e nunca remove o canal sozinha.
    if not p.aes128 and not probe.ts_sync_ok:
        return LegacyResult(entry.title, host, "uncertain", f"AUTOHLS {p.kind}: {probe.detail}", redirects,
                            final_host, media_url, p.kind, False, False)

    detail = {
        "simple": "MPEG-TS claro/proxy progressivo",
        "normalize": "normalizacao automatica HLS v3 + MPEG-TS",
        "aes128": "AES-128 CBC identity -> MPEG-TS em claro",
        "normalize+aes128": "normalizacao HLS v3 + AES-128 CBC -> MPEG-TS em claro",
    }.get(p.kind, p.reason)
    return LegacyResult(entry.title, host, "compatible", f"AUTOHLS {p.kind}: {detail}", redirects,
                        final_host, media_url, p.kind, probe.aes_decrypt_ok, probe.ts_sync_ok)

def playlist_structure(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    errors: list[str] = []
    if not lines or not lines[0].startswith("#EXTM3U"):
        errors.append("primeira linha deve ser #EXTM3U")
    if sum(x.startswith("#EXTM3U") for x in lines) != 1:
        errors.append("playlist deve conter exatamente um #EXTM3U")
    entries = base.parse_playlist(lines)
    if not entries:
        errors.append("nenhuma entrada #EXTINF")
    for e in entries:
        group = entry_group(e)
        if not group:
            errors.append(f"linha {e.line}: group-title ausente/vazio")
        elif len(group) > 48 or any(ord(c) < 32 for c in group):
            errors.append(f"linha {e.line}: group-title invalido")
        bad = simple_source_policy(e)
        if bad:
            errors.append(f"linha {e.line}: {bad}")
    return errors

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", default="old_hls.m3u8")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--report-dir", default="reports/old-hls")
    ap.add_argument("--strict", action="store_true", help="falha CI para incompatibilidade comprovada; rede inconclusiva nao remove canal")
    args = ap.parse_args()

    path = Path(args.playlist)
    if not path.exists():
        print(f"ERRO: {path} nao existe", file=sys.stderr)
        return 2
    structure = playlist_structure(path)
    entries = base.parse_playlist(path.read_text(encoding="utf-8-sig").splitlines())
    results: list[LegacyResult] = []
    if not structure:
        for e in entries:
            r = inspect_entry(e, max(2, args.timeout))
            results.append(r)
            print(f"[{r.status.upper():12}] {r.name}: {r.reason}")

    counts = {k: sum(r.status == k for r in results) for k in ("compatible", "incompatible", "uncertain")}
    profiles: dict[str, int] = {}
    for r in results:
        if r.auto_profile:
            profiles[r.auto_profile] = profiles.get(r.auto_profile, 0) + 1
    report = {
        "playlist": str(path),
        "checked_at_unix": int(time.time()),
        "validator_model": "AUTOHLS feature classifier; mirrors V7.3.5 bridge semantics",
        "structure_errors": structure,
        "counts": counts,
        "profiles": profiles,
        "results": [asdict(r) for r in results],
    }
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "legacy-profile.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = [
        "# Old HLS - AUTOHLS compatibility gate", "",
        f"- Estrutura: **{'PASS' if not structure else 'FAIL'}**",
        f"- Compativeis: **{counts['compatible']}**",
        f"- Incompativeis: **{counts['incompatible']}**",
        f"- Inconclusivos de rede/amostra: **{counts['uncertain']}**", "",
        "## Perfis detectados automaticamente",
    ]
    summary += [f"- `{k}`: **{v}**" for k, v in sorted(profiles.items())] or ["- nenhum"]
    if structure:
        summary += ["", "## Erros estruturais"] + [f"- {x}" for x in structure]
    (out / "legacy-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    if structure:
        return 1
    if args.strict and counts["incompatible"]:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
