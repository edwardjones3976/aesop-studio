# Paid stability review (gpt-6-astra)

_Codex API, 2026-10-23 03:10; 32961 input / 3892 output tokens; cost $0.52421; status completed; 93.7s. Findings are model output to be verified, not facts._

## Findings

### 1. High — Writing stdin before draining stdout can deadlock before the timeout starts
**Location:** `aesop_studio/tasks.py:261–284`

**Failure scenario:** A CLI prints enough startup output to fill its stdout pipe before reading the prompt. Studio simultaneously writes a prompt larger than the stdin pipe capacity. Both processes block. The output reader and timeout timer have not started yet, so the task can remain `RUNNING` indefinitely.

**Minimal fix:** Start stdout draining and the timeout watchdog before writing stdin. Feed stdin concurrently, and ensure cancellation terminates the process and unblocks the writer.

### 2. High — Exceptions outside the narrow handlers abandon task supervision
**Location:** `aesop_studio/tasks.py:163–168, 193–235, 247–323`

**Failure scenario:**
- `_set(..., "RUNNING")` at line 260 can fail—for example, from SQLite contention or a failed event insert—after the child has started but before its timeout and output reader exist.
- Opening the API log at line 206 can fail outside the stream exception handler, leaving the task `RUNNING` and its reservation active.
- Reading the final result at line 307 can fail after process cleanup, leaving the task permanently `RUNNING`, blocking subsequent agent tasks.
- Failure writing the initial snapshot leaves a `CREATED` task and reservation without a worker.

**Minimal fix:** Wrap each complete task lifecycle in an outer exception handler and `finally` cleanup. Always terminate/reap owned processes, cancel/join watchdogs, close streams, and unregister resources. Persist a failure or uncertain outcome without releasing potentially incurred exposure. Handle task preparation failures similarly.

### 3. High — Starting a second server reconciles the first server’s live tasks
**Location:** `aesop_studio/server.py:31–40, 470–474`; `aesop_studio/tasks.py:386–404`

**Failure scenario:** The owner launches Studio twice using the same data directory. The second instance runs reconciliation **before** attempting to bind the HTTP port. It changes the first instance’s active task states and settles reservations even if binding subsequently fails. A task caught in `RESERVED` can be settled at zero while the original instance proceeds to dispatch it. Using a different port allows both supervisors to continue sharing the database.

**Minimal fix:** Acquire an exclusive, Windows-compatible lock keyed by the data directory before opening/reconciling the store. Hold it for the server lifetime; refuse a second owner.

### 4. High — Task/ledger transitions have unrecoverable crash windows
**Location:** `aesop_studio/tasks.py:159–166, 176–184, 321–323, 397–402`

**Failure scenario:**
- A crash after `ledger.reserve()` but before saving `ledger_id` leaves a reservation that reconciliation never finds, despite its existing `task_ref`.
- A crash after reconciliation marks a task terminal at line 397 but before settling its ledger entry means subsequent reconciliations skip it permanently.
- CLI completion similarly persists terminal state before settlement.

These gaps can strand budget exposure indefinitely.

**Minimal fix:** Commit reservation creation and its task linkage together. Commit terminal task state and ledger disposition together. Add recovery that examines ledger entries through `task_ref`, including entries associated with terminal tasks or missing checkpoint links.

### 5. High — Uncertain surviving writers do not block another agent
**Location:** `aesop_studio/tasks.py:21, 139–142, 312–313, 393–397`

**Failure scenario:** Reconciliation finds the recorded process still alive and marks the task `EFFECT_UNKNOWN`. That state is terminal and excluded from the project busy check. The owner can immediately start another agent while the original process may still be modifying the same files. The same gap exists when descendant cleanup fails.

**Minimal fix:** Preserve a separate unresolved ownership/project-write lock. Do not release it merely because the task becomes `EFFECT_UNKNOWN`; require verified process-tree termination or an explicit owner resolution.

### 6. High — Process execution begins before Windows job containment
**Location:** `aesop_studio/tasks.py:250–256`

