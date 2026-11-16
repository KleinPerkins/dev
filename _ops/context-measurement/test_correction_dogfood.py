import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
HELPER = HERE / "correction_dogfood.py"
TOOL = HERE / "kp_context_measure.py"
_DOGFOOD_SPEC = importlib.util.spec_from_file_location(
    "correction_dogfood", HELPER
)
dogfood = importlib.util.module_from_spec(_DOGFOOD_SPEC)
_DOGFOOD_SPEC.loader.exec_module(dogfood)


class TestCorrectionDogfood(unittest.TestCase):
    SENTINEL = "TOKEN_SENTINEL_SECRET"
    FIXTURES = {
        "full-newlines": (
            "YWxwaGEgYmV0YQ0KZ2FtbWEK", "full", "OK"
        ),
        "unicode-cr": (
            "QQ1CwqBD4oCoRAo=", "full", "OK"
        ),
        "region": (
            "cHJlCjwhLS0gQkVHSU4geCAtLT4KbWlkIG9uZQo8IS0tIEVORCB4IC0tPgpwb3N0Cg==",
            "region", "OK",
        ),
        "sentinel": (
            "VE9LRU5fU0VOVElORUxfU0VDUkVUIHN0dWZmCg==",
            "full", "OK",
        ),
        "ambiguous": (
            "YWFhWgo=", "region", "REGION_AMBIGUOUS"
        ),
        "overlap": (
            "YWJjZAo=", "region", "REGION_MISORDERED"
        ),
    }

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _run_helper(self, *argv, cwd=None, optimize=False):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if optimize:
            env["PYTHONOPTIMIZE"] = "1"
        return subprocess.run(
            [sys.executable, str(HELPER), *[str(item) for item in argv]],
            cwd=str(cwd or self.root),
            env=env,
            capture_output=True,
            check=False,
        )

    def _git(self, *argv):
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *argv],
            capture_output=True,
            check=True,
            text=True,
        )
        return completed.stdout.strip()

    def _implementation_repo(
        self, *, tool_bytes=None, tracked=True, symlink_target=None
    ):
        index = getattr(self, "_implementation_index", 0)
        self._implementation_index = index + 1
        root = self.root / f"implementation-{index}"
        tool = root / "_ops/context-measurement/kp_context_measure.py"
        tool.parent.mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(root), "init", "-q"],
            check=True, capture_output=True,
        )
        if symlink_target is not None:
            tool.symlink_to(symlink_target)
        elif tracked:
            tool.write_bytes(tool_bytes if tool_bytes is not None else TOOL.read_bytes())
        subprocess.run(
            ["git", "-C", str(root), "add", "--all"],
            check=True, capture_output=True,
        )
        subprocess.run(
            [
                "git", "-C", str(root),
                "-c", "user.name=Fixture",
                "-c", "user.email=fixture@example.invalid",
                "commit", "--allow-empty", "-qm", "fixture",
            ],
            check=True, capture_output=True,
        )
        if not tracked:
            tool.write_bytes(tool_bytes if tool_bytes is not None else TOOL.read_bytes())
        return root, tool

    def _probe_tool_bytes(self, mode):
        script = """\
import json
import subprocess
import sys

real_tool = {real_tool!r}
mode = {mode!r}
completed = subprocess.run(
    [sys.executable, real_tool, *sys.argv[1:]],
    capture_output=True,
    check=False,
)
output = completed.stdout
is_measure = len(sys.argv) > 1 and sys.argv[1] == "measure"
is_compare = len(sys.argv) > 1 and sys.argv[1] == "compare"
is_blocked = any("blocked-manifest" in item for item in sys.argv[2:])
is_incompatible = any(
    "receipt-incompatible.json" in item for item in sys.argv[2:]
)
compatible_mutations = {{
    "compatible-schema": ("schema", "other/v1"),
    "compatible-algorithm": ("algorithm", "other/v1"),
    "compatible-tool": ("tool", "other"),
    "compatible-tool-contract": ("tool_contract", "other/v1"),
    "compatible-whitespace": ("whitespace_set_version", "other/v1"),
    "compatible-status": ("status", "OTHER"),
    "compatible-baseline-id": ("baseline_id", "abc"),
    "compatible-client-root": ("client_root_class", "abc"),
    "compatible-order": ("projection_order", ["abc"]),
    "compatible-baseline-totals": (
        "baseline_totals", {{"bytes": 0, "characters": 0, "words": 0}}
    ),
    "compatible-candidate-totals": (
        "candidate_totals", {{"bytes": 0, "characters": 0, "words": 0}}
    ),
    "compatible-delta": (
        "delta", {{"bytes": 1, "characters": 1, "words": 1}}
    ),
    "compatible-target": (
        "target_30pct",
        {{
            "max_characters": 1,
            "max_words": 1,
            "meets_characters": True,
            "meets_words": True,
        }},
    ),
}}
if (
    is_compare
    and completed.returncode == 0
    and mode == "comparison-short-marker"
):
    value = json.loads(output.decode("ascii"))
    value["baseline_id"] = "abc"
    output = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\\n"
    ).encode("ascii")
elif is_compare and completed.returncode == 0 and mode in compatible_mutations:
    value = json.loads(output.decode("ascii"))
    field, replacement = compatible_mutations[mode]
    value[field] = replacement
    output = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\\n"
    ).encode("ascii")
elif (
    is_compare
    and completed.returncode == 0
    and mode == "compatible-extra"
):
    value = json.loads(output.decode("ascii"))
    value["unexpected"] = "abc"
    output = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\\n"
    ).encode("ascii")
elif (
    is_compare
    and completed.returncode == 4
    and is_incompatible
    and mode.startswith("incompatible-")
):
    value = json.loads(output.decode("ascii"))
    if mode == "incompatible-schema":
        value["schema"] = "other/v1"
    elif mode == "incompatible-status":
        value["status"] = "OTHER"
    elif mode == "incompatible-reasons":
        value["reasons"] = ["abc"]
    else:
        value["unexpected"] = "abc"
    output = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\\n"
    ).encode("ascii")
elif (
    is_measure
    and completed.returncode == 0
    and mode in ("raw", "marker", "escaped")
):
    value = json.loads(output.decode("ascii"))
    leaks = {{
        "raw": "alpha beta\\r\\ngamma\\n",
        "marker": "<!-- BEGIN x -->",
        "escaped": "A\\rB\\u00a0C\\u2028D\\n",
    }}
    value["projections"][0]["path"] = leaks[mode]
    output = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\\n"
    ).encode("ascii")
elif is_measure and completed.returncode == 2 and mode == "unknown" and is_blocked:
    value = json.loads(output.decode("ascii"))
    value["unexpected_receipt_field"] = "not-source-metadata"
    output = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\\n"
    ).encode("ascii")
sys.stdout.buffer.write(output)
sys.stderr.buffer.write(completed.stderr)
raise SystemExit(completed.returncode)
""".format(real_tool=str(TOOL), mode=mode)
        return script.encode("utf-8")

    def _canonical(self, value):
        return (
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
            + "\n"
        ).encode("ascii")

    def _valid_evidence(self):
        commit = self._git("rev-parse", "HEAD")
        tree = self._git("rev-parse", commit + "^{tree}")
        return {
            "schema": "kp-context-measurement-correction-evidence/v1",
            "status": "PASS",
            "classification": "CORRECTION_PROVEN_NOT_E09",
            "captured_at_utc": "2026-08-17T00:00:00Z",
            "implementation_commit": commit,
            "implementation_tree": tree,
            "algorithm": "kp-context-measurement/v1",
            "tool_contract": "kp-context-measurement-tool/v2",
            "environment_class": "macos-bash3-stdlib",
            "command_set": "kp-context-measurement-correction-dogfood/v1",
            "fixture_manifest_sha256": "0" * 64,
            "run_a_receipt_sha256": "1" * 64,
            "run_b_receipt_sha256": "1" * 64,
            "pre_stats_sha256": "2" * 64,
            "post_stats_sha256": "2" * 64,
            "observed_exits": {
                "measure_a": 0,
                "measure_b": 0,
                "compare_compatible": 0,
                "compare_incompatible": 4,
                "blocked": 2,
                "usage": 3,
            },
            "content_safety": {
                "sentinel_absent": True,
                "source_content_present": False,
                "input_immutable": True,
                "receipts_byte_identical": True,
            },
        }

    def _write_evidence(self, value, name="evidence.json", canonical=True):
        path = self.root / name
        raw = self._canonical(value) if canonical else json.dumps(value).encode()
        path.write_bytes(raw)
        return path

    def _assert_fixed_failure(self, completed):
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, b"")
        self.assertNotIn(b"Traceback", completed.stderr)
        self.assertNotIn(self.SENTINEL.encode("ascii"), completed.stderr)

    def _expected_fixture_manifest_sha256(self):
        rows = []
        for fixture_id, (encoded, select_kind, expected_class) in (
            self.FIXTURES.items()
        ):
            raw = base64.b64decode(encoded)
            rows.append({
                "fixture_id": fixture_id,
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "select_kind": select_kind,
                "expected_class": expected_class,
            })
        rows.sort(key=lambda row: row["fixture_id"].encode("ascii"))
        return hashlib.sha256(self._canonical(rows)).hexdigest()

    def test_run_is_atomic_and_closed(self):
        failing_tool = self.root / "failing-tool.py"
        failing_tool.write_text(
            "raise SystemExit(9)\n", encoding="utf-8"
        )
        failed_output = self.root / "failed.json"
        failed = self._run_helper(
            "run",
            "--tool", failing_tool,
            "--implementation-root", REPO_ROOT,
            "--output", failed_output,
        )
        self._assert_fixed_failure(failed)
        self.assertFalse(failed_output.exists())
        self.assertEqual(list(self.root.glob("failed.json.tmp.*")), [])

        implementation_root, implementation_tool = self._implementation_repo()
        output = self.root / "evidence.json"
        completed = self._run_helper(
            "run",
            "--tool", implementation_tool,
            "--implementation-root", implementation_root,
            "--output", output,
            cwd=Path("/"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(completed.stderr, b"")
        self.assertTrue(output.is_file())
        value = json.loads(output.read_bytes())
        self.assertEqual(output.read_bytes(), self._canonical(value))
        self.assertEqual(
            set(value),
            {
                "schema", "status", "classification", "captured_at_utc",
                "implementation_commit", "implementation_tree",
                "algorithm", "tool_contract", "environment_class",
                "command_set", "fixture_manifest_sha256",
                "run_a_receipt_sha256", "run_b_receipt_sha256",
                "pre_stats_sha256", "post_stats_sha256",
                "observed_exits", "content_safety",
            },
        )
        self.assertEqual(
            value["fixture_manifest_sha256"],
            self._expected_fixture_manifest_sha256(),
        )
        self.assertEqual(value["observed_exits"], {
            "measure_a": 0,
            "measure_b": 0,
            "compare_compatible": 0,
            "compare_incompatible": 4,
            "blocked": 2,
            "usage": 3,
        })
        self.assertEqual(value["content_safety"], {
            "sentinel_absent": True,
            "source_content_present": False,
            "input_immutable": True,
            "receipts_byte_identical": True,
        })
        self.assertNotIn(self.SENTINEL.encode("ascii"), output.read_bytes())
        validated = self._run_helper(
            "validate",
            "--evidence", output,
            "--implementation-root", implementation_root,
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(validated.stdout, b"")
        self.assertEqual(validated.stderr, b"")

    def test_run_binds_exact_tool_path_and_tracked_blob(self):
        cases = []

        outside_root, _ = self._implementation_repo()
        outside_copy = self.root / "outside-tool.py"
        outside_copy.write_bytes(TOOL.read_bytes())
        cases.append(("outside-root", outside_root, outside_copy))

        modified_root, modified_tool = self._implementation_repo()
        modified_tool.write_bytes(modified_tool.read_bytes() + b"\n# modified\n")
        cases.append(("modified", modified_root, modified_tool))

        wrong_root, _ = self._implementation_repo()
        wrong_tool = wrong_root / "wrong-relative-path.py"
        wrong_tool.write_bytes(TOOL.read_bytes())
        cases.append(("wrong-relative-path", wrong_root, wrong_tool))

        untracked_root, untracked_tool = self._implementation_repo(tracked=False)
        cases.append(("untracked", untracked_root, untracked_tool))

        symlink_root, symlink_tool = self._implementation_repo(
            symlink_target=TOOL
        )
        cases.append(("symlink", symlink_root, symlink_tool))

        for name, implementation_root, tool in cases:
            with self.subTest(case=name):
                output = self.root / f"{name}.json"
                completed = self._run_helper(
                    "run",
                    "--tool", tool,
                    "--implementation-root", implementation_root,
                    "--output", output,
                )
                self._assert_fixed_failure(completed)
                self.assertFalse(output.exists())
                self.assertEqual(
                    list(self.root.glob(f"{name}.json.tmp.*")), []
                )

    def test_run_rejects_raw_marker_escaped_and_unknown_field_leaks(self):
        for mode in ("raw", "marker", "escaped", "unknown"):
            with self.subTest(mode=mode):
                implementation_root, tool = self._implementation_repo(
                    tool_bytes=self._probe_tool_bytes(mode)
                )
                output = self.root / f"leak-{mode}.json"
                completed = self._run_helper(
                    "run",
                    "--tool", tool,
                    "--implementation-root", implementation_root,
                    "--output", output,
                )
                self._assert_fixed_failure(completed)
                self.assertEqual(
                    completed.stderr, b"correction dogfood failed\n"
                )
                self.assertFalse(output.exists())
                self.assertEqual(
                    list(self.root.glob(f"leak-{mode}.json.tmp.*")), []
                )

    def test_run_rejects_short_marker_in_comparison_identity(self):
        implementation_root, tool = self._implementation_repo(
            tool_bytes=self._probe_tool_bytes("comparison-short-marker")
        )
        output = self.root / "comparison-short-marker.json"
        completed = self._run_helper(
            "run",
            "--tool", tool,
            "--implementation-root", implementation_root,
            "--output", output,
        )
        self._assert_fixed_failure(completed)
        self.assertEqual(
            completed.stderr, b"correction dogfood failed\n"
        )
        self.assertNotIn(b"abc", completed.stdout + completed.stderr)
        self.assertFalse(output.exists())
        self.assertEqual(
            list(self.root.glob("comparison-short-marker.json.tmp.*")), []
        )

    def test_run_closes_every_comparison_output_field(self):
        modes = (
            "compatible-schema",
            "compatible-algorithm",
            "compatible-tool",
            "compatible-tool-contract",
            "compatible-whitespace",
            "compatible-status",
            "compatible-baseline-id",
            "compatible-client-root",
            "compatible-order",
            "compatible-baseline-totals",
            "compatible-candidate-totals",
            "compatible-delta",
            "compatible-target",
            "compatible-extra",
            "incompatible-schema",
            "incompatible-status",
            "incompatible-reasons",
            "incompatible-extra",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                implementation_root, tool = self._implementation_repo(
                    tool_bytes=self._probe_tool_bytes(mode)
                )
                output = self.root / f"{mode}.json"
                completed = self._run_helper(
                    "run",
                    "--tool", tool,
                    "--implementation-root", implementation_root,
                    "--output", output,
                )
                self._assert_fixed_failure(completed)
                self.assertEqual(
                    completed.stderr, b"correction dogfood failed\n"
                )
                self.assertNotIn(b"abc", completed.stdout + completed.stderr)
                self.assertFalse(output.exists())
                self.assertEqual(
                    list(self.root.glob(f"{mode}.json.tmp.*")), []
                )

    def test_comparison_assertions_accept_legitimate_short_metadata(self):
        baseline = {
            "baseline_id": "a",
            "client_root_class": "c",
            "projection_order": ["x"],
            "totals": {"bytes": 1, "characters": 1, "words": 1},
        }
        candidate = json.loads(json.dumps(baseline))
        compatible = {
            "schema": "kp-context-measurement-comparison/v2",
            "algorithm": "kp-context-measurement/v1",
            "tool": "kp_context_measure",
            "tool_contract": "kp-context-measurement-tool/v2",
            "whitespace_set_version": "unicode-15.0-White_Space",
            "status": "OK",
            "baseline_id": "a",
            "client_root_class": "c",
            "projection_order": ["x"],
            "baseline_totals": {
                "bytes": 1, "characters": 1, "words": 1,
            },
            "candidate_totals": {
                "bytes": 1, "characters": 1, "words": 1,
            },
            "delta": {"bytes": 0, "characters": 0, "words": 0},
            "target_30pct": {
                "max_characters": 0,
                "max_words": 0,
                "meets_characters": False,
                "meets_words": False,
            },
        }
        dogfood._assert_compatible_comparison(
            compatible, baseline, candidate
        )
        dogfood._assert_incompatible_comparison({
            "schema": "kp-context-measurement-comparison/v2",
            "status": "COMPARISON_REFUSED",
            "reasons": ["BASELINE_ID_MISMATCH"],
        })

    def test_run_rejects_dangling_output_symlink_without_residue(self):
        implementation_root, tool = self._implementation_repo()
        target = self.root / "dangling-target.json"
        output = self.root / "dangling-output.json"
        output.symlink_to(target)
        completed = self._run_helper(
            "run",
            "--tool", tool,
            "--implementation-root", implementation_root,
            "--output", output,
        )
        self._assert_fixed_failure(completed)
        self.assertTrue(output.is_symlink())
        self.assertEqual(os.readlink(str(output)), str(target))
        self.assertFalse(target.exists())
        self.assertEqual(
            list(self.root.glob("dangling-output.json.tmp.*")), []
        )

    def test_validator_rejects_wrong_nested_types(self):
        cases = []
        boolean_exit = self._valid_evidence()
        boolean_exit["observed_exits"]["blocked"] = True
        cases.append(boolean_exit)
        integer_boolean = self._valid_evidence()
        integer_boolean["content_safety"]["input_immutable"] = 1
        cases.append(integer_boolean)
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                evidence = self._write_evidence(
                    value, f"wrong-type-{index}.json"
                )
                completed = self._run_helper(
                    "validate",
                    "--evidence", evidence,
                    "--implementation-root", REPO_ROOT,
                )
                self._assert_fixed_failure(completed)

    def test_validator_rejects_contradictory_digests(self):
        cases = []
        unequal_runs = self._valid_evidence()
        unequal_runs["run_b_receipt_sha256"] = "3" * 64
        cases.append(unequal_runs)
        unequal_stats = self._valid_evidence()
        unequal_stats["post_stats_sha256"] = "4" * 64
        cases.append(unequal_stats)
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                evidence = self._write_evidence(
                    value, f"contradictory-{index}.json"
                )
                completed = self._run_helper(
                    "validate",
                    "--evidence", evidence,
                    "--implementation-root", REPO_ROOT,
                )
                self._assert_fixed_failure(completed)

    def test_validator_checks_commit_tree_without_assert(self):
        value = self._valid_evidence()
        value["implementation_tree"] = "f" * 40
        evidence = self._write_evidence(value)
        for optimize in (False, True):
            with self.subTest(optimize=optimize):
                completed = self._run_helper(
                    "validate",
                    "--evidence", evidence,
                    "--implementation-root", REPO_ROOT,
                    optimize=optimize,
                )
                self._assert_fixed_failure(completed)

    def test_validator_accepts_valid_canonical_evidence_with_optimize(self):
        evidence = self._write_evidence(self._valid_evidence())
        for optimize in (False, True):
            with self.subTest(optimize=optimize):
                completed = self._run_helper(
                    "validate",
                    "--evidence", evidence,
                    "--implementation-root", REPO_ROOT,
                    optimize=optimize,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout, b"")
                self.assertEqual(completed.stderr, b"")

    def test_validator_rejects_unknown_noncanonical_null_and_bad_root(self):
        unknown = self._valid_evidence()
        unknown["unknown"] = self.SENTINEL
        looping_root = self.root / "looping-root"
        looping_root.symlink_to(looping_root.name)
        cases = [
            (self._write_evidence(unknown, "unknown.json"), REPO_ROOT),
            (
                self._write_evidence(
                    self._valid_evidence(),
                    "noncanonical.json",
                    canonical=False,
                ),
                REPO_ROOT,
            ),
            (self._write_evidence(None, "null.json"), REPO_ROOT),
            (
                self._write_evidence(
                    self._valid_evidence(), "bad-root.json"
                ),
                self.root,
            ),
            (
                self._write_evidence(
                    self._valid_evidence(), "looping-root.json"
                ),
                looping_root,
            ),
        ]
        for evidence, implementation_root in cases:
            with self.subTest(evidence=evidence.name):
                completed = self._run_helper(
                    "validate",
                    "--evidence", evidence,
                    "--implementation-root", implementation_root,
                )
                self._assert_fixed_failure(completed)

    def test_validator_failure_never_echoes_input_value(self):
        evidence = self.root / "sentinel.json"
        evidence.write_text(self.SENTINEL, encoding="utf-8")
        completed = self._run_helper(
            "validate",
            "--evidence", evidence,
            "--implementation-root", REPO_ROOT,
        )
        self._assert_fixed_failure(completed)

    def test_validator_normalizes_large_json_integer_decoder_value_error(self):
        large_integer = b"9" * 5000
        evidence = self.root / "large-integer.json"
        evidence.write_bytes(large_integer)
        completed = self._run_helper(
            "validate",
            "--evidence", evidence,
            "--implementation-root", REPO_ROOT,
        )
        self._assert_fixed_failure(completed)
        self.assertEqual(
            completed.stderr, b"correction evidence invalid\n"
        )
        self.assertNotIn(
            large_integer[:100], completed.stdout + completed.stderr
        )

    def test_run_refuses_existing_output_without_modifying_it(self):
        output = self.root / "existing.json"
        original = b"do-not-replace\n"
        output.write_bytes(original)
        completed = self._run_helper(
            "run",
            "--tool", TOOL,
            "--implementation-root", REPO_ROOT,
            "--output", output,
        )
        self._assert_fixed_failure(completed)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(list(self.root.glob("existing.json.tmp.*")), [])

    def test_only_closed_cli_interface_is_accepted(self):
        cases = [
            ("unknown",),
            ("run", "--tool", TOOL),
            (
                "run",
                "--tool", TOOL,
                "--implementation-root", REPO_ROOT,
                "--output", self.root / "out.json",
                "--fixture-override", self.SENTINEL,
            ),
            ("validate", "--evidence", self.root / "missing"),
        ]
        for index, argv in enumerate(cases):
            with self.subTest(case=index):
                completed = self._run_helper(*argv)
                self._assert_fixed_failure(completed)


if __name__ == "__main__":
    unittest.main()
