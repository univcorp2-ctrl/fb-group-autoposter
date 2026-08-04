"""Safely redact one revoked Telegram token from explicitly named log/result files."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import TextIO


REDACTION = "[REDACTED_TELEGRAM_TOKEN]"
_ALLOWED_TOP_LEVEL = frozenset({"logs", "output"})
_FORBIDDEN_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_ALLOWED_SUFFIXES = frozenset({".err", ".json", ".jsonl", ".log", ".ndjson", ".out", ".txt"})


def _read_token(token_stream: TextIO) -> str:
    token = token_stream.readline().rstrip("\r\n")
    if not token:
        raise ValueError("empty revoked token is refused")
    return token


def _is_reparse_or_symlink(path: Path) -> bool:
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(getattr(info, "st_mode", 0)) or bool(attributes & 0x400)


def _reject_reparse_components(repo_root: Path, candidate: Path) -> None:
    current = repo_root
    for part in candidate.parts:
        current = current / part
        if _is_reparse_or_symlink(current):
            raise ValueError("reparse-point or symlink paths may not be redacted")


def _safe_path(repo_root: Path, relative_path: str) -> tuple[str, Path]:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError("path must be repo-relative and may not traverse")
    if candidate.parts[0] not in _ALLOWED_TOP_LEVEL:
        raise ValueError("only logs or output paths may be redacted")
    if candidate.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError("only approved log/result extensions may be redacted")
    if candidate.name.lower().startswith(".env") or candidate.suffix.lower() in _FORBIDDEN_SUFFIXES:
        raise ValueError("environment and database files may not be redacted")
    resolved_root = repo_root.resolve()
    _reject_reparse_components(resolved_root, candidate)
    resolved = (resolved_root / candidate).resolve()
    approved_roots = ((resolved_root / "logs").resolve(), (resolved_root / "output").resolve())
    if (
        not any(resolved.is_relative_to(root) for root in approved_roots)
        or not resolved.exists()
        or not resolved.is_file()
    ):
        raise ValueError("path must name an existing approved log/result file inside the repository")
    return candidate.as_posix(), resolved


def _replace_atomic(path: Path, before: str, after: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        ) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def redact_paths(repo_root: Path, relative_paths: list[str], *, token_stream: TextIO) -> list[tuple[str, int]]:
    """Replace an exact stdin token only in explicit repo-relative logs/results."""
    token = _read_token(token_stream)
    if not relative_paths:
        raise ValueError("at least one log or result path is required")
    report: list[tuple[str, int]] = []
    for raw_path in relative_paths:
        display_path, path = _safe_path(repo_root, raw_path)
        before = path.read_text(encoding="utf-8")
        count = before.count(token)
        _replace_atomic(path, before, before.replace(token, REDACTION))
        report.append((display_path, count))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Redact a revoked Telegram token from explicit logs/results.")
    parser.add_argument("paths", nargs="+", help="repo-relative paths under logs/ or output/")
    args = parser.parse_args()
    for path, count in redact_paths(Path.cwd(), args.paths, token_stream=sys.stdin):
        print(f"{path}: replacements={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