**Failure scenario:** `Popen` starts the CLI running before `winjob.contain(proc.pid)` is called. A launcher can spawn a child during that interval. Assigning the parent to a Windows Job Object afterward does not retroactively assign already-created children, potentially leaving work outside cancellation and crash cleanup.

**Minimal fix:** Create the process suspended, assign it to the job, and only then resume execution; fail closed if containment fails.

**Qualification:** `winjob.py` was not supplied, so its handling of existing descendants cannot be assessed. The launch-before-containment window is visible here.

### 7. High — API cancellation is not prompt, and timeout is not an overall deadline
**Location:** `aesop_studio/openai_api.py:131–150`; `aesop_studio/tasks.py:363–369`

**Failure scenario:** Cancellation only sets an event, checked after a response line arrives. A stalled connection can remain blocked until the socket timeout. A server sending occasional bytes or events can keep the request alive indefinitely because the configured timeout applies to blocking socket operations, not total elapsed time. Cancellation before dispatch also does not prevent `conn.request()` from sending the billable request.

**Minimal fix:** Check cancellation before dispatch and enforce a monotonic overall deadline across connection, response headers, and streaming. Make blocked I/O interruptible using bounded reads/timeouts or a cancellation mechanism that actively shuts down the connection.

### 8. High — CLI output limits do not bound memory or individual writes
**Location:** `aesop_studio/tasks.py:272–282, 305–320`

**Failure scenario:** A CLI emits a huge line without a newline. `readline()` buffers the entire line before the limit is checked, potentially exhausting memory. Once returned, the entire line is written even if it exceeds the remaining limit. The final-result file is also read and redacted in full before truncation.

**Minimal fix:** Read stdout in bounded chunks, retain only the remaining byte allowance, and continue draining excess output without accumulating it. Bound reads of the final-result file before decoding/redaction.

### 9. High — Probe timeouts can leak descendants or hang during timeout cleanup
**Location:** `aesop_studio/providers.py:99–108, 120–127`

**Failure scenario:** A CLI probe or live verification launches a descendant that inherits stdout/stderr. On Windows, `subprocess.run(..., timeout=...)` kills the direct child, not its tree. Its subsequent communication cleanup can wait on pipes still held by descendants, so the advertised timeout need not bound the call. These probes also capture output without a size limit.

**Minimal fix:** Run probes and verification through bounded, job-contained supervision. On timeout, terminate the complete job before bounded reader cleanup, and cap retained output.

### 10. High — Backup filename collisions can destroy an existing backup
**Location:** `aesop_studio/backup.py:26–27, 38`

**Failure scenario:** Two backup requests within one second select the same path. Opening with `"w"` truncates the existing archive; concurrent writers can corrupt it. Even sequential requests overwrite the first successful backup, and a failure during the replacement destroys that earlier recovery point.

**Minimal fix:** Use a unique filename and exclusive creation. Write to a unique temporary archive, close and validate it, then atomically publish it without overwriting an existing backup.

### 11. High — Verified backups omit task files and retain invalid absolute paths
**Location:** `aesop_studio/backup.py:36–53, 75–81`; `aesop_studio/tasks.py:138, 165, 238, 377–384`

**Failure scenario:** Backups include the database and attachment files, but not `task-output`, including logs, final-result files, and snapshots. Task rows retain absolute `output_path` and `cwd` values. A restore can report `ok=True` even though task output is lost and restored rows point at the old installation. CLI chat answers that depend on the log fallback can consequently disappear.

**Minimal fix:** Include required task artifacts, make application-owned paths relative or remap them on restore, and verify referenced artifacts—not just table counts and SQLite integrity. Explicitly identify project roots as external data requiring separate backup.

### 12. High — Interrupted attachment writes can be accepted later as complete files
**Location:** `aesop_studio/services.py:94–101`

**Failure scenario:** Studio crashes or runs out of disk space during `write_bytes`, leaving a partial file at its final content-derived name. On retry, `exists()` causes the write to be skipped, and an attachment row is inserted with the full input’s hash and size despite the stored file being truncated. A concurrent identical upload can also observe the file while another request is still writing it.

**Minimal fix:** Write to a unique temporary file, close/flush it, then atomically publish the completed file. Verify an existing destination’s size and hash before reusing it.

