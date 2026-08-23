"""Deterministic integrity helpers for local model artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


_DIRECTORY_HASH_DOMAIN = b"grounded-answer-directory-sha256-v1\0"


def resolve_local_directory(
    reference: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> Path | None:
    """Resolve a model reference only when it names an existing local directory.

    Hub identifiers such as ``sentence-transformers/all-MiniLM-L6-v2`` remain
    remote references unless a directory with that exact relative path exists.
    Relative local references are resolved against ``base_dir`` when supplied.
    """

    candidate = Path(reference).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = Path(base_dir).expanduser() / candidate
    try:
        return candidate.resolve(strict=True) if candidate.is_dir() else None
    except OSError:
        return None


def sha256_directory(directory: str | Path) -> str:
    """Hash every regular file in a directory with stable path framing.

    Relative POSIX paths, file sizes, and contents are included in sorted order,
    so renames, additions, removals, and byte changes all alter the digest.
    Symlinks are rejected to keep the artifact boundary self-contained.
    """

    root = Path(directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Artifact path is not a directory: {root}")

    def raise_walk_error(error: OSError) -> None:
        raise error

    files: list[Path] = []
    for current, directory_names, file_names in os.walk(
        root,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            child = current_path / name
            if child.is_symlink():
                raise ValueError(f"Artifact directories must not contain symlinks: {child}")
        for name in file_names:
            child = current_path / name
            if child.is_symlink():
                raise ValueError(f"Artifact directories must not contain symlinks: {child}")
            if not child.is_file():
                raise ValueError(f"Artifact contains a non-regular file: {child}")
            files.append(child)

    if not files:
        raise ValueError(f"Artifact directory contains no files: {root}")

    digest = hashlib.sha256()
    digest.update(_DIRECTORY_HASH_DOMAIN)
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        stat_before = path.stat()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(stat_before.st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        stat_after = path.stat()
        if (
            stat_after.st_size != stat_before.st_size
            or stat_after.st_mtime_ns != stat_before.st_mtime_ns
        ):
            raise RuntimeError(f"Artifact changed while it was being hashed: {path}")
    return digest.hexdigest()
