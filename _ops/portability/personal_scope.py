"""Read-only target selection for the exact personal migration manifest.

This is a dependency for personal Dev projections, not an installed doctor,
capability activation, write authority, filesystem sandbox or hostile-user guard.
Select closed repository IDs before touching destination paths. Never enumerate
~/dev, other checkouts, linked worktrees, services, home config or remote state.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat

MANIFEST_SHA256 = 'e6e9bf948d1f664367456fffe06e408a08b50933466022b8b7dc2e30a35bf725'
MANIFEST_RELATIVE = '.local/share/personal-portability/bootstrap-17e962df/manifest.json'
PROJECTS = {
    'KleinPerkins/skills': ('capabilities/skills', 'f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a'),
    'KleinPerkins/kp-mcp': ('capabilities/mcp', 'a34a0f73b93650e4a6abe9c9dff9a2e3eced94cb'),
    'KleinPerkins/awa': ('capabilities/awa', '61c3bf1aa0f70b73644512f2befaafc2b31a6d18'),
    'KleinPerkins/intent-router': ('capabilities/intent-router', '3b9df28df6780178e3e25a9743d5c592aedbd085'),
    'KleinPerkins/operator-voice': ('capabilities/operator-voice', '3f787926467c5e0314f21c4e6bb5d2984ac651b8'),
    'KleinPerkins/sterling': ('personal/sterling', '74c555d62d0eeb32edefba08dd86f33e198183ad'),
    'KleinPerkins/sterling.io': ('personal/sterling.io', 'e83d1ecebf568ffc57602d36fd8b24c38985560f'),
    'KleinPerkins/local-jobs': ('personal/local-jobs', '0c106abea22cf0144d2a7959f384b2d732aff295'),
    'KleinPerkins/pr-automation-controller': ('personal/pr-automation-controller', 'fe9a3a20073e7fd4e2fed078188f50ec4a952c2e'),
    'KleinPerkins/server-guard': ('personal/server-guard', '8b364b616aa639eefdfd25dea417ddb8e150e5f8'),
    'KleinPerkins/doc-warden-canary': ('personal/doc-warden-canary', 'e35d30f9d6dd3b004d56c5744fe6b38102d6bc7a'),
    'KleinPerkins/kp-pr-bot-canary': ('personal/kp-pr-bot-canary', '1c16aeccce2de965c38ee6214daf0632554703b1'),
}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
MAX_FILE_BYTES = 1024 * 1024


def operator_home() -> Path:
    uid = os.getuid()
    if uid == 0 or os.geteuid() != uid:
        raise ValueError('run as the non-root personal operator')
    home = Path(pwd.getpwuid(uid).pw_dir)
    if not home.is_absolute() or Path.home().absolute() != home or '..' in home.parts:
        raise ValueError('HOME must match the operating-system operator home')
    return home


def selected_ids(values=None) -> tuple[str, ...]:
    identifiers = tuple(PROJECTS) if values is None else tuple(values)
    if (not identifiers or any(type(value) is not str or value not in PROJECTS for value in identifiers)
            or len(identifiers) != len(set(identifiers))):
        raise ValueError('select only distinct exact manifest-approved personal repository IDs')
    return identifiers


def relative_parts(value: str) -> tuple[str, ...]:
    if (type(value) is not str or not value or value.startswith(('/', '~'))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('explicit relative child path required')
    parts = tuple(value.split('/'))
    if any(part in {'', '.', '..'} for part in parts):
        raise ValueError('normalized relative child path required')
    return parts


def identity(info: os.stat_result) -> dict:
    return {'device': info.st_dev, 'inode': info.st_ino,
            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid}


def absolute_directory(path: Path) -> int:
    """Return a pinned no-follow directory fd, opening no sibling paths."""
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute lexical directory path required')
    fd = os.open('/', DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def child_directory(parent: int, parts: tuple[str, ...]) -> int:
    fd = os.dup(parent)
    try:
        for part in parts:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            if os.fstat(child).st_uid != os.getuid():
                os.close(child)
                raise ValueError('operator-owned child directory required')
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(parent: int, name: str, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """Bounded read of an owned unshared regular child; refuse visible edits."""
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_FILE_BYTES:
        raise ValueError('bounded positive byte limit required')
    if len(relative_parts(name)) != 1:
        raise ValueError('one child name required')
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
            or before.st_nlink != 1 or before.st_size > max_bytes):
        raise ValueError('bounded operator-owned unshared regular file required')
    fd = os.open(name, FILE_FLAGS, dir_fd=parent)
    try:
        start = os.fstat(fd)
        fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if (not stat.S_ISREG(start.st_mode) or start.st_nlink != 1
                or fields(start) != fields(before)):
            raise ValueError('child identity changed before read')
        content = bytearray()
        while len(content) <= max_bytes:
            block = os.read(fd, min(65536, max_bytes + 1 - len(content)))
            if not block:
                break
            content.extend(block)
        end = os.fstat(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if len(content) > max_bytes or fields(start) != fields(end) or fields(end) != fields(current):
            raise ValueError('child bytes, ownership or path changed during read')
        return bytes(content)
    finally:
        os.close(fd)


def parse_manifest(raw: bytes) -> dict:
    """Validate the closed structural selection after external digest binding."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate manifest key')
            result[key] = value
        return result
    document = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(document, dict) or document.get('schema') != 'personal-portability/manifest/v1'
            or document.get('profile') != 'personal-codex' or not isinstance(document.get('repositories'), list)):
        raise ValueError('exact personal portability manifest schema required')
    rows, seen = {}, set()
    for row in document['repositories']:
        if not isinstance(row, dict) or type(row.get('id')) is not str or row['id'] in seen:
            raise ValueError('distinct repository records required')
        identifier = row['id']
        seen.add(identifier)
        if identifier not in PROJECTS:
            continue  # Metadata only: never derive/open a path for excluded or held rows.
        relative, revision = PROJECTS[identifier]
        if (row.get('path') != relative or row.get('revision') != revision
                or row.get('required') is not True or row.get('disposition') != 'source-only'):
            raise ValueError('approved personal source record changed')
        rows[identifier] = {'id': identifier, 'path': relative, 'revision': revision}
    if set(rows) != set(PROJECTS):
        raise ValueError('all twelve approved personal source records required')
    return rows


