#!/usr/bin/env python3
"""Feature-based HLS compatibility model shared with the Philco AUTOHLS bridge.

No provider names and no custom M3U tags are required. The classifier looks at the
actual HLS manifest and selects one of the transformations implemented in firmware:
  simple              clear MPEG-TS, progressive proxy
  normalize           strip legacy-hostile bookkeeping and emit HLS v3 media
  aes128              AES-128/identity CBC -> plaintext MPEG-TS in bridge
  normalize+aes128    both transformations
  unsupported         formats not yet proven on the legacy decoder
"""
from __future__ import annotations

import http.cookiejar
import re
import ssl
import subprocess
from dataclasses import dataclass, asdict
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, HTTPSHandler, Request, build_opener

UA = "Mozilla/5.0 (Linux; SmartTV) Philco-AUTOHLS-Validator/1.0"
MAX_MANIFEST = 2 * 1024 * 1024
MAX_AES_SEGMENT = 8 * 1024 * 1024
BAD_CODEC = re.compile(r"(?:hvc1|hev1|hevc|h265|av01|av1|vp09|vp9|ac-3|ec-3|eac3)", re.I)
NORMALIZE_PREFIXES = (
    "#EXT-X-DISCONTINUITY-SEQUENCE:", "#EXT-X-MEDIA-SEGMENT-", "#EXT-X-CUE-",
    "#PLUTO-", "#EXT-OATCLS-SCTE35", "#EXT-X-SCTE35",
)
FMP4_SUFFIXES = (".m4s", ".mp4", ".cmfv", ".cmfa")
INHERITED_QUERY_KEYS = {
    "token", "auth", "authorization", "session", "sessionid", "sid", "sig", "signature",
    "policy", "key-pair-id", "expires", "exp", "hdnea", "hdnts", "jwt", "access_token", "st", "e",
}

@dataclass
class MediaProfile:
    kind: str = "simple"
    normalize: bool = False
    aes128: bool = False
    unsupported: str = ""
    reason: str = "classic-ts"
    has_map: bool = False
    has_byterange: bool = False

@dataclass
class ProbeResult:
    profile: MediaProfile
    adapted_manifest: str
    media_url: str
    segment_url: str = ""
    aes_key_url: str = ""
    aes_decrypt_ok: bool = False
    ts_sync_ok: bool = False
    detail: str = ""

