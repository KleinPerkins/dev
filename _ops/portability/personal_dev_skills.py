"""Install and check the two published Dev runtimes used by Personal Codex."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from engine import GitRunner, SafetyError, _rename_noreplace


DEV_REMOTE = "https://github.com/KleinPerkins/dev.git"
DEV_SOURCE = Path(__file__).resolve().parents[2]
RELEASES = json.loads(Path(__file__).with_name("personal-dev-skills.json").read_bytes())


class DevSkillRelease:
    def __init__(self, name, home):
        self.name = name
        self.revision = RELEASES[name]["revision"]
        self.files = RELEASES[name]["files"]
        self.root = home / ".local/share/dev-personal-skills/releases" / self.revision
        self.skill = self.root / "_ops/skills/personal" / name
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
            for path in (root / relative).iterdir():
                entry = relative / path.name
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode) and entry == Path(".git"):
                    continue
                if stat.S_ISDIR(info.st_mode) and entry in directories:
                    pending.append(entry)
                    continue
                record = self.files.get(entry.as_posix())
                if not record or not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"{self.name} contains an unexpected entry: {entry}")
                mode, length, digest = record
                expected_modes = (0o500, 0o700, 0o755) if mode == "100755" else (0o400, 0o600, 0o644)
                if (info.st_size != length or stat.S_IMODE(info.st_mode) not in expected_modes
                        or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                    raise ValueError(f"{self.name} differs from its released file: {entry}")
                seen.add(entry.as_posix())
        if seen != self.files.keys():
            raise ValueError(f"{self.name} is missing released files")
        # The earlier doctor package is a plain verified export. The creator's
        # Doc-Warden runtime also needs the exact Dev authority as a Git checkout.
        if self.name == "dev-new-repo" or (root / ".git").exists():
            metadata = root / ".git"
            if (not metadata.is_dir() or metadata.is_symlink()
                    or (metadata / "HEAD").is_symlink() or (metadata / "config").is_symlink()
                    or os.path.lexists(metadata / "commondir")
                    or (metadata / "HEAD").read_bytes() != (self.revision + "\n").encode()
                    or self.git.head(root) != self.revision
                    or self.git.remote_urls(root) != {"origin": DEV_REMOTE}):
                raise ValueError(f"{self.name} has a different Dev authority checkout")
            # A detached HEAD can still name the pin after its objects disappear.
            # Verify the local object store before accepting a Doc-Warden authority.
            options = ["--no-lazy-fetch", "--no-replace-objects", "-c", "protocol.allow=never"]
            for check in (["cat-file", "-e", self.revision + "^{commit}"],
                          ["fsck", "--full", "--strict", "--no-reflogs", "--no-dangling", self.revision]):
                result = self.git._run([*options, *check], cwd=root, operation="Dev authority integrity",
                                       check=False, timeout=120)
                if result.returncode:
                    raise ValueError(f"{self.name} is missing a valid Dev authority object store")

    def prepare(self):
        if self.root.resolve(strict=False) != self.root:
            raise ValueError(f"{self.name} release location contains an alias")
        if os.path.lexists(self.root):
            self.verify()
            return
        self.root.parent.mkdir(parents=True, exist_ok=True)
        # Publish within one directory. macOS permits renaming a sealed sibling
        # here, while a move from a different parent needs a writable release.
        with tempfile.TemporaryDirectory(prefix=".dev-skill-", dir=self.root.parent) as temporary:
            stage = Path(temporary)
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
            self.verify(stage)
            # Keep normal Python imports in this immutable runtime from adding
            # bytecode to the released files. Git metadata remains usable by Doc-Warden.
            directories = set()
            for name, (mode, _, _) in self.files.items():
                (stage / name).chmod(0o500 if mode == "100755" else 0o400)
                directories.update(Path(name).parents)
            for directory in directories:
                (stage / directory).chmod(0o500)
            try:
                _rename_noreplace(stage, self.root)
            except SafetyError:
                if not self.root.is_dir():
                    raise
            self.verify()
