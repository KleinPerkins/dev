"""Dev-owned projection for an approved Skills collector configuration."""

from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import time

from lib.adapters import normalize_remote, validate_git_pointer
from lib.checkout_admission import CheckoutAdmission, checked_digest
from lib.contracts import INPUT_MAX, Refusal, config, encode, fail, json_load
from lib.deadline import bound_until, deadline as read_deadline
from lib.io_safe import directory, outside_repositories, private_dir, read_at
from lib.receipt_store import install_record, load_qualified_snapshot

from checkout_git_config import verify_git_config
from personal_checkout_inventory import Excluded, Refused
from physical_checkout_binding import pin_checkout


@dataclass(frozen=True)
class Projection:
    version: tuple[str, int, str]
    settings_digest: str
    config_bytes: bytes
    omitted: tuple[tuple[str, str], ...]

    def config_digest(self):
        return sha256(self.config_bytes).hexdigest()

    def manifest_bytes(self):
        return encode({"schema": "dev-skills-inventory-projection/v1", "inventory_version": self.version,
                       "settings_digest": self.settings_digest, "config_digest": self.config_digest(),
                       "omissions": self.omitted})

    def manifest_digest(self):
        return sha256(self.manifest_bytes()).hexdigest()


@dataclass(frozen=True)
class StoredProjection:
    config: Path
    manifest_digest: str


def project_inventory(inventory, expected, trusted_settings, *, deadline):
    """Project owner-approved settings through the current Dev authority.

    The caller must supply the verified owner settings. This function classifies
    only their explicit locations. It neither probes a checkout nor grants an
    operation. The returned bytes are input for the guarded Skills collector.
    """
    settings = config(json_load(trusted_settings, INPUT_MAX))
    paths = tuple(root["path"] for root in settings["roots"])
    if len(paths) != len(set(paths)):
        raise Refused("the Skills projection has duplicate checkout locations")
    admitted, omitted, denied = inventory.enumeration_scope(expected, paths, deadline=deadline)
    roots = []
    for root in settings["roots"]:
        path = root["path"]
        if path not in admitted:
            continue
        if root["scope"] == "unknown" or root["identity"] is None:
            omitted[path] = "collector-scope-unknown"
            continue
        binding = admitted[path]
        provider = f"{binding.provider}:{binding.repository_id}"
        git = {"common_dir": binding.common_directory, "git_dir": binding.git_directory}
        if root["identity"]["provider"] not in (None, provider):
            omitted[path] = "provider-binding-conflict"
            continue
        if root["git"] is not None and root["git"] != git:
            omitted[path] = "git-binding-conflict"
            continue
        try:
            locator = normalize_remote(root["identity"]["remote"])
        except Refusal:
            omitted[path] = "collector-locator-invalid"
            continue
        remote = f"https://{locator}" if locator else None
        roots.append(dict(root, identity={"provider": provider, "remote": remote},
                          git=git if root["git"] is not None else None))
    settings["exclude_paths"] = sorted(set(settings["exclude_paths"]).union(denied))
    settings["roots"] = sorted(roots, key=lambda row: row["key"])
    raw = encode(config(settings))
    if len(raw) > INPUT_MAX:
        fail("bound_exceeded", 3)
    return Projection(tuple(expected), sha256(trusted_settings).hexdigest(), raw, tuple(sorted(omitted.items())))


def store_projection(parent, projection):
    """Publish exact configuration and classification records in private state."""
    base = Path(parent)
    outside_repositories(str(base))
    name = "skills-config-" + projection.config_digest() + ".json"
    manifest = projection.manifest_bytes()
    if len(manifest) > INPUT_MAX:
        fail("bound_exceeded", 3)
    manifest_digest = projection.manifest_digest()
    with directory(str(base)) as fd:
        private_dir(fd)
        records = ((name, projection.config_bytes), ("skills-projection-" + manifest_digest + ".json", manifest))
        for name_to_write, data in records:
            try:
                install_record(fd, name_to_write, data)
            except FileExistsError:
                if read_at(fd, name_to_write, INPUT_MAX, True) != data:
                    fail("unavailable", 3)
                os.fsync(fd)
    return StoredProjection(base / name, manifest_digest)


def load_projection(parent, manifest_digest, expected, settings_digest):
    """Load the exact owner settings/Dev binding before supplying it to Skills."""
    checked_digest(manifest_digest)
    checked_digest(settings_digest)
    outside_repositories(os.fspath(parent))
    with directory(os.fspath(parent)) as fd:
        private_dir(fd)
        manifest = read_at(fd, "skills-projection-" + manifest_digest + ".json", INPUT_MAX, True)
        if sha256(manifest).hexdigest() != manifest_digest:
            fail("unavailable", 3)
        value = json_load(manifest, INPUT_MAX)
        try:
            if (value["schema"] != "dev-skills-inventory-projection/v1"
                    or tuple(value["inventory_version"]) != tuple(expected)
                    or value["settings_digest"] != settings_digest):
                fail("unavailable", 3)
            config_digest = value["config_digest"]
            checked_digest(config_digest)
            raw = read_at(fd, "skills-config-" + config_digest + ".json", INPUT_MAX, True)
            config(json_load(raw, INPUT_MAX))
            omitted = tuple(tuple(item) for item in value["omissions"])
        except (TypeError, KeyError, ValueError):
            fail("unavailable", 3)
    projection = Projection(tuple(expected), settings_digest, raw, omitted)
    if projection.config_digest() != config_digest or projection.manifest_bytes() != manifest:
        fail("unavailable", 3)
    return projection


