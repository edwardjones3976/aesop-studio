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
             ".css", ".yaml", ".yml", ".toml", ".ini", ".xml", ".log", ".ps1", ".sh", ".sql", ".rst",
             # code folders (owner request 2026-10-23: attach files and folders in chat)
             ".tsx", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".scss", ".sass", ".less", ".java", ".kt", ".kts",
             ".gradle", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".dart",
             ".lua", ".r", ".pl", ".bat", ".cmd", ".psm1", ".cfg", ".conf", ".properties", ".tex", ".tf", ".hcl",
             ".proto", ".graphql", ".gql", ".ipynb", ".svg", ".tsv", ".jsonl", ".lock", ".editorconfig", ".gitignore"}
# Never read, even when they arrive inside a dropped folder: they usually hold credentials.
SECRET_FILE_RE = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx|keystore|jks)|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|"
                            r"\.npmrc|\.pypirc|\.netrc|credentials(\.json)?|secrets?\.(json|ya?ml|toml))$", re.I)

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bpplx-[A-Za-z0-9_\-]{20,}"),  # Perplexity API keys
    re.compile(r"\bfc-(?:live-)?[A-Za-z0-9_\-]{20,}"),  # Firecrawl API keys
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
    # Orphaned PEM body: base64 lines ending in an END marker whose BEGIN line was redacted separately
    # (e.g. by an earlier line-by-line pass). Newlines may be real or JSON-escaped ("\n").
    re.compile(r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/=]{16,}(?:\r?\n|(?:\\r)?\\n))+-----END [A-Z ]*PRIVATE KEY-----"),
]
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@?#\"'<>]+@")
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return _URL_USERINFO.sub(r"\1[REDACTED]@", text)


class LineRedactor:
    """Stateful redactor for line-at-a-time streams (subprocess stdout).

    redact() on a single line cannot see a PEM block that spans lines: only the BEGIN line would be
    replaced. feed() suppresses every line from an unmatched BEGIN marker through its END marker
    (or the end of the stream), so no key body line is ever returned.
    """

    def __init__(self):
        self.in_key = False

    def feed(self, line: str) -> str:
        nl = "\n" if line.endswith("\n") else ""
        if self.in_key:
            m = _PEM_END.search(line)
            if not m:
                return ""
            self.in_key = False
            rest = line[m.end():]
            return "[REDACTED]" + (self.feed(rest) if rest.strip() else nl)
        b = _PEM_BEGIN.search(line)
        if b and not _PEM_END.search(line, b.end()):
            self.in_key = True
            return redact(line[:b.start()]) + "[REDACTED]" + nl
        return redact(line)


_SECRET_QUERY_KEY = re.compile(r"(?i)(token|secret|passw|pwd|api[_-]?key|apikey|^key$|auth|credential|"
                               r"signature|^sig$|session|^code$|x-amz-)")


def sanitize_url(url: str) -> str:
    """Drop userinfo and blank out secret-looking query values so a URL can be stored or exported."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return redact(url)
    netloc = parts.netloc
    if host and (parts.username is not None or parts.password is not None or "@" in netloc):
        h = f"[{host}]" if ":" in host else host
        netloc = h + (f":{port}" if port else "")
    query = parts.query
    if query:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
        if any(_SECRET_QUERY_KEY.search(k) or redact(v) != v for k, v in pairs):
            query = urllib.parse.urlencode([(k, "REDACTED" if _SECRET_QUERY_KEY.search(k) else redact(v))
                                            for k, v in pairs])
    return urllib.parse.urlunsplit((parts.scheme, netloc, redact(parts.path), query, redact(parts.fragment)))


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
    if resolved.parent == resolved:
        raise ScopeError("drive roots are not allowed as project roots")
    rkey = _norm(resolved)
    home = Path.home()
    # Broad roots: refused only as exact matches, so ordinary project folders below home stay allowed.
    for f in (home,):
        if rkey == _norm(_resolve_quiet(f)):
            raise ScopeError(f"refusing broad or credential directory as project root: {resolved}")
    # Sensitive trees: refused as the tree itself, anything inside it, or any ancestor that would expose it.
    sensitive = [Path(os.environ.get("SystemRoot", r"C:\Windows"))] + [home / d for d in _CREDENTIAL_DIRS]
    for f in sensitive:
        skey = _norm(_resolve_quiet(f))
        if rkey == skey or _is_under(rkey, skey) or _is_under(skey, rkey):
            raise ScopeError(f"refusing broad or credential directory as project root: {resolved}")
    return resolved


_CREDENTIAL_DIRS = (".ssh", ".codex", ".claude", ".aws", ".azure", ".gnupg", ".kube", ".docker")


def _resolve_quiet(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _norm(p: Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _is_under(child: str, parent: str) -> bool:
    """True when child is strictly inside parent (both already normalized)."""
    return child != parent and child.startswith(parent.rstrip("\\/") + os.sep)


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


IMAGE_MIMES = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def image_kind(data: bytes) -> str | None:
    """png / jpeg / gif / webp, sniffed from the bytes (a renamed file never passes as an image)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    import struct
    k = image_kind(data)
    try:
        if k == "png":
            return struct.unpack(">II", data[16:24])
        if k == "gif":
            return struct.unpack("<HH", data[6:10])
        if k == "jpeg":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    hgt, wid = struct.unpack(">HH", data[i + 5:i + 9])
                    return wid, hgt
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        if k == "webp" and data[12:16] == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    except (struct.error, IndexError):
        return None
    return None


def extract(name: str, data: bytes) -> tuple[str, str | None, str]:
    """Return (status, text, note). Never claims to have read what it could not."""
    ext = Path(name).suffix.lower()
    if len(data) > MAX_UPLOAD_BYTES:
        return "too_large", None, f"File exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit; original not stored."
    if SECRET_FILE_RE.search(name.replace("\\", "/")):
        return "unsupported", None, "Looks like a credentials file (.env, key, certificate); not read or sent."
    kind = image_kind(data)
    if kind:
        dims = image_size(data)
        return "image", None, f"{kind.upper()} image" + (f", {dims[0]}×{dims[1]}" if dims else "") + \
            f", {len(data) // 1024} KB. Sent as an image to providers that can see images."
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
        # ProxyHandler({}): never route a pinned connection through env/registry proxies (it would connect
        # to the vetted IP on the proxy port and send Proxy-Authorization to the fetched site).
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect,
                                             _PinnedHTTP(ip), _PinnedHTTPS(ip))
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
