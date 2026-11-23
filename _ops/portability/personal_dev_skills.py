"""Install and check the two published Dev runtimes used by Personal Codex."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from engine import GitRunner, SafetyError, _rename_noreplace


DEV_REMOTE = "https://github.com/KleinPerkins/dev.git"
DEV_SOURCE = Path(__file__).resolve().parents[2]
RELEASES = json.loads(Path(__file__).with_name("personal-dev-skills.json").read_bytes())
AUTHORITY_CONFIG = f'[core]\n\trepositoryformatversion = 0\n\tbare = false\n[remote "origin"]\n\turl = {DEV_REMOTE}\n'.encode()


class DevSkillRelease:
    def __init__(self, name, home, slot=None):
        self.name = name
        self.revision = RELEASES[name]["revision"]
        self.files = RELEASES[name]["files"]
        store = home / ".local/share/dev-personal-skills"
        self.package = store / "packages" / self.revision
        previous = store / "releases" / self.revision
        skill_path = Path("_ops/skills/personal") / name
        earlier_entry = slot is not None and slot.is_symlink() and os.readlink(slot) == str(previous / skill_path)
        self.root = self.package / "runtime"
        if earlier_entry or (not os.path.lexists(self.package) and os.path.lexists(previous)):
            self.root = previous
        self.skill = self.root / skill_path
        self.git = GitRunner()

    def verify(self, root=None):
        root = self.root if root is None else root
        if root.resolve(strict=True) != root or not root.is_dir():
            raise ValueError(f"{self.name} requires a physical release directory")
        # Inspect only the published files. Reject extra code in a runtime directory.
        directories = {parent for name in self.files for parent in Path(name).parents}
        pending = [Path(".")]
        seen = set()
        while pending:
            relative = pending.pop()
            if self.name == "dev-new-repo" and stat.S_IMODE((root / relative).stat().st_mode) != 0o500:
                raise ValueError("dev-new-repo requires sealed runtime directories")
            for path in (root / relative).iterdir():
                entry = relative / path.name
                info = path.lstat()
                if self.name == "dev-new-repo" and stat.S_ISDIR(info.st_mode) and entry == Path(".git"):
                    continue
                if stat.S_ISDIR(info.st_mode) and entry in directories:
                    pending.append(entry)
                    continue
                record = self.files.get(entry.as_posix())
                if not record or not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"{self.name} contains an unexpected entry: {entry}")
                mode, length, digest = record
                expected_modes = (0o500, 0o700, 0o755) if mode == "100755" else (0o400, 0o600, 0o644)
                if self.name == "dev-new-repo":
                    expected_modes = expected_modes[:1]
                if (info.st_size != length or stat.S_IMODE(info.st_mode) not in expected_modes
                        or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                    raise ValueError(f"{self.name} differs from its released file: {entry}")
                seen.add(entry.as_posix())
        if seen != self.files.keys():
            raise ValueError(f"{self.name} is missing released files")
        # The earlier doctor package is a plain verified export. The creator's
        # Doc-Warden runtime also needs the exact Dev authority as a Git checkout.
        if self.name == "dev-new-repo":
            self.verify_authority(root)

    def authority_files(self):
        pin = (self.revision + "\n").encode()
        return {"HEAD": pin, "shallow": pin, "config": AUTHORITY_CONFIG}

    def verify_authority(self, root):
        # Check the storage layout before Git interprets even one configuration file.
        # The runtime only reads objects from the pinned commit. It needs no index,
        # hooks, symbolic refs, alternates, worktree config or remote helpers.
        metadata = root / ".git"
        fixed = self.authority_files()
        pending = [metadata]
        seen = set()
        while pending:
            directory = pending.pop()
            if not os.path.lexists(directory) or directory.lstat().st_mode != (stat.S_IFDIR | 0o500):
                raise ValueError("dev-new-repo requires a sealed Dev authority directory")
            for path in directory.iterdir():
                relative = path.relative_to(metadata).as_posix()
                mode = path.lstat().st_mode
                if stat.S_ISDIR(mode) and re.fullmatch(r"refs|objects(?:/(?:pack|info|[0-9a-f]{2}))?", relative):
                    pending.append(path)
                elif mode == (stat.S_IFREG | 0o400) and relative in fixed:
                    if path.stat().st_size != len(fixed[relative]) or path.read_bytes() != fixed[relative]:
                        raise ValueError(f"unexpected Dev authority contents: {relative}")
                    seen.add(relative)
                elif mode != (stat.S_IFREG | 0o400) or not re.fullmatch(
                    r"objects/(?:[0-9a-f]{2}/[0-9a-f]{38}|pack/pack-[0-9a-f]{40}\.(?:pack|idx|rev))", relative
                ):
                    raise ValueError(f"unexpected Dev authority entry: {relative}")
        if seen != fixed.keys() or not all((metadata / name).is_dir() for name in ("objects", "refs")):
            raise ValueError("incomplete Dev authority metadata")
        options = ["--no-lazy-fetch", "--no-replace-objects", "-c", "protocol.allow=never"]
        for check in (["cat-file", "-e", self.revision + "^{commit}"],
                      ["fsck", "--full", "--strict", "--no-reflogs", "--no-dangling", self.revision]):
            result = self.git._run([*options, *check], cwd=root, operation="Dev authority integrity",
                                   check=False, timeout=120)
            if result.returncode:
                raise ValueError("dev-new-repo is missing a valid Dev authority object store")

    def prepare(self):
        if self.root.resolve(strict=False) != self.root:
            raise ValueError(f"{self.name} release location contains an alias")
        if os.path.lexists(self.root):
            self.verify()
            return
        if self.root != self.package / "runtime" or os.path.lexists(self.package):
            raise ValueError(f"{self.name} has an incomplete release; preserved")
        self.package.parent.mkdir(parents=True, exist_ok=True)
        # Some macOS versions refuse to rename a read-only directory. Publish
        # its enclosing package atomically with the runtime already sealed.
        with tempfile.TemporaryDirectory(prefix=".dev-skill-", dir=self.package.parent) as temporary:
            package = Path(temporary)
            stage = package / "runtime"
            stage.mkdir(mode=0o700)
            # A normal Dev clone already contains the pinned objects. A shallow
            # clone can fetch just the pinned revision from the public successor.
            local = self.git._run(["--no-lazy-fetch", "--no-replace-objects", "cat-file", "-e",
                                   self.revision + "^{commit}"], cwd=DEV_SOURCE,
                                  operation="Dev release lookup", check=False)
            source = DEV_SOURCE.as_uri() if local.returncode == 0 else DEV_REMOTE
            protocol = "file" if local.returncode == 0 else "https"
            options = ["-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                       "-c", "protocol.allow=never", "-c", f"protocol.{protocol}.allow=always"]
            for command in (
                ["init", "--quiet", "--template="],
                ["remote", "add", "origin", DEV_REMOTE],
                ["fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--depth=1", source, self.revision],
                ["sparse-checkout", "set", "--no-cone", *("/" + name for name in self.files)],
                ["checkout", "--quiet", "--detach", self.revision],
            ):
                self.git._run([*options, *command], cwd=stage, operation=f"{self.name} {command[0]}", timeout=120)
            metadata = stage / ".git"
            if self.name == "dev-new-repo":
                # Rebuild the small read-only Git control directory. Keep only
                # the freshly fetched objects, never the fetch/checkout settings.
                objects = stage / "fetched-objects"
                (metadata / "objects").rename(objects)
                shutil.rmtree(metadata)
                metadata.mkdir()
                objects.rename(metadata / "objects")
                (metadata / "refs").mkdir()
                for name, content in self.authority_files().items():
                    (metadata / name).write_bytes(content)
                for path in metadata.rglob("*"):
                    path.chmod(0o500 if path.is_dir() else 0o400)
                metadata.chmod(0o500)
            else:
                shutil.rmtree(metadata)
            # Keep normal Python imports from adding bytecode to the release.
            directories = set()
            for name, (mode, _, _) in self.files.items():
                (stage / name).chmod(0o500 if mode == "100755" else 0o400)
                directories.update(Path(name).parents)
            for directory in directories:
                (stage / directory).chmod(0o500)
            self.verify(stage)
            try:
                _rename_noreplace(package, self.package)
            except SafetyError:
                if not self.root.is_dir():
                    raise
            self.verify()
