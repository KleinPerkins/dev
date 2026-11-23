"""Provision the standard operator and repository skills in a Personal Codex home."""

import argparse
from dataclasses import dataclass
from functools import partial
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import urllib.request
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import FileLock, PortabilityError, SafetyError, _rename_noreplace
from personal_dev_skills import DevSkillRelease


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


def finish_withdrawal(operation, slot, anchor, release):
    # Receipts and captured entries are append-only. A competing writer can
    # replace a name at any instant, so a successful check never authorizes a
    # subsequent unlink of that name. Keeping the entry also supports recovery.
    physical_path(operation)
    completed = operation / "completed"
    if completed.exists():
        return
    parked = operation / "entry"
    witness = operation / "witness"
    if not owns_slot(witness, anchor, release):
        if os.path.lexists(parked) or os.path.lexists(witness):
            raise ValueError(f"unowned withdrawal record at {operation}; preserved")
        return  # Interrupted before arming; no discovery entry could have moved.
    restored = False
    if os.path.lexists(parked) and not owns_slot(parked, witness, release):
        try:
            _rename_noreplace(parked, slot)
        except SafetyError as error:
            raise ValueError(
                f"Withdrawal stopped. The entry captured from {slot} is preserved at {parked}. "
                "When the discovery slot is vacant, rerun --withdraw to restore it."
            ) from error
        restored = True
    with completed.open("xb"):
        pass
    if restored:
        raise ValueError(f"Withdrawal stopped. Restored the independently changed entry to {slot}")


@dataclass(frozen=True)
class SkillEntry:
    slot: Path
    release: Path
    control: Path
    label: str
    prepare: Callable[[], None]
    verify: Callable[[], None]


def core_entry(home, codex_home):
    slot = physical_path(codex_home / "skills") / "capability"
    releases = physical_path(home / ".local/share/personal-portability/releases")
    release = releases / f"capability-{REVISION}" / "capability"
    return SkillEntry(slot, release, physical_path(codex_home / "dev-personal-core"),
                      "core capability", partial(prepare_release, release), partial(verify_release, release))


def configure(home, codex_home, action):
    return configure_entry(core_entry(home, codex_home), action)


def configure_entry(entry, action):
    slot, release, control = entry.slot, entry.release, entry.control
    label = entry.label
    anchor = control / slot.name
    history = physical_path(control / "withdrawals")

    if action == "check":
        if not points_to(slot, release):
            raise ValueError(f"the selected Codex home does not expose the pinned {label}")
        entry.verify()
        return f"verified {label} files and Codex entry"

    if action == "withdraw" and not control.exists():
        if os.path.lexists(slot):
            raise ValueError("existing entry has no ownership record for this installer")
        return f"{label} entry already absent"

    control.mkdir(parents=True, exist_ok=True)
    with FileLock(control / "writer.lock"):
        if history.exists():
            for operation in sorted(history.glob("withdraw-*")):
                finish_withdrawal(operation, slot, anchor, release)
        if action == "withdraw":
            if not os.path.lexists(slot):
                return f"{label} entry already absent"
            if not owns_slot(slot, anchor, release):
                raise ValueError("the Codex entry changed or belongs to another installer")
            history.mkdir(exist_ok=True)
            operation = Path(tempfile.mkdtemp(prefix="withdraw-", dir=history))
            os.link(anchor, operation / "witness", follow_symlinks=False)
            _rename_noreplace(slot, operation / "entry")
            finish_withdrawal(operation, slot, anchor, release)
            return f"withdrew the owned Codex entry; recovery record: {operation}"
        if os.path.lexists(slot):
            if not points_to(slot, release):
                raise ValueError(f"the Codex {slot.name} slot is occupied")
            entry.verify()
            return f"{label} files and Codex entry already present"
        entry.prepare()
        if not os.path.lexists(anchor):
            anchor.symlink_to(release, target_is_directory=True)
        if not points_to(anchor, release):
            raise ValueError(f"the {label} ownership record changed")
        slot.parent.mkdir(parents=True, exist_ok=True)
        # Link the ownership witness itself. Equality of the target string alone
        # cannot establish authority to withdraw a pre-existing or replaced link.
        os.link(anchor, slot, follow_symlinks=False)
        if not owns_slot(slot, anchor, release):
            raise ValueError("the new Codex entry could not be verified")
        return f"configured {label} for Personal Codex"


def configure_profile(home, codex_home, action):
    core = core_entry(home, codex_home)
    entries = [core]
    for name in ("dev-doctor", "dev-new-repo"):
        bundle = DevSkillRelease(name, home)
        entries.append(SkillEntry(core.slot.with_name(name), bundle.skill,
                                  physical_path(core.control / name), name, bundle.prepare, bundle.verify))

    if action == "check":
        return [configure_entry(entry, action) for entry in entries]
    if action == "withdraw" and not core.control.exists():
        for entry in entries:
            if os.path.lexists(entry.slot) and not points_to(entry.slot, entry.release):
                raise ValueError(f"unrecognized entry preserved at {entry.slot}")
        return ["no profile-owned entries to withdraw"]

    core.control.mkdir(parents=True, exist_ok=True)
    with FileLock(core.control / "profile.lock"):
        if action == "install":
            # Catch conflicts and incomplete downloads before publishing new entries.
            for entry in entries:
                if os.path.lexists(entry.slot) and not points_to(entry.slot, entry.release):
                    raise ValueError(f"the Codex {entry.slot.name} slot is occupied")
            for entry in entries:
                entry.prepare()
        messages = []
        errors = []
        for entry in entries:
            if (action == "withdraw" and points_to(entry.slot, entry.release)
                    and not os.path.lexists(entry.control / entry.slot.name)):
                messages.append(f"preserved earlier installation of {entry.slot.name}")
                continue
            try:
                messages.append(configure_entry(entry, action))
            except (OSError, ValueError, PortabilityError) as exc:
                if action != "withdraw":
                    raise
                errors.append(f"{entry.slot.name}: {exc}")
        if errors:
            raise ValueError("\n".join([*messages, *errors]))
        return messages


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
        print(*configure_profile(home, codex_home, args.action), sep="\n")
    except (OSError, ValueError, PortabilityError) as error:
        sys.exit(f"personal configuration: {error}")


if __name__ == "__main__":
    main()
