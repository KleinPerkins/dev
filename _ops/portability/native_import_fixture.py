"""Bounded synthetic input for native shell qualification; never an installer."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import stat
import sys
import time

TEXT = b"personal-shell-preservation-fixture\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in {"files", "nonzero", "interactive", "cancel"}:
        raise ValueError("one closed synthetic mode is required")
    root = Path.cwd()
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("the caller must supply a private owned disposable cwd")
    started = time.monotonic()

    def expire(_number, _frame):
        raise SystemExit(124)

    signal.signal(signal.SIGALRM, expire)
    signal.alarm(15)
    mode = args[0]
    if mode == "files":
        path = root / "preserved-input.txt"
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600:
                raise ValueError("fixture input must be a private owned regular file")
            raw = os.read(fd, 1024)
        finally:
            os.close(fd)
        if raw != TEXT or platform.system() != "Darwin" or platform.machine() != "arm64":
            raise ValueError("wrong fixture or destination")
        if os.environ.get("MIGRATION_EXEC_FIXTURE") != "fixture-v1":
            raise ValueError("child-only environment binding missing")
        result = {"schema": "personal-portability/native-shell-files/v1", "cwd_matches": True,
                  "native_system": platform.system(), "native_architecture": platform.machine(),
                  "child_scoped_env_matches": True, "preserved_input_sha256": hashlib.sha256(raw).hexdigest(),
                  "preserved_input_inode": before.st_ino, "preserved_input_mode": stat.S_IMODE(before.st_mode)}
        fd = os.open(root / "child-result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(result, output)
            output.write("\n")
        after = path.lstat()
        if (before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns) or path.read_bytes() != raw:
            raise ValueError("synthetic input changed")
        print(json.dumps(result), flush=True)
        return 0
    if mode == "nonzero":
        print("synthetic-stdout-before-error", flush=True)
        print("synthetic-stderr-before-error", file=sys.stderr, flush=True)
        return 17
    if mode == "interactive":
        print("READY-FOR-SYNTHETIC-INPUT", flush=True)
        text = sys.stdin.readline().rstrip("\n")
        if text != "seed-7":
            raise ValueError("wrong synthetic input")
        print(json.dumps({"stdin_sha256": hashlib.sha256(text.encode()).hexdigest(),
                          "stdin_roundtrip_passed": True, "elapsed_seconds": time.monotonic() - started}), flush=True)
        return 0

    def interrupt(_number, _frame):
        print(json.dumps({"native_sigint_received": True, "elapsed_seconds": time.monotonic() - started}), flush=True)
        raise SystemExit(130)

    signal.signal(signal.SIGINT, interrupt)
    print("READY-FOR-SCOPED-CANCEL", flush=True)
    time.sleep(15)
    return 124


if __name__ == "__main__":
    raise SystemExit(main())
