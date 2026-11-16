from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _ops.verification import path_gate

ROOT = Path(__file__).resolve().parents[2]


def change(path: str, status: str = "M") -> dict[str, str]:
    return {"status": status, "path": path}


class NameStatusTests(unittest.TestCase):
    def test_order_duplicates_spaces_deletes_and_renames(self) -> None:
        raw = (
            b"M\0docs/z file.md\0"
            b"D\0docs/a.md\0"
            b"R100\0_ops/doc-warden/old name.py\0"
            b"_ops/doc-warden/new name.py\0"
            b"D\0docs/a.md\0"
        )
        self.assertEqual(
            path_gate.parse_name_status_z(raw),
            [
                change("_ops/doc-warden/new name.py", "R100"),
                change("_ops/doc-warden/old name.py", "R100"),
                change("docs/a.md", "D"),
                change("docs/z file.md"),
            ],
        )

    def test_empty_and_malformed_input(self) -> None:
        self.assertEqual(path_gate.parse_name_status_z(b""), [])
        with self.assertRaises(path_gate.RouteError):
            path_gate.parse_name_status_z(b"M\0docs/missing-terminator.md")
        with self.assertRaises(path_gate.RouteError):
            path_gate.parse_name_status_z(b"M\0../outside\0")

    def test_live_git_rename_preserves_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            old = repo / "docs" / "old name.md"
            old.parent.mkdir()
            old.write_text("content\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "mv",
                    "docs/old name.md",
                    "docs/new name.md",
                ],
                check=True,
            )
            paths = [item["path"] for item in path_gate.staged_changes(repo)]
            self.assertEqual(paths, ["docs/new name.md", "docs/old name.md"])


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = path_gate.load_mapping(ROOT)

    def select(self, *paths: str) -> dict:
        return path_gate.select(
            self.mapping, [change(path) for path in reversed(paths)]
        )

    def test_doc_warden_selects_only_doc_warden_check(self) -> None:
        selected = self.select(
            "_ops/doc-warden/v2/doc_warden/validators.py",
            "_ops/doc-warden/v2/tests/test_validators.py",
        )
        self.assertIsNone(selected["escalation_reason"])
        self.assertEqual([a["id"] for a in selected["areas"]], ["doc-warden"])
        self.assertEqual(
            [check["id"] for check in selected["checks"]],
            ["doc-warden.full-compat"],
        )

    def test_another_mapped_area_selects_its_existing_checks(self) -> None:
        selected = self.select(
            "_ops/baseline/profiles/pr-automation/v3/profile.py"
        )
        self.assertIsNone(selected["escalation_reason"])
        self.assertEqual([a["id"] for a in selected["areas"]], ["pr-automation"])
        self.assertEqual(
            [check["id"] for check in selected["checks"]],
            ["pr-automation.legacy", "pr-automation.v3"],
        )

    def test_docs_only_is_an_explicit_low_risk_area(self) -> None:
        selected = self.select("docs/runbooks/operator guide.md")
        self.assertIsNone(selected["escalation_reason"])
        self.assertEqual([a["id"] for a in selected["areas"]], ["documentation"])

    def test_fallback_cases(self) -> None:
        cases = {
            "mixed_or_cross_cutting": (
                "_ops/doc-warden/POLICY.md",
                "docs/runbooks/example.md",
            ),
            "unmapped_or_ambiguous_path": ("unexpected/new-file.txt",),
            "verifier_or_self_modifying": (
                "_ops/verification/test_path_gate.py",
            ),
            "explicitly_high_risk": ("_ops/rules/agent-context.md",),
        }
        for reason, paths in cases.items():
            with self.subTest(reason=reason):
                selected = self.select(*paths)
                self.assertEqual(selected["escalation_reason"], reason)
                self.assertEqual(
                    [check["id"] for check in selected["checks"]], ["full.repo"]
                )

    def test_selection_is_independent_of_order_and_duplicates(self) -> None:
        left = path_gate.select(
            self.mapping,
            [
                change("_ops/doc-warden/z.py"),
                change("_ops/doc-warden/a.py"),
                change("_ops/doc-warden/a.py"),
            ],
        )
        right = path_gate.select(
            self.mapping,
            [
                change("_ops/doc-warden/a.py"),
                change("_ops/doc-warden/z.py"),
            ],
        )
        self.assertEqual(path_gate.receipt(left), path_gate.receipt(right))