class RedirectCounter(HTTPRedirectHandler):
    def __init__(self):
        super().__init__(); self.count = 0
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > 8:
            raise HTTPError(req.full_url, code, "redirect limit", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Session:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
    def _opener(self, counter: RedirectCounter):
        return build_opener(counter, HTTPCookieProcessor(self.jar), HTTPSHandler(context=ssl.create_default_context()))
    def fetch(self, url: str, *, timeout: int = 12, max_bytes: int = MAX_MANIFEST,
              accept: str = "*/*", range_header: str | None = None) -> tuple[bytes, str, int, str]:
        counter = RedirectCounter()
        headers = {"User-Agent": UA, "Accept": accept, "Accept-Encoding": "identity"}
        if range_header:
            headers["Range"] = range_header
        req = Request(url, headers=headers)
        with self._opener(counter).open(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError(f"objeto maior que {max_bytes} bytes")
            return raw, resp.geturl(), counter.count, resp.headers.get("Content-Type", "")
    def fetch_text(self, url: str, timeout: int = 12) -> tuple[str, str, int, str]:
        raw, final, redirects, ctype = self.fetch(
            url, timeout=timeout, max_bytes=MAX_MANIFEST,
            accept="application/vnd.apple.mpegurl,application/x-mpegURL,*/*")
        text = raw.decode("utf-8-sig", "replace")
        if not text.lstrip().startswith("#EXTM3U"):
            raise ValueError("resposta nao e manifesto HLS")
        return text, final, redirects, ctype

def parse_attrs(line: str) -> dict[str, str]:
    payload = line.split(":", 1)[1] if ":" in line else ""
    out: dict[str, str] = {}; cur: list[str] = []; quoted = False; parts: list[str] = []
    for ch in payload:
        if ch == '"': quoted = not quoted
        if ch == "," and not quoted:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1); out[k.strip().upper()] = v.strip().strip('"')
    return out

def _inherit_key(k: str) -> bool:
    low = k.lower()
    return low in INHERITED_QUERY_KEYS or "token" in low or "signature" in low or low.startswith("hdn")

def resolve_with_context(base_url: str, ref: str) -> str:
    """Mirror the bridge's controlled same-host auth query inheritance."""
    absolute = urljoin(base_url, ref)
    b = urlsplit(base_url); r = urlsplit(ref); a = urlsplit(absolute)
    if r.scheme or r.netloc or a.hostname != b.hostname or not b.query:
        return absolute
    aq = dict(parse_qsl(a.query, keep_blank_values=True)); changed = False
    for k, v in parse_qsl(b.query, keep_blank_values=True):
        if _inherit_key(k) and k not in aq:
            aq[k] = v; changed = True
    if changed:
        a = a._replace(query=urlencode(aq)); return urlunsplit(a)
    return absolute

def classify_media_manifest(text: str, base_url: str = "") -> MediaProfile:
    p = MediaProfile(); reasons: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        t = raw.strip(); u = t.upper()
        if u.startswith("#EXT-X-MAP:"):
            p.has_map = True; p.unsupported = "fmp4/cmaf EXT-X-MAP"; p.kind = "unsupported"; p.reason = p.unsupported; return p
        if u.startswith("#EXT-X-BYTERANGE:"):
            p.has_byterange = True; p.unsupported = "byterange media not proven"; p.kind = "unsupported"; p.reason = p.unsupported; return p
        if u.startswith("#EXT-X-KEY:"):
            a = parse_attrs(t); method = a.get("METHOD", "").upper().strip(); keyformat = (a.get("KEYFORMAT") or "identity").strip()
            if method in ("", "NONE"):
                continue
            if method == "AES-128" and keyformat.lower() == "identity" and a.get("URI"):
                p.aes128 = True
                if "aes128-identity" not in reasons: reasons.append("aes128-identity")
                continue
            p.unsupported = f"encryption {method}/{keyformat}"; p.kind = "unsupported"; p.reason = p.unsupported; return p
        if any(u.startswith(prefix) for prefix in NORMALIZE_PREFIXES):
            p.normalize = True
        if t and not t.startswith("#"):
            low = t.split("?", 1)[0].lower()
            if low.endswith(FMP4_SUFFIXES):
                p.unsupported = "fmp4/cmaf media segment"; p.kind = "unsupported"; p.reason = p.unsupported; return p
    if p.normalize: reasons.append("legacy-tag-normalization")
    if p.aes128 and p.normalize: p.kind = "normalize+aes128"
    elif p.aes128: p.kind = "aes128"
    elif p.normalize: p.kind = "normalize"
    else: p.kind = "simple"
    if reasons: p.reason = "+".join(reasons)
    return p

def _resolution(attrs: dict[str, str]) -> tuple[int, int]:
    try:
        w, h = attrs.get("RESOLUTION", "").lower().split("x", 1); return int(w), int(h)
    except Exception:
        return 0, 0

def choose_variant(text: str, base_url: str, max_height: int = 720) -> str | None:
    """Mirror the TV path: H.264/AAC compatible, 720 first, 1080 fallback."""
    lines = [x.strip() for x in text.replace("\r\n", "\n").split("\n")]
    candidates: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"): continue
        a = parse_attrs(line); uri = ""
        for nxt in lines[i + 1:]:
            if nxt and not nxt.startswith("#"): uri = nxt; break
        if not uri: continue
        codecs = a.get("CODECS", "")
        if BAD_CODEC.search(codecs): continue
        w, h = _resolution(a)
        try: fps = float(a.get("FRAME-RATE", "0") or 0)
        except ValueError: fps = 0.0
        if w > 1920 or h > max_height or fps > 60.5: continue
        try: bw = int(a.get("AVERAGE-BANDWIDTH") or a.get("BANDWIDTH") or 0)
        except ValueError: bw = 0
        candidates.append((h or 1, bw, resolve_with_context(base_url, uri)))
    if not candidates: return None
    candidates.sort(reverse=True); return candidates[0][2]

def choose_variant_with_fallback(text: str, base_url: str) -> str | None:
    return choose_variant(text, base_url, 720) or choose_variant(text, base_url, 1080)

def _first_media_segment(text: str, base_url: str) -> tuple[str, str, str, int]:
    seq = 0; key_url = ""; iv = ""; active_aes = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        t = raw.strip()
        if t.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try: seq = int(t.split(":", 1)[1].strip())
            except ValueError: seq = 0
            continue
        if t.startswith("#EXT-X-KEY:"):
            a = parse_attrs(t); method = a.get("METHOD", "").upper()
            if method == "NONE": key_url = ""; iv = ""; active_aes = False
            elif method == "AES-128" and (a.get("KEYFORMAT") or "identity").lower() == "identity" and a.get("URI"):
                key_url = resolve_with_context(base_url, a["URI"]); iv = a.get("IV", ""); active_aes = True
            continue
        if not t or t.startswith("#"): continue
        return resolve_with_context(base_url, t), key_url if active_aes else "", iv, seq
    return "", "", "", seq

def _iv_bytes(raw: str, seq: int) -> bytes:
    if not raw: return b"\x00" * 8 + int(seq).to_bytes(8, "big")
    s = raw.strip(); s = s[2:] if s.lower().startswith("0x") else s
    if not s or len(s) > 32: raise ValueError("IV AES invalido")
    if len(s) % 2: s = "0" + s
    b = bytes.fromhex(s)
    if len(b) > 16: raise ValueError("IV AES invalido")
    return b.rjust(16, b"\x00")

def ts_sync_ok(data: bytes) -> bool:
    lim = min(188, max(0, len(data) - 377))
    for off in range(lim + 1):
        if data[off:off+1] == b"\x47" and data[off+188:off+189] == b"\x47" and data[off+376:off+377] == b"\x47":
            return True
    return False

def decrypt_aes128_cbc(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Use OpenSSL in CI to mirror the firmware's AES-128-CBC operation."""
    if len(key) != 16 or len(iv) != 16: raise ValueError("chave/IV AES deve ter 16 bytes")
    usable = len(ciphertext) - (len(ciphertext) % 16)
    if usable < 16: raise ValueError("segmento AES curto")
    cmd = ["openssl", "enc", "-d", "-aes-128-cbc", "-K", key.hex(), "-iv", iv.hex(), "-nopad"]
    p = subprocess.run(cmd, input=ciphertext[:usable], capture_output=True, timeout=10)
    if p.returncode:
        raise RuntimeError((p.stderr or b"openssl AES falhou").decode("utf-8", "replace")[-300:])
    return p.stdout

def adapt_media_manifest(text: str, base_url: str, profile: MediaProfile) -> str:
    """Produce the same semantic legacy view as the firmware for validation."""
    if profile.kind == "unsupported": raise ValueError(profile.unsupported or "perfil nao suportado")
    if not (profile.normalize or profile.aes128):
        out = []
        for raw in text.replace("\r\n", "\n").split("\n"):
            if raw.strip().startswith("#EXT-X-DISCONTINUITY-SEQUENCE:"): continue
            out.append(raw)
        return "\n".join(out)
    out = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for raw in text.replace("\r\n", "\n").split("\n"):
        t = raw.strip()
        if not t or t == "#EXTM3U" or t.startswith("#EXT-X-VERSION:"): continue
        if t.startswith("#EXT-X-MEDIA-SEQUENCE:") or t.startswith("#EXT-X-TARGETDURATION:") or t == "#EXT-X-DISCONTINUITY" or t.startswith("#EXTINF:") or t == "#EXT-X-ENDLIST":
            out.append(t); continue
        if t.startswith("#EXT-X-KEY:") and profile.aes128: continue
        if t.startswith("#"): continue
        out.append(resolve_with_context(base_url, t))
    return "\n".join(out) + "\n"

def probe_media_profile(session: Session, text: str, media_url: str, *, timeout: int = 12) -> ProbeResult:
    profile = classify_media_manifest(text, media_url)
    if profile.kind == "unsupported": return ProbeResult(profile, "", media_url, detail=profile.unsupported)
    adapted = adapt_media_manifest(text, media_url, profile)
    seg_url, key_url, iv_raw, seq = _first_media_segment(text, media_url)
    result = ProbeResult(profile, adapted, media_url, segment_url=seg_url, aes_key_url=key_url)
    if not seg_url:
        result.detail = "playlist de midia sem segmento"; return result
    try:
        if profile.aes128:
            key, _, _, _ = session.fetch(key_url, timeout=timeout, max_bytes=64)
            if len(key) != 16:
                result.detail = f"chave AES com {len(key)} bytes"; return result
            enc, _, _, _ = session.fetch(seg_url, timeout=timeout, max_bytes=MAX_AES_SEGMENT)
            plain = decrypt_aes128_cbc(enc, key, _iv_bytes(iv_raw, seq))
            result.aes_decrypt_ok = True; result.ts_sync_ok = ts_sync_ok(plain)
            result.detail = "AES-128 CBC -> MPEG-TS" if result.ts_sync_ok else "AES descriptografou, mas sync MPEG-TS nao apareceu"
        else:
            sample, _, _, _ = session.fetch(seg_url, timeout=timeout, max_bytes=64 * 1024, range_header="bytes=0-65535")
            result.ts_sync_ok = ts_sync_ok(sample)
            result.detail = "MPEG-TS claro" if result.ts_sync_ok else "segmento acessivel; sync TS nao confirmado na amostra"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result.detail = f"probe de segmento inconclusivo: {type(exc).__name__}: {exc}"
    return result

def profile_dict(p: MediaProfile) -> dict:
    return asdict(p)
