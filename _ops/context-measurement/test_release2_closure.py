#!/usr/bin/env python3
"""Closed-schema + content-safety tests for release2_closure.

The valid fixture is built from the module's fixed program-closure constants
plus synthetic dynamic fields (hex digests, totals, and the 13 reduced rows),
so the tests exercise the validator, not a hand-copied duplicate of the record.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kp_context_measure as kpcm  # noqa: E402
import release2_closure as r2  # noqa: E402

HEX40 = "a" * 40
HEX64 = "b" * 64


def _valid_release_evidence() -> dict:
    evidence = {}
    for key, (name, schema, status) in r2.RELEASE_EVIDENCE_FILES.items():
        evidence[key] = {
            "path": f"{r2.EVIDENCE_DIR}/{name}",
            "schema": schema,
            "status": status,
            "sha256": HEX64,
        }
    evidence["d04_cpp_payload_landing"] = {
        "repository": "Affirm/card-platform-product",
        "main_commit": r2.D04_CPP_MAIN_COMMIT,
        "payloads_merged": r2.D04_PAYLOADS_MERGED,
        "description_targets": len(r2.REDUCED_TARGETS),
    }
    evidence["d04_orchestrator_repin"] = {
        "repository": "KleinPerkins/ecosystem-orchestrator",
        "approve_merge_commit": r2.D04_ORCH_APPROVE_COMMIT,
        "prereq_merge_commit": r2.D04_ORCH_PREREQ_COMMIT,
    }
    return evidence


def _valid_catalog() -> dict:
    surfaces = []
    for surface in r2.CATALOG_SURFACES:
        entry = dict(surface)
        entry["catalog_sha256"] = HEX64 if entry["eligible"] else None
        surfaces.append(entry)
    reduced = []
    for name in sorted(r2.REDUCED_TARGETS, key=lambda item: item.encode("ascii")):
        target = r2.REDUCED_TARGETS[name]
        reduced.append({
            "capability_id": name,
            "owner_source_repo": "KleinPerkins/skills",
            "exposure_class": "cursor-skill-description",
            "eligibility": "eligible-skills-d02",
            "description_chars": target,
            "description_words": 30,
            "installed_sha256": HEX64,
            "target_chars": target,
            "result": "PASS",
        })
    return {
        "c01_artifact_sha256": HEX64,
        "dev_commit": HEX40,
        "capture_provenance": "synthetic fixture provenance note",
        "surfaces": surfaces,
        "reduced_ids": reduced,
        "reduced_target_total": r2.REDUCED_TARGET_TOTAL,
        "projection_result": r2.C01_PROJECTION_RESULT,
    }


def _valid_document() -> dict:
    return {
        "schema": r2.SCHEMA,
        "status": "PASS",
        "captured_at_utc": "2026-08-24T00:00:00Z",
        "repository": r2.REPOSITORY,
        "dev_commit": HEX40,
        "dev_tree": HEX40,
        "owner_refs": {
            repo: {"default_branch": "main", "commit": HEX40}
            for repo in r2.OWNER_REPOS
        },
        "release_evidence": _valid_release_evidence(),
        "static_result": {
            "classification": "RELEASE1_STATIC_TARGET_MET",
            "status": "PASS",
            "baseline_totals": {"bytes": 65805, "characters": 65405, "words": 8579},
            "candidate_totals": {"bytes": 45657, "characters": 45521, "words": 5866},
            "delta": {"bytes": -20148, "characters": -19884, "words": -2713},
            "target_30pct": {
                "max_characters": 45783,
                "max_words": 6005,
                "meets_characters": True,
                "meets_words": True,
            },
        },
        "catalog_result": _valid_catalog(),
        "residuals": [dict(item) for item in r2.RESIDUALS],
        "rollback_refs": dict(r2.ROLLBACK_REFS),
        "built_versus_planned": [dict(item) for item in r2.BUILT_VERSUS_PLANNED],
        "content_safety": dict(r2.CONTENT_SAFETY),
        "no_unresolved_p0_p1": {
            "value": True,
            "open_items": [dict(item) for item in r2.NO_P0_P1_OPEN_ITEMS],
        },
    }


class TestValidDocument(unittest.TestCase):
    def test_valid_document_passes(self):
        r2.validate_document(_valid_document())

    def test_canonical_bytes_round_trip_validates(self):
        doc = _valid_document()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release2-closure-v1.json"
            path.write_bytes(kpcm.emit(doc).encode("ascii"))
            r2.validate_path(path)

    def test_main_validate_returns_zero_on_valid(self):
        doc = _valid_document()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release2-closure-v1.json"
            path.write_bytes(kpcm.emit(doc).encode("ascii"))
            self.assertEqual(r2.main(["validate", str(path)]), 0)

    def test_bvp_covers_all_25_program_tasks_in_order(self):
        doc = _valid_document()
        tasks = [row["task"] for row in doc["built_versus_planned"]]
        self.assertEqual(len(tasks), 25)
        self.assertEqual(tasks[:5], ["M-00", "M-01", "M-02", "M-03", "M-04"])
        self.assertEqual(tasks[-3:], ["C-01", "C-02", "C-03"])


class TestRejections(unittest.TestCase):
    def _assert_invalid(self, mutate):
        doc = _valid_document()
        mutate(doc)
        with self.assertRaises(r2.ValidationError):
            r2.validate_document(doc)

    def test_extra_top_level_key_rejected(self):
        self._assert_invalid(lambda d: d.__setitem__("unexpected", 1))

    def test_missing_top_level_key_rejected(self):
        self._assert_invalid(lambda d: d.pop("residuals"))

    def test_status_must_be_pass(self):
        self._assert_invalid(lambda d: d.__setitem__("status", "FAIL"))

    def test_bad_dev_commit_rejected(self):
        self._assert_invalid(lambda d: d.__setitem__("dev_commit", "xyz"))

    def test_owner_ref_repo_set_enforced(self):
        self._assert_invalid(lambda d: d["owner_refs"].pop("KleinPerkins/awa"))

    def test_release_evidence_bad_sha_rejected(self):
        self._assert_invalid(
            lambda d: d["release_evidence"]["release1_static_reduction"]
            .__setitem__("sha256", "nothex")
        )

    def test_static_result_must_meet_target(self):
        self._assert_invalid(
            lambda d: d["static_result"]["target_30pct"]
            .__setitem__("meets_words", False)
        )

    def test_d04_cpp_main_commit_pinned(self):
        # Valid hex40, but not the fixed D-04 CPP landing anchor.
        def mutate(d):
            d["release_evidence"]["d04_cpp_payload_landing"]["main_commit"] = "d" * 40
        self._assert_invalid(mutate)

    def test_d04_orch_prereq_commit_pinned(self):
        def mutate(d):
            d["release_evidence"]["d04_orchestrator_repin"]["prereq_merge_commit"] = "e" * 40
        self._assert_invalid(mutate)

    def test_d04_payloads_merged_pinned(self):
        def mutate(d):
            d["release_evidence"]["d04_cpp_payload_landing"]["payloads_merged"] = 14
        self._assert_invalid(mutate)

    def test_static_delta_inconsistent_rejected(self):
        # delta no longer equals candidate - baseline.
        def mutate(d):
            d["static_result"]["delta"]["characters"] += 1
        self._assert_invalid(mutate)

    def test_static_30pct_derivation_enforced(self):
        # max_characters no longer equals floor(baseline * 70 / 100).
        def mutate(d):
            d["static_result"]["target_30pct"]["max_characters"] += 1
        self._assert_invalid(mutate)

    def test_residual_reword_rejected(self):
        def mutate(d):
            d["residuals"][0]["follow_up_ref"] = "silently reworded follow-up"
        self._assert_invalid(mutate)

    def test_rollback_ref_reword_rejected(self):
        def mutate(d):
            key = next(iter(d["rollback_refs"]))
            d["rollback_refs"][key] = "silently reworded rollback"
        self._assert_invalid(mutate)

    def test_built_versus_planned_text_reword_rejected(self):
        def mutate(d):
            d["built_versus_planned"][0]["built"] = "silently reworded outcome"
        self._assert_invalid(mutate)

    def test_eligible_surface_must_be_pass(self):
        def mutate(d):
            d["catalog_result"]["surfaces"][0]["result"] = "PRODUCT_CONSTRAINED"
        self._assert_invalid(mutate)

    def test_ineligible_surface_cannot_carry_catalog_sha(self):
        def mutate(d):
            d["catalog_result"]["surfaces"][1]["catalog_sha256"] = HEX64
        self._assert_invalid(mutate)

    def test_eligible_surface_sha_must_match_c01_artifact(self):
        # Valid hex, but not equal to the top-level c01_artifact_sha256.
        def mutate(d):
            d["catalog_result"]["surfaces"][0]["catalog_sha256"] = "c" * 64
        self._assert_invalid(mutate)

    def test_surface_eligibility_cannot_be_flipped(self):
        # Flipping the eligible PASS client off the fixed Gate-1 matrix is rejected.
        def mutate(d):
            d["catalog_result"]["surfaces"][0]["eligible"] = False
        self._assert_invalid(mutate)

    def test_surface_constraint_reason_cannot_be_rewritten(self):
        def mutate(d):
            d["catalog_result"]["surfaces"][1]["product_constraint"] = "different reason"
        self._assert_invalid(mutate)

    def test_reduced_count_not_equal_target_rejected(self):
        def mutate(d):
            d["catalog_result"]["reduced_ids"][0]["description_chars"] += 1
        self._assert_invalid(mutate)

    def test_reduced_ids_must_be_thirteen(self):
        self._assert_invalid(
            lambda d: d["catalog_result"]["reduced_ids"].pop()
        )

    def test_projection_result_must_pass(self):
        self._assert_invalid(
            lambda d: d["catalog_result"].__setitem__("projection_result", "FAIL")
        )

    def test_p0_p1_residual_rejected(self):
        def mutate(d):
            d["residuals"][0]["severity"] = "P1"
        self._assert_invalid(mutate)

    def test_no_p0_p1_value_must_be_true(self):
        self._assert_invalid(
            lambda d: d["no_unresolved_p0_p1"].__setitem__("value", False)
        )

    def test_open_item_p0_rejected(self):
        def mutate(d):
            d["no_unresolved_p0_p1"]["open_items"][0]["severity"] = "P0"
        self._assert_invalid(mutate)

    def test_built_versus_planned_missing_task_rejected(self):
        self._assert_invalid(lambda d: d["built_versus_planned"].pop())

    def test_content_safety_flag_flip_rejected(self):
        def mutate(d):
            d["content_safety"]["raw_descriptions_present"] = True
        self._assert_invalid(mutate)

    def test_non_canonical_bytes_rejected_on_path(self):
        doc = _valid_document()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release2-closure-v1.json"
            path.write_text(json.dumps(doc), encoding="utf-8")  # not canonical
            with self.assertRaises(r2.ValidationError):
                r2.validate_path(path)

    def test_main_validate_returns_three_on_invalid(self):
        doc = _valid_document()
        doc["status"] = "FAIL"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release2-closure-v1.json"
            path.write_bytes(kpcm.emit(doc).encode("ascii"))
            self.assertEqual(r2.main(["validate", str(path)]), 3)


if __name__ == "__main__":
    unittest.main()
