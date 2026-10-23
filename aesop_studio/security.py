"""Boundary checks: path scope, redaction, SSRF-safe fetching, extraction limits."""
from __future__ import annotations

import html
import http.client
import ipaddress
import ssl
import os
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_EXTRACT_CHARS = 60_000
MAX_FETCH_BYTES = 2 * 1024 * 1024
TEXT_EXTS = {".txt", ".md", ".markdown", ".py", ".js", ".ts", ".json", ".csv", ".html", ".htm",
             ".css", ".yaml", ".yml", ".toml", ".ini", ".xml", ".log", ".ps1", ".sh", ".sql", ".rst"}

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{8,}=*"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|token|secret|password|passwd|authorization)[\"']?\s*[:=]\s*"
               r"[\"']?(?!\[REDACTED)[^\s\"',}]{6,}"),
]


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


class ScopeError(ValueError):
    pass


def _is_link(p: Path) -> bool:
    try:
        if p.is_symlink():
            return True
        is_junction = getattr(os.path, "isjunction", None)
        return bool(is_junction and is_junction(p))
    except OSError:
        return True


def contained_path(root: str | os.PathLike, rel: str) -> Path:
    """Resolve rel inside root; reject traversal, absolute paths, symlinks and junctions."""
    root_p = Path(root).resolve(strict=True)
    if not rel or "\x00" in rel:
        raise ScopeError("empty or invalid path")
    candidate = Path(rel)
    if candidate.is_absolute() or candidate.drive or any(part == ".." for part in candidate.parts):
        raise ScopeError("path escapes the selected project root")
    full = root_p / candidate
    cur = root_p
    for part in candidate.parts:
        cur = cur / part
        if cur.exists() and _is_link(cur):
            raise ScopeError("symlinks and junctions are not followed")
    resolved = full.resolve()
    if os.path.commonpath([str(resolved), str(root_p)]) != str(root_p):
        raise ScopeError("path escapes the selected project root")
    return resolved


def validate_root(root: str) -> Path:
    p = Path(root)
    if not p.is_absolute():
        raise ScopeError("project root must be an absolute path")
    if not p.is_dir():
        raise ScopeError("project root does not exist or is not a folder")
    if _is_link(p):
        raise ScopeError("project root may not be a symlink or junction")
    resolved = p.resolve()
    forbidden = [Path(os.environ.get("SystemRoot", r"C:\Windows")), Path.home() / ".ssh",
                 Path.home() / ".codex", Path.home() / ".claude", Path.home()]
    for f in forbidden:
        try:
            if resolved == f.resolve():
                raise ScopeError(f"refusing broad or credential directory as project root: {resolved}")
        except OSError:
            pass
    if resolved.parent == resolved:
        raise ScopeError("drive roots are not allowed as project roots")
    return resolved


# ---------- extraction ----------

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> tuple[str, str]:
    ex = _TextExtractor()
    ex.feed(raw)
    text = re.sub(r"[ \t]+", " ", "".join(ex.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return html.unescape(ex.title.strip()), text


def extract(name: str, data: bytes) -> tuple[str, str | None, str]:
    """Return (status, text, note). Never claims to have read what it could not."""
    ext = Path(name).suffix.lower()
    if len(data) > MAX_UPLOAD_BYTES:
        return "too_large", None, f"File exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit; original not stored."
    if ext == ".pdf":
        if b"/Encrypt" in data[:4096] or b"/Encrypt" in data[-4096:]:
            return "encrypted", None, "Encrypted PDF; decrypt it locally and re-attach."
        return "unsupported", None, "PDF text extraction is not bundled; export to .txt/.md and attach that."
    if ext in (".docx", ".xlsx", ".pptx", ".zip", ".exe", ".dll", ".png", ".jpg", ".jpeg", ".gif"):
        return "unsupported", None, f"{ext} content is not extracted; original preserved with hash."
    if ext and ext not in TEXT_EXTS:
        return "unsupported", None, f"{ext} is not a supported text format."
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "malformed", None, "File is not valid UTF-8 text."
    if "\x00" in text:
        return "malformed", None, "Binary content detected."
    note = ""
    if ext in (".html", ".htm"):
        _, text = html_to_text(text)
        note = "HTML converted to plain text; scripts/styles removed."
    if len(text) > MAX_EXTRACT_CHARS:
        text = text[:MAX_EXTRACT_CHARS]
        note = (note + " " if note else "") + f"Truncated to first {MAX_EXTRACT_CHARS} characters."
    return "extracted", text, note or "Full text extracted."


# ---------- SSRF-safe fetch ----------

class FetchError(ValueError):
    pass


def _check_host(host: str, allow_hosts: set[str]) -> str:
    if host in allow_hosts:
        return host
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise FetchError(f"cannot resolve {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError(f"blocked non-public address for {host}")
    return infos[0][4][0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class _PinnedHTTP(urllib.request.HTTPHandler):
    """Connect to the IP vetted by _check_host (defeats DNS rebinding between check and connect)."""
    def __init__(self, ip):
        super().__init__()
        self.ip = ip

    def http_open(self, req):
        ip = self.ip

        class Conn(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.create_connection((ip, self.port), self.timeout)
        return self.do_open(Conn, req)


class _PinnedHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, ip):
        super().__init__()
        self.ip = ip

    def https_open(self, req):
        ip = self.ip

        class Conn(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection((ip, self.port), self.timeout)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        return self.do_open(Conn, req, context=ssl.create_default_context())


def safe_fetch(url: str, allow_hosts: set[str] | None = None, max_redirects: int = 3) -> tuple[str, str, str]:
    """Fetch a public http(s) URL, validating every redirect hop. Returns (final_url, content_type, text)."""
    allow_hosts = allow_hosts or set()
    for _ in range(max_redirects + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError("only http(s) URLs are allowed")
        if parts.username or parts.password:
            raise FetchError("credentials in URLs are not allowed")
        ip = _check_host(parts.hostname, allow_hosts)
        opener = urllib.request.build_opener(_NoRedirect, _PinnedHTTP(ip), _PinnedHTTPS(ip))
        req = urllib.request.Request(url, headers={"User-Agent": "AesopStudio/0.1 (local research notebook)"})
        try:
            resp = opener.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise FetchError(f"HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise FetchError(str(e.reason)) from e
        with resp:
            ctype = resp.headers.get("Content-Type", "")
            body = resp.read(MAX_FETCH_BYTES + 1)
        if len(body) > MAX_FETCH_BYTES:
            body = body[:MAX_FETCH_BYTES]
        charset = "utf-8"
        m = re.search(r"charset=([\w\-]+)", ctype)
        if m:
            charset = m.group(1)
        return url, ctype, body.decode(charset, errors="replace")
    raise FetchError("too many redirects")
