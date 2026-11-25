"""Dev owner evidence and no-follow handles for one already admitted checkout."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import time

from personal_checkout_inventory import Refused, canonical
from personal_scope import absolute_directory, child_directory, read_regular, relative_parts


class PhysicalMismatch(Refused):
    """The checked-out directory no longer matches its owner-verified binding."""


ROLES = ("checkout", "git_directory", "common_directory")


@dataclass(frozen=True)
class OwnerPhysicalBinding:
    provider: str
    repository_id: int
    clone_id: str
    worktree_id: str
    # Each role contains its exact lexical path, device and inode.
    locations: tuple[tuple[str, str, int, int], ...]

    def validate(self, binding):
        identity = (binding.provider, binding.repository_id, binding.clone_id, binding.worktree_id)
        if identity != (self.provider, self.repository_id, self.clone_id, self.worktree_id):
            raise PhysicalMismatch("the physical proof names a different checkout identity")
        if len(self.locations) != len(ROLES) or any(len(row) != 4 for row in self.locations):
            raise PhysicalMismatch("the physical proof has incomplete directory identities")
        expected = tuple((role, getattr(binding, role)) for role in ROLES)
        if tuple(row[:2] for row in self.locations) != expected:
            raise PhysicalMismatch("the physical proof names different checkout or Git locations")
        if any(type(value) is not int or value <= 0 for row in self.locations for value in row[2:]):
            raise PhysicalMismatch("the physical proof has an invalid directory identity")


@dataclass(frozen=True)
class OwnerPhysicalBindings:
    entries: tuple[OwnerPhysicalBinding, ...]

    def digest(self):
        fields = [(p.provider, p.repository_id, p.clone_id, p.worktree_id, p.locations) for p in self.entries]
        return sha256(canonical(sorted(fields)).encode()).hexdigest()

    def find(self, binding):
        matches = [item for item in self.entries if item.locations and item.locations[0][1] == binding.checkout]
        if len(matches) != 1:
            raise PhysicalMismatch("no unique owner physical proof exists for the selected checkout")
        proof, = matches
        proof.validate(binding)
        return proof


class PinnedReader:
    """Expose only declared reads through the verified directory handles."""

    def __init__(self, fds, binding, locations, expires):
        self.fds, self.binding, self.locations, self.expires = fds, binding, set(locations), expires

    def check_budget(self):
        if time.monotonic() >= self.expires:
            raise PhysicalMismatch("checkout access budget expired")

    def verify_directories(self, proof):
        for _, path, device, inode in proof.locations:
            self.check_budget()
            os.close(checked_directory(path, device, inode))

    @contextmanager
    def directory(self, path):
        self.check_budget()
        roles = [r for r in ROLES if (r, path) in self.locations]
        if not roles:
            raise PhysicalMismatch("the collector requested an undeclared directory")
        # Only the duplicate is handed to the caller.
        fd = os.dup(self.fds[roles[0]])
        try:
            yield fd
        finally:
            os.close(fd)

    def read_worktree_config(self, maximum):
        """Read the optional config from the admitted per-worktree Git directory."""
        path = self.binding.git_directory
        if ("git_directory", path) not in self.locations:
            raise PhysicalMismatch("the worktree Git configuration is outside the declared read scope")
        with self.directory(path) as fd:
            try:
                return read_regular(fd, "config.worktree", max_bytes=maximum)
            except FileNotFoundError:
                return None
            except (OSError, ValueError) as error:
                raise PhysicalMismatch("the declared worktree Git configuration could not be read safely") from error

    def read_file(self, path, maximum, private=False):
        self.check_budget()
        b = self.binding
        if private:
            raise PhysicalMismatch("private state reads are outside the checkout guard")
        if ("source", path) in self.locations:
            role = "checkout"
        else:
            fixed = {
                b.checkout + "/.git": ("checkout", ("checkout", b.checkout)),
                b.git_directory + "/commondir": ("git_directory", ("git_directory", b.git_directory)),
                b.common_directory + "/config": ("common_directory", ("common_directory", b.common_directory)),
            }
            linked = dict(b.linked_metadata())
            if linked:
                for metadata_role, directory_role in (("linked_gitfile", "checkout"),
                                                      ("linked_common_pointer", "git_directory"),
                                                      ("linked_reverse_pointer", "git_directory")):
                    declared = (metadata_role, linked[metadata_role])
                    if declared in self.locations:
                        fixed[declared[1]] = (directory_role, declared)
            match = fixed.get(path)
            if match is None:
                raise PhysicalMismatch("the collector requested an undeclared target file")
            role, declared = match
            if declared not in self.locations:
                raise PhysicalMismatch("the collector requested an undeclared target file")
        prefix = getattr(b, role) + "/"
        if not path.startswith(prefix):
            raise PhysicalMismatch("the collector requested a target outside the admitted directory")
        parts = relative_parts(path.removeprefix(prefix))
        try:
            parent = child_directory(self.fds[role], parts[:-1])
            try:
                return read_regular(parent, parts[-1], max_bytes=maximum)
            finally:
                os.close(parent)
        except (OSError, ValueError) as error:
            raise PhysicalMismatch("the declared target file could not be read through the owner binding") from error


def checked_directory(path, device, inode):
    try:
        opened = absolute_directory(Path(path))
    except (ValueError, OSError) as error:
        raise PhysicalMismatch("the physical checkout location cannot be opened safely") from error
    try:
        value = os.fstat(opened)
        if (value.st_dev, value.st_ino, value.st_uid) != (device, inode, os.getuid()):
            raise PhysicalMismatch("the physical checkout location changed")
        return opened
    except BaseException:
        os.close(opened)
        raise


@contextmanager
def pin_checkout(binding, proof, locations, expires, *, recheck=True):
    """Open only exact admitted roles and recheck their bindings after access."""
    proof.validate(binding)
    with ExitStack() as stack:
        fds = {}
        for role, path, device, inode in proof.locations:
            if time.monotonic() >= expires:
                raise PhysicalMismatch("checkout access budget expired")
            fd = checked_directory(path, device, inode)
            stack.callback(os.close, fd)
            fds[role] = fd
        reader = PinnedReader(fds, binding, locations, expires)
        yield reader
        if recheck:
            reader.verify_directories(proof)
