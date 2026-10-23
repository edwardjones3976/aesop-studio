# Paid security review (gpt-6-astra)

_Codex API, 2026-10-23 03:11; 37385 input / 4638 output tokens; cost $0.60575; status completed; 122.1s. Findings are model output to be verified, not facts._

## Findings

### 1. High — Provider processes are not confined to the advertised filesystem scope

**Locations:** `aesop_studio/tasks.py:137,248–256`; `aesop_studio/providers.py:135,341–358,381`; `aesop_studio/openai_api.py:40–42,61–70`

**Failure scenario:** The application advertises access limited to an empty chat directory or the selected project root, but launches CLIs as the Studio user. Changing `cwd` is not filesystem isolation. Claude agent mode enables `acceptEdits` and blocks only a few tools/command patterns; it does not establish a filesystem boundary. Codex’s read-only setting likewise should not be treated as confinement of reads to `cwd`.

A task or prompt-injected project can request reads of absolute paths outside the project, including credentials. A process capable of executing code as the owner can also invoke DPAPI to decrypt that owner’s provider secret; stripping `OPENAI_API_KEY` from its environment does not prevent this.

**Minimal fix:** Disable routes whose promised scope cannot be enforced, or launch them under an actual filesystem/identity sandbox that excludes credential stores and grants only the selected workspace. Use a narrowly scoped credential broker where necessary. CLI permission settings can supplement, but should not substitute for, that boundary.

*Exact restrictions imposed independently by installed CLI versions are not supplied; this finding concerns the boundary established by the shown application.*

### 2. Medium — Credential-directory exclusions can be bypassed by selecting a descendant

**Locations:** `aesop_studio/security.py:77–96`; `aesop_studio/services.py:29–40`

**Failure scenario:** `validate_root()` rejects only exact matches with forbidden directories. For example, an existing `~/.codex/provider-mcp-secrets` directory is accepted even though `~/.codex` is forbidden. A project can therefore explicitly place the provider secret store inside its approved workspace. Ancestors that expose forbidden directories are also not generally excluded.

**Minimal fix:** For sensitive directory trees, reject both descendants and enclosing roots that would expose them. Preserve the distinction between a broad-root restriction, such as the home directory itself, and a sensitive-tree restriction, such as `.ssh` or `.codex`.

### 3. High — Session cookies can be stolen by another service on the same hostname

**Locations:** `aesop_studio/server.py:85–88,120–128,169–171,152–153`

**Failure scenario:** Cookies are not scoped by TCP port. After login at `127.0.0.1:8765`, the browser can send `aesop_session` to another service at `127.0.0.1:<other-port>`. `HttpOnly` prevents JavaScript access, not access by that service’s HTTP server; `SameSite=Strict` does not distinguish ports.

If the owner visits an attacker-controlled local service on the same hostname, that service can obtain the cookie. It can then make native HTTP requests to Studio, retrieve the CSRF token, and supply the expected `Host` and `Origin` headers to launch tasks or change settings. This also matters where different OS users can host loopback services.

**Minimal fix:** Do not use a hostname-scoped cookie as the sole API credential. Require an additional unguessable, origin-scoped browser credential on **every** API request, including reads, obtained through the launch handshake and retained in browser memory. Another localhost port must not receive it.

### 4. High — Default proxy handling can disclose proxy credentials to a fetched website

**Locations:** `aesop_studio/security.py:192–204,231–235`

**Failure scenario:** `build_opener()` installs the default environment-driven `ProxyHandler`. For an HTTP proxy configured with credentials, that handler adds `Proxy-Authorization` and changes the request to use the proxy.

However, `_PinnedHTTP.connect()` ignores the proxy hostname and connects to the fetched website’s vetted IP, using the connection’s port. An attacker controlling a public destination and listening on the configured proxy port can therefore receive the proxy authorization header directly. For example, an authenticated notebook fetch can expose credentials from an inherited `http_proxy=http://user:password@proxy:8080`.

**Minimal fix:** Explicitly disable proxy discovery for this direct, IP-pinned fetcher:

```python
urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirect,
    _PinnedHTTP(ip),
    _PinnedHTTPS(ip),
)
```

If proxy support is required, implement it separately with correct proxy authentication and destination-validation semantics.

### 5. Medium — An authenticated page can launch unbounded work and consume persistent storage

