import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import kp_context_measure as kpcm
import validate_static_context_manifest as validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOL = HERE / "validate_static_context_manifest.py"


class StaticManifestFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git_root = self.root / "source"
        self.git_root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.git_root)], check=True)
        (self.git_root / "AGENTS.md").write_text("Synthetic source provenance fixture.\n")
        subprocess.run(["git", "-C", str(self.git_root), "add", "AGENTS.md"], check=True)
        subprocess.run(["git", "-C", str(self.git_root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "synthetic source"], check=True)
        self.owner_checkouts = {
            "KleinPerkins/awa": self.git_root,
            "KleinPerkins/dev": self.git_root,
            "KleinPerkins/skills": self.git_root,
        }

    def _git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.git_root), *args],
            text=True,
        ).strip()

    def _git_bytes(self, *args):
        return subprocess.check_output(["git", "-C", str(self.git_root), *args])

    def _source(self):
        source_path = "AGENTS.md"
        raw = self._git_bytes("show", "HEAD:" + source_path)
        return {
            "path": source_path,
            "blob": self._git("rev-parse", "HEAD:" + source_path),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def _write_json(self, name, value, canonical=True):
        path = self.root / name
        if canonical:
            path.write_bytes(kpcm.emit(value).encode("ascii"))
        else:
            path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _write_projection_files(self, region_projection_id=None):
        paths = {}
        for projection_id in validator.PROJECTION_ORDER:
            path = self.root / (projection_id + ".md")
            if projection_id == region_projection_id:
                body = (
                    "before\n"
                    "<!-- BEGIN region -->\n"
                    "projection " + projection_id + "\n"
                    "<!-- END region -->\n"
                    "after\n"
                )
            else:
                body = "projection " + projection_id + "\n"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
            paths[projection_id] = str(path)
        return paths

    def _candidate(self, region_projection_id=None):
        source = self._source()
        commit = self._git("rev-parse", "HEAD")
        tree = self._git("rev-parse", "HEAD^{tree}")
        logical_paths = self._write_projection_files(region_projection_id)
        input_value = {
            "schema": kpcm.INPUT_SCHEMA,
            "client_root_class": "cursor-desktop/dev-root",
            "baseline_id": "context-efficiency-e09-release0-20260820",
            "projections": [
                {
                    "projection_id": projection_id,
                    "path": logical_paths[projection_id],
                    "select": (
                        {
                            "kind": "region",
                            "begin": "<!-- BEGIN region -->",
                            "end": "<!-- END region -->",
                        }
                        if projection_id == region_projection_id
                        else {"kind": "full"}
                    ),
                }
                for projection_id in reversed(validator.PROJECTION_ORDER)
            ],
        }
        input_path = self._write_json("input.json", input_value)
        _root_class, _baseline_id, entries = kpcm.validate_manifest(input_value)
        receipt, code = kpcm.build_receipt(
            input_value["client_root_class"],
            input_value["baseline_id"],
            entries,
        )
        self.assertEqual(code, 0)
        receipt_path = self._write_json("receipt.json", receipt)
        rows = {row["projection_id"]: row for row in receipt["projections"]}
        owner_by_projection = {
            "awa-operator": "KleinPerkins/awa",
            "dev-operating-model": "KleinPerkins/dev",
            "generated-home-agents": "KleinPerkins/skills",
            "subagent-orchestration": "KleinPerkins/skills",
            "terse-output": "KleinPerkins/dev",
            "workspace-agents": "KleinPerkins/dev",
            "worktree-default": "KleinPerkins/dev",
        }
        projections = []
        for projection_id in validator.PROJECTION_ORDER:
            row = rows[projection_id]
            category = (
                "generated-memory"
                if projection_id == "generated-home-agents"
                else "rules"
            )
            generated_inputs = None
            if category == "generated-memory":
                generated_inputs = {
                    "source_count": 2,
                    "source_digests": sorted([
                        hashlib.sha256(b"").hexdigest(),
                        hashlib.sha256(b"source").hexdigest(),
                    ]),
                    "output_sha256": row["raw_sha256"],
                }
            projections.append({
                "projection_id": projection_id,
                "logical_path": row["path"],
                "category": category,
                "owner_repository": owner_by_projection[projection_id],
                "owner_commit": commit,
                "source_path": source["path"],
                "source_blob": source["blob"],
                "source_sha256": source["sha256"],
                "installed_raw_sha256": row["raw_sha256"],
                "normalized_sha256": row["normalized_sha256"],
                "bytes": row["bytes"],
                "characters": row["characters"],
                "words": row["words"],
                "generated_inputs": generated_inputs,
            })
        manifest = {
            "schema": validator.SCHEMA,
            "status": validator.STATUS,
            "captured_at_utc": "2026-08-20T00:00:00Z",
            "baseline_id": input_value["baseline_id"],
            "client_root_class": input_value["client_root_class"],
            "algorithm": kpcm.ALGORITHM,
            "tool_contract": kpcm.TOOL_CONTRACT,
            "whitespace_set_version": kpcm.WHITESPACE_SET_VERSION,
            "projection_order": list(validator.PROJECTION_ORDER),
            "projections": projections,
            "totals": receipt["totals"],
            "target_30pct": {
                "max_characters": (receipt["totals"]["characters"] * 70) // 100,
                "max_words": (receipt["totals"]["words"] * 70) // 100,
                "meets_characters": False,
                "meets_words": False,
            },
            "measurement_input_sha256": hashlib.sha256(
                kpcm.emit(input_value).encode("ascii")
            ).hexdigest(),
            "measurement_receipt_sha256": hashlib.sha256(
                kpcm.emit(receipt).encode("ascii")
            ).hexdigest(),
            "owner_refs": {
                repository: {
                    "default_branch": "main",
                    "commit": commit,
                    "tree": tree,
                }
                for repository in validator.OWNER_REPOSITORIES
            },
        }
        manifest_path = self._write_json("manifest.json", manifest)
        return manifest, manifest_path, input_value, input_path, receipt, receipt_path

    def _validate(self, manifest_path, input_path, receipt_path):
        return validator.validate_static_context_manifest(
            manifest_path=manifest_path,
            input_path=input_path,
            receipt_path=receipt_path,
            owner_checkouts=self.owner_checkouts,
        )

    def test_valid_manifest_returns_content_free_digests(self):
        _manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        result = self._validate(manifest_path, input_path, receipt_path)
        self.assertEqual(result["schema"], validator.VALIDATION_SCHEMA)
        self.assertEqual(result["status"], "OK")
        for key in ("manifest_sha256", "input_sha256", "receipt_sha256"):
            self.assertRegex(result[key], r"^[0-9a-f]{64}$")

    def test_region_selector_join_uses_receipt_marker_digests(self):
        _manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate(region_projection_id="workspace-agents")
        )
        result = self._validate(manifest_path, input_path, receipt_path)
        self.assertEqual(result["status"], "OK")

    def test_cli_failure_is_fixed_and_value_free(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["unexpected"] = "TOKEN_SENTINEL_SECRET"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--manifest",
                str(manifest_path),
                "--input",
                str(input_path),
                "--receipt",
                str(receipt_path),
                "--owner-checkout",
                "KleinPerkins/awa=" + str(self.git_root),
                "--owner-checkout",
                "KleinPerkins/dev=" + str(self.git_root),
                "--owner-checkout",
                "KleinPerkins/skills=" + str(self.git_root),
            ],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(
            completed.stderr,
            b"validate_static_context_manifest: VALIDATION_ERROR\n",
        )
        self.assertNotIn(b"TOKEN_SENTINEL_SECRET", completed.stderr)
        self.assertNotIn(b"Traceback", completed.stderr)

    def test_cli_malformed_input_failure_is_fixed_and_value_free(self):
        _manifest, manifest_path, input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        input_value["schema"] = "TOKEN_SENTINEL_SECRET"
        input_path = self._write_json("input-bad.json", input_value)
        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--manifest",
                str(manifest_path),
                "--input",
                str(input_path),
                "--receipt",
                str(receipt_path),
                "--owner-checkout",
                "KleinPerkins/awa=" + str(self.git_root),
                "--owner-checkout",
                "KleinPerkins/dev=" + str(self.git_root),
                "--owner-checkout",
                "KleinPerkins/skills=" + str(self.git_root),
            ],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(
            completed.stderr,
            b"validate_static_context_manifest: VALIDATION_ERROR\n",
        )
        self.assertNotIn(b"TOKEN_SENTINEL_SECRET", completed.stderr)
        self.assertNotIn(b"Traceback", completed.stderr)

    def test_cli_schema_invalid_input_missing_key_is_fixed(self):
        manifest, _manifest_path, input_value, _input_path, _receipt, receipt_path = (
            self._candidate()
        )
        del input_value["client_root_class"]
        input_path = self._write_json("input-bad.json", input_value)
        manifest["measurement_input_sha256"] = hashlib.sha256(
            kpcm.emit(input_value).encode("ascii")
        ).hexdigest()
        manifest_path = self._write_json("manifest-updated.json", manifest)
        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--manifest",
                str(manifest_path),
                "--input",
                str(input_path),
                "--receipt",
                str(receipt_path),
                "--owner-checkout",
                "KleinPerkins/awa=" + str(self.git_root),
                "--owner-checkout",
                "KleinPerkins/dev=" + str(self.git_root),
                "--owner-checkout",
                "KleinPerkins/skills=" + str(self.git_root),
            ],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(
            completed.stderr,
            b"validate_static_context_manifest: VALIDATION_ERROR\n",
        )
        self.assertNotIn(b"Traceback", completed.stderr)

    def test_rejects_invalid_captured_at_utc(self):
        manifest, _manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["captured_at_utc"] = "2026-08-20 00:00:00"
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_owner_commit_mismatch(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["owner_refs"]["KleinPerkins/dev"]["commit"] = "0" * 40
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_projection_owner_swap(self):
        manifest, _manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        row = next(
            item
            for item in manifest["projections"]
            if item["projection_id"] == "awa-operator"
        )
        row["owner_repository"] = "KleinPerkins/dev"
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_projection_category_swap(self):
        manifest, _manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        row = next(
            item
            for item in manifest["projections"]
            if item["projection_id"] == "generated-home-agents"
        )
        row["category"] = "rules"
        row["generated_inputs"] = None
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_source_blob_mismatch(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["projections"][0]["source_blob"] = "0" * 40
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_generated_memory_output_mismatch(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        row = next(
            item
            for item in manifest["projections"]
            if item["projection_id"] == "generated-home-agents"
        )
        row["generated_inputs"]["output_sha256"] = "0" * 64
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_generated_source_count_smaller_than_digest_set(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        row = next(
            item
            for item in manifest["projections"]
            if item["projection_id"] == "generated-home-agents"
        )
        row["generated_inputs"]["source_count"] = 1
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_empty_generated_source_digest_set(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        row = next(
            item
            for item in manifest["projections"]
            if item["projection_id"] == "generated-home-agents"
        )
        row["generated_inputs"]["source_digests"] = []
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_target_meets_flags_that_do_not_match_totals(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["target_30pct"]["meets_characters"] = True
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_manifest_receipt_path_mismatch(self):
        manifest, manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["projections"][0]["logical_path"] = str(self.root / "other.md")
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_input_projection_superset(self):
        manifest, _manifest_path, input_value, _input_path, _receipt, receipt_path = (
            self._candidate()
        )
        extra_path = self.root / "extra.md"
        extra_path.write_text("extra\n", encoding="utf-8")
        input_value["projections"].append({
            "projection_id": "zzz-extra",
            "path": str(extra_path),
            "select": {"kind": "full"},
        })
        input_path = self._write_json("input-extra.json", input_value)
        manifest["measurement_input_sha256"] = hashlib.sha256(
            kpcm.emit(input_value).encode("ascii")
        ).hexdigest()
        manifest_path = self._write_json("manifest-updated.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)

    def test_rejects_noncanonical_static_manifest_bytes(self):
        manifest, _manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        compact_path = self._write_json("compact.json", manifest, canonical=False)
        with self.assertRaises(validator.ValidationError):
            self._validate(compact_path, input_path, receipt_path)

    def test_rejects_static_manifest_projection_order_mismatch(self):
        manifest, _manifest_path, _input_value, input_path, _receipt, receipt_path = (
            self._candidate()
        )
        manifest["projections"] = list(reversed(copy.deepcopy(manifest["projections"])))
        manifest_path = self._write_json("manifest-bad.json", manifest)
        with self.assertRaises(validator.ValidationError):
            self._validate(manifest_path, input_path, receipt_path)


if __name__ == "__main__":
    unittest.main()
