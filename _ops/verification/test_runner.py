from __future__ import annotations

import ast
import base64
import copy
import hashlib
import io
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from _ops.verification import contracts, runner, selector


ROOT = Path(__file__).resolve().parents[2]
VERIFICATION = ROOT / "_ops" / "verification"
PROCESS_FIXTURE = VERIFICATION / "fixtures" / "runner_process.py"
WIRE_GOLDENS = VERIFICATION / "fixtures" / "wire-goldens-v1.json"
AUTHORITY_FILES = (
    "verification-manifest.json",
    "verification-manifest.schema.json",
    "verification-receipt.schema.json",
    "verification-rollout-ledger.schema.json",
    "verification-rollout-ledger.json",
)
SAFE_ENVIRONMENT = (
    "HOME",
    "PATH",
    "PYTHONDONTWRITEBYTECODE",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
)


def git_blob_oid(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def limits(**overrides: int | float) -> runner.ResourceLimits:
    values: dict[str, int | float] = {
        "timeout_ms": 1500,
        "cpu_seconds": 2,
        "memory_bytes": 256 * 1024 * 1024,
        "file_size_bytes": 1024 * 1024,
        "open_files": 64,
        "processes": 16,
        "output_bytes": 8192,
        "terminate_grace_seconds": 0.05,
        "kill_grace_seconds": 1.5,
    }
    values.update(overrides)
    return runner.ResourceLimits(**values)  # type: ignore[arg-type]


def process_result(outcome: str = "passed", exit_code: int | None = 0) -> runner.ProcessResult:
    return runner.ProcessResult(
        outcome=outcome,
        exit_code=exit_code,
        duration_ms=7,
        timed_out=outcome == "timed_out",
        interrupted=outcome == "interrupted",
        output_limited=False,
        memory_limited=False,
        processes_limited=False,
        sentinel_seen=True,
        children_reaped=True,
        bytecode_absent=True,
        temp_removed=True,
    )


class ProcessRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-process-tests-")
        self.base = Path(self.temporary.name)
        self.run_root = self.base / "run"
        self.snapshot_work = self.run_root / "snapshot" / "work"
        self.snapshot_work.mkdir(parents=True, mode=0o700)
        shutil.copyfile(PROCESS_FIXTURE, self.snapshot_work / "fixture.py")
        self.evidence = self.base / "evidence"
        self.evidence.mkdir(mode=0o700)

    def tearDown(self) -> None:
        runner._remove_owned_tree(self.run_root)
        self.temporary.cleanup()

    def spec(
        self,
        *arguments: str,
        sentinel: str | None = None,
        resource_limits: runner.ResourceLimits | None = None,
    ) -> runner.ProcessSpec:
        return runner.ProcessSpec(
            argv=("python3", "fixture.py", *arguments),
            cwd=Path("work"),
            environment_allowlist=SAFE_ENVIRONMENT,
            limits=resource_limits or limits(),
            stdout_sentinel=sentinel,
        )

    def assert_pid_gone(self, pid: int) -> None:
        for _attempt in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail(f"owned process {pid} survived")

    def test_runs_fixed_commands_strictly_sequentially(self) -> None:
        order = self.evidence / "order"
        results = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec("record-order", str(order), "first", "OK", sentinel="OK"),
                self.spec("record-order", str(order), "second", "OK", sentinel="OK"),
            ),
        )
        self.assertEqual([item.outcome for item in results], ["passed", "passed"])
        self.assertEqual(order.read_text(encoding="utf-8"), "first\nsecond\n")
        self.assertFalse((self.run_root / "process-000").exists())
        self.assertFalse((self.run_root / "process-001").exists())

    def test_process_and_child_share_one_owned_process_group(self) -> None:
        groups = self.evidence / "groups"
        result = runner.run_sequential_processes(
            self.run_root,
            (self.spec("record-group", str(groups), "OK", sentinel="OK"),),
        )[0]
        self.assertEqual(result.outcome, "passed")
        records = {
            line.split(":", 1)[0]: tuple(map(int, line.split(":")[1:]))
            for line in groups.read_text(encoding="utf-8").splitlines()
        }
        self.assertEqual(records["parent"][0], records["parent"][1])
        self.assertEqual(records["child"][1], records["parent"][1])

    def test_environment_is_exactly_allowlisted_and_values_are_not_emitted(self) -> None:
        observed = self.evidence / "environment"
        host_secret = "RUNNER_PRIVACY_ENVIRONMENT_SENTINEL"
        with mock.patch.dict(os.environ, {"UNLISTED_SECRET": host_secret}, clear=False):
            result = runner.run_sequential_processes(
                self.run_root,
                (
                    self.spec(
                        "record-environment",
                        str(observed),
                        "OK",
                        sentinel="OK",
                    ),
                ),
            )[0]
        self.assertEqual(result.outcome, "passed")
        supplied = runner._execution_environment(
            SAFE_ENVIRONMENT,
            self.run_root / "environment-probe",
        )
        self.assertEqual(set(supplied), set(SAFE_ENVIRONMENT))
        observed_names = set(
            observed.read_text(encoding="utf-8").splitlines()
        )
        self.assertTrue(set(SAFE_ENVIRONMENT) <= observed_names)
        self.assertNotIn(host_secret, observed.read_text(encoding="utf-8"))

    def test_noncanonical_or_secret_like_environment_names_are_rejected(self) -> None:
        for allowlist in (
            ("PATH", "HOME", "PYTHONDONTWRITEBYTECODE"),
            ("HOME", "PATH"),
            ("HOME", "PATH", "PRIVATE_TOKEN", "PYTHONDONTWRITEBYTECODE"),
        ):
            process_root = self.run_root / "process-000"
            process_root.mkdir(mode=0o700)
            with self.subTest(allowlist=allowlist):
                with self.assertRaises(runner.RunnerError):
                    runner._execution_environment(allowlist, process_root)
            runner._remove_owned_tree(process_root)

    def test_stdout_and_stderr_are_bounded_discarded_and_never_leaked(self) -> None:
        privacy = "RUNNER_PRIVACY_OUTPUT_SENTINEL"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = runner.run_sequential_processes(
                self.run_root,
                (
                    self.spec(
                        "output-flood",
                        privacy,
                        resource_limits=limits(output_bytes=4096),
                    ),
                ),
            )[0]
        self.assertEqual(result.outcome, "resource_limited")
        self.assertTrue(result.output_limited)
        self.assertNotIn(privacy, stdout.getvalue() + stderr.getvalue())

    def test_failed_process_records_only_exit_status_not_output(self) -> None:
        privacy = "RUNNER_PRIVACY_FAILURE_SENTINEL"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = runner.run_sequential_processes(
                self.run_root,
                (self.spec("failure", privacy, "17"),),
            )[0]
        self.assertEqual((result.outcome, result.exit_code), ("failed", 17))
        self.assertNotIn(privacy, stdout.getvalue() + stderr.getvalue())

    def test_prelaunch_failures_remove_owned_process_paths(self) -> None:
        invalid = (
            runner.ProcessSpec(
                argv=("/definitely/not/a/runner-command",),
                cwd=Path("."),
                environment_allowlist=SAFE_ENVIRONMENT,
                limits=limits(),
            ),
            runner.ProcessSpec(
                argv=(sys.executable, str(PROCESS_FIXTURE), "success", "OK"),
                cwd=Path("missing"),
                environment_allowlist=SAFE_ENVIRONMENT,
                limits=limits(),
            ),
        )
        for specification in invalid:
            with self.subTest(argv=specification.argv, cwd=specification.cwd):
                with self.assertRaises(runner.RunnerError):
                    runner.run_sequential_processes(
                        self.run_root,
                        (specification,),
                    )
                self.assertFalse((self.run_root / "process-000").exists())

    def test_timeout_terms_kills_waits_and_reaps_child_and_grandchild(self) -> None:
        child_pid = self.evidence / "child-pid"
        privacy = "RUNNER_PRIVACY_TIMEOUT_SENTINEL"
        result = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec(
                    "hang",
                    str(child_pid),
                    privacy,
                    resource_limits=limits(timeout_ms=500),
                ),
            ),
        )[0]
        self.assertEqual(result.outcome, "timed_out")
        self.assertTrue(result.timed_out)
        self.assertTrue(result.children_reaped)
        self.assertTrue(result.temp_removed)
        self.assert_pid_gone(int(child_pid.read_text(encoding="ascii")))

    def test_orphaned_descendant_is_killed_and_reaped_after_parent_exit(self) -> None:
        child_pid = self.evidence / "orphan-pid"
        result = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec(
                    "orphan",
                    str(child_pid),
                    "RUNNER_PRIVACY_ORPHAN_SENTINEL",
                ),
            ),
        )[0]
        self.assertEqual(result.outcome, "passed")
        self.assertTrue(result.children_reaped)
        self.assert_pid_gone(int(child_pid.read_text(encoding="ascii")))

    def test_int_term_and_hup_interruptions_all_quiesce_the_group(self) -> None:
        for handled_signal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=handled_signal):
                child_pid = self.evidence / f"interrupt-{handled_signal.value}"
                timer = threading.Timer(
                    0.25,
                    lambda current=handled_signal: os.kill(os.getpid(), current),
                )
                timer.start()
                try:
                    result = runner.run_sequential_processes(
                        self.run_root,
                        (
                            self.spec(
                                "hang",
                                str(child_pid),
                                "RUNNER_PRIVACY_INTERRUPT_SENTINEL",
                                resource_limits=limits(timeout_ms=5000),
                            ),
                        ),
                    )[0]
                finally:
                    timer.cancel()
                self.assertEqual(result.outcome, "interrupted")
                self.assertTrue(result.interrupted)
                self.assertTrue(result.children_reaped)
                self.assert_pid_gone(int(child_pid.read_text(encoding="ascii")))

    def test_memory_and_process_counts_are_bounded_per_process_group(self) -> None:
        memory = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec(
                    "allocate-memory",
                    "64",
                    "OK",
                    sentinel="OK",
                    resource_limits=limits(
                        memory_bytes=24 * 1024 * 1024,
                        timeout_ms=5000,
                    ),
                ),
            ),
        )[0]
        self.assertEqual(memory.outcome, "resource_limited")
        self.assertTrue(memory.memory_limited)

        pids = self.evidence / "many-pids"
        processes = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec(
                    "spawn-many",
                    "8",
                    str(pids),
                    "OK",
                    sentinel="OK",
                    resource_limits=limits(processes=2, timeout_ms=5000),
                ),
            ),
        )[0]
        self.assertEqual(processes.outcome, "resource_limited")
        self.assertTrue(processes.processes_limited)
        for raw_pid in pids.read_text(encoding="ascii").splitlines():
            self.assert_pid_gone(int(raw_pid))

    def test_resource_monitor_failure_is_fail_closed(self) -> None:
        with mock.patch.object(runner, "_process_group_usage", return_value=None):
            result = runner.run_sequential_processes(
                self.run_root,
                (
                    self.spec(
                        "allocate-memory",
                        "1",
                        "OK",
                        sentinel="OK",
                        resource_limits=limits(timeout_ms=5000),
                    ),
                ),
            )[0]
        self.assertEqual(result.outcome, "resource_limited")
        self.assertTrue(result.processes_limited)
        self.assertTrue(result.children_reaped)

    def test_file_size_and_descriptor_counts_are_bounded(self) -> None:
        descriptor_count = self.evidence / "descriptor-count"
        descriptor_result = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec(
                    "open-many",
                    "200",
                    str(descriptor_count),
                    "OK",
                    sentinel="OK",
                    resource_limits=limits(open_files=64),
                ),
            ),
        )[0]
        self.assertEqual(descriptor_result.outcome, "passed")
        self.assertLess(int(descriptor_count.read_text(encoding="ascii")), 200)

        file_result = runner.run_sequential_processes(
            self.run_root,
            (
                self.spec(
                    "write-large",
                    str(1024 * 1024),
                    "OK",
                    sentinel="OK",
                    resource_limits=limits(file_size_bytes=4096),
                ),
            ),
        )[0]
        self.assertIn(file_result.outcome, {"failed", "passed"})
        self.assertTrue(runner._remove_owned_tree(self.run_root))
        self.assertFalse(self.run_root.exists())

    def test_bytecode_attempt_is_red_and_final_cleanup_removes_it(self) -> None:
        result = runner.run_sequential_processes(
            self.run_root,
            (self.spec("create-bytecode", "OK", sentinel="OK"),),
        )[0]
        self.assertFalse(result.bytecode_absent)
        self.assertTrue(runner._remove_owned_tree(self.run_root))
        self.assertFalse(self.run_root.exists())


class SnapshotAndReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = selector.load_manifest(
            runner.MANIFEST_PATH,
            schema_path=runner.MANIFEST_SCHEMA_PATH,
        )
        cls.receipt_schema = contracts.parse_json_document(
            runner.RECEIPT_SCHEMA_PATH.read_bytes()
        )

    def source_and_selection(
        self,
        *,
        causes: tuple[str, ...] = ("direct",),
        disposition: str = "run",
    ) -> tuple[selector.SourceBinding, selector.Selection]:
        source = selector.SourceBinding(
            repository_id=contracts.REPOSITORY_ID,
            source_kind="staged_index",
            candidate_tree_sha256="sha256:" + ("1" * 64),
            manifest_id=self.manifest.manifest_id,
            selector_version=selector.SELECTOR_VERSION,
            base_commit_sha="1" * 40,
            head_commit_sha=None,
            merge_base_sha=None,
            index_tree_sha="2" * 40,
            commit_sha=None,
        )
        decision = selector.ObligationDecision(
            "dev.structure",
            disposition,
            causes,
        )
        selection = selector.Selection(
            source=source,
            lane="local",
            requested_mode="pre_commit",
            effective_mode="full",
            focus_eligible=False,
            selector_control_ok=True,
            change_tags=(),
            focused_obligation_ids=(),
            effective_obligation_ids=("dev.structure",),
            decisions=(decision,),
            diagnostic_codes=(),
            fallback_executor="preserved.full",
        )
        return source, selection

    def receipt_pair(
        self,
    ) -> tuple[dict, dict, dict[str, dict]]:
        source, selection = self.source_and_selection()
        timing = {
            "snapshot_ms": 1,
            "selection_ms": 0,
            "execution_ms": 7,
            "cleanup_ms": 1,
            "total_ms": 9,
        }
        full, shadow = runner._full_and_shadow_receipts(
            source,
            self.manifest,
            selection,
            process_result(),
            temp_removed=True,
            timing=timing,
        )
        store = {full["receipt_id"]: full, shadow["receipt_id"]: shadow}
        return full, shadow, store

    def test_focused_disposition_precedence_and_multicause_deduplication(self) -> None:
        cases = (
            (("direct", "not_applicable"), False, "not_applicable"),
            (("full_mode", "not_applicable"), True, "blocked"),
            (("deep_mode",), False, "run"),
            (("fallback",), False, "run"),
            (("self_protection",), False, "run"),
            (("full_mode",), False, "run"),
            (("dependency",), False, "run"),
            (("direct",), False, "run"),
            (("reverse_impact",), False, "run"),
            (("universal",), False, "run"),
            (("inert",), False, "skip"),
            ((), False, "skip"),
        )
        for causes, blocked, expected in cases:
            with self.subTest(causes=causes, blocked=blocked):
                disposition, canonical = runner.focused_decision(
                    causes,
                    blocked=blocked,
                )
                self.assertEqual(disposition, expected)
                self.assertEqual(canonical, tuple(sorted(set(causes))))
        disposition, canonical = runner.focused_decision(
            ("direct", "dependency", "direct")
        )
        self.assertEqual((disposition, canonical), ("run", ("dependency", "direct")))

    def test_runner_rejects_noncanonical_causes_or_false_scalar_disposition(self) -> None:
        for causes, disposition in (
            (("direct", "dependency"), "run"),
            (("direct",), "skip"),
        ):
            source, selection = self.source_and_selection(
                causes=causes,
                disposition=disposition,
            )
            with self.subTest(causes=causes, disposition=disposition):
                with self.assertRaises(runner.RunnerError):
                    runner._focused_rows(selection, self.manifest)

    def test_m1_shadow_tuple_never_claims_execution_or_pass(self) -> None:
        full, shadow, store = self.receipt_pair()
        row = shadow["rows"][0]
        self.assertEqual(
            (
                row["execution_disposition"],
                row["outcome"],
                row["exit_code"],
                row["duration_ms"],
                row["diagnostic_code"],
            ),
            ("not_applicable", "not_observed", None, None, "shadow.unobserved"),
        )
        self.assertEqual(row["focused_disposition"], "run")
        self.assertEqual(row["selection_causes"], ["direct"])
        contracts.validate_against_schema(shadow, self.receipt_schema)
        contracts.validate_receipt(
            shadow,
            manifests={self.manifest.manifest_id: self.manifest.value},
            receipt_store=store,
        )
        self.assertEqual(full["aggregate_execution"]["outcome"], "passed")

    def test_every_shadow_tuple_mutation_is_rejected(self) -> None:
        full, shadow, _store = self.receipt_pair()
        mutations = {
            "execution_disposition": "run",
            "outcome": "passed",
            "exit_code": 0,
            "duration_ms": 1,
            "diagnostic_code": "focused.passed",
        }
        for field, value in mutations.items():
            changed = copy.deepcopy(shadow)
            changed["rows"][0][field] = value
            changed = contracts.with_derived_identity(changed, "receipt_id")
            store = {full["receipt_id"]: full, changed["receipt_id"]: changed}
            with self.subTest(field=field):
                with self.assertRaises(contracts.ContractError):
                    contracts.validate_receipt(
                        changed,
                        manifests={self.manifest.manifest_id: self.manifest.value},
                        receipt_store=store,
                    )

    def test_full_is_content_addressed_and_shadow_links_identical_source_and_aggregate(self) -> None:
        full, shadow, store = self.receipt_pair()
        self.assertEqual(
            shadow["authoritative_receipt_id"],
            full["receipt_id"],
        )
        self.assertEqual(shadow["source"], full["source"])
        self.assertEqual(
            shadow["aggregate_execution"],
            full["aggregate_execution"],
        )
        self.assertEqual(
            full["aggregate_execution"]["selection_causes"],
            ["full_mode"],
        )
        self.assertEqual(
            str(contracts.derive_identity(full, "receipt_id")),
            full["receipt_id"],
        )
        self.assertEqual(
            str(contracts.derive_identity(shadow, "receipt_id")),
            shadow["receipt_id"],
        )
        contracts.validate_receipt(
            shadow,
            manifests={self.manifest.manifest_id: self.manifest.value},
            receipt_store=store,
        )

    def test_runner_reproduces_frozen_exact_receipt_bytes_and_id(self) -> None:
        goldens = contracts.parse_json_document(WIRE_GOLDENS.read_bytes())
        expected = goldens["receipts"]["staged_full"]["value"]
        manifest_value = goldens["manifest"]["valid"]["value"]
        manifest = selector.Manifest(
            value=manifest_value,
            canonical_bytes=contracts.canonical_json(manifest_value),
        )
        source = selector.SourceBinding(**expected["source"])
        generated = runner._receipt_base(
            mode=expected["mode"],
            source=source,
            manifest=manifest,
            aggregate_execution=expected["aggregate_execution"],
            changes=expected["changes"],
            rows=expected["rows"],
            cleanup=expected["cleanup"],
            authoritative_receipt_id=expected["authoritative_receipt_id"],
            lane=expected["lane"],
            requested_mode=expected["requested_mode"],
            timing=expected["timing"],
            created_at=expected["created_at"],
        )
        self.assertEqual(generated, expected)
        self.assertEqual(generated["receipt_id"], goldens["receipts"]["staged_full"]["receipt_id"])
        self.assertEqual(
            contracts.canonical_json(generated),
            base64.b64decode(goldens["receipts"]["staged_full"]["canonical_b64"]),
        )
        self.assertNotIn("receipt_sha256", generated)

    def test_missing_or_mismatched_authoritative_full_rejects_shadow(self) -> None:
        full, shadow, _store = self.receipt_pair()
        mutations = []
        missing = copy.deepcopy(shadow)
        missing["authoritative_receipt_id"] = "sha256:" + ("f" * 64)
        mutations.append(
            (
                contracts.with_derived_identity(missing, "receipt_id"),
                {full["receipt_id"]: full},
            )
        )
        altered_full = copy.deepcopy(full)
        altered_full["aggregate_execution"]["duration_ms"] += 1
        altered_full = contracts.with_derived_identity(altered_full, "receipt_id")
        altered_shadow = copy.deepcopy(shadow)
        altered_shadow["authoritative_receipt_id"] = altered_full["receipt_id"]
        altered_shadow = contracts.with_derived_identity(altered_shadow, "receipt_id")
        mutations.append(
            (
                altered_shadow,
                {
                    altered_full["receipt_id"]: altered_full,
                    altered_shadow["receipt_id"]: altered_shadow,
                },
            )
        )
        for changed, store in mutations:
            with self.assertRaises(contracts.ContractError):
                contracts.validate_receipt(
                    changed,
                    manifests={self.manifest.manifest_id: self.manifest.value},
                    receipt_store=store,
                )

    def test_empty_full_rows_are_transitional_only_and_never_graduation_evidence(self) -> None:
        full, _shadow, _store = self.receipt_pair()
        contracts.validate_receipt(
            full,
            manifests={self.manifest.manifest_id: self.manifest.value},
            receipt_store={full["receipt_id"]: full},
        )
        self.assertFalse(
            runner.receipt_is_graduation_eligible(full, self.manifest.value)
        )

        decomposed = copy.deepcopy(dict(self.manifest.value))
        decomposed["activation"]["full_profile"] = "decomposed"
        decomposed = contracts.with_derived_identity(decomposed, "manifest_id")
        changed = copy.deepcopy(full)
        changed["manifest_id"] = decomposed["manifest_id"]
        changed["source"]["manifest_id"] = decomposed["manifest_id"]
        changed = contracts.with_derived_identity(changed, "receipt_id")
        with self.assertRaises(contracts.ContractError):
            contracts.validate_receipt(
                changed,
                manifests={decomposed["manifest_id"]: decomposed},
                receipt_store={changed["receipt_id"]: changed},
            )

    def test_authoritative_full_is_stored_before_linked_shadow(self) -> None:
        source, selection = self.source_and_selection()
        observed: list[dict] = []

        def record_store(payload, **_kwargs):
            observed.append(copy.deepcopy(payload))
            return runner.StoredReceipt(
                payload["receipt_id"],
                Path(payload["receipt_id"].removeprefix("sha256:")),
                copy.deepcopy(payload),
            )

        with (
            mock.patch.object(runner, "_validate_exact_source"),
            mock.patch.object(runner, "materialize_candidate_snapshot"),
            mock.patch.object(runner, "_initialize_snapshot_git"),
            mock.patch.object(
                runner,
                "run_sequential_processes",
                return_value=(process_result(),),
            ),
            mock.patch.object(runner, "store_receipt", side_effect=record_store),
        ):
            runner.execute_local_shadow(
                source,
                self.manifest,
                selection,
                repo=ROOT,
            )
        self.assertEqual([item["mode"] for item in observed], ["full", "shadow"])
        self.assertEqual(
            observed[1]["authoritative_receipt_id"],
            observed[0]["receipt_id"],
        )

    def test_materialized_snapshot_preserves_bytes_modes_symlinks_and_private_root(self) -> None:
        blobs = {
            selector.MANIFEST_RELATIVE_PATH: self.manifest.canonical_bytes,
            selector.MANIFEST_SCHEMA_RELATIVE_PATH: runner.MANIFEST_SCHEMA_PATH.read_bytes(),
            b"data/file.txt": b"regular\n",
            b"exec.sh": b"#!/bin/sh\nexit 0\n",
            b"link": b"data/file.txt",
        }
        modes = {
            selector.MANIFEST_RELATIVE_PATH: "100644",
            selector.MANIFEST_SCHEMA_RELATIVE_PATH: "100644",
            b"data/file.txt": "100644",
            b"exec.sh": "100755",
            b"link": "120000",
        }
        if sys.platform != "darwin":
            blobs[b"non-utf8-\xff.bin"] = b"\x00\xff"
            modes[b"non-utf8-\xff.bin"] = "100644"
        entries = tuple(
            selector.CandidateEntry(
                selector.PathIdentity.from_bytes(raw),
                modes[raw],
                str(contracts.sha256_id(blobs[raw])),
                _oid=git_blob_oid(blobs[raw]),
            )
            for raw in sorted(blobs)
        )
        source = selector.SourceBinding(
            repository_id=contracts.REPOSITORY_ID,
            source_kind="commit",
            candidate_tree_sha256=selector._candidate_digest(entries),
            manifest_id=self.manifest.manifest_id,
            selector_version=selector.SELECTOR_VERSION,
            base_commit_sha=None,
            head_commit_sha=None,
            merge_base_sha=None,
            index_tree_sha=None,
            commit_sha="a" * 40,
            _candidate_entries=entries,
            _base_entries=(),
            _candidate_blobs=blobs,
            _base_blobs={},
            _manifest_bytes=self.manifest.canonical_bytes,
            _manifest_schema_bytes=runner.MANIFEST_SCHEMA_PATH.read_bytes(),
        )
        with tempfile.TemporaryDirectory(prefix="runner-snapshot-test-") as name:
            snapshot = Path(name) / "snapshot"
            runner.materialize_candidate_snapshot(source, self.manifest, snapshot)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((snapshot / "data" / "file.txt").stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE((snapshot / "exec.sh").stat().st_mode),
                0o700,
            )
            self.assertEqual(os.readlink(snapshot / "link"), "data/file.txt")
            if sys.platform != "darwin":
                raw_non_utf8 = os.path.join(
                    os.fsencode(snapshot),
                    b"non-utf8-\xff.bin",
                )
                descriptor = os.open(raw_non_utf8, os.O_RDONLY)
                try:
                    self.assertEqual(os.read(descriptor, 16), b"\x00\xff")
                finally:
                    os.close(descriptor)
            runner._initialize_snapshot_git(source, snapshot)
            self.assertEqual(
                runner._git(snapshot, "diff", "--quiet").returncode,
                0,
            )

            unsafe_entries = [
                (b"absolute-link", "120000", b"/private/privacy-sentinel"),
                (b"nested/escape-link", "120000", b"../../privacy-sentinel"),
                (b"git-link", "120000", b".git/config"),
            ]
            if sys.platform == "darwin":
                # Darwin filesystems cannot materialize arbitrary Git path bytes.
                unsafe_entries.append(
                    (b"non-utf8-\xff.bin", "100644", b"\x00\xff")
                )
            for index, (invalid_path, invalid_mode, invalid_blob) in enumerate(
                unsafe_entries
            ):
                invalid_entry = selector.CandidateEntry(
                    selector.PathIdentity.from_bytes(invalid_path),
                    invalid_mode,
                    str(contracts.sha256_id(invalid_blob)),
                    _oid=git_blob_oid(invalid_blob),
                )
                invalid_entries = tuple(
                    sorted(
                        (*source._candidate_entries, invalid_entry),
                        key=lambda item: item.path.raw,
                    )
                )
                invalid_source = replace(
                    source,
                    candidate_tree_sha256=selector._candidate_digest(
                        invalid_entries
                    ),
                    _candidate_entries=invalid_entries,
                    _candidate_blobs={
                        **source._candidate_blobs,
                        invalid_path: invalid_blob,
                    },
                )
                refused = Path(name) / f"refused-{index}"
                with self.subTest(path=invalid_path, target=invalid_blob):
                    with self.assertRaises(runner.RunnerError):
                        runner.materialize_candidate_snapshot(
                            invalid_source,
                            self.manifest,
                            refused,
                        )
                    self.assertFalse(refused.exists())


class StorageAndImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-import-tests-")
        self.repo = Path(self.temporary.name) / "repo"
        target = self.repo / "_ops" / "verification"
        target.mkdir(parents=True)
        for name in AUTHORITY_FILES:
            shutil.copyfile(VERIFICATION / name, target / name)
        runner._git(self.repo, "init", "--quiet")
        runner._git(self.repo, "add", "--all")
        runner._git(
            self.repo,
            "-c",
            "user.name=Runner Tests",
            "-c",
            "user.email=runner@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture authority",
        )
        self.manifest = contracts.validate_canonical_input(
            (target / "verification-manifest.json").read_bytes()
        )
        self.ledger_path = target / "verification-rollout-ledger.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def head(self) -> str:
        return runner._git(self.repo, "rev-parse", "HEAD").stdout.rstrip().decode("ascii")

    def tree(self) -> str:
        return (
            runner._git(self.repo, "rev-parse", "HEAD^{tree}")
            .stdout.rstrip()
            .decode("ascii")
        )

    def new_commit(self, marker: str) -> str:
        path = self.repo / marker
        path.write_text(marker, encoding="utf-8")
        runner._git(self.repo, "add", marker)
        runner._git(
            self.repo,
            "-c",
            "user.name=Runner Tests",
            "-c",
            "user.email=runner@example.invalid",
            "commit",
            "--quiet",
            "-m",
            marker,
        )
        return self.head()

    def receipt(
        self,
        *,
        source_kind: str = "commit",
        candidate_digest: str | None = None,
        outcome: str = "passed",
        created_at: str = "2026-09-04T00:00:00Z",
    ) -> dict:
        receipt = contracts.validate_canonical_input(
            base64.b64decode(
                __import__("json")
                .loads(
                    (VERIFICATION / "fixtures" / "wire-goldens-v1.json").read_text(
                        encoding="utf-8"
                    )
                )["receipts"][
                    "commit_release" if source_kind == "commit" else "staged_full"
                ]["canonical_b64"],
                validate=True,
            )
        )
        digest = candidate_digest or runner._commit_candidate_digest(
            self.repo, "HEAD"
        )
        receipt["created_at"] = created_at
        receipt["manifest_id"] = self.manifest["manifest_id"]
        receipt["activation_generation"] = self.manifest["activation"]["generation"]
        receipt["source"]["manifest_id"] = self.manifest["manifest_id"]
        receipt["source"]["candidate_tree_sha256"] = digest
        if source_kind == "commit":
            receipt["source"].update(
                {
                    "source_kind": "commit",
                    "base_commit_sha": None,
                    "head_commit_sha": None,
                    "merge_base_sha": None,
                    "index_tree_sha": None,
                    "commit_sha": self.head(),
                }
            )
        else:
            receipt["source"].update(
                {
                    "source_kind": "staged_index",
                    "base_commit_sha": self.head(),
                    "head_commit_sha": None,
                    "merge_base_sha": None,
                    "index_tree_sha": self.tree(),
                    "commit_sha": None,
                }
            )
        receipt["changes"] = []
        receipt["aggregate_execution"]["outcome"] = outcome
        receipt["aggregate_execution"]["exit_code"] = 0 if outcome in {"passed", "failed"} else None
        return contracts.with_derived_identity(receipt, "receipt_id")

    def store(self, receipt: dict | None = None) -> runner.StoredReceipt:
        return runner.store_receipt(
            receipt or self.receipt(),
            repo=self.repo,
            manifest=self.manifest,
        )

    def test_git_local_store_has_exact_modes_name_identity_and_canonical_bytes(self) -> None:
        stored = self.store()
        state = stored.path.parents[2]
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(stored.path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(stored.path.stat().st_mode), 0o600)
        self.assertEqual(
            stored.path.name,
            f"{stored.receipt_id.removeprefix('sha256:')}.json",
        )
        raw = stored.path.read_bytes()
        self.assertEqual(raw, contracts.canonical_json(stored.payload))
        self.assertFalse(raw.endswith(b"\n"))
        self.assertEqual(
            str(contracts.derive_identity(stored.payload, "receipt_id")),
            stored.receipt_id,
        )
        self.assertNotIn("receipt_digest", stored.payload)
        self.assertEqual(
            [path.name for path in stored.path.parent.iterdir()],
            [stored.path.name],
        )

    def test_store_uses_same_directory_atomic_rename_and_is_idempotent(self) -> None:
        receipt = self.receipt()
        with mock.patch.object(
            runner.os,
            "replace",
            wraps=os.replace,
        ) as replace:
            first = self.store(receipt)
        source, destination = replace.call_args.args
        self.assertEqual(Path(source).parent, first.path.parent)
        self.assertEqual(Path(destination), first.path)
        second = self.store(receipt)
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.path.read_bytes(), second.path.read_bytes())

    def test_crash_left_owned_temp_is_recovered_before_store(self) -> None:
        store = runner.receipt_store_root(self.repo, create=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".receipt-",
            dir=store,
        )
        temporary = Path(temporary_name)
        try:
            os.write(descriptor, b"partial-private-receipt")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.assertRegex(temporary.name, runner.RECEIPT_TEMP_NAME)
        self.assertEqual(stat.S_IMODE(temporary.stat().st_mode), 0o600)

        stored = self.store()

        self.assertFalse(temporary.exists())
        self.assertEqual(
            [path.name for path in store.iterdir()],
            [stored.path.name],
        )
        event = runner.import_receipt(
            stored.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.assertEqual(event["receipt_ids"], [stored.receipt_id])

    def test_unsafe_or_foreign_store_artifacts_fail_closed_untouched(self) -> None:
        store = runner.receipt_store_root(self.repo, create=True)
        target = self.repo / "symlink-target"
        target.write_bytes(b"do-not-delete")
        cases = (
            ("symlink", ".receipt-abcdefgh"),
            ("directory", ".receipt-12345678"),
            ("unsafe-mode", ".receipt-abcd1234"),
            ("foreign-name", ".receipt-foreign"),
        )
        for kind, name in cases:
            artifact = store / name
            if kind == "symlink":
                artifact.symlink_to(target)
            elif kind == "directory":
                artifact.mkdir(mode=0o700)
            else:
                artifact.write_bytes(b"foreign-private-data")
                artifact.chmod(0o644 if kind == "unsafe-mode" else 0o600)
            before = artifact.lstat()
            before_target = os.readlink(artifact) if artifact.is_symlink() else None
            before_bytes = (
                artifact.read_bytes() if artifact.is_file() and not artifact.is_symlink() else None
            )

            with self.subTest(kind=kind):
                with self.assertRaisesRegex(
                    runner.RunnerError,
                    "receipt_invalid",
                ):
                    self.store()
                after = artifact.lstat()
                self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
                if before_target is not None:
                    self.assertEqual(os.readlink(artifact), before_target)
                    self.assertEqual(target.read_bytes(), b"do-not-delete")
                if before_bytes is not None:
                    self.assertEqual(artifact.read_bytes(), before_bytes)

            if artifact.is_dir() and not artifact.is_symlink():
                artifact.rmdir()
            else:
                artifact.unlink()

    def test_post_rename_failure_removes_installed_receipt(self) -> None:
        store = runner.receipt_store_root(self.repo, create=True)
        with mock.patch.object(
            runner.os,
            "chmod",
            side_effect=OSError("privacy-storage-sentinel"),
        ):
            with self.assertRaisesRegex(runner.RunnerError, "receipt_invalid"):
                self.store()
        self.assertEqual(list(store.iterdir()), [])

    def test_invalid_receipt_leaves_no_final_or_temporary_file(self) -> None:
        invalid = self.receipt()
        invalid["unexpected"] = "RUNNER_PRIVACY_SOURCE_SENTINEL"
        with self.assertRaises(runner.RunnerError):
            self.store(invalid)
        store = runner.receipt_store_root(self.repo, create=True)
        self.assertEqual(list(store.iterdir()), [])

    def test_cleanup_failure_never_earns_or_persists_passing_evidence(self) -> None:
        for flag in (
            "children_reaped",
            "temp_removed",
            "index_removed",
            "objects_unchanged",
            "bytecode_absent",
        ):
            changed = self.receipt()
            changed["cleanup"][flag] = False
            changed = contracts.with_derived_identity(changed, "receipt_id")
            with self.subTest(flag=flag):
                with self.assertRaisesRegex(runner.RunnerError, "cleanup_failed"):
                    self.store(changed)
        store = runner.receipt_store_root(self.repo, create=True)
        self.assertEqual(list(store.iterdir()), [])

    def test_privacy_channels_are_rejected_without_persisting_sentinels(self) -> None:
        paths = (
            b"home/RUNNER_PRIVACY_SECRET_SENTINEL",
            b"tmp/RUNNER_PRIVACY_TEMP_SENTINEL",
            b"private/RUNNER_PRIVACY_OPERATOR_SENTINEL",
            b"https:/RUNNER_PRIVACY_NETWORK_SENTINEL",
            b"host.example.com/RUNNER_PRIVACY_NETWORK_SENTINEL",
            b"192.0.2.10/RUNNER_PRIVACY_NETWORK_SENTINEL",
            f"{os.environ.get('USER', 'user')}/RUNNER_PRIVACY_USER_SENTINEL".encode(),
        )
        for raw_path in paths:
            changed = self.receipt()
            changed["changes"] = [
                {
                    "status": "add",
                    "old_path": None,
                    "new_path": contracts.PathValue.from_bytes(raw_path).to_object(),
                    "old_mode": None,
                    "new_mode": "100644",
                    "old_blob_sha256": None,
                    "new_blob_sha256": "sha256:" + ("a" * 64),
                }
            ]
            changed = contracts.with_derived_identity(changed, "receipt_id")
            with self.subTest(path=raw_path):
                with self.assertRaises(runner.RunnerError):
                    self.store(changed)
        store = runner.receipt_store_root(self.repo, create=True)
        combined = b"".join(path.read_bytes() for path in store.glob("*.json"))
        self.assertNotIn(b"RUNNER_PRIVACY", combined)

    def test_import_accepts_only_exact_root_regular_mode_0600_receipt(self) -> None:
        stored = self.store()
        outside = self.repo / stored.path.name
        outside.write_bytes(stored.path.read_bytes())
        outside.chmod(0o600)
        with self.assertRaises(runner.RunnerError):
            runner.import_receipt(
                outside,
                repo=self.repo,
                ledger_path=self.ledger_path,
            )
        link = stored.path.parent / ("f" * 64 + ".json")
        link.symlink_to(stored.path)
        with self.assertRaises(runner.RunnerError):
            runner.import_receipt(
                link,
                repo=self.repo,
                ledger_path=self.ledger_path,
            )
        link.unlink()
        stored.path.chmod(0o644)
        with self.assertRaises(runner.RunnerError):
            runner.import_receipt(
                stored.path,
                repo=self.repo,
                ledger_path=self.ledger_path,
            )

    def test_import_rejects_noncanonical_altered_identity_and_privacy_bytes(self) -> None:
        variants: list[bytes] = []
        receipt = self.receipt()
        variants.append(contracts.canonical_json(receipt) + b"\n")
        altered = copy.deepcopy(receipt)
        altered["created_at"] = "2026-09-04T00:00:01Z"
        variants.append(contracts.canonical_json(altered))
        private = copy.deepcopy(receipt)
        private["cleanup"]["diagnostic_code"] = "privacy.operator"
        private = contracts.with_derived_identity(private, "receipt_id")
        variants.append(contracts.canonical_json(private))
        for raw in variants:
            with self.subTest(raw=raw[-32:]):
                stored = self.store(receipt)
                stored.path.write_bytes(raw)
                stored.path.chmod(0o600)
                before = self.ledger_path.read_bytes()
                with self.assertRaises(runner.RunnerError):
                    runner.import_receipt(
                        stored.path,
                        repo=self.repo,
                        ledger_path=self.ledger_path,
                    )
                self.assertEqual(self.ledger_path.read_bytes(), before)
                stored.path.unlink()

    def test_committed_receipt_import_appends_closed_source_bound_observation(self) -> None:
        stored = self.store()
        event = runner.import_receipt(
            stored.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.assertEqual(event["payload"]["outcome"], "passed")
        self.assertEqual(event["payload"]["observation_kind"], "real_change")
        self.assertEqual(event["source"], stored.payload["source"])
        self.assertEqual(
            event["source"]["candidate_tree_sha256"],
            runner._commit_candidate_digest(self.repo, "HEAD"),
        )
        self.assertEqual(event["receipt_ids"], [stored.receipt_id])
        self.assertEqual(event["provenance"]["kind"], "local_command")
        self.assertEqual(
            event["provenance"]["reference"],
            event["provenance"]["reference_sha256"],
        )
        ledger = contracts.validate_canonical_input(self.ledger_path.read_bytes())
        self.assertEqual(ledger["events"][-1], event)
        self.assertEqual(
            event["previous_event_id"],
            ledger["events"][-2]["event_id"],
        )

    def test_ledger_write_failure_preserves_ledger_and_all_receipts(self) -> None:
        first = self.store()
        runner.import_receipt(
            first.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.new_commit("candidate-two")
        second = self.store(
            self.receipt(created_at="2026-09-04T00:00:01Z")
        )
        ledger_before = self.ledger_path.read_bytes()
        store_before = {
            path.name: path.read_bytes()
            for path in second.path.parent.iterdir()
        }
        real_replace = os.replace

        def fail_ledger_replace(source: str, destination: str) -> None:
            if Path(destination) == self.ledger_path:
                raise OSError("injected ledger write failure")
            real_replace(source, destination)

        with mock.patch.object(runner.os, "replace", side_effect=fail_ledger_replace):
            with self.assertRaisesRegex(runner.RunnerError, "ledger_invalid"):
                runner.import_receipt(
                    second.path,
                    repo=self.repo,
                    ledger_path=self.ledger_path,
                    now="2026-09-04T01:00:01Z",
                )

        self.assertEqual(self.ledger_path.read_bytes(), ledger_before)
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in second.path.parent.iterdir()
            },
            store_before,
        )
        self.assertFalse(
            any(
                path.name.startswith(f".{self.ledger_path.name}.")
                for path in self.ledger_path.parent.iterdir()
            )
        )

    def test_post_append_prune_failure_returns_success_and_recovers_on_retry(self) -> None:
        first = self.store()
        runner.import_receipt(
            first.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.new_commit("candidate-two")
        second = self.store(
            self.receipt(created_at="2026-09-04T00:00:01Z")
        )

        with mock.patch.object(
            runner,
            "_prune_imported_receipts",
            side_effect=runner.RunnerError("receipt_invalid"),
        ):
            event = runner.import_receipt(
                second.path,
                repo=self.repo,
                ledger_path=self.ledger_path,
                now="2026-09-04T01:00:01Z",
            )

        ledger_after_append = self.ledger_path.read_bytes()
        self.assertEqual(
            contracts.validate_canonical_input(ledger_after_append)["events"][-1],
            event,
        )
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())

        retried = runner.import_receipt(
            second.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:02Z",
        )
        self.assertEqual(retried, event)
        self.assertEqual(self.ledger_path.read_bytes(), ledger_after_append)
        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())

    def _assert_post_append_prune_control_propagates(
        self,
        interruption: BaseException,
    ) -> None:
        first = self.store()
        runner.import_receipt(
            first.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        events_before = len(
            contracts.validate_canonical_input(
                self.ledger_path.read_bytes()
            )["events"]
        )
        self.new_commit("candidate-two")
        second = self.store(
            self.receipt(created_at="2026-09-04T00:00:01Z")
        )

        with mock.patch.object(
            runner,
            "_prune_imported_receipts",
            side_effect=interruption,
        ):
            with self.assertRaises(type(interruption)) as raised:
                runner.import_receipt(
                    second.path,
                    repo=self.repo,
                    ledger_path=self.ledger_path,
                    now="2026-09-04T01:00:01Z",
                )
        self.assertIs(raised.exception, interruption)

        ledger_after = self.ledger_path.read_bytes()
        ledger = contracts.validate_canonical_input(ledger_after)
        self.assertEqual(len(ledger["events"]), events_before + 1)
        event = ledger["events"][-1]
        self.assertEqual(event["receipt_ids"], [second.receipt_id])
        self.assertEqual(
            sum(second.receipt_id in item["receipt_ids"] for item in ledger["events"]),
            1,
        )
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())

        retried = runner.import_receipt(
            second.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:02Z",
        )
        self.assertEqual(retried, event)
        self.assertEqual(self.ledger_path.read_bytes(), ledger_after)
        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())

    def test_post_append_prune_propagates_keyboard_interrupt(self) -> None:
        self._assert_post_append_prune_control_propagates(KeyboardInterrupt())

    def test_post_append_prune_propagates_system_exit(self) -> None:
        self._assert_post_append_prune_control_propagates(SystemExit(17))

    def _assert_existing_retry_prune_control_propagates(
        self,
        interruption: BaseException,
    ) -> None:
        first = self.store()
        runner.import_receipt(
            first.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.new_commit("candidate-two")
        second = self.store(
            self.receipt(created_at="2026-09-04T00:00:01Z")
        )
        with mock.patch.object(
            runner,
            "_prune_imported_receipts",
            side_effect=runner.RunnerError("receipt_invalid"),
        ):
            event = runner.import_receipt(
                second.path,
                repo=self.repo,
                ledger_path=self.ledger_path,
                now="2026-09-04T01:00:01Z",
            )
        ledger_before_retry = self.ledger_path.read_bytes()

        with mock.patch.object(
            runner,
            "_prune_imported_receipts",
            side_effect=interruption,
        ):
            with self.assertRaises(type(interruption)) as raised:
                runner.import_receipt(
                    second.path,
                    repo=self.repo,
                    ledger_path=self.ledger_path,
                    now="2026-09-04T01:00:02Z",
                )
        self.assertIs(raised.exception, interruption)

        ledger = contracts.validate_canonical_input(
            self.ledger_path.read_bytes()
        )
        self.assertEqual(self.ledger_path.read_bytes(), ledger_before_retry)
        self.assertEqual(
            sum(second.receipt_id in item["receipt_ids"] for item in ledger["events"]),
            1,
        )
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())

        retried = runner.import_receipt(
            second.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:03Z",
        )
        self.assertEqual(retried, event)
        self.assertEqual(self.ledger_path.read_bytes(), ledger_before_retry)
        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())

    def test_existing_retry_prune_propagates_keyboard_interrupt(self) -> None:
        self._assert_existing_retry_prune_control_propagates(KeyboardInterrupt())

    def test_existing_retry_prune_propagates_system_exit(self) -> None:
        self._assert_existing_retry_prune_control_propagates(SystemExit(17))

    def test_staged_replay_is_blocked_until_exact_commit_tree_matches(self) -> None:
        mismatch = self.receipt(
            source_kind="staged_index",
            candidate_digest="sha256:" + ("e" * 64),
        )
        blocked = self.store(mismatch)
        event = runner.import_receipt(
            blocked.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.assertEqual(event["payload"]["outcome"], "blocked")

        matching = self.receipt(
            source_kind="staged_index",
            created_at="2026-09-04T00:00:01Z",
        )
        passed = self.store(matching)
        event = runner.import_receipt(
            passed.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:01Z",
        )
        self.assertEqual(event["payload"]["outcome"], "passed")

    def test_commit_source_with_false_candidate_digest_is_rejected(self) -> None:
        receipt = self.receipt(candidate_digest="sha256:" + ("d" * 64))
        stored = self.store(receipt)
        with self.assertRaises(runner.RunnerError) as raised:
            runner.import_receipt(
                stored.path,
                repo=self.repo,
                ledger_path=self.ledger_path,
            )
        self.assertEqual(raised.exception.reason, "safety_mismatch")

    def test_pull_request_source_requires_exact_merge_base(self) -> None:
        receipt = self.receipt(source_kind="staged_index")
        receipt["source"].update(
            {
                "source_kind": "pull_request",
                "base_commit_sha": self.head(),
                "head_commit_sha": self.head(),
                "merge_base_sha": "f" * 40,
                "index_tree_sha": None,
                "commit_sha": None,
            }
        )
        receipt["lane"] = "runnerless_pr"
        receipt = contracts.with_derived_identity(receipt, "receipt_id")
        stored = self.store(receipt)
        with self.assertRaisesRegex(runner.RunnerError, "safety_mismatch"):
            runner.import_receipt(
                stored.path,
                repo=self.repo,
                ledger_path=self.ledger_path,
            )

    def test_anchored_import_rejects_edited_truncated_and_rehashed_prefixes(self) -> None:
        stored = self.store()
        base = contracts.validate_canonical_input(self.ledger_path.read_bytes())
        variants = []
        edited = copy.deepcopy(base)
        edited["events"][0]["occurred_at"] = "2026-09-02T17:51:35Z"
        variants.append(edited)
        truncated = copy.deepcopy(base)
        truncated["events"].pop()
        variants.append(truncated)
        rehashed = copy.deepcopy(base)
        rehashed["events"][0] = contracts.with_derived_identity(
            {
                **rehashed["events"][0],
                "occurred_at": "2026-09-02T17:51:35Z",
            },
            "event_id",
        )
        previous = rehashed["events"][0]["event_id"]
        for index in range(1, len(rehashed["events"])):
            rehashed["events"][index]["previous_event_id"] = previous
            rehashed["events"][index] = contracts.with_derived_identity(
                rehashed["events"][index],
                "event_id",
            )
            previous = rehashed["events"][index]["event_id"]
        variants.append(rehashed)
        for variant in variants:
            with self.subTest(events=len(variant["events"])):
                self.ledger_path.write_bytes(contracts.canonical_json(variant))
                before = self.ledger_path.read_bytes()
                with self.assertRaises(runner.RunnerError) as raised:
                    runner.import_receipt(
                        stored.path,
                        repo=self.repo,
                        ledger_path=self.ledger_path,
                    )
                self.assertEqual(raised.exception.reason, "ledger_invalid")
                self.assertEqual(self.ledger_path.read_bytes(), before)
        self.ledger_path.write_bytes(contracts.canonical_json(base))

    def test_standalone_ledger_validation_enforces_committed_anchor(self) -> None:
        base = contracts.validate_canonical_input(self.ledger_path.read_bytes())
        rehashed = copy.deepcopy(base)
        rehashed["events"][0] = contracts.with_derived_identity(
            {
                **rehashed["events"][0],
                "occurred_at": "2026-09-02T17:51:35Z",
            },
            "event_id",
        )
        previous = rehashed["events"][0]["event_id"]
        for index in range(1, len(rehashed["events"])):
            rehashed["events"][index]["previous_event_id"] = previous
            rehashed["events"][index] = contracts.with_derived_identity(
                rehashed["events"][index],
                "event_id",
            )
            previous = rehashed["events"][index]["event_id"]
        self.ledger_path.write_bytes(contracts.canonical_json(rehashed))
        with self.assertRaisesRegex(runner.RunnerError, "ledger_invalid"):
            runner.validate_current_ledger(
                repo=self.repo,
                ledger_path=self.ledger_path,
            )

    def test_second_conflicting_passing_logical_credit_is_rejected(self) -> None:
        stored = self.store()
        first_event = runner.import_receipt(
            stored.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        before_retry = self.ledger_path.read_bytes()
        retried = runner.import_receipt(
            stored.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:01Z",
        )
        self.assertEqual(retried, first_event)
        self.assertEqual(self.ledger_path.read_bytes(), before_retry)

        conflicting = self.store(
            self.receipt(created_at="2026-09-04T00:00:01Z")
        )
        before = self.ledger_path.read_bytes()
        with self.assertRaises(runner.RunnerError) as raised:
            runner.import_receipt(
                conflicting.path,
                repo=self.repo,
                ledger_path=self.ledger_path,
                now="2026-09-04T01:00:02Z",
            )
        self.assertEqual(raised.exception.reason, "ledger_invalid")
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_retention_keeps_latest_success_and_bounded_failed_evidence(self) -> None:
        first = self.store()
        runner.import_receipt(
            first.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        self.new_commit("candidate-two")
        second = self.store(
            self.receipt(created_at="2026-09-04T00:00:01Z")
        )
        runner.import_receipt(
            second.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:01Z",
        )
        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())

        failed = self.store(
            self.receipt(
                outcome="failed",
                created_at="2026-09-04T00:00:02Z",
            )
        )
        runner.import_receipt(
            failed.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:02Z",
        )
        self.assertTrue(failed.path.exists())

    def test_failed_receipt_retention_has_a_hard_bound(self) -> None:
        stored = []
        with mock.patch.object(runner, "MAX_RETAINED_FAILED_EVENTS", 3):
            for second in range(5):
                failed = self.store(
                    self.receipt(
                        outcome="failed",
                        created_at=f"2026-09-04T00:00:0{second}Z",
                    )
                )
                stored.append(failed)
                runner.import_receipt(
                    failed.path,
                    repo=self.repo,
                    ledger_path=self.ledger_path,
                    now=f"2026-09-04T01:00:0{second}Z",
                )
        self.assertEqual(
            [item.path.exists() for item in stored],
            [False, False, True, True, True],
        )

    def test_no_result_cache_api_key_or_unowned_temp_file_is_created(self) -> None:
        stored = self.store()
        runner.import_receipt(
            stored.path,
            repo=self.repo,
            ledger_path=self.ledger_path,
            now="2026-09-04T01:00:00Z",
        )
        state_root = stored.path.parents[2]
        relative = sorted(
            str(path.relative_to(state_root))
            for path in state_root.rglob("*")
        )
        self.assertEqual(
            relative,
            [
                "receipts",
                "receipts/sha256",
                f"receipts/sha256/{stored.path.name}",
            ],
        )
        source = runner.__file__ and Path(runner.__file__).read_text(encoding="utf-8")
        for forbidden in ("cache_key", "cache_api", "requests.", "urllib.request"):
            self.assertNotIn(forbidden, source)


class ExplanationTests(unittest.TestCase):
    def test_catalog_is_exactly_existing_closed_codes(self) -> None:
        expected_selector_codes = {
            "selector.capability-blocked",
            "selector.classification-failed",
            "selector.control-failed",
            "selector.empty-change-set",
            "selector.empty-change-tags",
            "selector.lane-shadow",
            "selector.relationship-ineligible",
            "selector.self-protection",
            "selector.tags-ungraduated",
            "source.capture-failed",
            "source.diff-ambiguous",
            "source.diff-malformed",
            "source.git-missing",
            "source.git-refused",
            "source.gitlink-unsupported",
            "source.head-ambiguous",
            "source.head-drift",
            "source.head-malformed",
            "source.index-ambiguous",
            "source.index-drift",
            "source.index-invalid",
            "source.index-malformed",
            "source.index-unmerged",
            "source.intent-to-add",
            "source.manifest-invalid",
            "source.manifest-missing",
            "source.object-path-invalid",
            "source.object-store-drift",
            "source.path-invalid",
            "source.repo-invalid",
            "source.tree-malformed",
        }
        selector_literals = {
            node.value
            for node in ast.walk(
                ast.parse(Path(selector.__file__).read_text(encoding="utf-8"))
            )
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("selector.", "source."))
        }
        self.assertEqual(selector_literals, expected_selector_codes)
        self.assertEqual(set(runner.SELECTOR_DIAGNOSTIC_CODES), expected_selector_codes)
        self.assertEqual(
            set(runner.EXPLANATIONS),
            set(
                runner.RECEIPT_DIAGNOSTIC_CODES
                | runner.INVALIDATION_REASONS
                | runner.SELECTOR_DIAGNOSTIC_CODES
            ),
        )
        for code, explanation in runner.EXPLANATIONS.items():
            self.assertEqual(len(explanation.splitlines()), 1, code)
            self.assertGreaterEqual(explanation.count(";"), 2, code)

    def test_cli_and_importable_renderer_are_byte_identical(self) -> None:
        codes = ["fallback.full", "receipt_invalid"]
        expected = runner.render_explanations(codes)
        output = io.StringIO()
        with redirect_stdout(output):
            result = runner.main(["explain", *codes])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), expected + "\n")
        self.assertIn("full remains required", expected)
        self.assertNotIn("passed", expected)
        direct = subprocess.run(
            [
                sys.executable,
                str(Path(runner.__file__)),
                "explain",
                *codes,
            ],
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", os.defpath),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
        self.assertEqual((direct.returncode, direct.stderr), (0, ""))
        self.assertEqual(direct.stdout, expected + "\n")

    def test_unknown_explanation_code_is_rejected_and_cannot_green_a_run(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = runner.main(["explain", "privacy.operator.sentinel"])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            error.getvalue(),
            "unknown diagnostic or invalidation code\n",
        )


if __name__ == "__main__":
    unittest.main()