**Locations:** `aesop_studio/tasks.py:137–168`; `aesop_studio/providers.py:89–103`; `aesop_studio/server.py:177–185,454–466`; `aesop_studio/services.py:85–101`; `aesop_studio/backup.py:23–44`

**Failure scenario:** The only task concurrency check is one **agent** task per project. Chat tasks are not subject to it, and live verification bypasses the supervisor entirely. An authenticated page can repeatedly start chat/verification requests to accumulate provider processes and worker threads.

The same page can upload distinct files repeatedly or create backups in successive seconds, accumulating unlimited disk usage. The 5 MB upload limit and individual task timeouts do not impose aggregate limits.

**Minimal fix:** Add a server-wide bounded job queue and concurrency limit covering chat, agent tasks, verification, probing, and backup work. Enforce cumulative storage quotas and backup retention, reject excess work before allocation, and clean up temporary chat/verification directories.

### 6. Medium — A provider can deadlock before its watchdog starts

**Location:** `aesop_studio/tasks.py:261–284`

**Failure scenario:** The supervisor writes the entire prompt to the child’s stdin before starting either the output reader or timeout timer. If the child fills stdout while waiting for more input, Studio blocks writing stdin while the child blocks writing stdout. Neither side progresses, and the configured timeout has not yet been installed.

A large authenticated prompt makes pipe-capacity exhaustion practical. The task can remain running indefinitely and block further agent work for the project.

**Minimal fix:** Start the timeout and output-draining machinery before writing stdin. Feed stdin concurrently with output draining, and ensure timeout/cancellation interrupts a blocked writer and terminates the process tree.

### 7. Medium — CLI output limits do not bound memory or even a single log write

**Locations:** `aesop_studio/tasks.py:272–282,306–320`

**Failure scenario:** `proc.stdout.readline()` can accumulate an arbitrarily large line before returning. When it does return, the code checks only whether the *previous* total is below the limit, then writes the entire line. One large line can therefore exhaust memory or greatly exceed the 512 KB log cap.

The result file is also read completely with `read_text()` before `result[:MAX_OUTPUT_BYTES]` is applied.

**Minimal fix:** Read both stdout and result files in bounded chunks. Enforce the remaining byte allowance before appending or writing. Continue draining discarded subprocess output in bounded chunks, or terminate a process that exceeds its output budget.

### 8. Medium — CLI output redaction leaks multiline secrets, and the original result file remains plaintext

**Locations:** `aesop_studio/security.py:30,37–40`; `aesop_studio/tasks.py:272–280,306–307`; `aesop_studio/providers.py:342–343`

**Failure scenario:** CLI logs are redacted one line at a time. If a CLI prints a PEM private key, the first line containing `-----BEGIN ... PRIVATE KEY-----` is redacted, but subsequent base64 lines have no matching header and are written unchanged. The key material remains recoverable from the log and can be returned through the task-output API.

Separately, Codex writes its answer to `.last.txt`. Studio redacts the text after reading it but leaves the original unredacted file on disk. A secret echoed in that answer therefore remains in the task-output directory.

**Minimal fix:** Use a stateful streaming redactor that suppresses an entire private-key block across reads. Create raw result files with owner-only access, sanitize them immediately, and remove the raw copy after ingestion. Prefer avoiding provider-output echoes of known application secrets altogether.

### 9. Medium — Rejected credential-bearing URLs are stored as public sources and exported verbatim

**Locations:** `aesop_studio/security.py:229–230`; `aesop_studio/services.py:230–240,275–293`; `aesop_studio/server.py:385–389`

**Failure scenario:** Submitting `https://alice:password@example.com/document` causes `safe_fetch()` to reject URL credentials. Nevertheless, `add_public_source()` catches the exception and stores the **original URL** as `final`, including its credentials. It is saved as a non-private source, and the title and publisher can also contain those credentials.

The default notebook export includes these unavailable public sources and writes their fields without redaction. Thus, even a rejected fetch can put a password into a shareable export.

**Minimal fix:** Reject credential-bearing URLs before creating a source record, or sanitize them before any persistence or response. Apply an export sanitization policy as defense in depth; do not rely on the current generic regexes to remove URL userinfo.

## Review limits

`store.py`, `ledger.py`, `winjob.py`, and the browser code were not supplied. Consequently, data-directory ACLs, ledger enforcement, process-tree containment details, and DOM/XSS handling cannot be verified. I found no concrete direct shell-injection or ordinary static-path traversal issue in the shown code, and have not inferred additional SSRF bypasses from missing implementations.
