from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import Mock, patch

from bind_retirement_inventory import destruction_roots
from checkout_git_config import observe_git_config
from personal_checkout_inventory import Binding, Inventory, Refused


def deadline():
    return time.monotonic() + 3


class CheckoutInventoryTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory(prefix="dev-checkout-inventory-")
        self.addCleanup(work.cleanup)
        self.root = Path(work.name).resolve()
        self.private = self.root / "state"
        self.private.mkdir(mode=0o700)
        self.inventory = Inventory(self.private)
        self.first = self.binding("sample.product", 901)
        self.peer = self.binding("other.product", 902)
        self.denied = str(self.root / "recovery")
        self.version = self.inventory.initialize("test-host", "private-policy-1", [self.denied],
                                                 [self.first, self.peer])
        self.calls = []

    def binding(self, name, identity):
        checkout = str(self.root / name)
        git = checkout + "/.git"
        return Binding(checkout, git, git, "github", identity, "clone-" + name, "primary",
                       ("adopt", "enumerate"))

    def probe(self, binding=None, version=None, *, operation="adopt", role="checkout", location=None):
        binding = binding or self.first
        return self.inventory.probe(
            version or self.version, binding.checkout, operation, role,
            location or getattr(binding, role), lambda path, _: self.calls.append(path), deadline=deadline(),
        )

    def test_checkout_evidence_requires_origin_as_the_selected_remote(self):
        origin = b'[remote "origin"]\n url = git@github.com:KleinPerkins/sample.product.git\n'
        worktree_enabled = b'[extensions]\n worktreeConfig = true\n'
        selectors = (
            b'[remote]\n pushDefault = %s\n',
            b'[branch "feature.with.dots"]\n pushRemote = %s\n',
            b'[branch "feature.with.dots"]\n remote = %s\n',
        )
        reader = Mock()
        reader.read_file.return_value = origin
        reader.read_worktree_config.return_value = None
        self.assertFalse(observe_git_config(self.first, reader, "KleinPerkins/sample.product", deadline()).worktree_enabled)
        reader.read_worktree_config.assert_not_called()
        for selector in selectors:
            for use_worktree in (False, True):
                for remote in (b"origin", b"other", b"Origin"):
                    with self.subTest(selector=selector, use_worktree=use_worktree, remote=remote):
                        setting = selector % remote
                        reader.read_file.return_value = origin + (worktree_enabled if use_worktree else setting)
                        reader.read_worktree_config.return_value = setting if use_worktree else None
                        if remote == b"origin":
                            proof = observe_git_config(self.first, reader, "KleinPerkins/sample.product", deadline())
                            self.assertEqual(proof.worktree_enabled, use_worktree)
                        else:
                            with self.assertRaisesRegex(Refused, "default remote.*origin"):
                                observe_git_config(self.first, reader, "KleinPerkins/sample.product", deadline())

    def test_checkout_evidence_does_not_treat_case_variant_as_origin(self):
        reader = Mock()
        reader.read_file.return_value = b'[remote "Origin"]\n url = git@github.com:KleinPerkins/sample.product.git\n'
        with self.assertRaisesRegex(Refused, "fetch or push endpoint"):
            observe_git_config(self.first, reader, "KleinPerkins/sample.product", deadline())

    def test_exact_operation_and_lexical_refusals(self):
        raw, chosen = self.inventory.snapshot()
        self.assertEqual(chosen, self.version)
        self.assertEqual(chosen[2], sha256(raw).hexdigest())
        self.assertEqual(json.loads(raw)["bindings"][self.first.checkout]["repository_id"], 901)
        self.probe(role="common_directory")
        self.assertEqual(self.calls, [self.first.git_directory])
        for location in (self.denied + "/child", self.first.checkout + "/../unknown",
                         self.first.checkout + "//alias", str(self.root / "unknown-alias")):
            with self.subTest(location=location), self.assertRaises(Refused):
                self.probe(location=location)
        with self.assertRaises(Refused):
            self.probe(operation="write")
        self.assertEqual(self.calls, [self.first.git_directory])

    def test_authority_observation_uses_current_repository_id_for_the_exact_path(self):
        selected = self.inventory.owner_observation_scope(self.version, "read", [self.first.checkout],
                                                          deadline=deadline())
        self.assertEqual([item.repository_id for item in selected], [901])
        self.assertEqual([item.checkout for item in selected], [self.first.checkout])
        for path in (self.denied + "/child", self.first.checkout + "-other"):
            with self.subTest(path=path), self.assertRaises(Refused):
                self.inventory.owner_observation_scope(self.version, "read", [path], deadline=deadline())

    def test_authority_observation_cannot_reuse_an_unrelated_pending_operation(self):
        reserved = self.inventory.reserve(self.version, "foreign-move", {self.first.checkout: None},
                                           deadline=deadline())
        with self.assertRaisesRegex(Refused, "pending"):
            self.inventory.owner_observation_scope(reserved, "other-operation", [self.first.checkout],
                                                   deadline=deadline())
        with self.assertRaisesRegex(Refused, "no active prepared evidence"):
            self.inventory.owner_observation_scope(reserved, "foreign-move", [self.first.checkout],
                                                   deadline=deadline())

    def owner_record(self, operation, physical, observations):
        record = {"schema": "dev-checkout-owner-evidence/v1", "operation": operation,
                  "physical_binding_digest": physical, "dev_policy_revision": self.version[0]}
        if observations is not None:
            record["observations"] = observations
        return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def test_owner_evidence_requires_one_git_configuration_for_each_selected_checkout(self):
        operation = "owner-configurations"
        physical = "c" * 64
        first = {"checkout": self.first.checkout, "git_config_sha256": "b" * 64}
        peer = {"checkout": self.peer.checkout, "git_config_sha256": "d" * 64}
        changes = {binding.checkout: binding for binding in (self.first, self.peer)}
        for rows in (None, [], [first], [first, first], [first, peer, peer],
                     [first, peer | {"checkout": self.denied}],
                     [first, {"checkout": self.peer.checkout}],
                     [first, peer | {"worktree_git_config_enabled": True}]):
            with self.subTest(observations=rows), self.assertRaises(Refused):
                self.inventory.reserve_evidence_reissue(
                    self.version, operation, changes, owner_record=self.owner_record(operation, physical, rows),
                    physical_binding_digest=physical, deadline=deadline(),
                )
        self.assertIsNone(self.inventory.read_prepared_evidence_reissue(operation, deadline=deadline(),
                                                                        allow_missing=True))
        self.assertEqual(self.inventory.snapshot()[1], self.version)
        record = self.owner_record(operation, physical, [first, peer])
        self.inventory.reserve_evidence_reissue(self.version, operation, changes, owner_record=record,
                                                physical_binding_digest=physical, deadline=deadline())
        self.inventory.finish_evidence_reissue(operation, owner_record=record, physical_binding_digest=physical,
                                              deadline=deadline())
        self.assertEqual(self.inventory.current_owner_evidence(operation, deadline=deadline()).record, record)
        self.assertTrue(self.inventory.finished_refresh_scope(operation).requires_owner_evidence)

    def test_completing_an_owner_record_requires_the_reserved_checkout_configurations(self):
        operation = "plain-reservation"
        physical = "c" * 64
        pending = self.inventory.reserve(self.version, operation, {self.first.checkout: self.first},
                                         deadline=deadline())
        for observations in (None, [{"checkout": self.peer.checkout, "git_config_sha256": "d" * 64}]):
            record = self.owner_record(operation, physical, observations)
            with self.subTest(observations=observations), self.assertRaises(Refused):
                self.inventory.finish_evidence_reissue(operation, owner_record=record,
                                                       physical_binding_digest=physical, deadline=deadline())
        self.assertEqual(self.inventory.snapshot()[1], pending)

    def test_rolled_back_operation_does_not_supersede_prior_checkout_evidence(self):
        operation = "owner-configurations"
        physical = "c" * 64
        changes = {self.first.checkout: self.first}
        observations = [{"checkout": self.first.checkout, "git_config_sha256": "b" * 64}]
        record = self.owner_record(operation, physical, observations)
        self.inventory.reserve_evidence_reissue(self.version, operation, changes, owner_record=record,
                                                physical_binding_digest=physical, deadline=deadline())
        current = self.inventory.finish_evidence_reissue(operation, owner_record=record,
                                                         physical_binding_digest=physical, deadline=deadline())
        earlier = self.inventory.current_owner_evidence(operation, deadline=deadline())
        self.inventory.reserve(current, "interrupted-retirement", {self.first.checkout: None}, deadline=deadline())
        with self.assertRaisesRegex(Refused, "pending"):
            self.inventory.current_owner_evidence(operation, deadline=deadline())
        restored = self.inventory.finish("interrupted-retirement", outcome="rolled-back",
                                         owner_evidence="owner verified the original checkout", deadline=deadline())
        self.assertGreater(restored[1], current[1])
        self.assertEqual(self.inventory.current_owner_evidence(operation, deadline=deadline()),
                         replace(earlier, current=restored))
        with self.assertRaisesRegex(Refused, "no committed checkout evidence"):
            self.inventory.current_owner_evidence("interrupted-retirement", deadline=deadline())
        self.inventory.reserve(restored, "new-binding-proof", changes, deadline=deadline())
        self.inventory.finish("new-binding-proof", outcome="committed", owner_evidence="owner verified the renewal",
                              deadline=deadline())
        with self.assertRaisesRegex(Refused, "superseded for a selected checkout"):
            self.inventory.current_owner_evidence(operation, deadline=deadline())

    def test_prepared_evidence_may_observe_only_its_reserved_checkout(self):
        operation = "owner-reissue"
        physical = "c" * 64
        record = self.owner_record(operation, physical,
                                   [{"checkout": self.first.checkout, "git_config_sha256": "d" * 64}])
        pending = self.inventory.reserve_evidence_reissue(
            self.version, operation, {self.first.checkout: self.first}, owner_record=record,
            physical_binding_digest=physical, deadline=deadline(),
        )
        with self.assertRaisesRegex(Refused, "pending"):
            self.inventory.owner_observation_scope(pending, "different-operation", [self.first.checkout],
                                                   deadline=deadline())
        observed, = self.inventory.owner_observation_scope(pending, operation, [self.first.checkout],
                                                            deadline=deadline())
        self.assertEqual(observed.repository_id, 901)
        with self.assertRaisesRegex(Refused, "differs from the explicit checkout selections"):
            self.inventory.owner_observation_scope(pending, operation, [self.peer.checkout], deadline=deadline())

        complete = self.inventory.finish_evidence_reissue(operation, owner_record=record,
                                                          physical_binding_digest=physical, deadline=deadline())
        observed, = self.inventory.owner_observation_scope(complete, operation, [self.first.checkout],
                                                            deadline=deadline())
        self.assertEqual(observed.repository_id, 901)
        proposed = self.inventory.reserve(complete, "independent", {self.peer.checkout: self.peer}, deadline=deadline())
        self.assertGreater(proposed[1], complete[1])
        newer = self.inventory.finish("independent", outcome="committed", owner_evidence="verified owner change",
                                      deadline=deadline())
        with self.assertRaisesRegex(Refused, "no longer binds current authority"):
            self.inventory.owner_observation_scope(newer, operation, [self.first.checkout], deadline=deadline())

    def test_move_fences_old_and_new_until_owner_completion(self):
        new = self.binding("moved.product", 901)
        changes = {self.first.checkout: None, new.checkout: new}
        pending = self.inventory.reserve(self.version, "move", changes, deadline=deadline())
        self.assertEqual(pending[1], self.version[1] + 1)
        for binding in (self.first, new):
            with self.assertRaises(Refused):
                self.probe(binding, pending)
        self.probe(self.peer, pending)
        next_version = self.inventory.finish("move", outcome="committed", owner_evidence="verified-source-move",
                                             deadline=deadline())
        self.assertFalse(self.inventory.finished_refresh_scope("move").requires_owner_evidence)
        self.assertEqual(next_version[1], pending[1] + 1)
        self.probe(new, next_version)
        with self.assertRaises(Refused):
            self.probe(self.first, next_version)
        self.assertEqual(self.calls, [self.peer.checkout, new.checkout])
        self.assertEqual(pending, self.inventory.reserve(self.version, "move", changes, deadline=deadline()))
        self.assertEqual(next_version, self.inventory.finish("move", outcome="committed",
                         owner_evidence="verified-source-move", deadline=deadline()))
        with self.assertRaises(Refused):
            self.inventory.finish("move", outcome="rolled-back", owner_evidence="different", deadline=deadline())

    def test_interrupted_process_leaves_durable_reservation(self):
        script = '''
from pathlib import Path
import json, os, sys, time
from personal_checkout_inventory import Inventory
inv = Inventory(Path(sys.argv[1]))
inv.reserve(json.loads(sys.argv[2]), "crashed", {sys.argv[3]: None}, deadline=time.monotonic() + 3)
os._exit(42)
'''
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.private), json.dumps(self.version),
                                 self.first.checkout], cwd=Path(__file__).parent, check=False, timeout=8)
        self.assertEqual(result.returncode, 42)
        self.inventory = Inventory(self.private)
        self.assertEqual(self.inventory.operation("crashed")["phase"], "reserved")
        _, pending = self.inventory.snapshot()
        with self.assertRaises(Refused):
            self.probe(self.first, pending)
        recovered = self.inventory.finish("crashed", outcome="rolled-back", owner_evidence="source-intact",
                                          deadline=deadline())
        self.probe(self.first, recovered)
        self.assertEqual(self.calls, [self.first.checkout])

    def test_recorded_intent_has_priority_and_can_resume_after_a_timeout(self):
        entered, release = Event(), Event()
        errors = []
        def read():
            def hold(location, expires):
                entered.set()
                if not release.wait(2):
                    raise AssertionError("test did not release its probe")
            try:
                self.inventory.probe(self.version, self.first.checkout, "adopt", "checkout",
                                     self.first.checkout, hold, deadline=deadline())
            except Exception as error:
                errors.append(error)
        current = Thread(target=read)
        current.start()
        try:
            self.assertTrue(entered.wait(1))
            changes = {self.first.checkout: None}
            with self.assertRaisesRegex(Refused, "within the budget"):
                self.inventory.reserve(self.version, "queued", changes, deadline=time.monotonic() + 0.05)
            self.assertEqual(self.inventory.operation("queued")["phase"], "requested")
        finally:
            release.set()
            current.join(3)
        self.assertFalse(current.is_alive())
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(Refused, "pending"):
            self.probe()
        self.probe(self.peer)
        pending = self.inventory.reserve(self.version, "queued", changes, deadline=deadline())
        with self.assertRaises(Refused):
            self.probe(self.first, pending)
        self.assertEqual(self.calls, [self.peer.checkout])

    def test_stale_queued_request_releases_only_its_uncommitted_claim(self):
        script = '''
import json, os, sys, time
from personal_checkout_inventory import Inventory, Refused
inventory = Inventory(sys.argv[1])
try:
    inventory.reserve(json.loads(sys.argv[2]), "stale", {sys.argv[3]: None},
                      deadline=time.monotonic() + 0.05)
except Refused as error:
    os._exit(42 if "within the budget" in str(error) else 43)
os._exit(44)
'''
        with self.inventory._gate(deadline()):
            child = subprocess.run([sys.executable, "-B", "-c", script, str(self.private),
                                    json.dumps(self.version), self.first.checkout],
                                   cwd=Path(__file__).parent, timeout=8, check=False)
        self.assertEqual(child.returncode, 42)
        self.inventory = Inventory(self.private)
        self.assertEqual(self.inventory.operation("stale")["phase"], "requested")
        with self.assertRaisesRegex(Refused, "pending"):
            self.probe()
        self.assertEqual(self.calls, [])

        third = self.binding("unrelated.product", 903)
        self.inventory.reserve(self.version, "unrelated", {third.checkout: third}, deadline=deadline())
        active = self.inventory.finish("unrelated", outcome="committed", owner_evidence="unrelated",
                                       deadline=deadline())
        raw, _ = self.inventory.snapshot()
        self.probe(self.first, active)
        self.assertEqual(self.calls, [self.first.checkout])
        self.assertEqual(self.inventory.snapshot(), (raw, active))
        self.assertEqual(self.inventory.operation("stale")["phase"], "requested")

        changes = {self.first.checkout: None}
        pending = self.inventory.reserve(active, "new-owner-request", changes, deadline=deadline())
        with self.assertRaisesRegex(Refused, "changed before reservation"):
            self.inventory.reserve(self.version, "stale", changes, deadline=deadline())
        self.assertEqual(self.inventory.operation("stale")["phase"], "superseded")
        unrelated_pending = self.inventory.reserve(pending, "other-removal", {third.checkout: None},
                                                   deadline=deadline())
        with self.assertRaisesRegex(Refused, "pending"):
            self.probe(self.first, unrelated_pending)
        self.assertEqual(self.calls, [self.first.checkout])
        self.assertEqual(self.inventory.operation("new-owner-request")["phase"], "reserved")

    def test_shared_git_location_is_fenced(self):
        linked = replace(self.first, checkout=str(self.root / "linked"),
                         git_directory=self.first.git_directory + "/worktrees/linked", worktree_id="linked")
        self.inventory.reserve(self.version, "add-linked", {linked.checkout: linked}, deadline=deadline())
        linked_version = self.inventory.finish("add-linked", outcome="committed", owner_evidence="linked-present",
                                               deadline=deadline())
        self.probe(linked, linked_version, role="common_directory")
        pending = self.inventory.reserve(linked_version, "retire-linked", {linked.checkout: None}, deadline=deadline())
        with self.assertRaisesRegex(Refused, "pending"):
            self.probe(self.first, pending, role="common_directory")
        self.probe(self.peer, pending)
        self.assertEqual(self.calls, [self.first.common_directory, self.peer.checkout])

    def test_overlapping_checkout_and_git_locations_are_refused_before_reservation(self):
        checkout = self.first.checkout
        git = self.first.git_directory
        separate = self.peer.checkout + "-sibling"
        competing = (
            self.binding("sample.product/nested", 903),
            self.binding("sample.product/.git/nested", 904),
            replace(self.peer, git_directory=checkout + "/foreign-metadata",
                    common_directory=checkout + "/foreign-metadata"),
            replace(self.peer, git_directory=git + "/foreign-git", common_directory=git + "/foreign-git"),
            replace(self.peer, common_directory=git + "/foreign-common"),
            replace(self.first, checkout=separate, git_directory=git + "/private", worktree_id="invalid-link"),
        )
        for row in competing:
            with self.subTest(row=row):
                with self.assertRaisesRegex(Refused, "overlap"):
                    self.inventory.reserve(self.version, "overlapping", {row.checkout: row}, deadline=deadline())
                self.assertEqual(self.inventory.snapshot()[1], self.version)
        (self.root / "other-inventory").mkdir(mode=0o700)
        with self.assertRaisesRegex(Refused, "overlap"):
            Inventory(self.root / "other-inventory").initialize("test-host", "policy", [], [competing[0], self.first])

    def test_linked_git_regions_share_only_the_modeled_common_directory(self):
        common = self.first.common_directory
        worktrees = common + "/worktrees"
        first = replace(self.first, checkout=self.first.checkout + "-link", git_directory=worktrees + "/first",
                        worktree_id="first-linked")
        second = replace(first, checkout=self.first.checkout + "-second-link", git_directory=worktrees + "/second",
                         worktree_id="second-linked")
        version = self.inventory.reserve(self.version, "linked-family",
                                         {row.checkout: row for row in (first, second)}, deadline=deadline())
        version = self.inventory.finish("linked-family", outcome="committed", owner_evidence="two verified links",
                                        deadline=deadline())
        self.probe(first, version, role="common_directory")
        self.probe(second, version, role="git_directory")
        self.assertEqual(self.calls, [common, second.git_directory])
        nested = replace(second, git_directory=first.git_directory + "/nested")
        with self.assertRaisesRegex(Refused, "overlap"):
            self.inventory.reserve(version, "nested-link", {nested.checkout: nested}, deadline=deadline())

    def test_shared_git_metadata_cannot_be_read_as_checkout_source(self):
        source = self.first.checkout + "/meta.yml"
        git = self.first.git_directory
        collect = Mock()
        for location in (git, git + "/config", git + "/worktrees/other/config.worktree"):
            with self.subTest(location=location), self.assertRaisesRegex(Refused, "checkout source"):
                self.inventory.authorized_read(self.version, self.first.checkout, "enumerate",
                                               (("source", location),), collect, deadline=deadline())
        collect.assert_not_called()
        for role, location in (("source", source), ("common_directory", git)):
            self.inventory.authorized_read(self.version, self.first.checkout, "enumerate",
                                           ((role, location),), collect, deadline=deadline())
        self.assertEqual(collect.call_count, 2)

    def test_legacy_overlapping_checkout_cannot_open_targets(self):
        nested = self.binding("sample.product/nested", 903)
        with self.inventory._update(deadline()) as (db, commit):
            state = self.inventory._read(db)
            state["bindings"][nested.checkout] = asdict(nested)
            self.inventory._write(db, state)
            commit()
        _, older_version = self.inventory.snapshot()
        collect = Mock()
        with self.assertRaisesRegex(Refused, "overlap"):
            self.inventory.authorized_read(older_version, self.first.checkout, "enumerate",
                                           (("source", nested.checkout + "/meta.yml"),), collect,
                                           deadline=deadline())
        with self.assertRaisesRegex(Refused, "overlap"):
            self.probe(nested, older_version)
        collect.assert_not_called()
        self.probe(self.peer, older_version)
        self.assertEqual(self.calls, [self.peer.checkout])

    def test_conflicting_binding_and_operation_reuse_are_refused(self):
        duplicate = replace(self.peer, common_directory=self.first.common_directory)
        with self.assertRaisesRegex(Refused, "ambiguous"):
            self.inventory.reserve(self.version, "conflict", {self.peer.checkout: duplicate}, deadline=deadline())
        self.assertEqual(self.inventory.snapshot()[1], self.version)
        self.inventory.reserve(self.version, "retire", {self.first.checkout: None}, deadline=deadline())
        with self.assertRaisesRegex(Refused, "different request"):
            self.inventory.reserve(self.version, "retire", {self.peer.checkout: None}, deadline=deadline())
        with self.assertRaisesRegex(Refused, "changed"):
            self.probe(self.peer)
        self.assertEqual(self.calls, [])

    def test_owner_only_store_and_snapshot_no_auto_create(self):
        self.assertEqual(self.inventory.database.stat().st_mode & 0o777, 0o600)
        empty = self.root / "empty"
        empty.mkdir(mode=0o700)
        new = Inventory(empty)
        with self.assertRaisesRegex(Refused, "could not be opened"):
            new.snapshot()
        self.assertEqual(list(empty.iterdir()), [])

    def test_inventory_refuses_oversized_file_before_reading_it(self):
        size = self.inventory.database.stat().st_size
        with patch("personal_checkout_inventory.MAX_INVENTORY_BYTES", size, create=True):
            self.assertEqual(self.inventory.snapshot()[1], self.version)
            with self.inventory.database.open("ab") as file:
                file.truncate(size + 1)
            real_fdopen = os.fdopen
            observed = []

            @contextmanager
            def watch_read(*args, **kwargs):
                with real_fdopen(*args, **kwargs) as file:
                    reader = Mock(wraps=file)
                    observed.append(reader)
                    yield reader

            with patch("personal_checkout_inventory.os.fdopen", side_effect=watch_read):
                with self.assertRaisesRegex(Refused, "exceeds its size limit"):
                    self.inventory.snapshot()
            reader, = observed
            reader.read.assert_not_called()

    def test_oversized_update_preserves_the_last_readable_inventory(self):
        previous = self.inventory.database.read_bytes()
        with patch("personal_checkout_inventory.MAX_INVENTORY_BYTES", len(previous), create=True):
            with self.assertRaisesRegex(Refused, "exceeds its size limit"):
                with self.inventory._update(deadline()) as (db, commit):
                    db.execute("INSERT INTO lifecycle VALUES (?, ?, ?, ?)",
                               ("large-fixture", "x" * len(previous), "requested", None))
                    commit()
            self.assertEqual(self.inventory.database.read_bytes(), previous)
            self.assertEqual(self.inventory.snapshot()[1], self.version)
            with self.assertRaisesRegex(Refused, "unknown owner lifecycle operation"):
                self.inventory.operation("large-fixture")
        self.assertFalse(any(self.private.glob(".checkout-inventory-*")))

    def test_database_open_refuses_symlink_substitution(self):
        database = self.inventory.database
        saved = self.private / "saved.sqlite"
        other = self.root / "other.sqlite"
        original = database.read_bytes()
        other.write_bytes(original)
        other.chmod(0o600)
        open_file = os.open

        def replace_before_open(path, flags, *args, **kwargs):
            if path == database.name:
                database.rename(saved)
                database.symlink_to(other)
            return open_file(path, flags, *args, **kwargs)

        with patch("personal_checkout_inventory.os.open", side_effect=replace_before_open):
            with self.assertRaisesRegex(Refused, "could not be opened safely"):
                self.inventory.snapshot()
        self.assertTrue(database.is_symlink())
        self.assertEqual(other.read_bytes(), original)
        self.assertEqual(saved.read_bytes(), original)

    def test_publication_refuses_a_replaced_database(self):
        database = self.inventory.database
        saved = self.private / "saved.sqlite"
        other = self.root / "other.sqlite"
        original = database.read_bytes()
        other.write_bytes(original)
        other.chmod(0o600)
        entry = self.inventory._entry

        def replace_before_publication(parent, name):
            if name == database.name:
                database.rename(saved)
                database.symlink_to(other)
            return entry(parent, name)

        with patch.object(self.inventory, "_entry", side_effect=replace_before_publication):
            with self.assertRaisesRegex(Refused, "changed before publication"):
                self.inventory.reserve(self.version, "move", {self.first.checkout: None}, deadline=deadline())
        self.assertEqual(other.read_bytes(), original)
        self.assertEqual(saved.read_bytes(), original)
        self.assertTrue(database.is_symlink())
        self.assertFalse(list(self.private.glob(".checkout-inventory-*")))
        database.unlink()
        saved.rename(database)
        self.assertEqual(self.inventory.snapshot()[1], self.version)
        with self.assertRaisesRegex(Refused, "unknown owner lifecycle operation"):
            self.inventory.operation("move")

    def test_published_snapshot_remains_a_standard_sqlite_database(self):
        reserved = self.inventory.reserve(self.version, "reserve", {self.first.checkout: None}, deadline=deadline())
        uri = self.inventory.database.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT phase FROM lifecycle").fetchone(), ("reserved",))
        finally:
            connection.close()
        self.assertEqual(reserved, Inventory(self.private).snapshot()[1])

    def test_guard_open_errors_refuse_without_checkout_access(self):
        lock = self.private / "checkout-access.lock"
        lock.unlink()
        foreign = self.root / "foreign-guard"
        foreign.write_bytes(b"unrelated")
        lock.symlink_to(foreign)
        with self.assertRaisesRegex(Refused, "invalid Dev checkout guard"):
            self.probe()
        self.assertEqual(self.calls, [])
        self.assertEqual(foreign.read_bytes(), b"unrelated")

    def test_malformed_relative_retirement_paths_refuse(self):
        for invalid in (None, 42, ["checkout"], "", "/abs", "one/../two", "one//two"):
            with self.subTest(value=invalid), self.assertRaisesRegex(Refused, "not relative and canonical"):
                destruction_roots(str(self.root), [{"kind": "delete-checkout", "params": {"rel": invalid}}])
        self.assertEqual(destruction_roots(str(self.root), [
            {"kind": "delete-checkout", "params": {"rel": "owner/project"}}
        ]), {str(self.root / "owner/project")})

    def test_policy_reservation_invalidates_old_generations_and_preserves_withdrawn_binding(self):
        revision = "private-policy-2"
        denied = [self.denied, self.first.checkout]
        pending = self.inventory.reserve_policy(self.version, "policy", revision, denied, deadline=deadline())
        self.assertEqual(pending[0], self.version[0])
        for binding in (self.first, self.peer):
            with self.assertRaises(Refused):
                self.probe(binding, pending)
        new = self.inventory.finish("policy", outcome="committed", owner_evidence="owner-policy-verified",
                                    deadline=deadline())
        self.assertEqual(new[0], revision)
        with self.assertRaisesRegex(Refused, "excludes"):
            self.probe(self.first, new)
        self.probe(self.peer, new)
        evidence = self.inventory.operation("policy")["result"]
        self.assertEqual(evidence["previous_policy"]["revision"], self.version[0])
        self.assertEqual(evidence["withdrawn_bindings"][self.first.checkout]["repository_id"], 901)
        self.assertEqual(self.calls, [self.peer.checkout])
        self.assertEqual(pending, self.inventory.reserve_policy(self.version, "policy", revision, denied,
                                                                  deadline=deadline()))

    def test_policy_rollback_advances_generation_without_replacing_old_authority(self):
        pending = self.inventory.reserve_policy(self.version, "rollback", "proposed-policy", [self.first.checkout],
                                                deadline=deadline())
        with self.assertRaisesRegex(Refused, "pending"):
            self.probe(self.first, pending)
        changed = self.inventory.finish("rollback", outcome="rolled-back", owner_evidence="owner-kept-old-policy",
                                         deadline=deadline())
        self.assertEqual(changed[0], self.version[0])
        self.assertEqual(changed[1], pending[1] + 1)
        self.probe(self.first, changed)
        self.assertEqual(self.calls, [self.first.checkout])

    def test_pending_policy_prevents_new_bindings_even_with_no_overlap(self):
        pending = self.inventory.reserve_policy(self.version, "policy", "other-policy", [], deadline=deadline())
        additional = self.binding("new.product", 903)
        with self.assertRaisesRegex(Refused, "already claims"):
            self.inventory.reserve(pending, "add", {additional.checkout: additional}, deadline=deadline())


if __name__ == "__main__":
    unittest.main()