class RepositoryView:
    """A caller-owned read-only view. This grants no Git, write or service authority."""
    def __init__(self, fd: int, row: dict, path: Path):
        self._fd, self.row, self.path = fd, dict(row), path
        info = os.fstat(fd)
        if info.st_uid != os.getuid():
            raise ValueError('operator-owned repository directory required')
        self.identity = identity(info)

    def read_file(self, relative: str, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
        parts = relative_parts(relative)
        parent = child_directory(self._fd, parts[:-1])
        try:
            result = read_regular(parent, parts[-1], max_bytes=max_bytes)
            current = child_directory(self._fd, parts[:-1])
            try:
                if identity(os.fstat(current)) != identity(os.fstat(parent)):
                    raise ValueError('child directory path changed during read')
            finally:
                os.close(current)
            return result
        finally:
            os.close(parent)


class PersonalScope:
    def __init__(self, manifest: Path | None = None, *, repositories=None):
        # Reject unknown/ambiguous IDs before even reading the manifest/home.
        self.repositories = selected_ids(repositories)
        self.home = operator_home()
        expected = self.home / MANIFEST_RELATIVE
        manifest = expected if manifest is None else Path(manifest)
        if not manifest.is_absolute() or str(manifest) != str(expected):
            raise ValueError('exact operator-home portability manifest path required')
        parent = absolute_directory(manifest.parent)
        try:
            raw = read_regular(parent, manifest.name)
        finally:
            os.close(parent)
        if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
            raise ValueError('exact approved portability manifest bytes required')
        self._rows = parse_manifest(raw)
        self.manifest = str(manifest)

    def targets(self) -> list[dict]:
        # Selection never stats, resolves, globs or scans any repository.
        return [{**self._rows[identifier], 'absolute_path': str(self.home/'dev'/PROJECTS[identifier][0])}
                for identifier in self.repositories]

    @contextmanager
    def repository(self, identifier: str):
        if type(identifier) is not str or identifier not in self.repositories or identifier not in PROJECTS:
            raise ValueError('repository is outside this exact selected personal scope')
        relative, revision = PROJECTS[identifier]
        row = self._rows[identifier]
        if row != {'id': identifier, 'path': relative, 'revision': revision}:
            raise ValueError('personal source binding changed')
        path = self.home/'dev'/relative
        fd = absolute_directory(path)
        try:
            view = RepositoryView(fd, row, path)
            yield view
            current = absolute_directory(path)
            try:
                if identity(os.fstat(current)) != view.identity:
                    raise ValueError('selected repository path changed while observed')
            finally:
                os.close(current)
        finally:
            os.close(fd)


def inspect(scope: PersonalScope) -> dict:
    observations = []
    for row in scope.targets():
        with scope.repository(row['id']) as repo:
            observations.append({**row, 'directory_identity': repo.identity})
    return {'schema': 'personal-portability/personal-source-scope/v1',
            'manifest_path': scope.manifest, 'manifest_sha256': MANIFEST_SHA256,
            'targets': observations, 'target_count': len(observations),
            'enumerated_roots_or_worktrees': False, 'git_or_network_probes': False,
            'source_pins_or_cleanliness_inspected': False, 'writes': False,
            'doctor_or_native_qualification_proven': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inspect'])
    parser.add_argument('--portability-manifest', type=Path)
    parser.add_argument('--repository', action='append')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(PersonalScope(args.portability_manifest, repositories=args.repository)), sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'refused', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
