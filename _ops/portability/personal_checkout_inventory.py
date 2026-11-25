"""Private Dev checkout allowance and lifecycle reservation store.

The owner supplies validated bindings and identifies its operation. This store
does not discover checkouts, operate on target files, or authorize a source
change on the owner's behalf.
"""

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from secrets import token_hex
import sqlite3
import stat
import time

from personal_scope import FILE_FLAGS, absolute_directory


# Snapshots include the current bindings and the retained lifecycle receipts.
MAX_INVENTORY_BYTES = 32 * 1024 * 1024


class Refused(ValueError):
    """The requested authority or state is unavailable."""


class Excluded(Refused):
    """Live policy or a pending owner operation excludes the target."""

    def __init__(self, message, reason="policy-excluded"):
        super().__init__(message)
        self.reason = reason


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def lexical(path):
    if (not isinstance(path, str) or not path.startswith("/") or "\x00" in path
            or any(part in {"", ".", ".."} for part in path[1:].split("/"))):
        raise Refused("the selected location is not a canonical absolute path")
    return path


def intersects(known, claimed):
    return any(left == right or left.startswith(right + "/") or right.startswith(left + "/")
               for left in known for right in claimed)


@dataclass(frozen=True)
class Binding:
    checkout: str
    git_directory: str
    common_directory: str
    provider: str
    repository_id: int
    clone_id: str
    worktree_id: str
    operations: tuple[str, ...]

    def locations(self):
        return {self.checkout, self.git_directory, self.common_directory}

    def linked_metadata(self):
        if self.git_directory == self.common_directory:
            return ()
        return (("linked_gitfile", self.checkout + "/.git"),
                ("linked_common_pointer", self.git_directory + "/commondir"),
                ("linked_reverse_pointer", self.git_directory + "/gitdir"))

    def validate(self):
        for location in self.locations():
            lexical(location)
        if type(self.repository_id) is not int or self.repository_id < 1:
            raise Refused("the owner binding requires a positive immutable repository ID")
        for identity in (self.provider, self.clone_id, self.worktree_id):
            if not isinstance(identity, str) or not identity.strip():
                raise Refused("the owner binding requires complete identities")
        if (not isinstance(self.operations, (tuple, list)) or not self.operations
                or set(self.operations) - {"adopt", "enumerate"}
                or len(self.operations) != len(set(self.operations))):
            raise Refused("the owner binding has an invalid operation grant")


def _shared_git_location(path, common):
    if path == common:
        return True
    worktree = path.removeprefix(common + "/worktrees/")
    return worktree != path and bool(worktree) and "/" not in worktree


def _bindings_overlap(first, second):
    if first.git_directory == second.git_directory or intersects((first.checkout,), (second.checkout,)):
        return True
    common = first.common_directory
    shared = (first.provider, first.repository_id, first.clone_id, common) == (
        second.provider, second.repository_id, second.clone_id, second.common_directory,
    )
    for owner, other in ((first, second), (second, first)):
        for path in (other.git_directory, other.common_directory):
            if intersects((owner.checkout,), (path,)):
                # A primary checkout may contain its clone's common Git
                # directory and its registered linked-worktree metadata.
                if not (shared and owner.git_directory == common and common.startswith(owner.checkout + "/")
                        and _shared_git_location(path, common)):
                    return True
    for left in (first.git_directory, first.common_directory):
        for right in (second.git_directory, second.common_directory):
            if intersects((left,), (right,)):
                if not (shared and ((left == common and _shared_git_location(right, common))
                                    or (right == common and _shared_git_location(left, common)))):
                    return True
    return False


@dataclass(frozen=True)
class FinishedRefreshScope:
    completed: tuple[str, int, str]
    current: tuple[str, int, str]
    required_checkouts: frozenset[str]
    requires_owner_evidence: bool


@dataclass(frozen=True)
class CurrentOwnerEvidence:
    current: tuple[str, int, str]
    digest: str
    bindings: tuple[Binding, ...]
    record: bytes | None


@dataclass(frozen=True)
class PreparedOwnerEvidence:
    expected: tuple[str, int, str]
    current: tuple[str, int, str]
    completed: tuple[str, int, str] | None
    bindings: tuple[Binding, ...]
    record: bytes


SAFETY = """
CREATE TABLE inventory (only_row INTEGER PRIMARY KEY CHECK (only_row = 1), value TEXT NOT NULL);
CREATE TABLE lifecycle (
    operation TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('requested', 'reserved', 'finished', 'superseded')),
    result TEXT
);
"""


