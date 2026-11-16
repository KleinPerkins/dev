#!/usr/bin/env python3
"""Synthetic capability lifecycle only; writes one marked private fixture file."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def read_regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("private unshared fixture file required")
    return path.read_bytes(), (info.st_dev, info.st_ino)


def root_proof(root):
    root = root.absolute()
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ValueError("linked fixture root refused")
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("private operator-owned fixture directory required")
    marker = json.loads(read_regular(root / "fixture-owner.json")[0])
    if (set(marker) != {"schema", "operation_id", "action_sha256"}
            or marker["schema"] != "interoperability/selected-skill-fixture/v1"
            or str(uuid.UUID(marker["operation_id"])) != marker["operation_id"]
            or not re.fullmatch("[0-9a-f]{64}", marker["action_sha256"])):
        raise ValueError("fixture owner marker changed")
    return root


def state(root):
    path = root / "capability-state.json"
    try:
        data, identity = read_regular(path)
    except FileNotFoundError:
        return {"installed": False, "active": False, "install_count": 0, "repair_count": 0}, None
    value = json.loads(data)
    if (set(value) != {"installed", "active", "install_count", "repair_count"}
            or type(value["installed"]) is not bool or type(value["active"]) is not bool
            or type(value["install_count"]) is not int or type(value["repair_count"]) is not int
            or value["install_count"] != 1 or value["repair_count"] not in {0, 1}
            or not value["installed"] or value["active"] != (value["repair_count"] == 1)):
        raise ValueError("foreign or malformed fixture state preserved")
    return value, (identity, hashlib.sha256(data).hexdigest())


def run(root, verb):
    root = root_proof(root)
    value, before = state(root)
    if verb == "describe":
        return {"fixture": True, "verbs": ["describe", "status", "install", "repair", "doctor"], "scope": "synthetic private fixture only"}
    if verb in {"install", "repair"}:
        desired = dict(value)
        if verb == "install" and not value["installed"]:
            desired.update(installed=True, active=False, install_count=1)
        elif verb == "repair" and value["installed"] and not value["active"]:
            desired.update(active=True, repair_count=1)
        elif verb == "repair" and not value["installed"]:
            raise ValueError("install the synthetic fixture first")
        if desired != value:
            path = root / "capability-state.json"
            if before is None:
                with path.open("xb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(canonical(desired))
            else:
                fd, temporary = tempfile.mkstemp(prefix=".fixture-state-", dir=root)
                temporary = Path(temporary)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        os.fchmod(stream.fileno(), 0o600)
                        stream.write(canonical(desired))
                    if state(root)[1] != before:
                        raise ValueError("concurrent fixture edit preserved")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            value, _ = state(root)
    verdict = "Ready" if value["active"] else "Needs repair" if value["installed"] else "Not installed"
    return {"fixture": True, **value, "verdict": verdict}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=("describe", "status", "install", "repair", "doctor"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.root, args.verb), sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"fixture": True, "status": "refused", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