### 13. Medium — Windows junctions bypass the snapshot traversal exclusion
**Location:** `aesop_studio/tasks.py:29–42`

**Failure scenario:** A directory junction is not necessarily reported as a symbolic link by `os.path.islink()`. `os.walk(..., followlinks=False)` therefore does not establish the claimed “no junction following” guarantee. A junction can send scanning outside the root or into a cycle. The 5,000-file limit does not bound traversal through empty directories, and the initial scan happens before the task watchdog exists.

**Minimal fix:** Explicitly exclude junctions/reparse-point directories, with a compatible fallback for supported Python versions. Also bound visited directories and elapsed scan time.

### 14. Medium — Independently truncated snapshots produce false file-change reports
**Location:** `aesop_studio/tasks.py:40–49, 301–302`

**Failure scenario:** A project has more than 5,000 files. Adding files early in traversal pushes unchanged files outside the second snapshot’s cutoff. The diff reports those files as removed even though they remain on disk. Unspecified traversal order can further change which files are sampled.

**Minimal fix:** Persist whether each snapshot was truncated and do not represent missing sampled entries as proven additions/removals. Use deterministic traversal and report incomplete coverage explicitly.

### 15. Medium — Runtime exposure disappears at a month boundary
**Location:** `aesop_studio/ledger.py:63–69, 145–148`

**Failure scenario:** A metered task is reserved just before midnight at month-end and remains active after midnight. Its reservation is excluded from the new month solely because its `created` timestamp is old. New requests can consume the entire new monthly limit while the older call is still incurring charges. Unresolved exposure is excluded in the same way.

**Minimal fix:** Include outstanding reservations regardless of creation month until resolved. Define a billing-period allocation for settled charges rather than assuming reservation creation time identifies the charge period.

### 16. Medium — HTTP connections and task launches have no concurrency bound
**Location:** `aesop_studio/server.py:56–59, 93–98, 258–267, 470–475`; `aesop_studio/tasks.py:167–168, 188–189`

**Failure scenario:** Clients open many connections and stop partway through request headers or bodies. No socket deadline is configured, and `ThreadingHTTPServer` creates an unbounded number of handler threads. Separately, repeated chat requests can create unbounded provider workers/processes because only agent tasks have an ownership check.

**Minimal fix:** Set accepted-socket read/write deadlines and bound concurrent handlers. Add a global task/process concurrency limit with bounded queuing or explicit rejection.

### 17. Medium — Chat and verification temporary directories are never removed
**Location:** `aesop_studio/tasks.py:137`; `aesop_studio/providers.py:96–113`

**Failure scenario:** Every chat—including API calls and unusable routes—creates a temporary directory. Live verification does likewise. No cleanup path removes these directories or anything providers put inside them. Repeated usage accumulates files indefinitely in the Windows temporary directory.

**Minimal fix:** Avoid creating a sandbox for API-only calls. Remove CLI sandboxes after confirmed process-tree cleanup, including failure paths, and perform conservative startup cleanup for abandoned owned sandboxes.

### 18. Medium — Chat dispatch can succeed without a durable assistant-message link
**Location:** `aesop_studio/services.py:202–208`

**Failure scenario:** `sup.create()` starts the provider before the assistant message containing `task_id` is inserted. A crash or database write failure in that interval leaves a running or billed task with no assistant message to resolve. Chat history loses the result linkage, and retrying can dispatch duplicate work.

**Minimal fix:** Separate task preparation from dispatch. Atomically persist the user message, assistant placeholder, and task association first; launch only after commit. Reconcile committed-but-undispatched work without automatically replaying uncertain dispatches.

### 19. Medium — Concurrent memory corrections leave conflicting current records
**Location:** `aesop_studio/services.py:337–344`

**Failure scenario:** Two requests read the same memory row and each inserts a replacement marked `current`. Both then update the old row; the last update wins its `superseded_by`, but both replacements remain current. A crash between insertion and supersession similarly leaves the old and new versions current.

**Minimal fix:** Perform lookup, replacement insertion, and supersession in one transaction. Require the old record to still be current using a conditional update, and return a conflict if another correction already superseded it.
