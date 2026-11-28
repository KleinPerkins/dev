"""Check pinned files and the complete directory layout of a Personal skill package."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory


def physical_path(path):
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise ValueError(f"expected an absolute path without aliases: {path}")
    return path


def verify_file(path, length, digest, modes):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size != length
            or stat.S_IMODE(info.st_mode) not in modes
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
        raise ValueError(f"release differs from the published {path.name}")


def _copy_pinned_file(path, target, length, digest, modes, target_mode):
    source_fd = os.open(physical_path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(source_fd, "rb") as source, target.open("xb") as copy:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size != length
                or stat.S_IMODE(info.st_mode) not in modes):
            raise ValueError(f"release differs from the pinned {path.name}")
        measured = hashlib.sha256()
        remaining = length
        while remaining:
            data = source.read(min(remaining, 1024 * 1024))
            if not data:
                raise ValueError(f"release differs from the pinned {path.name}")
            copy.write(data)
            measured.update(data)
            remaining -= len(data)
        if source.read(1) or measured.hexdigest() != digest:
            raise ValueError(f"release differs from the pinned {path.name}")
    target.chmod(target_mode)


@contextmanager
def verified_executable_copy(path, length, digest, *, bundle_files=None):
    """Run the measured bytes from a fresh private directory, away from app updates."""
    path = physical_path(path)
    temporary_root = Path("/tmp").resolve(strict=True)
    info = temporary_root.stat()
    if info.st_uid != 0 or not info.st_mode & stat.S_ISVTX:
        raise ValueError("pinned executables require the protected system temporary directory")
    with TemporaryDirectory(prefix="dev-pinned-executable-", dir=temporary_root) as raw:
        directory = Path(raw).resolve(strict=True)
        executable = directory / path.name
        bundles = {}
        if bundle_files:
            app = path.parents[2]
            bundle = directory / app.name
            executable = bundle / path.relative_to(app)
            bundles = {bundle / relative: (app / relative, size, sha)
                       for relative, (size, sha) in bundle_files.items()}
        for target, (source, size, sha) in bundles.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_pinned_file(source, target, size, sha, (0o400, 0o444, 0o600, 0o644), 0o400)
        executable.parent.mkdir(parents=True, exist_ok=True)
        _copy_pinned_file(path, executable, length, digest, (0o500, 0o555, 0o700, 0o755), 0o500)
        folders = {directory / parent for target in (*bundles, executable)
                   for parent in target.relative_to(directory).parents}
        try:
            for folder in folders:
                folder.chmod(0o500)
            yield executable
        finally:
            for folder in folders:
                folder.chmod(0o700)


def verify_skill_tree(directory, files, *, checkout=False, extra_entries=()):
    physical_path(directory)
    members = {Path(name) for name in files} | {Path(name) for name in extra_entries}
    directories = {parent for name in members for parent in name.parents}
    entries = directories | members
    for relative in sorted(directories, key=lambda path: len(path.parts)):
        folder = directory / relative
        mode = folder.lstat().st_mode
        if not checkout and mode != (stat.S_IFDIR | 0o500):
            raise ValueError(f"{directory.name} requires read-only skill directories")
        if checkout and not stat.S_ISDIR(mode):
            raise ValueError(f"{directory.name} requires physical skill directories")
        expected = {p.name for p in entries if p != relative and p.parent == relative}
        if {p.name for p in folder.iterdir()} != expected:
            raise ValueError(f"unexpected entries in {directory.name}/{relative}")
    for name, (mode, length, digest) in files.items():
        modes = (0o500,) if mode == "100755" else (0o400,)
        if checkout:
            modes += (0o700, 0o755, 0o555) if mode == "100755" else (0o600, 0o644, 0o444)
        verify_file(directory / name, length, digest, modes)


def seal_directories(stage, files):
    for directory in {parent for relative in files for parent in Path(relative).parents}:
        (stage / directory).chmod(0o500)