def linked_relationship(binding, reader):
    if not binding.linked_metadata():
        return
    work = binding.git_directory
    marker = binding.checkout + "/.git"
    try:
        validate_git_pointer(reader.read_file(marker, 4096), binding.checkout, work, prefix="gitdir: ")
        validate_git_pointer(reader.read_file(work + "/commondir", 4096), work, binding.common_directory)
        validate_git_pointer(reader.read_file(work + "/gitdir", 4096), work, marker)
    except Refusal as error:
        if error.code != "source_failed":
            raise
        raise Refused("linked-worktree registration changed") from error


def verify_owner_git_config(binding, reader, owner_config_digests):
    expected = owner_config_digests.get(binding.checkout)
    if expected is not None:
        verify_git_config(binding, reader, expected)


def with_current_checkouts(inventory, expected, checkouts, current_checkouts, physical, use, expires, *,
                           owner_config_digests=None):
    """Keep Dev authority across the exact current checkout validation and result use."""
    owner_config_digests = owner_config_digests or {}
    def read(bindings):
        with bound_until(expires), ExitStack() as stack:
            readers = []
            if physical is not None:
                for binding in bindings:
                    proof = physical.find(binding)
                    metadata = binding.linked_metadata() if binding.checkout in current_checkouts else ()
                    locations = metadata
                    if binding.checkout in owner_config_digests:
                        locations += (("common_directory", binding.common_directory),
                                      ("git_directory", binding.git_directory))
                    reader = stack.enter_context(pin_checkout(binding, proof, locations, expires, recheck=False))
                    readers.append((binding, proof, metadata, reader))

            def verify_current():
                for binding, proof, metadata, reader in readers:
                    reader.verify_directories(proof)
                    if metadata:
                        linked_relationship(binding, reader)
                    verify_owner_git_config(binding, reader, owner_config_digests)

            verify_current()
            return use(verify_current)

    return inventory.commit_bound_index(expected, checkouts, read, deadline=expires,
                                        linked_metadata_checkouts=current_checkouts)


def qualify_current_snapshot(inventory, projection, physical, snapshot, *, owner_config_digests=None):
    """Revalidate currently observed paths without opening retired or stale roots."""
    current_input_keys = {row["key"] for row in snapshot["inputs"] if row["state"] == "current"}
    roots = json_load(projection.config_bytes, INPUT_MAX)["roots"]
    checkouts = tuple(root["path"] for root in roots if "inventory/" + root["key"] in current_input_keys)
    seconds = 2
    expires = time.monotonic() + seconds
    with read_deadline(seconds):
        with_current_checkouts(inventory, projection.version, checkouts, frozenset(checkouts),
                               physical, lambda _: None, expires, owner_config_digests=owner_config_digests)


def guarded_admission(inventory, projection, skills_revision, *, physical=None, clock=time.monotonic,
                      owner_config_digests=None):
    """Connect a verified Skills package to the Dev guards and owner evidence."""
    owner_config_digests = owner_config_digests or {}
    def probe(expected, checkout, locations, collect):
        def bounded_collect(binding, expires):
            with bound_until(expires):
                if physical is None:
                    return collect()
                metadata = binding.linked_metadata()
                allowed = (*locations, *metadata)
                if binding.checkout in owner_config_digests:
                    allowed += (("common_directory", binding.common_directory),
                                ("git_directory", binding.git_directory))
                with pin_checkout(binding, physical.find(binding), allowed, expires) as reader:
                    if metadata:
                        linked_relationship(binding, reader)
                    verify_owner_git_config(binding, reader, owner_config_digests)
                    value = collect(reader)
                    if metadata:
                        linked_relationship(binding, reader)
                    verify_owner_git_config(binding, reader, owner_config_digests)
                    return value
        try:
            return inventory.read_bound(expected, checkout, "enumerate", locations, bounded_collect,
                                        deadline=clock() + 2, include_linked_metadata=physical is not None)
        except Excluded:
            fail("excluded", 3)
        except Refused:
            fail("unavailable", 3)

    def commit_current(expected, checkouts, current_checkouts, publish):
        try:
            return with_current_checkouts(inventory, expected, checkouts, current_checkouts, physical, publish,
                                          clock() + 2, owner_config_digests=owner_config_digests)
        except Refused:
            fail("unavailable", 3)

    def commit(expected, checkouts, publish):
        return commit_current(expected, checkouts, frozenset(), lambda _: publish())

    return CheckoutAdmission(projection.version, projection.config_digest(), projection.manifest_digest(),
                             skills_revision, probe, commit, physical.digest() if physical else None,
                             commit_current if physical is not None else None)


def load_projected_snapshot(cache, inventory, projection, skills_revision):
    """Join the qualified snapshot to its exact owner omission record."""
    authority = guarded_admission(inventory, projection, skills_revision)
    value, receipt = load_qualified_snapshot(cache, authority)
    return value, receipt, projection.omitted


def load_selected_snapshot(cache, inventory, projection, skills_revision, physical, checkout):
    """Verify the current selected binding before using physically qualified observations."""
    authority = guarded_admission(inventory, projection, skills_revision, physical=physical)

    def read(binding, expires):
        with pin_checkout(binding, physical.find(binding), binding.linked_metadata(), expires) as reader:
            linked_relationship(binding, reader)
            value, receipt = load_qualified_snapshot(cache, authority)
            linked_relationship(binding, reader)
            return value, receipt, projection.omitted
    seconds = 2
    expires = time.monotonic() + seconds
    with read_deadline(seconds):
        return inventory.read_bound(projection.version, checkout, "adopt", (("checkout", checkout),),
                                    read, deadline=expires, include_linked_metadata=True)
