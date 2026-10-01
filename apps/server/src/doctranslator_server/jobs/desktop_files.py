"""Streaming folder discovery and collision-safe publication of user-owned exports."""

import hashlib
import os
import stat
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = frozenset({".txt", ".docx", ".pptx", ".xlsx", ".pdf"})


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    relative: Path
    error: str | None = None


def discover(
    roots: Iterable[Path],
    *,
    excluded: Iterable[Path] = (),
    cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[DiscoveredFile]:
    """Yield incrementally. Never follow junctions/symlinks or fail valid siblings."""
    seen: set[Path] = set()
    excluded_paths = tuple(p.resolve() for p in excluded)

    def visit(path: Path, relative: Path) -> Iterator[DiscoveredFile]:
        if cancelled():
            return
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return
            resolved = path.resolve()
            if resolved in seen or any(resolved.is_relative_to(p) for p in excluded_paths):
                return
            seen.add(resolved)
            if path.is_dir():
                with os.scandir(path) as entries:
                    for entry in entries:
                        if cancelled():
                            return
                        yield from visit(Path(entry.path), relative / entry.name)
            elif path.suffix.lower() not in SUPPORTED:
                yield DiscoveredFile(path, relative, "Unsupported file type")
            else:
                yield DiscoveredFile(path, relative)
        except OSError:
            yield DiscoveredFile(path, relative, "File or folder is not accessible")

    root_names: dict[str, int] = {}
    for root in roots:
        key = root.name.casefold()
        root_names[key] = root_names.get(key, 0) + 1
        label = root.name if root_names[key] == 1 else f"{root.name} ({root_names[key]})"
        yield from visit(root, Path(label))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_file(
    output: Path,
    source: Path,
    destination: Path,
    target: str,
    sha256: str,
    *,
    planned: Path | None = None,
    before_publish: Callable[[Path], None] | None = None,
) -> Path:
    """Verify then publish using an atomic hard-link create (never overwrite).

    The staging file is on the destination volume. A crash cannot expose a partial
    result. Filesystems without atomic hard links fail explicitly instead of
    silently degrading to overwriting a user's file.
    """
    if target not in {"en", "zh", "ja", "es"}:
        raise ValueError("Unsupported target language")
    destination.mkdir(parents=True, exist_ok=True)
    if planned is not None and planned.exists():
        if digest(planned) == sha256:
            return planned
        raise FileExistsError("Previously selected export path now contains a different file")
    fd, name = tempfile.mkstemp(prefix=".lenny-export-", dir=destination)
    stage = Path(name)
    try:
        with os.fdopen(fd, "wb") as sink, output.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                sink.write(block)
            sink.flush()
            os.fsync(sink.fileno())
        if digest(stage) != sha256:
            raise ValueError("Translated file failed integrity verification")
        index = 0
        while True:
            suffix = "" if index == 0 else f" ({index})"
            path = planned or destination / f"{source.stem}.{target}{suffix}{source.suffix}"
            try:
                if before_publish is not None:
                    before_publish(path)
                os.link(stage, path)
                return path
            except FileExistsError:
                if planned is not None:
                    raise
                index += 1
    finally:
        stage.unlink(missing_ok=True)
