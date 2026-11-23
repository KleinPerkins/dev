"""Observe open references to objects in one already admitted personal scaffold on macOS."""
from contextlib import ExitStack
import os
import re
import stat
import subprocess
import sys
import time


def external_hard_links(entries):
    names = {}
    for path, (device, inode, mode, _, links) in entries.items():
        if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            names.setdefault((device, inode), []).append(path)

    result = []
    for paths in names.values():
        links = entries[paths[0]][4]
        if links < len(paths) or any(entries[path][4] != links for path in paths):
            raise ValueError("the number of hard links changed during checkout inspection")
        if links > len(paths):
            result.append({"paths": sorted(paths), "outside_count": links - len(paths)})
    return sorted(result, key=lambda row: row["paths"][0])


def inspect_open_files(root):
    if sys.platform != "darwin":
        raise ValueError("the selected checkout open-file observation requires macOS")
    deadline = time.monotonic() + 45
    device = os.fstat(root).st_dev
    processes = {}
    pending = set()
    groups = 0
    symlinks = 0

    def observe():
        nonlocal groups
        if not pending:
            return
        # Each ID is pinned by an open descriptor in this process until lsof exits.
        # Darwin's /.vol path selects that object even if its directory entry is renamed.
        paths = [f"/.vol/{device}/{ino}" for ino in sorted(pending)]
        try:
            result = subprocess.run(["/usr/sbin/lsof", "-nP", "-F0pfaDi", "--", *paths],
                                    cwd="/", env={"PATH": os.defpath, "LC_ALL": "C"}, capture_output=True,
                                    timeout=max(0, deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("the selected open-file observer could not finish") from exc
        if result.returncode or result.stderr:
            raise ValueError("lsof could not inspect all selected objects")
        own = set()
        pid = None
        for line in result.stdout.splitlines():
            proc = re.fullmatch(rb"p([0-9]+)\x00", line)
            if proc:
                pid = int(proc[1])
                continue
            row = re.fullmatch(rb"f([^\x00]+)\x00a([^\x00]*)\x00D(0x[0-9a-fA-F]+)\x00i([0-9]+)\x00", line)
            if row is None or pid is None:
                raise ValueError("lsof returned an incomplete object observation")
            ino = int(row[4])
            if int(row[3], 16) != device or ino not in pending:
                raise ValueError("lsof returned an object outside the selection")
            if pid == os.getpid():
                own.add(ino)
            else:
                kind = "open-reference"
                if row[1] == b"cwd":
                    kind = "working-directory"
                elif row[2] in (b"w", b"u"):
                    kind = "writable-descriptor"
                processes.setdefault(pid, set()).add(kind)
        if own != pending:
            raise ValueError("lsof did not see the observer's held descriptor for every selected object")
        groups += 1
        pending.clear()
        held.close()

    def pin(fd):
        if os.fstat(fd).st_ino in pending:
            return
        pinned = os.dup(fd)
        held.callback(os.close, pinned)
        pending.add(os.fstat(pinned).st_ino)
        if len(pending) >= 64:
            observe()

    def snapshot(scan):
        entries = {}

        def register(path, info):
            if len(entries) >= 50000 or time.monotonic() >= deadline:
                raise ValueError("the selected checkout exceeds the open-file inspection limit")
            if info.st_dev != device or info.st_uid != os.getuid():
                raise ValueError("a checkout entry has a different volume or owner")
            entries[path] = (info.st_dev, info.st_ino, info.st_mode, info.st_ctime_ns, info.st_nlink)

        def walk(fd, path, depth):
            nonlocal symlinks
            if depth > 64:
                raise ValueError("the checkout exceeds the open-file directory depth limit")
            if path:
                try:
                    os.stat(".git", dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError("the checkout contains a nested repository")
            if scan:
                pin(fd)
            with os.scandir(fd) as children:
                for child in children:
                    info = child.stat(follow_symlinks=False)
                    relative = os.path.join(path, child.name)
                    register(relative, info)
                    if stat.S_ISLNK(info.st_mode):
                        if scan:
                            symlinks += 1
                        continue
                    directory = stat.S_ISDIR(info.st_mode)
                    if not directory and not stat.S_ISREG(info.st_mode):
                        raise ValueError("the checkout contains a special file")
                    if directory or scan:
                        flags = os.O_DIRECTORY if directory else os.O_EVTONLY
                        selected = os.open(child.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                        try:
                            if not os.path.samestat(info, os.fstat(selected)):
                                raise ValueError("a checkout entry changed during open-file inspection")
                            if directory:
                                walk(selected, relative, depth + 1)
                            else:
                                pin(selected)
                        finally:
                            os.close(selected)

        register("", os.fstat(root))
        walk(root, "", 0)
        return entries

    with ExitStack() as held:
        before = snapshot(True)
        observe()
        if before != snapshot(False):
            raise ValueError("the selected checkout changed during open-file inspection")
    return {"scope": "visible-processes-on-selected-regular-files-and-directories",
            "objects": len({r[:2] for r in before.values() if not stat.S_ISLNK(r[2])}),
            "skipped_symlinks": symlinks, "batches": groups,
            "external_hard_links": external_hard_links(before),
            "processes": [{"pid": pid, "observations": sorted(kinds)} for pid, kinds in sorted(processes.items())]}