class MappingIndexBindingTests(unittest.TestCase):
    """load_mapping must read from the Git index, not the working tree."""

    _WIDE = {
        "version": 1,
        "high_risk": [],
        "areas": [
            {
                "id": "test-area",
                "coverage": "Regression fixture.",
                "rationale": "Isolated to docs/.",
                "paths": [{"kind": "prefix", "path": "docs/"}],
                "checks": [{"id": "t.check", "argv": ["true"], "cwd": "."}],
            }
        ],
    }
    _NARROW = {"version": 1, "high_risk": [], "areas": []}

    def test_unstaged_narrowing_edit_does_not_affect_receipt(self) -> None:
        """Overwriting the mapping in the working tree must not change routing."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            mapping_path = repo / "_ops" / "verification" / "path-checks.json"
            mapping_path.parent.mkdir(parents=True)
            mapping_path.write_text(json.dumps(self._WIDE), encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "t@x.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "init"],
                check=True,
            )
            # Unstaged narrowing edit: replaces areas with empty list on disk only.
            mapping_path.write_text(json.dumps(self._NARROW), encoding="utf-8")
            loaded = path_gate.load_mapping(repo)
            # Index (committed) version must win — one area, not zero.
            self.assertEqual(len(loaded["areas"]), 1)
            self.assertEqual(loaded["areas"][0]["id"], "test-area")
            # Routing must not degrade to unmapped_or_ambiguous_path.
            selected = path_gate.select(loaded, [change("docs/guide.md")])
            self.assertIsNone(selected["escalation_reason"])
            self.assertEqual([a["id"] for a in selected["areas"]], ["test-area"])


class ReceiptExecutionAndWiringTests(unittest.TestCase):
    def test_receipt_contains_required_explanation(self) -> None:
        mapping = path_gate.load_mapping(ROOT)
        selected = path_gate.select(
            mapping, [change("_ops/doc-warden/v2/tests/test_dashboard.py")]
        )
        value = path_gate.receipt(selected)
        self.assertEqual(
            value["changed_paths"],
            [change("_ops/doc-warden/v2/tests/test_dashboard.py")],
        )
        self.assertEqual(value["matched_areas"], ["doc-warden"])
        check = value["selected_checks"][0]
        for field in ("id", "command", "cwd", "coverage", "rationale"):
            self.assertTrue(check[field])
        self.assertIn("doc-warden-verify.sh", check["command"])
        self.assertIsNone(value["escalation_reason"])
        json.dumps(value, sort_keys=True)

    def test_targeted_executor_runs_only_selected_literal_commands(self) -> None:
        selection = path_gate.select(
            path_gate.load_mapping(ROOT),
            [change("_ops/doc-warden/POLICY.md")],
        )
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.dict(
            os.environ, {"GIT_DIR": "/unsafe", "KEEP": "yes"}, clear=True
        ), mock.patch.object(
            path_gate.subprocess, "run", return_value=completed
        ) as run:
            self.assertEqual(path_gate.execute(ROOT, selection), 0)
        self.assertEqual(run.call_count, 1)
        call = run.call_args
        self.assertEqual(
            call.args[0], ["bash", "_ops/checks/doc-warden-verify.sh"]
        )
        self.assertEqual(call.kwargs["env"], {"KEEP": "yes"})
        self.assertFalse(call.kwargs["shell"] if "shell" in call.kwargs else False)

    def test_full_fallback_launches_existing_full_gate_once(self) -> None:
        selected = path_gate.select(
            path_gate.load_mapping(ROOT), [change("Makefile")]
        )
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(
            path_gate.subprocess, "run", return_value=completed
        ) as run:
            self.assertEqual(path_gate.execute(ROOT, selected), 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(
            run.call_args.args[0],
            ["bash", "_ops/checks/verify-operating-model.sh", "--ci"],
        )

    def test_hook_has_one_router_and_no_broad_second_path(self) -> None:
        hook = (ROOT / "_ops/hooks/pre-commit").read_text(encoding="utf-8")
        self.assertEqual(hook.count("path_gate.py"), 1)
        self.assertNotIn("verify-operating-model.sh --ci", hook)

    def test_make_keeps_explicit_full_paths_and_exposes_router(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in ("verify:", "verify-ci:", "verify-staged:"):
            self.assertIn(target, makefile)
        self.assertEqual(makefile.count("path_gate.py"), 1)


if __name__ == "__main__":
    unittest.main()