class Inventory:
    def __init__(self, directory):
        self.directory = Path(directory)
        self._directory_identity = None
        with self._state_directory() as parent:
            info = os.fstat(parent)
            self._directory_identity = (info.st_dev, info.st_ino)
        self.database = self.directory / "checkout-inventory.sqlite"

    @contextmanager
    def _state_directory(self):
        try:
            parent = absolute_directory(self.directory)
        except (OSError, ValueError) as error:
            raise Refused("Dev inventory requires its physical owner-only state directory") from error
        try:
            info = os.fstat(parent)
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
                    or self._directory_identity not in (None, (info.st_dev, info.st_ino))):
                raise Refused("Dev inventory requires its physical owner-only state directory")
            yield parent
        finally:
            os.close(parent)

    def initialize(self, machine, policy, denied_roots, bindings):
        if any(not isinstance(value, str) or not value.strip() for value in (machine, policy)):
            raise Refused("the machine and current Dev policy revision are required")
        denied_roots = sorted({lexical(root) for root in denied_roots})
        rows = {}
        for binding in bindings:
            if binding.checkout in rows:
                raise Refused("a checkout identity is ambiguous")
            rows[binding.checkout] = asdict(binding)
        self._validate_bindings(rows, denied_roots)
        state = dict(schema="dev-checkout-inventory/v1", machine=machine, policy=policy,
                     denied_roots=denied_roots, generation=1, bindings=rows, pending={})
        with self._gate(time.monotonic() + 2), self._state_directory() as parent:
            if self._entry(parent, self.database.name) is not None:
                raise Refused("the checkout inventory already exists")
            stage = "checkout-inventory.initializing.sqlite"
            if self._entry(parent, stage) is not None:
                raise Refused("an interrupted inventory initialization needs reconciliation")
            with self._memory() as db:
                db.executescript(SAFETY)
                db.execute("INSERT INTO inventory VALUES (1, ?)", (canonical(state),))
                db.commit()
                self._publish(parent, db, stage, previous=None)
        return self._version(state)

    @staticmethod
    def _entry(parent, name):
        try:
            return os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None

    @staticmethod
    def _database_identity(info):
        if info is None:
            return None
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _database_bytes(self, parent):
        name = self.database.name
        try:
            if any(self._entry(parent, name + suffix) is not None for suffix in ("-journal", "-wal")):
                raise Refused("Dev inventory has a legacy SQLite journal that needs reconciliation")
            with os.fdopen(os.open(name, FILE_FLAGS, dir_fd=parent), "rb") as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink > 1 or stat.S_IMODE(info.st_mode) != 0o600):
                    raise Refused("invalid Dev inventory database")
                if info.st_size > MAX_INVENTORY_BYTES:
                    raise Refused("Dev inventory database exceeds its size limit")
                before = self._database_identity(info)
                raw = source.read(info.st_size + 1)
                after = os.fstat(source.fileno())
                if (len(raw) != info.st_size or after.st_nlink > 1
                        or (after.st_mode, after.st_uid, after.st_size, after.st_mtime_ns)
                        != (info.st_mode, info.st_uid, info.st_size, info.st_mtime_ns)):
                    raise Refused("Dev inventory database changed during its read")
        except OSError as error:
            raise Refused("Dev inventory could not be opened safely") from error
        return raw, before

    @staticmethod
    @contextmanager
    def _memory():
        try:
            with closing(sqlite3.connect(":memory:")) as db:
                if not hasattr(db, "serialize") or not hasattr(db, "deserialize"):
                    raise Refused("Dev inventory requires SQLite serialize and deserialize support")
                db.execute("PRAGMA trusted_schema=OFF")
                yield db
        except sqlite3.Error as error:
            raise Refused("Dev inventory transaction did not complete") from error

    @contextmanager
    def _open(self):
        # SQLite never reopens an inventory pathname. A read uses one immutable
        # snapshot even if a writer publishes the next generation concurrently.
        with self._state_directory() as parent, self._memory() as db:
            raw, _ = self._database_bytes(parent)
            db.deserialize(raw)
            db.execute("PRAGMA query_only=ON")
            yield db

    @contextmanager
    def _update(self, deadline):
        # Recording an intent must be possible while a reader holds the checkout
        # guard. A separate short lock serializes snapshot writers.
        lock_deadline = min(deadline, time.monotonic() + 0.25)
        with self._state_directory() as parent, self._lock(parent, "inventory-write.lock", lock_deadline), self._memory() as db:
            raw, before = self._database_bytes(parent)
            db.deserialize(raw)
            db.execute("BEGIN IMMEDIATE")

            def commit():
                db.commit()
                self._publish(parent, db, ".checkout-inventory-" + token_hex(16), previous=before)

            yield db, commit

    def _publish(self, parent, db, stage, *, previous):
        page_count, = db.execute("PRAGMA page_count").fetchone()
        page_size, = db.execute("PRAGMA page_size").fetchone()
        if page_count * page_size > MAX_INVENTORY_BYTES:
            raise Refused("Dev inventory database exceeds its size limit")
        name = self.database.name
        created = False
        try:
            fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            created = True
            with os.fdopen(fd, "wb") as target:
                target.write(db.serialize())
                target.flush()
                os.fsync(target.fileno())
            with self._state_directory() as current:
                if not os.path.samestat(os.fstat(parent), os.fstat(current)):
                    raise Refused("Dev inventory directory changed before publication")
            if self._database_identity(self._entry(parent, name)) != previous:
                raise Refused("Dev inventory database changed before publication")
            if previous is None:
                os.link(stage, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                os.unlink(stage, dir_fd=parent)
            else:
                os.replace(stage, name, src_dir_fd=parent, dst_dir_fd=parent)
            created = False
            os.fsync(parent)
        except OSError as error:
            raise Refused("Dev inventory publication did not complete") from error
        finally:
            if created:
                try:
                    os.unlink(stage, dir_fd=parent)
                except FileNotFoundError:
                    pass

    @contextmanager
    def _gate(self, deadline):
        with self._state_directory() as parent, self._lock(parent, "checkout-access.lock", deadline):
            yield

    @staticmethod
    @contextmanager
    def _lock(parent, name, deadline):
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        except OSError as error:
            raise Refused("invalid Dev checkout guard") from error
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise Refused("invalid Dev checkout guard")
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Refused("Dev checkout guard did not become available within the budget")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(0.01, remaining))
                except OSError as error:
                    raise Refused("Dev checkout guard could not be acquired") from error
            current = Inventory._entry(parent, name)
            if current is None or not os.path.samestat(info, current):
                raise Refused("Dev checkout guard changed before access")
            yield
        finally:
            os.close(fd)

    @staticmethod
    def _read(db):
        row = db.execute("SELECT value FROM inventory").fetchone()
        if row is None:
            raise Refused("Dev inventory has no committed snapshot")
        try:
            value = json.loads(row[0])
        except json.JSONDecodeError as error:
            raise Refused("Dev inventory contains an unreadable snapshot") from error
        if not isinstance(value, dict) or value.get("schema") != "dev-checkout-inventory/v1":
            raise Refused("Dev inventory snapshot schema is unavailable")
        return value

    @staticmethod
    def _write(db, state):
        db.execute("UPDATE inventory SET value = ? WHERE only_row = 1", (canonical(state),))

    @staticmethod
    def _version(state):
        return state["policy"], state["generation"], sha256(canonical(state).encode()).hexdigest()

    @staticmethod
    def _check_denied(path, roots):
        if any(path == root or path.startswith(root + "/") for root in roots):
            raise Excluded("Dev policy excludes the selected location")

    def _validate_bindings(self, rows, roots):
        identities, git_directories, common = set(), set(), {}
        checked = []
        for checkout, record in rows.items():
            binding = Binding(**record)
            binding.validate()
            for location in binding.locations():
                self._check_denied(location, roots)
            identity = (binding.provider, binding.repository_id, binding.clone_id)
            key = (identity, binding.worktree_id)
            if (binding.checkout != checkout or key in identities or binding.git_directory in git_directories
                    or common.setdefault(binding.common_directory, identity) != identity):
                raise Refused("a checkout identity is ambiguous")
            if any(_bindings_overlap(binding, other) for other in checked):
                raise Refused("checkout or Git locations overlap")
            checked.append(binding)
            identities.add(key)
            git_directories.add(binding.git_directory)

    @staticmethod
    def _changed_bindings(rows, changes):
        updated = dict(rows)
        for path, binding in changes.items():
            if binding is None:
                updated.pop(path)
            else:
                updated[path] = binding
        return updated

    @staticmethod
    def _check_version(state, expected):
        if not isinstance(expected, (tuple, list)) or Inventory._version(state) != tuple(expected):
            raise Refused("Dev inventory changed; re-read current authority")

    def snapshot(self):
        """Return the exact committed inventory bytes and their version."""
        with self._open() as db:
            state = self._read(db)
        return canonical(state).encode(), self._version(state)

    def operation(self, operation):
        with self._open() as db:
            row = db.execute("SELECT phase, result FROM lifecycle WHERE operation = ?",
                             (operation,)).fetchone()
        if row is None:
            raise Refused("unknown owner lifecycle operation")
        state, raw = row
        result = json.loads(raw) if raw else None
        if result is not None:
            result.pop("owner_record", None)
        return {"phase": state, "result": result}

    def finished_refresh_scope(self, operation):
        """Join a finished operation to one consistent current Dev inventory read."""
        with self._open() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT request, phase, result FROM lifecycle WHERE operation = ?", (operation,)).fetchone()
            if row is None or row[1] != "finished":
                raise Refused("discovery refresh requires a finished Dev lifecycle operation")
            state = self._read(db)
        result = json.loads(row[2])
        completed = tuple(result["version"])
        current = self._version(state)
        if current[1] < completed[1] or (current[1] == completed[1] and current != completed):
            raise Refused("the committed Dev operation cannot be reconciled to current inventory")
        changed = json.loads(row[0])["changes"]
        required = frozenset(path for path in changed if path in state["bindings"]
                             and "enumerate" in state["bindings"][path]["operations"])
        return FinishedRefreshScope(completed, current, required, "owner_record" in result)

    def current_owner_evidence(self, operation, *, deadline):
        """Read the committed evidence reference under the selected Dev admission."""
        with self._gate(deadline), self._open() as db:
            db.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
            db.execute("BEGIN")
            row = db.execute(
                "SELECT request, result FROM lifecycle WHERE operation = ? AND phase = 'finished'", (operation,)
            ).fetchone()
            if row is None:
                raise Refused("the owner evidence requires a committed checkout operation")
            changes = json.loads(row[0])["changes"]
            result = json.loads(row[1])
            digest = result["owner_evidence"]
            if (result["outcome"] != "committed" or not changes or any(value is None for value in changes.values())
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
                raise Refused("the operation has no committed checkout evidence")
            state = self._read(db)
            version = self._version(state)
            completed = tuple(result["version"])
            if version[1] < completed[1] or (version[1] == completed[1] and version != completed):
                raise Refused("the committed evidence cannot be reconciled to current inventory")
            bindings = tuple(self._binding(db, state, path, "enumerate") for path in sorted(changes))
            if any(state["bindings"][path] != change for path, change in changes.items()):
                raise Refused("the owner evidence bindings were superseded")
            operations = db.execute(
                "SELECT request, result FROM lifecycle WHERE phase = 'finished' AND operation != ?", (operation,)
            )
            for request, other_result in operations:
                if time.monotonic() >= deadline:
                    raise Refused("the owner evidence read exceeded its authority budget")
                later = json.loads(other_result)
                if (later["outcome"] == "committed" and later["version"][1] > completed[1]
                        and not changes.keys().isdisjoint(json.loads(request)["changes"])):
                    raise Refused("the owner evidence was superseded for a selected checkout")
            if time.monotonic() >= deadline:
                raise Refused("the owner evidence read exceeded its authority budget")
            record = result.get("owner_record")
            if record is not None:
                if not isinstance(record, str):
                    raise Refused("the durable owner evidence record is unreadable")
                record = record.encode("utf-8")
                if "sha256:" + sha256(record).hexdigest() != digest:
                    raise Refused("the durable owner evidence record differs from its committed digest")
            return CurrentOwnerEvidence(version, digest, bindings, record)

    def _request(self, expected, operation, changes, policy=None, *, prepared_evidence=None):
        if not isinstance(operation, str) or not operation or (not changes and policy is None):
            raise Refused("a lifecycle request needs an operation ID and a requested change")
        with self._update(time.monotonic() + 0.25) as (db, commit):
            request = dict(expected=expected, changes=changes, policy=policy)
            if prepared_evidence is not None:
                request["prepared_evidence"] = prepared_evidence
            prior = db.execute("SELECT request FROM lifecycle WHERE operation = ?", (operation,)).fetchone()
            if prior is not None:
                old = json.loads(prior[0])
                if (old.get("prepared_evidence") != prepared_evidence
                        or any(canonical(old.get(key)) != canonical(value) for key, value in request.items())):
                    raise Refused("the operation ID belongs to a different request")
                return
            state = self._read(db)
            self._check_version(state, expected)
            if prepared_evidence is not None:
                self._validate_reissue_bindings(state, request, prepared_evidence["policy_revision"])
            if policy is None:
                affected = sorted(self._locations(state, changes))
                self._validate_bindings(self._changed_bindings(state["bindings"], changes), state["denied_roots"])
            else:
                if policy["revision"] == state["policy"]:
                    raise Refused("a policy change requires a distinct owner policy revision")
                affected = None
            if self._blocked(db, state, affected):
                raise Refused("an existing owner lifecycle change already claims the location")
            db.execute("INSERT INTO lifecycle VALUES (?, ?, 'requested', NULL)",
                       (operation, canonical(dict(request, locations=affected))))
            commit()

    def _locations(self, state, changes):
        locations = set()
        for checkout, new in changes.items():
            lexical(checkout)
            self._check_denied(checkout, state["denied_roots"])
            before = state["bindings"].get(checkout)
            if new is None and before is None:
                raise Refused("the named checkout has no prior admission")
            for record in (before, new):
                if record is not None:
                    binding = Binding(**record)
                    binding.validate()
                    if binding.checkout != checkout:
                        raise Refused("the new binding differs from the selected checkout path")
                    for location in binding.locations():
                        self._check_denied(location, state["denied_roots"])
                    locations.update(binding.locations())
        return locations

    def _blocked(self, db, state, locations, *, resuming=None):
        def overlaps(other):
            # A policy transition changes the authority for all known and
            # future checkouts, including when the current inventory is empty.
            return locations is None or other is None or intersects(locations, other)
        if any(operation != resuming and overlaps(paths) for operation, paths in state["pending"].items()):
            return True
        version = None
        for operation, raw in db.execute("SELECT operation, request FROM lifecycle WHERE phase = 'requested'"):
            if operation == resuming:
                continue
            request = json.loads(raw)
            if not overlaps(request["locations"]):
                continue
            # A request that lost its input version cannot commit a reservation.
            # Its historical record remains available to the source owner.
            if version is None:
                version = self._version(state)
            if tuple(request["expected"]) == version:
                return True
        return False

    def reserve(self, expected, operation, changes, *, deadline):
        """Queue before waiting for the guard, then commit the affected locations."""
        changes = {path: asdict(binding) if binding else None for path, binding in changes.items()}
        self._request(expected, operation, changes)
        return self._reserve_requested(expected, operation, deadline)

    def reserve_evidence_reissue(self, expected, operation, changes, *, owner_record, physical_binding_digest, deadline):
        """Persist vetted evidence before placing the reissue reservation."""
        text, policy_revision = self._decode_owner_record(operation, owner_record, physical_binding_digest, changes)
        changes = {path: asdict(binding) if binding else None for path, binding in changes.items()}
        self._request(expected, operation, changes,
                      prepared_evidence={"record": text, "policy_revision": policy_revision})
        return self._reserve_requested(expected, operation, deadline)

    def read_prepared_evidence_reissue(self, operation, *, deadline, allow_missing=False):
        """Read the source owner's preparation without opening checkout paths."""
        with self._gate(deadline), self._open() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT request, phase, result FROM lifecycle WHERE operation = ?",
                             (operation,)).fetchone()
            if row is None and allow_missing:
                return None
            if row is None or row[1] == "superseded":
                raise Refused("the operation has no active prepared evidence")
            completed = None
            if row[1] == "finished":
                result = json.loads(row[2])
                if result["outcome"] != "committed":
                    raise Refused("the operation has no active prepared evidence")
                completed = tuple(result["version"])
            request = json.loads(row[0])
            prepared = request.get("prepared_evidence")
            if prepared is None:
                raise Refused("the operation has no active prepared evidence")
            state = self._read(db)
            bindings = tuple(Binding(**request["changes"][path]) for path in sorted(request["changes"]))
            return PreparedOwnerEvidence(tuple(request["expected"]), self._version(state), completed,
                                         bindings, prepared["record"].encode("utf-8"))

    def owner_observation_scope(self, expected, operation, checkouts, *, deadline):
        """Identify the permitted repositories before the owner asks external sources."""
        paths = tuple(sorted(lexical(path) for path in checkouts))
        if not paths or not isinstance(operation, str) or not operation:
            raise Refused("owner observation requires explicit checkouts and an operation ID")
        with self._gate(deadline), self._open() as db:
            db.execute("BEGIN")
            state = self._read(db)
            row = db.execute("SELECT request, phase, result FROM lifecycle WHERE operation = ?", (operation,)).fetchone()
            resuming = None
            if row is None:
                self._check_version(state, expected)
            else:
                raw_request, phase, raw_result = row
                request = json.loads(raw_request)
                prepared = request.get("prepared_evidence")
                if prepared is None or phase not in {"requested", "reserved", "finished"}:
                    raise Refused("the operation has no active prepared evidence")
                current = self._version(state)
                if tuple(expected) not in (tuple(request["expected"]), current):
                    raise Refused("Dev inventory changed; re-read current authority")
                if tuple(sorted(request["changes"])) != paths:
                    raise Refused("the prepared owner evidence differs from the explicit checkout selections")
                self._validate_reissue_bindings(state, request, prepared["policy_revision"])
                if phase == "finished":
                    result = json.loads(raw_result)
                    if result["outcome"] != "committed" or tuple(result["version"]) != current:
                        raise Refused("the completed owner evidence no longer binds current authority")
                elif phase == "requested":
                    self._check_version(state, request["expected"])
                    resuming = operation
                else:
                    resuming = operation
            bindings = tuple(self._binding(db, state, path, "enumerate", resuming=resuming) for path in paths)
            for binding in bindings:
                for _, location in binding.linked_metadata():
                    self._check_denied(location, state["denied_roots"])
            if time.monotonic() >= deadline:
                raise Refused("owner observation scope exceeded its authority budget")
            return bindings

    def resume_prepared_evidence_reissue(self, operation, *, checked_owner_digest, physical_binding_digest, deadline):
        """Resume after the owning caller revalidates the original independent evidence."""
        prepared = self.read_prepared_evidence_reissue(operation, deadline=deadline)
        if "sha256:" + sha256(prepared.record).hexdigest() != checked_owner_digest:
            raise Refused("the revalidated owner record differs from the preparation")
        self._decode_owner_record(operation, prepared.record, physical_binding_digest,
                                  (binding.checkout for binding in prepared.bindings))
        self._reserve_requested(prepared.expected, operation, deadline)
        return self.finish_evidence_reissue(operation, owner_record=prepared.record,
                                            physical_binding_digest=physical_binding_digest, deadline=deadline)

    def abandon_prepared_evidence_request(self, operation, *, checked_owner_digest, owner_reason, deadline):
        """Release a queued evidence request before it has reserved any checkout."""
        if not isinstance(owner_reason, str) or not owner_reason.strip() or len(owner_reason) > 256:
            raise Refused("the source owner must record why the preparation changed")
        with self._gate(deadline), self._update(deadline) as (db, commit):
            row = db.execute("SELECT request FROM lifecycle WHERE operation = ? AND phase = 'requested'",
                             (operation,)).fetchone()
            prepared = json.loads(row[0]).get("prepared_evidence") if row else None
            if prepared is None or "sha256:" + sha256(prepared["record"].encode("utf-8")).hexdigest() != checked_owner_digest:
                raise Refused("the pending request does not match the prepared owner evidence")
            outcome = {"outcome": "abandoned", "owner_evidence": checked_owner_digest, "owner_reason": owner_reason}
            db.execute("UPDATE lifecycle SET phase = 'superseded', result = ? WHERE operation = ?",
                       (canonical(outcome), operation))
            commit()

    def reserve_policy(self, expected, operation, revision, denied_roots, *, deadline):
        """Reserve the whole inventory before the owner changes its policy."""
        if not isinstance(revision, str) or not revision.strip():
            raise Refused("the next owner policy revision is required")
        denied = sorted({lexical(path) for path in denied_roots})
        self._request(expected, operation, {}, {"revision": revision, "denied_roots": denied})
        return self._reserve_requested(expected, operation, deadline)

    def _reserve_requested(self, expected, operation, deadline):
        with self._gate(deadline), self._update(deadline) as (db, commit):
            phase, result, request = db.execute("SELECT phase, result, request FROM lifecycle WHERE operation = ?",
                                                (operation,)).fetchone()
            if phase in {"reserved", "finished"}:
                return tuple(json.loads(result)["reservation"])
            state = self._read(db)
            if phase == "superseded" or self._version(state) != tuple(expected):
                db.execute("UPDATE lifecycle SET phase = 'superseded' WHERE operation = ?", (operation,))
                commit()
                raise Refused("Dev inventory changed before reservation; re-read and submit a new request")
            state["pending"][operation] = json.loads(request)["locations"]
            state["generation"] += 1
            self._write(db, state)
            version = self._version(state)
            db.execute("UPDATE lifecycle SET phase = 'reserved', result = ? WHERE operation = ?",
                       (canonical(dict(reservation=version)), operation))
            commit()
            return version

    def _commit_change(self, state, request, result):
        policy = request.get("policy")
        if policy is not None:
            result["previous_policy"] = dict(revision=state["policy"], denied_roots=state["denied_roots"])
            state["policy"] = policy["revision"]
            state["denied_roots"] = policy["denied_roots"]
            withdrawn = {}
            denied = state["denied_roots"]
            for checkout, record in state["bindings"].items():
                try:
                    for location in Binding(**record).locations():
                        self._check_denied(location, denied)
                except Excluded:
                    withdrawn[checkout] = record
            result["withdrawn_bindings"] = withdrawn
            for checkout in withdrawn:
                state["bindings"].pop(checkout)
        updated = self._changed_bindings(state["bindings"], request["changes"])
        self._validate_bindings(updated, state["denied_roots"])
        state["bindings"] = updated

    def finish(self, operation, *, outcome, owner_evidence, deadline):
        """Finish a reserved operation after the source owner verifies its outcome."""
        if outcome not in {"committed", "rolled-back"} or not isinstance(owner_evidence, str) or not owner_evidence.strip():
            raise Refused("a verified source outcome is required")
        return self._finish(operation, outcome, owner_evidence, deadline)

    def finish_evidence_reissue(self, operation, *, owner_record, physical_binding_digest, deadline):
        """Commit an owner's reissue for existing bindings and retain its exact bytes."""
        if not isinstance(owner_record, bytes) or not 0 < len(owner_record) <= 65536:
            raise Refused("a bounded owner evidence record is required")
        digest = "sha256:" + sha256(owner_record).hexdigest()
        return self._finish(operation, "committed", digest, deadline, owner_record=owner_record,
                            physical_binding_digest=physical_binding_digest)

    @staticmethod
    def _decode_owner_record(operation, owner_record, physical_binding_digest, checkouts):
        from checkout_git_config import owner_config_proofs

        if not isinstance(owner_record, bytes) or not 0 < len(owner_record) <= 65536:
            raise Refused("a bounded owner evidence record is required")
        try:
            text = owner_record.decode("utf-8")
            record = json.loads(text)
            canonical_text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                        allow_nan=False) + "\n"
        except (ValueError, RecursionError) as error:
            raise Refused("a canonical UTF-8 owner evidence record is required") from error
        if text != canonical_text:
            raise Refused("a canonical UTF-8 owner evidence record is required")
        if (not isinstance(record, dict) or record.get("schema") != "dev-checkout-owner-evidence/v1"
                or record.get("operation") != operation):
            raise Refused("the owner evidence does not bind the reserved operation")
        if not isinstance(record.get("physical_binding_digest"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", record["physical_binding_digest"]):
            raise Refused("the owner evidence has no checked physical binding digest")
        if record["physical_binding_digest"] != physical_binding_digest:
            raise Refused("the owner evidence differs from the observed physical bindings")
        policy_revision = record.get("dev_policy_revision")
        if not isinstance(policy_revision, str) or not policy_revision:
            raise Refused("the owner evidence has no current policy revision")
        owner_config_proofs(record, checkouts)
        return text, policy_revision

    @staticmethod
    def _validate_reissue_bindings(state, request, policy_revision):
        if state["policy"] != policy_revision:
            raise Refused("the owner evidence was checked against a different policy revision")
        changes = request["changes"]
        if (request["policy"] is not None or not changes
                or any(value is None or canonical(state["bindings"].get(path)) != canonical(value)
                       or "enumerate" not in value["operations"] for path, value in changes.items())):
            raise Refused("evidence renewal requires unchanged admitted checkout bindings")

    def _finish(self, operation, outcome, owner_evidence, deadline, *, owner_record=None, physical_binding_digest=None):
        with self._gate(deadline), self._update(deadline) as (db, commit):
            row = db.execute("SELECT request, phase, result FROM lifecycle WHERE operation = ?",
                             (operation,)).fetchone()
            if not row or row[1] not in {"reserved", "finished"}:
                raise Refused("the owner operation has no committed reservation")
            raw_request, phase, raw_result = row
            request = json.loads(raw_request)
            record_text, policy_revision = None, None
            if owner_record is not None:
                record_text, policy_revision = self._decode_owner_record(
                    operation, owner_record, physical_binding_digest, request["changes"],
                )
            result = json.loads(raw_result)
            if phase == "finished":
                if ((result["outcome"], result["owner_evidence"]) != (outcome, owner_evidence)
                        or (record_text is not None and result.get("owner_record") != record_text)):
                    raise Refused("the operation already has a different observed outcome")
                return tuple(result["version"])
            state = self._read(db)
            prepared = request.get("prepared_evidence")
            if prepared is not None and outcome == "committed" and record_text != prepared["record"]:
                raise Refused("the completed record must match the prepared owner evidence")
            if record_text is not None:
                self._validate_reissue_bindings(state, request, policy_revision)
                result["owner_record"] = record_text
            if outcome == "committed":
                self._commit_change(state, request, result)
            del state["pending"][operation]
            state["generation"] += 1
            result.update(outcome=outcome, owner_evidence=owner_evidence, version=self._version(state))
            self._write(db, state)
            db.execute("UPDATE lifecycle SET phase = 'finished', result = ? WHERE operation = ?",
                       (canonical(result), operation))
            commit()
            return tuple(result["version"])

    def probe(self, expected, checkout, operation, role, location, callback, *, deadline):
        """Run one caller-bounded target operation while its exact admission is held."""
        def collect(expires):
            return callback(location, expires)
        return self.authorized_read(expected, checkout, operation, ((role, location),), collect,
                                    deadline=deadline)

    def _binding(self, db, state, checkout, operation, *, resuming=None):
        lexical(checkout)
        self._check_denied(checkout, state["denied_roots"])
        record = state["bindings"].get(checkout)
        if record is None or operation not in record["operations"]:
            raise Excluded("Dev has no approval for the selected checkout operation", "operation-not-admitted")
        binding = Binding(**record)
        if any(_bindings_overlap(binding, Binding(**other)) for path, other in state["bindings"].items()
               if path != checkout):
            raise Excluded("checkout or Git locations overlap", "binding-overlap")
        if self._blocked(db, state, binding.locations(), resuming=resuming):
            raise Excluded("an owner lifecycle change is pending for the selected location", "lifecycle-pending")
        return binding

    def enumeration_scope(self, expected, checkouts, *, deadline):
        """Read the exact owner classification for explicit checkout locations only."""
        with self._gate(deadline), self._open() as db:
            state = self._read(db)
            self._check_version(state, expected)
            admitted, omissions = {}, {}
            for checkout in checkouts:
                if time.monotonic() >= deadline:
                    raise Refused("the inventory projection exceeded its authority budget")
                try:
                    admitted[checkout] = self._binding(db, state, checkout, "enumerate")
                except Excluded as error:
                    omissions[checkout] = error.reason
            return admitted, omissions, tuple(state["denied_roots"])

    def authorized_read(self, expected, checkout, operation, locations, collect, *, deadline):
        """Bind a single bounded read of declared checkout, Git, or metadata locations."""
        def read(_, expires):
            return collect(expires)
        return self.read_bound(expected, checkout, operation, locations, read, deadline=deadline)

    def read_bound(self, expected, checkout, operation, locations, collect, *, deadline, include_linked_metadata=False):
        """Expose the current verified inventory row only while its guard is held."""
        if not locations:
            raise Refused("checkout probes require named locations")
        with self._gate(deadline), self._open() as db:
            state = self._read(db)
            self._check_version(state, expected)
            binding = self._binding(db, state, checkout, operation)
            if include_linked_metadata:
                locations = (*locations, *binding.linked_metadata())
            for role, location in locations:
                lexical(location)
                self._check_denied(location, state["denied_roots"])
                if role == "source":
                    if operation != "enumerate" or not location.startswith(binding.checkout + "/"):
                        raise Excluded("the declared source is outside the permitted checkout")
                    if intersects((location,), (binding.checkout + "/.git", binding.git_directory,
                                                binding.common_directory)):
                        raise Excluded("Git metadata is outside the checkout source scope")
                elif (role, location) in binding.linked_metadata():
                    continue
                elif role not in {"checkout", "git_directory", "common_directory"} or getattr(binding, role) != location:
                    raise Excluded("Dev has no approval for the selected location")
            if time.monotonic() >= deadline:
                raise Refused("checkout probe budget expired before target access")
            return collect(binding, deadline)

    def commit_index(self, expected, checkouts, commit, *, deadline):
        """Reconcile every contributing checkout before replacing the Skills snapshot."""
        return self.commit_bound_index(expected, checkouts, lambda _: commit(), deadline=deadline)

    def commit_bound_index(self, expected, checkouts, commit, *, deadline, linked_metadata_checkouts=frozenset()):
        with self._gate(deadline), self._open() as db:
            state = self._read(db)
            self._check_version(state, expected)
            bindings = tuple(self._binding(db, state, checkout, "enumerate") for checkout in checkouts)
            if not linked_metadata_checkouts <= {binding.checkout for binding in bindings}:
                raise Refused("linked metadata check is outside the contributing checkout scope")
            for binding in bindings:
                if binding.checkout in linked_metadata_checkouts:
                    for _, path in binding.linked_metadata():
                        self._check_denied(path, state["denied_roots"])
            if time.monotonic() >= deadline:
                raise Refused("the inventory changed or the publication budget expired")
            return commit(bindings)
