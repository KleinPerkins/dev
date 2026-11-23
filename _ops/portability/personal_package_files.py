"""Check pinned files and the complete directory layout of a Personal skill package."""

import hashlib
from pathlib import Path
import stat


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
