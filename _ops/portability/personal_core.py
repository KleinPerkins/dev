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
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import FileLock, PortabilityError, SafetyError, _rename_noreplace
from personal_dev_skills import DevSkillRelease
from personal_package_files import physical_path, seal_directories, verify_file, verify_skill_tree
import personal_local_jobs


REVISION = "1afae724d8e7d42110d3d9670d85a467c436935c"
SOURCE = f"https://raw.githubusercontent.com/KleinPerkins/skills/{REVISION}/global/skills/capability"
# Public source bytes and Git executable bits. No upstream installer is executed.
FILES = {
    "SKILL.md": (7146, "62012d84b2e6cde86e5488c7c419c23fc3cfa88d70fe084e9dd7bcec12a608be", False),
    "install.sh": (2120, "28a280abbe0e2079ed670d6ba7aefe4e130b28c3ebd6210e8db78ecfee3340f9", True),
    "meta.yml": (506, "f84a3d999eb5d79f606e0f6656b89e6d83bf8d650c7f23ef00da08fefd077c48", False),
}
DESIGN_RELEASE = json.loads(Path(__file__).with_name("personal-design-skills.json").read_bytes())
ISOKIT_RELEASE = json.loads(Path(__file__).with_name("personal-isokit.json").read_bytes())
AUTHORING_RELEASE = json.loads(Path(__file__).with_name("personal-authoring-skills.json").read_bytes())
LOCAL_JOBS_RELEASE = json.loads(Path(__file__).with_name("personal-local-jobs.json").read_bytes())
SAVE_GAME_RELEASE = json.loads(Path(__file__).with_name("personal-save-game.json").read_bytes())


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


def verify_skill_package(directory, release):
    physical_path(directory)
    names = {directory.name}
    notice = release.get("notice")
    if notice:
        names.add(notice["name"])
        verify_file(directory.parent / notice["name"], notice["length"], notice["sha256"], (0o400, 0o600))
    if {p.name for p in directory.parent.iterdir()} != names:
        raise ValueError(f"unexpected package contents for {directory.name}")
    verify_selected_skill(directory, release, checkout=False)


def write_skill_package(stage, release):
    name = stage.name
    collection = "local" if "runtime" in release else "global"
    source = f"https://raw.githubusercontent.com/KleinPerkins/skills/{release['revision']}/{collection}"
    notice = release.get("notice")
    if notice:
        notice_path = stage.parent / notice["name"]
        notice_path.write_bytes(read_url(f"{source}/{notice['name']}", notice["length"]))
        notice_path.chmod(0o400)
    files = release["skills"][name]
    for relative, (mode, length, _) in files.items():
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_url(f"{source}/skills/{name}/{relative}", length))
        path.chmod(0o500 if mode == "100755" else 0o400)
    if "runtime" in release:
        # Verify the complete owner script, lockfile and other source before running it.
        verify_skill_tree(stage, files, checkout=True)
        provision_isokit(stage)
        dependency = verify_isokit_runtime(stage, release["runtime"], checkout=True)
        for relative, (mode, _, _) in release["runtime"].items():
            (dependency / relative).chmod(0o500 if mode == "100755" else 0o400)
        seal_directories(dependency, release["runtime"])
        modules = dependency.parent
        (modules / ".package-lock.json").chmod(0o400)
        (modules / ".bin").chmod(0o500)
        modules.chmod(0o500)
    if "pyyaml" in release:
        dependency = release["pyyaml"]
        personal_local_jobs.provision(stage, dependency, read_url(dependency["archive"], dependency["length"]))
    seal_directories(stage, files)


