#!/usr/bin/env python3
"""Synthetic-only publication safety tests. Never inspect host repositories."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("host_policy", ROOT / "_ops/bin/shadow-sync-host-policy.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)

POLICY = b"""version: 1
governed_roots:
  - ~/workspace
managed_location: ~/.cursor/worktrees
modes_file: worktree-modes.yml
default: include
include:
  - projects/*
exclude:
  - .
  - references/*
hard_no_touch_paths:
  exact_roots:
    - ~/workspace/projects/fixture-protected
  managed_namespace_prefixes:
    - ~/.cursor/worktrees/fixture-protected
detectors:
  governed_markers:
    - _ops/POLICY.md
  artifact_paths:
    - projects/fixture-artifact
  foreign_hook_frameworks:
    - husky
  read_only_paths:
    - references/*
overrides:
  include: []
  exclude: []
"""
OVERLAY = {
    "schema": "shadow-sync-host-overlay/v1", "governed_root_repository_id": "fixture/workspace",
    "shelves": [["projects"], ["references"]], "writable_paths": ["."],
    "permanent_no_touch_repository_ids": ["fixture/protected"],
    "managed_locations": [{"kind": "cursor", "components": [".cursor", "worktrees"], "minimum_depth": 2}],
    "awa_evidence": {"adapter_path": "dev/_ops/bin/dev-worktree.sh",
                     "root_records_path": ".state/fixture-roots", "lease_components": [".awa", "lease.json"]},
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="host-policy-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.fd = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(os.close, self.fd)
        self.tree = P.Tree(self.fd, os.geteuid())
        self.module = b"# Explicit synthetic AWA module fixture; never imported.\n"
        self.pin = {"version": "1.2.3", "revision": "a" * 40, "module_sha256": P.digest(self.module)}
        self.write(P.POLICY, POLICY)
        self.write(P.OVERLAY, P.encoded(OVERLAY))
        self.write(P.DISPATCHER, b"#!/bin/sh\n# fixture dispatcher\nexit 0\n")
        self.write(P.MODULE, self.module)
        self.write(P.POINTER, P.encoded({"schema": "awa-release-pointer/v1", "version": "1.2.3",
                   "commit": "a" * 40, "runtime": str(self.home) + "/" + P.RUNTIME,
                   "hook_owner_mode": "external"}))
        self.write(P.PIN_SOURCE, ("VERSION = '1.2.3'\nPIN = '" + "a" * 40
                                  + "'\nPOLICY_MODULE_SHA256 = '" + self.pin["module_sha256"] + "'\n").encode())

    def write(self, path, data):
        target = self.home / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        target.chmod(0o600)

    def preview(self):
        return P.preview(self.tree, str(self.home), self.pin)

    def publish(self):
        plan = self.preview()
        return P.apply(self.tree, str(self.home), self.pin, plan["action_digest"])

    def snapshot(self):
        # Only this disposable fixture, not any path from policy data.
        return {str(path.relative_to(self.home)): path.read_bytes()
                for path in self.home.rglob("*") if path.is_file() and not path.is_symlink()}


class PublicationTests(Fixture):
    def test_preview_is_read_only_and_projection_has_exact_source_bindings(self):
        before = self.snapshot()
        plan = self.preview()
        self.assertEqual(before, self.snapshot())
        value = json.loads(plan["projection"])
        self.assertEqual(value["governed_root"]["components"], ["workspace"])
        self.assertEqual(value["path_policy"]["read_only"], ["references/*"])
        self.assertEqual(value["source_inputs"]["worktree_policy"]["sha256"], P.digest(POLICY))
        self.assertNotIn("hard_no_touch_paths", value)  # AWA interprets the bound original.
        self.assertFalse((self.home / P.DESTINATION).exists())

    def test_only_explicit_configuration_paths_are_read(self):
        calls = []
        original = self.tree.read
        def audited(path, **kwargs):
            calls.append(path)
            return original(path, **kwargs)
        with mock.patch.object(self.tree, "read", audited):
            self.preview()
        self.assertEqual(set(calls), {P.POLICY, P.OVERLAY, P.DISPATCHER, P.POINTER,
                                      P.MODULE, P.PIN_SOURCE, P.BINDING})
        self.assertFalse((self.home / "workspace").exists())

    def test_initial_publish_and_idempotent_retry_preserve_lock_inode(self):
        result = self.publish()
        binding = (self.home / P.BINDING).read_bytes()
        lock = self.home / P.DESTINATION / "policy-publisher.lock"
        inode = lock.stat().st_ino
        before = self.snapshot()
        second = self.publish()
        self.assertEqual(second, result)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(inode, lock.stat().st_ino)
        self.assertEqual(self.preview()["binding"], binding)
        self.assertEqual(stat.S_IMODE((self.home / P.BINDING).stat().st_mode), 0o600)

    def test_updated_source_preserves_previous_binding_and_generation(self):
        self.publish()
        old = (self.home / P.BINDING).read_bytes()
        self.write(P.POLICY, POLICY + b"# reviewed source-only comment\n")
        self.publish()
        history = self.home / P.DESTINATION / "binding-history" / (P.digest(old) + ".json")
        self.assertEqual(history.read_bytes(), old)
        prior = json.loads(old)
        self.assertEqual(P.digest((self.home / prior["projection"]["path"]).read_bytes()),
                         prior["projection"]["sha256"])

    def test_stale_preview_cannot_publish(self):
        plan = self.preview()
        self.write(P.DISPATCHER, b"#!/bin/sh\n# changed\n")
        with self.assertRaisesRegex(P.Refusal, "stale"):
            P.apply(self.tree, str(self.home), self.pin, plan["action_digest"])
        self.assertFalse((self.home / P.BINDING).exists())

    def test_competing_publisher_refuses_without_unlinking_lock(self):
        with P.publisher_lock(self.tree):
            inode = (self.home / P.DESTINATION / "policy-publisher.lock").stat().st_ino
            with self.assertRaisesRegex(P.Refusal, "active"):
                self.publish()
            self.assertEqual(inode, (self.home / P.DESTINATION / "policy-publisher.lock").stat().st_ino)

    def test_crash_after_generation_before_binding_preserves_prior_and_retries(self):
        self.publish()
        old = (self.home / P.BINDING).read_bytes()
        self.write(P.POLICY, POLICY + b"# new generation\n")
        publish = self.tree.publish
        def fail_binding(path, *args, **kwargs):
            if path == P.BINDING:
                raise OSError("synthetic process interruption")
            return publish(path, *args, **kwargs)
        with mock.patch.object(self.tree, "publish", fail_binding), self.assertRaises(OSError):
            self.publish()
        self.assertEqual((self.home / P.BINDING).read_bytes(), old)
        self.publish()
        self.assertNotEqual((self.home / P.BINDING).read_bytes(), old)

    def test_initial_interruption_never_leaves_partial_binding(self):
        rename = os.rename
        def fail_final(src, dst, **kwargs):
            if dst == "host-policy-binding.json":
                raise OSError("synthetic replacement failure")
            return rename(src, dst, **kwargs)
        with mock.patch.object(P.os, "rename", fail_final), self.assertRaises(OSError):
            self.publish()
        self.assertFalse((self.home / P.BINDING).exists())
        self.assertEqual(list((self.home / P.DESTINATION).glob(".shadow-sync-policy-*")), [])
        self.publish()

    def test_source_drift_after_generation_leaves_binding_unchanged(self):
        self.publish()
        old = (self.home / P.BINDING).read_bytes()
        self.write(P.POLICY, POLICY + b"# first change\n")
        publish = self.tree.publish
        def drift_after_generation(path, *args, **kwargs):
            value = publish(path, *args, **kwargs)
            if "/projections/" in path:
                self.write(P.POLICY, POLICY + b"# race\n")
            return value
        with mock.patch.object(self.tree, "publish", drift_after_generation), self.assertRaises(P.Refusal):
            self.publish()
        self.assertEqual((self.home / P.BINDING).read_bytes(), old)

    def test_corrupt_generation_is_not_overwritten(self):
        plan = self.preview()
        self.write(plan["projection_path"], b"corrupt")
        with self.assertRaisesRegex(P.Refusal, "immutable"):
            self.publish()
        self.assertEqual((self.home / plan["projection_path"]).read_bytes(), b"corrupt")
        self.assertFalse((self.home / P.BINDING).exists())

    def test_malformed_prior_binding_is_preserved(self):
        for data in (b"null", b"{", b'{"schema":"unknown"}', b'{"schema":1,"schema":2}'):
            with self.subTest(data=data):
                self.write(P.BINDING, data)
                with self.assertRaises(P.Refusal):
                    self.publish()
                self.assertEqual((self.home / P.BINDING).read_bytes(), data)

    def test_previous_generation_damage_refuses_replacement(self):
        self.publish()
        prior = json.loads((self.home / P.BINDING).read_bytes())
        self.write(prior["projection"]["path"], b"damaged")
        before = self.snapshot()
        with self.assertRaisesRegex(P.Refusal, "damaged"):
            self.publish()
        self.assertEqual(before, self.snapshot())

    def test_release_and_module_mismatch_refuse(self):
        original = (self.home / P.POINTER).read_bytes()
        for key, value in (("version", "0.0.1"), ("commit", "b" * 40),
                           ("runtime", "/untrusted"), ("hook_owner_mode", "ssp")):
            pointer = json.loads(original)
            pointer[key] = value
            self.write(P.POINTER, P.encoded(pointer))
            with self.subTest(key=key), self.assertRaises(P.Refusal):
                self.preview()
        self.write(P.POINTER, original)
        self.write(P.MODULE, b"wrong module")
        with self.assertRaisesRegex(P.Refusal, "module"):
            self.preview()

    def test_pin_drift_refuses_and_pin_reader_executes_nothing(self):
        raw = (self.home / P.PIN_SOURCE).read_bytes()
        self.assertEqual(P.read_pin(raw + b"\nraise RuntimeError('must not execute')\n"), self.pin)
        self.write(P.PIN_SOURCE, raw.replace(b"1.2.3", b"1.2.4"))
        with self.assertRaisesRegex(P.Refusal, "pin source changed"):
            self.preview()


class FilesystemTests(Fixture):
    def test_symlink_file_refuses_without_following_target(self):
        target = self.home / "unrelated"
        target.write_bytes(b"preserve")
        source = self.home / P.OVERLAY
        source.unlink()
        source.symlink_to(target)
        with self.assertRaises(P.Refusal):
            self.preview()
        self.assertEqual(target.read_bytes(), b"preserve")

    def test_symlink_parent_refuses(self):
        parent = self.home / "dev/_ops/policy"
        renamed = parent.with_name("saved-policy")
        parent.rename(renamed)
        parent.symlink_to(renamed, target_is_directory=True)
        with self.assertRaises(P.Refusal):
            self.preview()

    def test_unsafe_file_and_directory_modes_refuse(self):
        for relative in (P.OVERLAY, "dev/_ops/policy"):
            path = self.home / relative
            before = path.stat().st_mode
            path.chmod(before | 0o020)
            with self.subTest(relative=relative), self.assertRaises(P.Refusal):
                self.preview()
            path.chmod(stat.S_IMODE(before))

    def test_hardlinked_file_refuses(self):
        os.link(self.home / P.MODULE, self.home / "alias")
        with self.assertRaises(P.Refusal):
            self.preview()

    def test_fifo_is_nonblocking_refusal(self):
        path = self.home / P.MODULE
        path.unlink()
        os.mkfifo(path, 0o600)
        with self.assertRaises(P.Refusal):
            self.preview()

    def test_oversize_source_refuses(self):
        self.write(P.OVERLAY, b" " * (P.MAX_FILE + 1))
        with self.assertRaises(P.Refusal):
            self.preview()

    def test_inode_substitution_during_read_refuses(self):
        original_read = P.os.read
        changed = False
        path = self.home / P.POLICY
        def replace_after_read(fd, length):
            nonlocal changed
            raw = original_read(fd, length)
            if not changed:
                changed = True
                alternative = path.with_suffix(".new")
                alternative.write_bytes(POLICY)
                alternative.chmod(0o600)
                alternative.replace(path)
            return raw
        with mock.patch.object(P.os, "read", replace_after_read), self.assertRaises(P.Refusal):
            self.tree.read(P.POLICY)

    def test_descriptor_cleanup_on_unsafe_parent(self):
        path = self.home / "dev/_ops"
        path.chmod(0o777)
        opened, closed = [], []
        original_open, original_close = os.open, os.close
        def audit_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            opened.append(fd)
            return fd
        def audit_close(fd):
            closed.append(fd)
            return original_close(fd)
        with mock.patch.object(P.os, "open", audit_open), mock.patch.object(P.os, "close", audit_close):
            with self.assertRaises(P.Refusal):
                self.tree.read(P.POLICY)
        self.assertTrue(set(opened) <= set(closed))

    def test_lock_symlink_never_modifies_target(self):
        self.write(P.DESTINATION + "/preserved", b"keep")
        lock = self.home / P.DESTINATION / "policy-publisher.lock"
        lock.symlink_to("preserved")
        with self.assertRaises(OSError):
            self.publish()
        self.assertEqual((lock.parent / "preserved").read_bytes(), b"keep")


class SchemaTests(Fixture):
    def test_missing_duplicate_unknown_or_noncanonical_policy_refuses(self):
        cases = [POLICY.replace(b"version: 1", b"version: 2"),
                 POLICY + b"version: 1\n", POLICY + b"unknown: yes\n",
                 POLICY.replace(b"default: include", b"default: exclude"),
                 POLICY.replace(b"  include: []", b"  include:\n    - projects/restricted"),
                 POLICY.replace(b"hard_no_touch_paths:", b"'hard_no_touch_paths':"),
                 POLICY.replace(b"    - ~/workspace/projects/fixture-protected", b"    # missing"),
                 POLICY.replace(b"hard_no_touch_paths:", b"hard_no_touch_paths: &alias"),
                 POLICY.replace(b"version: 1", b"version: 1\t"),
                 POLICY.replace(b"version: 1", b"version: 1\n---")]
        for raw in cases:
            with self.subTest(raw=raw[:60]), self.assertRaises(P.Refusal):
                P.policy_projection_input(raw)

    def test_overlay_unknown_duplicate_and_numeric_boolean_refuse(self):
        for kind in ("unknown", "duplicate", "boolean", "overlap", "bad-id", "writable", "traversal"):
            overlay = copy.deepcopy(OVERLAY)
            if kind == "unknown": overlay["unexpected"] = True
            elif kind == "boolean": overlay["managed_locations"][0]["minimum_depth"] = True
            elif kind == "overlap": overlay["shelves"].append(["projects", "nested"])
            elif kind == "bad-id": overlay["governed_root_repository_id"] = "Fixture/Repo"
            elif kind == "writable": overlay["writable_paths"] = ["references/unsafe"]
            elif kind == "traversal": overlay["awa_evidence"]["adapter_path"] = "../untrusted"
            raw = P.encoded(overlay)
            if kind == "duplicate": raw = raw.replace(b'{\n', b'{"schema":"duplicate",\n', 1)
            with self.subTest(kind=kind), self.assertRaises(P.Refusal):
                P.project(POLICY, raw, b"fixture")

    def test_protected_paths_remain_only_data_in_original_policy(self):
        raw = POLICY.replace(b"fixture-protected", b"does-not-exist-at-all")
        projected = P.project(raw, P.encoded(OVERLAY), b"fixture")
        self.assertNotIn("does-not-exist-at-all", json.dumps(projected))
        self.assertEqual(projected["source_inputs"]["worktree_policy"]["sha256"], P.digest(raw))

    def test_root_and_evidence_depth_limits_match_consumer(self):
        for count in (16, 17):
            raw = POLICY.replace(b"~/workspace\n", ("~/" + "/".join(["x"] * count) + "\n").encode())
            if count == 16:
                P.project(raw, P.encoded(OVERLAY), b"fixture")
            else:
                with self.assertRaises(P.Refusal):
                    P.project(raw, P.encoded(OVERLAY), b"fixture")
        for key in ("adapter_path", "root_records_path"):
            overlay = copy.deepcopy(OVERLAY)
            overlay["awa_evidence"][key] = "/".join(["x"] * 17)
            with self.subTest(key=key), self.assertRaises(P.Refusal):
                P.project(POLICY, P.encoded(overlay), b"fixture")

    def test_every_projected_path_role_obeys_component_limit(self):
        for role in ("exclude", "read_only_paths", "artifact_paths", "writable_paths"):
            for depth in (16, 17):
                path = "/".join(["x"] * depth)
                policy, overlay = POLICY, copy.deepcopy(OVERLAY)
                if role == "writable_paths":
                    overlay[role] = [path]
                else:
                    indentation = "  " if role == "exclude" else "    "
                    marker = (role + ":\n").encode()
                    policy = policy.replace(marker, marker + (indentation + "- " + path + "\n").encode())
                with self.subTest(role=role, depth=depth):
                    if depth == 16:
                        P.project(policy, P.encoded(overlay), b"fixture")
                    else:
                        with self.assertRaises(P.Refusal):
                            P.project(policy, P.encoded(overlay), b"fixture")

    def test_path_bound_is_utf8_bytes_and_surrogates_refuse(self):
        self.assertEqual(P.components("é" * 2048), ["é" * 2048])
        for path in ("é" * 2049, "\ud800"):
            with self.assertRaises(P.Refusal):
                P.components(path)
        overlay = copy.deepcopy(OVERLAY)
        overlay["awa_evidence"]["adapter_path"] = "é" * 2049
        with self.assertRaises(P.Refusal):
            P.project(POLICY, P.encoded(overlay), b"fixture")

    def test_pin_reader_refuses_expressions_duplicates_and_wrong_types(self):
        good = (self.home / P.PIN_SOURCE).read_bytes()
        for raw in (good + b"VERSION = '1.2.3'\n", good.replace(b"'1.2.3'", b"str(123)"),
                    good.replace(b"'1.2.3'", b"True"), b"PIN = 'x'\n"):
            with self.subTest(raw=raw[:30]), self.assertRaises(P.Refusal):
                P.read_pin(raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
