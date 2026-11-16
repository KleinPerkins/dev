#!/usr/bin/env python3
"""Deterministic subprocess fixture for manifest-verification runner tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _append(path: str, value: str) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"{value}\n")


def main() -> int:
    action = sys.argv[1]
    if action == "success":
        print(sys.argv[2])
        return 0
    if action == "failure":
        print(sys.argv[2], file=sys.stderr)
        return int(sys.argv[3])
    if action == "record-order":
        _append(sys.argv[2], sys.argv[3])
        print(sys.argv[4])
        return 0
    if action == "record-environment":
        Path(sys.argv[2]).write_text(
            "\n".join(sorted(os.environ)) + "\n",
            encoding="utf-8",
        )
        print(sys.argv[3])
        return 0
    if action == "create-bytecode":
        residue = Path.cwd() / "__pycache__"
        residue.mkdir()
        (residue / "privacy-sentinel.pyc").write_bytes(b"privacy-sentinel")
        print(sys.argv[2])
        return 0
    if action == "allocate-memory":
        allocation = bytearray(int(sys.argv[2]) * 1024 * 1024)
        allocation[0] = 1
        print(sys.argv[3], flush=True)
        time.sleep(300)
        return 0
    if action == "open-many":
        handles = []
        try:
            for _index in range(int(sys.argv[2])):
                handles.append(Path("/dev/null").open("rb"))
        except OSError:
            for handle in handles:
                handle.close()
            Path(sys.argv[3]).write_text(str(len(handles)), encoding="ascii")
            print(sys.argv[4])
            return 0
        return 29
    if action == "write-large":
        try:
            (Path.cwd() / "bounded-output.bin").write_bytes(
                b"x" * int(sys.argv[2])
            )
        except OSError:
            print(sys.argv[3])
            return 0
        return 28
    if action == "spawn-many":
        children = [
            subprocess.Popen([sys.executable, "-c", "import time;time.sleep(300)"])
            for _index in range(int(sys.argv[2]))
        ]
        Path(sys.argv[3]).write_text(
            "\n".join(str(child.pid) for child in children),
            encoding="ascii",
        )
        print(sys.argv[4], flush=True)
        time.sleep(300)
        return 0
    if action == "record-group":
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import os,sys;"
                    "open(sys.argv[1],'a').write("
                    "'child:%s:%s\\n'%(os.getpid(),os.getpgrp()))"
                ),
                sys.argv[2],
            ]
        )
        _append(sys.argv[2], f"parent:{os.getpid()}:{os.getpgrp()}")
        child.wait()
        print(sys.argv[3])
        return 0
    if action in {"hang", "orphan"}:
        pid_path, privacy_sentinel = sys.argv[2:4]
        child_code = (
            "import os,signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            f"open({pid_path!r},'w').write(str(os.getpid()));"
            f"print({privacy_sentinel!r},flush=True);"
            "time.sleep(300)"
        )
        subprocess.Popen([sys.executable, "-c", child_code])
        if action == "orphan":
            evidence = Path(pid_path)
            deadline = time.monotonic() + 1
            while not evidence.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            print(privacy_sentinel)
            return 0
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print(privacy_sentinel, flush=True)
        time.sleep(300)
        return 0
    if action == "output-flood":
        block = (sys.argv[2] * 4096).encode("utf-8")
        while True:
            os.write(sys.stdout.fileno(), block)
    raise ValueError("unknown fixture action")


if __name__ == "__main__":
    raise SystemExit(main())
