"""Project-folder tree and text-file read/write for the in-app editor.

Every path is resolved with contained_path: never leaves the project's selected root,
never follows symlinks or junctions, and never opens credential-shaped names.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .security import SECRET_FILE_RE, TEXT_EXTS, ScopeError, _is_link, contained_path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    "dist", "build", "out", ".next", ".nuxt", "target", "coverage", ".cache", ".idea", ".gradle",
    ".aesop", ".hg", ".svn", "bin", "obj",
}
MAX_ENTRIES = 400
MAX_DEPTH = 6
MAX_CHARS = 400_000
MAX_BYTES = MAX_CHARS * 4


def _posix(root: Path, full: Path) -> str:
    return full.relative_to(root).as_posix()


def _secret(rel: str) -> bool:
    return bool(SECRET_FILE_RE.search(rel.replace("\\", "/")))


def _is_text_name(name: str) -> bool:
    return Path(name).suffix.lower() in TEXT_EXTS or name in {".gitignore", ".editorconfig", "Makefile", "Dockerfile"}


def _ack_on(store, pid: str) -> bool:
    row = store.one("SELECT v FROM kv WHERE k=?", (f"agent_ack:{pid}",))
    return bool(row and row["v"] == "on")


def _atomic_write(path: Path, data: bytes) -> None:
    """Exclusive temp file in the already-validated parent, then replace. Never write through a pre-existing name."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".aesop-edit-", suffix=".partial")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def list_tree(project: dict, rel: str = "") -> dict:
    """Immediate children of rel ('' = project root), plus a truncated walk for the sidebar."""
    root = Path(project["root"]).resolve(strict=True)
    base = root if not rel else contained_path(root, rel)
    if not base.is_dir() or _is_link(base):
        raise ScopeError("not a folder inside this project")
    entries = []
    truncated = False

    def walk(folder: Path, depth: int) -> None:
        nonlocal truncated
        if len(entries) >= MAX_ENTRIES:
            truncated = True
            return
        try:
            names = sorted(os.listdir(folder), key=lambda n: n.lower())
        except OSError as e:
            raise ScopeError(f"cannot list {folder}: {e}") from e
        dirs, files = [], []
        for name in names:
            if name.startswith(".aesop-edit-"):
                continue
            if name.startswith(".") and name not in {".gitignore", ".editorconfig"}:
                continue
            child = folder / name
            try:
                if _is_link(child):
                    continue
                rel_s = _posix(root, child)
                contained_path(root, rel_s)
                is_dir = child.is_dir()
            except (OSError, ScopeError, ValueError):
                continue
            if is_dir:
                if name.lower() in {d.lower() for d in SKIP_DIRS}:
                    continue
                dirs.append(child)
            else:
                if _secret(rel_s):
                    continue
                files.append(child)
        for child in dirs:
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                return
            rel_s = _posix(root, child)
            entries.append({"path": rel_s, "name": child.name, "kind": "dir",
                            "parent": "" if child.parent == root else _posix(root, child.parent)})
            if depth < MAX_DEPTH:
                walk(child, depth + 1)
        for child in files:
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                return
            rel_s = _posix(root, child)
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            entries.append({"path": rel_s, "name": child.name, "kind": "file", "size": size,
                            "text": _is_text_name(child.name),
                            "parent": "" if child.parent == root else _posix(root, child.parent)})

    walk(base, 0)
    return {"root": str(root), "project_id": project["id"], "entries": entries, "truncated": truncated}


def read_file(project: dict, rel: str) -> dict:
    path = contained_path(project["root"], rel)
    if path.is_dir() or _is_link(path):
        raise ScopeError("not a file inside this project")
    if _secret(_posix(Path(project["root"]).resolve(), path)):
        raise ScopeError("that file is not opened in Studio")
    if not _is_text_name(path.name):
        raise ScopeError("the editor opens text files only")
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ScopeError(f"cannot read {rel}: {e}") from e
    if b"\x00" in data[:8192]:
        raise ScopeError("that file looks binary")
    if len(data) > MAX_BYTES:
        raise ScopeError(f"file is larger than {MAX_CHARS} characters")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ScopeError("that file is not UTF-8 text") from e
    if len(text) > MAX_CHARS:
        raise ScopeError(f"file is larger than {MAX_CHARS} characters")
    return {"path": _posix(Path(project["root"]).resolve(), path), "content": text,
            "chars": len(text), "writable": True}


def write_file(store, project: dict, rel: str, content: str) -> dict:
    if not _ack_on(store, project["id"]):
        raise PermissionError("acknowledge how folder work runs before the editor can save files here")
    if not isinstance(content, str):
        raise ValueError("content must be text")
    if len(content) > MAX_CHARS:
        raise ValueError(f"file is larger than {MAX_CHARS} characters")
    path = contained_path(project["root"], rel)
    if _secret(_posix(Path(project["root"]).resolve(), path)):
        raise ScopeError("that file is not opened in Studio")
    if not _is_text_name(path.name):
        raise ScopeError("the editor writes text files only")
    parent = path.parent
    root = Path(project["root"]).resolve(strict=True)
    if not parent.exists() or not parent.is_dir() or _is_link(parent):
        raise ScopeError("the folder for that file does not exist in this project")
    if parent != root:
        contained_path(root, parent.relative_to(root).as_posix())
    if path.exists() and (path.is_dir() or _is_link(path)):
        raise ScopeError("not a file inside this project")
    try:
        _atomic_write(path, content.encode("utf-8"))
    except OSError as e:
        raise ScopeError(f"cannot write {rel}: {e}") from e
    store.event("editor_save", project["id"], path=_posix(root, path), chars=len(content))
    return {"path": _posix(root, path), "chars": len(content), "saved": True}
