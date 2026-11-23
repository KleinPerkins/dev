"""Provision the core operator playbook in a configured Personal Codex home."""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import FileLock, SafetyError, _rename_noreplace


REVISION = "1afae724d8e7d42110d3d9670d85a467c436935c"
SOURCE = f"https://raw.githubusercontent.com/KleinPerkins/skills/{REVISION}/global/skills/capability"
# Public source bytes and Git executable bits. No upstream installer is executed.
FILES = {
    "SKILL.md": (7146, "62012d84b2e6cde86e5488c7c419c23fc3cfa88d70fe084e9dd7bcec12a608be", False),
    "install.sh": (2120, "28a280abbe0e2079ed670d6ba7aefe4e130b28c3ebd6210e8db78ecfee3340f9", True),
    "meta.yml": (506, "f84a3d999eb5d79f606e0f6656b89e6d83bf8d650c7f23ef00da08fefd077c48", False),
}


def physical_path(path):
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise ValueError(f"expected an absolute path without aliases: {path}")
    return path


def verify_release(directory):
    physical_path(directory)
    if {p.name for p in directory.iterdir()} != FILES.keys():
        raise ValueError("core capability release has missing or unexpected files")
    for name, (length, digest, executable) in FILES.items():
        path = directory / name
        info = path.lstat()
        # Existing Git-mode releases and private copies are both supported.
        modes = (0o700, 0o755) if executable else (0o600, 0o644)
        if (not stat.S_ISREG(info.st_mode) or info.st_size != length
                or stat.S_IMODE(info.st_mode) not in modes
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError(f"core capability release differs from the published {name}")


def fetch_file(name, length):
    with urllib.request.urlopen(f"{SOURCE}/{name}", timeout=30) as response:
        return response.read(length + 1)


def prepare_release(directory):
    if os.path.lexists(directory.parent):
        verify_release(directory)
        return
    releases = physical_path(directory.parent.parent)
    releases.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".core-stage-", dir=releases) as temp:
        bundle = Path(temp) / "release"
        stage = bundle / directory.name
        stage.mkdir(parents=True)
        for name, (length, digest, executable) in FILES.items():
            data = fetch_file(name, length)
            if len(data) != length or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"downloaded {name} differs from the published revision")
            (stage / name).write_bytes(data)
            (stage / name).chmod(0o700 if executable else 0o600)
        verify_release(stage)
        try:
            _rename_noreplace(bundle, directory.parent)
        except SafetyError:
            if not directory.parent.exists():
                raise
            # Another Codex profile on this machine can use the same immutable release.
        verify_release(directory)


def points_to(path, release):
    return path.is_symlink() and os.readlink(path) == str(release)


def owns_slot(slot, anchor, release):
    return (points_to(slot, release) and points_to(anchor, release)
            and os.path.samestat(slot.lstat(), anchor.lstat()))


def finish_withdrawal(parked, slot, anchor, release):
    # Inspect the actual entry captured by the exclusive rename. The hardlink
    # witness keeps the expected inode alive even if the discovery name changes.
    if owns_slot(parked, anchor, release):
        parked.unlink()
        return
    try:
        _rename_noreplace(parked, slot)
    except SafetyError as error:
        raise ValueError(
            f"Withdrawal stopped. The entry captured from {slot} is preserved at {parked}. "
            "When the discovery slot is vacant, rerun --withdraw to restore it."
        ) from error
    raise ValueError(f"Withdrawal stopped. Restored the independently changed entry to {slot}")


def configure(home, codex_home, action):
    slot = physical_path(codex_home / "skills") / "capability"
    releases = physical_path(home / ".local/share/personal-portability/releases")
    release = releases / f"capability-{REVISION}" / "capability"
    control = physical_path(codex_home / "dev-personal-core")
    anchor = control / "capability"
    intent = control / "withdrawal-in-progress"
    parked = control / "recover-capability-entry"

    if action == "check":
        if not points_to(slot, release):
            raise ValueError("the selected Codex home does not expose the pinned core capability")
        verify_release(release)
        return "verified core capability files and Codex entry"

    if action == "withdraw" and not control.exists():
        if os.path.lexists(slot):
            raise ValueError("existing entry has no ownership record for this installer")
        return "core capability entry already absent"

    control.mkdir(parents=True, exist_ok=True)
    with FileLock(control / "writer.lock"):
        if os.path.lexists(intent):
            if not owns_slot(intent, anchor, release):
                raise ValueError(f"unexpected withdrawal record at {intent}")
            if os.path.lexists(parked):
                finish_withdrawal(parked, slot, anchor, release)
            intent.unlink()
        elif os.path.lexists(parked):
            raise ValueError(f"unowned recovery entry at {parked}; preserved")
        if action == "withdraw":
            if not os.path.lexists(slot):
                return "core capability entry already absent"
            if not owns_slot(slot, anchor, release):
                raise ValueError("the Codex entry changed or belongs to another installer")
            os.link(anchor, intent, follow_symlinks=False)
            _rename_noreplace(slot, parked)
            finish_withdrawal(parked, slot, anchor, release)
            intent.unlink()
            return "withdrew the owned Codex entry and kept the versioned release"
        if os.path.lexists(slot):
            if not points_to(slot, release):
                raise ValueError("the Codex capability slot is occupied")
            verify_release(release)
            return "core capability files and Codex entry already present"
        prepare_release(release)
        if not os.path.lexists(anchor):
            anchor.symlink_to(release, target_is_directory=True)
        if not points_to(anchor, release):
            raise ValueError("the core capability ownership record changed")
        slot.parent.mkdir(parents=True, exist_ok=True)
        # Link the ownership witness itself. Equality of the target string alone
        # cannot establish authority to withdraw a pre-existing or replaced link.
        os.link(anchor, slot, follow_symlinks=False)
        if not owns_slot(slot, anchor, release):
            raise ValueError("the new Codex entry could not be verified")
        return "configured core capability for Personal Codex"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_const", const="check", dest="action")
    group.add_argument("--withdraw", action="store_const", const="withdraw", dest="action")
    parser.set_defaults(action="install")
    args = parser.parse_args()
    os.umask(0o077)
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    try:
        print(configure(home, codex_home, args.action))
    except (OSError, ValueError, SafetyError) as error:
        sys.exit(f"personal configuration: {error}")


if __name__ == "__main__":
    main()