def provision_isokit(stage):
    # The published Skills installer provisions its lockfile with lifecycle scripts
    # disabled. Dev owns the one Codex link. Let the operator add browsers separately.
    with tempfile.TemporaryDirectory(prefix=".isokit-home-", dir=stage.parent.parent) as temporary:
        env = {"PATH": os.environ["PATH"], "HOME": temporary, "KP_BOOTSTRAP_MANAGES_EXPOSURE": "1",
               "npm_config_userconfig": os.devnull, "npm_config_globalconfig": str(Path(temporary) / "npmrc"),
               "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}
        try:
            subprocess.run(["/bin/bash", stage / "install.sh", "--apply"], cwd=stage, env=env,
                           check=True, timeout=180)
        except (subprocess.SubprocessError, OSError) as error:
            raise ValueError("IsoKit provisioning failed. Check Node.js 20 or later, npm and registry access.") from error


def verify_isokit_runtime(directory, files, *, checkout):
    modules = directory / "node_modules"
    binaries = modules / ".bin"
    for folder, expected in ((modules, {"playwright-core", ".bin", ".package-lock.json"}),
                             (binaries, {"playwright-core"})):
        mode = folder.lstat().st_mode
        if not stat.S_ISDIR(mode) or (not checkout and stat.S_IMODE(mode) != 0o500):
            raise ValueError(f"IsoKit requires a physical runtime directory at {folder}")
        if {p.name for p in folder.iterdir()} != expected:
            raise ValueError(f"unexpected IsoKit runtime entries at {folder}")
    command = binaries / "playwright-core"
    if not command.is_symlink() or os.readlink(command) != "../playwright-core/cli.js":
        raise ValueError("IsoKit's Playwright command link differs")
    lock = modules / ".package-lock.json"
    info = lock.lstat()
    modes = (0o400, 0o444, 0o600, 0o644) if checkout else (0o400,)
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536 or stat.S_IMODE(info.st_mode) not in modes:
        raise ValueError("IsoKit requires a regular npm installation lock")
    installed = json.loads(lock.read_bytes())
    key = "node_modules/playwright-core"
    expected = json.loads((directory / "package-lock.json").read_bytes())["packages"][key]
    packages = installed.get("packages") if isinstance(installed, dict) else None
    if (not isinstance(packages, dict) or set(packages) != {key} or not isinstance(packages[key], dict)
            or any(packages[key].get(field) != expected[field] for field in ("version", "resolved", "integrity", "bin"))):
        raise ValueError("IsoKit's installed dependency differs from its source lock")
    dependency = modules / "playwright-core"
    verify_skill_tree(dependency, files, checkout=checkout)
    return dependency


def verify_selected_skill(directory, release, *, checkout):
    files = release["skills"][directory.name]
    if "pyyaml" in release:
        extras = personal_local_jobs.output_entries(directory, checkout=checkout)
        verify_skill_tree(directory, files, checkout=checkout, extra_entries=["_ops", *extras])
        personal_local_jobs.verify(directory, release["pyyaml"], checkout=checkout)
        return
    if "runtime" not in release:
        verify_skill_tree(directory, files, checkout=checkout)
        return
    verify_skill_tree(directory, files, checkout=checkout, extra_entries=("node_modules",))
    verify_isokit_runtime(directory, release["runtime"], checkout=checkout)
    probe = ('import {chromium} from "playwright-core"; '
             'if (parseInt(process.versions.node, 10) < 20 || typeof chromium.launch !== "function") process.exit(1)')
    try:
        subprocess.run(["node", "--input-type=module", "-e", probe], cwd=directory, env={"PATH": os.environ["PATH"]},
                       check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.SubprocessError, OSError) as error:
        raise ValueError("IsoKit needs Node.js 20 or later with an importable Playwright Core runtime") from error


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
    checkout: Path | None = None
    verify_checkout: Callable[[], None] | None = None


def checkout_installation(entry, action):
    """Recognize the independently installed Skills checkout without acquiring its link."""
    if entry.checkout is None or not points_to(entry.slot, entry.checkout):
        return None
    if action == "withdraw":
        anchor = entry.control / entry.slot.name
        if os.path.lexists(anchor):
            # The original discovery link is already gone. Like a normal
            # withdrawal, retain its witness and release for offline reuse.
            if not points_to(anchor, entry.release):
                raise ValueError(f"the {entry.label} ownership record changed")
            entry.verify()
            return f"preserved independently installed {entry.label}; verified cached profile release for reuse"
        return f"preserved independently installed {entry.label}"
    before = entry.slot.lstat()
    entry.verify_checkout()
    if not points_to(entry.slot, entry.checkout) or not os.path.samestat(before, entry.slot.lstat()):
        raise ValueError(f"the {entry.label} checkout entry changed during verification")
    if entry.label in ("save-game", "local-jobs"):
        return f"verified {entry.label} from the existing Skills release"
    return f"verified {entry.label} from the existing Skills checkout"


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
        existing = checkout_installation(entry, action)
        if existing:
            return existing
        if not points_to(slot, release):
            raise ValueError(f"the selected Codex home does not expose the pinned {label}")
        entry.verify()
        return f"verified {label} files and Codex entry"

    if action == "withdraw" and not control.exists():
        existing = checkout_installation(entry, action)
        if existing:
            return existing
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
    existing = checkout_installation(entry, action)
    if existing:
        return existing
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


def install_profile_entries(entries, previous):
    # Hold the same per-entry locks as standalone installers throughout
    # recovery, preflight and publication, in stable profile order.
    with ExitStack() as locks:
        for entry in (*previous.values(), *entries):
            physical_path(entry.control).mkdir(parents=True, exist_ok=True)
            locks.enter_context(FileLock(entry.control / "writer.lock"))
        upgrades = {}
        for prior in previous.values():
            recover_withdrawals(prior)
            if points_to(prior.slot, prior.release):
                if not owns_slot(prior.slot, prior.control / prior.slot.name, prior.release):
                    raise ValueError(f"independently installed earlier {prior.label} preserved at {prior.slot}")
                prior.verify()
                upgrades[prior.slot] = prior
        for entry in entries:
            recover_withdrawals(entry)
            if (os.path.lexists(entry.slot) and not points_to(entry.slot, entry.release)
                    and not checkout_installation(entry, "install")
                    and entry.slot not in upgrades):
                raise ValueError(f"the Codex {entry.slot.name} slot is occupied")
            anchor = entry.control / entry.slot.name
            if os.path.lexists(anchor) and not points_to(anchor, entry.release):
                raise ValueError(f"the {entry.label} ownership record changed")
        for entry in entries:
            if entry.checkout is None or not points_to(entry.slot, entry.checkout):
                entry.prepare()
        # Prepare every release before withdrawing a working old link.
        # Withdrawal retains its witness and validates the captured inode.
        for prior in upgrades.values():
            change_entry(prior, "withdraw")
        return [change_entry(entry, "install") for entry in entries]


def withdraw_profile_entries(entries, previous):
    messages = []
    errors = []
    for entry in entries:
        try:
            prior = previous.get(entry.slot)
            if prior and prior.control.exists():
                with FileLock(prior.control / "writer.lock"):
                    recover_withdrawals(prior)
            if prior and points_to(entry.slot, prior.release):
                entry = prior
            if (points_to(entry.slot, entry.release)
                    and not os.path.lexists(entry.control / entry.slot.name)):
                messages.append(f"preserved earlier installation of {entry.slot.name}")
                continue
            messages.append(configure_entry(entry, "withdraw"))
        except (OSError, ValueError, PortabilityError) as exc:
            errors.append(f"{entry.slot.name}: {exc}")
    if errors:
        raise ValueError("\n".join([*messages, *errors]))
    return messages


def configure_profile(home, codex_home, action):
    core = core_entry(home, codex_home)
    entries = [core]
    previous = {}
    for name in ("dev-doctor", "dev-new-repo"):
        slot = core.slot.with_name(name)
        bundle = DevSkillRelease(name, home, slot)
        control = physical_path(core.control / name)
        if bundle.previous:
            # Older installations kept their ownership witness directly in control.
            # Use it to select the original package layout even after withdrawal.
            anchor = control / name
            prior = DevSkillRelease(name, home, anchor if os.path.lexists(anchor) else slot,
                                    release=bundle.previous)
            previous[slot] = SkillEntry(slot, prior.skill, control, name, prior.prepare, prior.verify)
            control = physical_path(control / "releases" / bundle.revision)
        entries.append(SkillEntry(slot, bundle.skill, control, name, bundle.prepare, bundle.verify))
    skills_checkout = home / "dev/capabilities/skills"
    save_game_source = home / ".local/share/save-game/source" / SAVE_GAME_RELEASE["revision"]
    local_jobs_source = home / ".local/share/local-jobs/releases" / LOCAL_JOBS_RELEASE["revision"]
    for release, existing_root in (
        (DESIGN_RELEASE, None),
        (AUTHORING_RELEASE, skills_checkout / "global/skills"),
        (ISOKIT_RELEASE, skills_checkout / "local/skills"),
        (SAVE_GAME_RELEASE, save_game_source / "global/skills"),
        (LOCAL_JOBS_RELEASE, local_jobs_source / "global/skills"),
    ):
        for name in release["skills"]:
            folder = core.release.parent.parent / f"{name}-{release['revision']}" / name
            populate = partial(write_skill_package, release=release)
            verify = partial(verify_skill_package, release=release)
            checkout = existing_root / name if existing_root is not None else None
            verify_checkout = partial(verify_selected_skill, checkout, release, checkout=True) if checkout else None
            entries.append(SkillEntry(core.slot.with_name(name), folder, physical_path(core.control / name),
                                      name, partial(prepare_release, folder, populate, verify),
                                      partial(verify, folder), checkout, verify_checkout))

    if action == "check":
        return [configure_entry(entry, action) for entry in entries]
    if action == "withdraw" and not core.control.exists():
        for entry in entries:
            if (os.path.lexists(entry.slot) and not points_to(entry.slot, entry.release)
                    and not checkout_installation(entry, action)
                    and not (entry.slot in previous and points_to(entry.slot, previous[entry.slot].release))):
                raise ValueError(f"unrecognized entry preserved at {entry.slot}")
        return ["no profile-owned entries to withdraw"]

    core.control.mkdir(parents=True, exist_ok=True)
    with FileLock(core.control / "profile.lock"):
        if action == "install":
            return install_profile_entries(entries, previous)
        return withdraw_profile_entries(entries, previous)


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
