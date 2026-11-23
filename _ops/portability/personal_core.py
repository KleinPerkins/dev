"""Provision the standard operator and repository skills in a Personal Codex home."""

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
import hashlib
import json
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
DESIGN_RELEASE = json.loads(Path(__file__).with_name("personal-design-skills.json").read_bytes())


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


def verify_release(directory):
    physical_path(directory)
    if {p.name for p in directory.iterdir()} != FILES.keys():
        raise ValueError("core capability release has missing or unexpected files")
    for name, (length, digest, executable) in FILES.items():
        path = directory / name
        # Existing Git-mode releases and private copies are both supported.
        modes = (0o700, 0o755) if executable else (0o600, 0o644)
        verify_file(path, length, digest, modes)


def read_url(url, length):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read(length + 1)


def fetch_file(name, length):
    return read_url(f"{SOURCE}/{name}", length)


def write_capability(stage):
    for name, (length, digest, executable) in FILES.items():
        data = fetch_file(name, length)
        if len(data) != length or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"downloaded {name} differs from the published revision")
        (stage / name).write_bytes(data)
        (stage / name).chmod(0o700 if executable else 0o600)


def prepare_release(directory, populate=write_capability, verify=verify_release):
    if os.path.lexists(directory.parent):
        verify(directory)
        return
    releases = physical_path(directory.parent.parent)
    releases.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".core-stage-", dir=releases) as temp:
        bundle = Path(temp) / "release"
        stage = bundle / directory.name
        stage.mkdir(parents=True)
        populate(stage)
        verify(stage)
        try:
            _rename_noreplace(bundle, directory.parent)
        except SafetyError:
            if not directory.parent.exists():
                raise
            # Another Codex profile on this machine can use the same immutable release.
        verify(directory)


def verify_design_skill(directory):
    physical_path(directory)
    files = DESIGN_RELEASE["skills"][directory.name]
    notice = DESIGN_RELEASE["notice"]
    if {p.name for p in directory.parent.iterdir()} != {directory.name, notice["name"]}:
        raise ValueError(f"unexpected package contents for {directory.name}")
    verify_file(directory.parent / notice["name"], notice["length"], notice["sha256"], (0o400, 0o600))
    directories = {parent for name in files for parent in Path(name).parents}
    entries = directories | {Path(name) for name in files}
    for relative in sorted(directories, key=lambda path: len(path.parts)):
        folder = directory / relative
        if folder.lstat().st_mode != (stat.S_IFDIR | 0o500):
            raise ValueError(f"{directory.name} requires read-only skill directories")
        expected = {p.name for p in entries if p != relative and p.parent == relative}
        if {p.name for p in folder.iterdir()} != expected:
            raise ValueError(f"unexpected entries in {directory.name}/{relative}")
    for name, (mode, length, digest) in files.items():
        verify_file(directory / name, length, digest, (0o500 if mode == "100755" else 0o400,))


def write_design_skill(stage):
    name = stage.name
    source = f"https://raw.githubusercontent.com/KleinPerkins/skills/{DESIGN_RELEASE['revision']}/global"
    notice = DESIGN_RELEASE["notice"]
    notice_path = stage.parent / notice["name"]
    notice_path.write_bytes(read_url(f"{source}/{notice['name']}", notice["length"]))
    notice_path.chmod(0o400)
    files = DESIGN_RELEASE["skills"][name]
    for relative, (mode, length, _) in files.items():
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_url(f"{source}/skills/{name}/{relative}", length))
        path.chmod(0o500 if mode == "100755" else 0o400)
    for directory in {parent for relative in files for parent in Path(relative).parents}:
        (stage / directory).chmod(0o500)


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

    if action == "check":
        physical_path(control / "withdrawals")
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
        recover_withdrawals(entry)
        return change_entry(entry, action)


def recover_withdrawals(entry):
    history = physical_path(entry.control / "withdrawals")
    if history.exists():
        if not history.is_dir():
            raise ValueError(f"invalid withdrawal history for {entry.label}")
        for operation in sorted(history.glob("withdraw-*")):
            finish_withdrawal(operation, entry.slot, entry.control / entry.slot.name, entry.release)


def change_entry(entry, action):
    slot, release, control = entry.slot, entry.release, entry.control
    label = entry.label
    anchor = control / slot.name
    history = control / "withdrawals"
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
        slot = core.slot.with_name(name)
        bundle = DevSkillRelease(name, home, slot)
        entries.append(SkillEntry(slot, bundle.skill,
                                  physical_path(core.control / name), name, bundle.prepare, bundle.verify))
    for name in DESIGN_RELEASE["skills"]:
        folder = core.release.parent.parent / f"{name}-{DESIGN_RELEASE['revision']}" / name
        entries.append(SkillEntry(core.slot.with_name(name), folder, physical_path(core.control / name),
                                  name, partial(prepare_release, folder, write_design_skill, verify_design_skill),
                                  partial(verify_design_skill, folder)))

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
            # Hold the same per-entry locks as standalone installers throughout
            # recovery, preflight and publication, in stable profile order.
            with ExitStack() as locks:
                for entry in entries:
                    physical_path(entry.control).mkdir(parents=True, exist_ok=True)
                    locks.enter_context(FileLock(entry.control / "writer.lock"))
                for entry in entries:
                    recover_withdrawals(entry)
                    if os.path.lexists(entry.slot) and not points_to(entry.slot, entry.release):
                        raise ValueError(f"the Codex {entry.slot.name} slot is occupied")
                    anchor = entry.control / entry.slot.name
                    if os.path.lexists(anchor) and not points_to(anchor, entry.release):
                        raise ValueError(f"the {entry.label} ownership record changed")
                for entry in entries:
                    entry.prepare()
                return [change_entry(entry, action) for entry in entries]
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
