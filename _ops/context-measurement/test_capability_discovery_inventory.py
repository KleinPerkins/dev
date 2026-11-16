import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import capability_discovery_inventory as d01


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CapabilityDiscoveryInventoryTest(unittest.TestCase):
    def _artifact(self):
        row = {
            "capability_id": "cursor/cursor-user-skills/example",
            "client": "cursor",
            "root_scope": "cursor-user-skills",
            "owner_source_repo": "KleinPerkins/skills",
            "exposure_class": "cursor-skill-description",
            "installed_path": "/tmp/example/SKILL.md",
            "installed_sha256": "0" * 64,
            "installed_kind": "regular-file",
            "description_chars": 12,
            "description_words": 2,
            "eligibility": "eligible-skills-d02",
        }
        root = {
            "root_id": "cursor/cursor-user-skills",
            "client": "cursor",
            "root_scope": "cursor-user-skills",
            "root_path": "/tmp/example",
            "required": True,
            "exists": True,
            "discovery_source_class": "cursor-session-context",
            "discovery_source_sha256": "1" * 64,
            "installed_count": 1,
            "exposed_count": 1,
            "installed_only_count": 0,
            "classification_rule": "cursor-skills-agent-catalog/v1",
        }
        return {
            "schema": d01.SCHEMA,
            "status": d01.STATUS,
            "captured_at_utc": "2026-08-21T00:00:00Z",
            "repository": d01.REPOSITORY,
            "dev_commit": "2" * 40,
            "dev_tree": "3" * 40,
            "client_scope": ["cursor"],
            "environment_class": d01.ENVIRONMENT_CLASS,
            "method": d01.METHOD,
            "catalog_completeness": [
                {
                    "client": "cursor",
                    "complete": True,
                    "source_sections": [
                        {
                            "section": "agent_skills",
                            "source_sha256": "4" * 64,
                            "source_entry_count": 1,
                            "canonical_entry_count": 1,
                        }
                    ],
                    "canonical_entries": 1,
                    "emitted_rows": 1,
                    "dropped_entries": 0,
                    "canonical_catalog_sha256_by_root": {
                        "cursor/cursor-user-skills": "1" * 64,
                    },
                }
            ],
            "roots": [root],
            "rows": [row],
            "totals": {
                "by_client": {"cursor": 1},
                "by_owner_source_repo": {"KleinPerkins/skills": 1},
                "by_exposure_class": {"cursor-skill-description": 1},
                "by_eligibility": {"eligible-skills-d02": 1},
            },
        }

    def test_valid_minimal_artifact_passes(self):
        d01.validate_object(self._artifact())

    def test_rejects_dropped_catalog_entries(self):
        artifact = self._artifact()
        artifact["catalog_completeness"][0]["dropped_entries"] = 1
        with self.assertRaises(d01.InventoryError):
            d01.validate_object(artifact)

    def test_zero_count_exposures_must_have_zero_description(self):
        artifact = self._artifact()
        row = artifact["rows"][0]
        row["exposure_class"] = "cursor-rule-always-applied"
        row["eligibility"] = "ineligible-full-context-rule"
        artifact["totals"] = {
            "by_client": {"cursor": 1},
            "by_owner_source_repo": {"KleinPerkins/skills": 1},
            "by_exposure_class": {"cursor-rule-always-applied": 1},
            "by_eligibility": {"ineligible-full-context-rule": 1},
        }
        with self.assertRaises(d01.InventoryError):
            d01.validate_object(artifact)

    def test_canonical_file_validation_rejects_unsorted_json(self):
        artifact = self._artifact()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            path.write_text(json.dumps(artifact, sort_keys=False), encoding="utf-8")
            with self.assertRaises(d01.InventoryError):
                d01.validate_path(path)

    def test_cursor_source_requires_digest_match(self):
        section_text = '<agent_skill fullPath="/tmp/SKILL.md">desc</agent_skill>\n'
        source = {
            "schema": d01.CURSOR_SOURCE_SCHEMA,
            "workspace_root": "/tmp/dev",
            "captured_at_utc": "2026-08-21T00:00:00Z",
            "sections": [
                {
                    "section": "always_applied_workspace_rules",
                    "source_text": "",
                    "source_sha256": digest(""),
                },
                {
                    "section": "agent_requestable_workspace_rules",
                    "source_text": "",
                    "source_sha256": digest(""),
                },
                {
                    "section": "agent_skills",
                    "source_text": section_text,
                    "source_sha256": digest(section_text),
                },
            ],
        }
        self.assertEqual(set(d01._section_map(source)), {
            "always_applied_workspace_rules",
            "agent_requestable_workspace_rules",
            "agent_skills",
        })
        bad = copy.deepcopy(source)
        bad["sections"][2]["source_sha256"] = "0" * 64
        with self.assertRaises(d01.InventoryError):
            d01._section_map(bad)

    def test_rule_frontmatter_requires_string_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.mdc"
            path.write_text("---\ndescription: []\n---\nbody\n", encoding="utf-8")
            with self.assertRaises(d01.InventoryError):
                d01._parse_rule_frontmatter(path)

    def test_eligibility_precedence_for_client_owned_and_full_context(self):
        self.assertEqual(
            d01._eligibility("cursor-client", "cursor-skill-description", 10),
            "ineligible-client-owned",
        )
        self.assertEqual(
            d01._eligibility("KleinPerkins/skills", "cursor-home-full-context", 0),
            "ineligible-full-context-rule",
        )

    def test_installed_only_scan_emits_row_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "skills"
            skill = root / "orphan" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\ndescription: Orphan\n---\nbody\n", encoding="utf-8")
            dev_root = base / "dev"
            skills_root = base / "owner-skills"
            cpp_root = base / "cpp"
            awa_root = base / "awa"
            for owner_root in (dev_root, skills_root, cpp_root, awa_root):
                owner_root.mkdir()
            spec = {
                "root_id": "cursor/cursor-user-skills",
                "client": "cursor",
                "root_scope": "cursor-user-skills",
                "root_path": str(root),
                "required": True,
                "exists": True,
                "discovery_source_class": "cursor-session-context",
                "classification_rule": "cursor-skills-agent-catalog/v1",
            }
            rows = []
            scanned = {"cursor/cursor-user-skills": d01._scan_descriptor_root(spec, set())}
            d01._append_installed_only_rows(
                rows,
                {"cursor/cursor-user-skills": spec},
                scanned,
                {"cursor/cursor-user-skills": set()},
                dev_root,
                skills_root,
                cpp_root,
                awa_root,
            )
            roots = d01._build_roots(
                rows,
                [],
                {"cursor/cursor-user-skills": spec},
                scanned,
                {"cursor/cursor-user-skills": d01._canonical_sha256([])},
                dev_root,
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["exposure_class"], "installed-not-client-exposed")
            self.assertEqual(rows[0]["eligibility"], "ineligible-not-client-exposed")
            self.assertEqual(rows[0]["description_chars"], 0)
            self.assertEqual(roots[0]["installed_count"], 1)
            self.assertEqual(roots[0]["exposed_count"], 0)
            self.assertEqual(roots[0]["installed_only_count"], 1)

    def test_installed_only_scan_discovers_nested_sub_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            parent_skill = root / "affirm-design" / "SKILL.md"
            parent_skill.parent.mkdir(parents=True)
            parent_skill.write_text("---\ndescription: Parent\n---\nbody\n", encoding="utf-8")
            nested_skill = root / "affirm-design" / "sub-skills" / "web" / "SKILL.md"
            nested_skill.parent.mkdir(parents=True)
            nested_skill.write_text("---\ndescription: Web\n---\nbody\n", encoding="utf-8")
            spec = {
                "root_id": "cursor/cursor-user-skills",
                "client": "cursor",
                "root_scope": "cursor-user-skills",
                "root_path": str(root),
                "required": True,
                "exists": True,
                "discovery_source_class": "cursor-session-context",
                "classification_rule": "cursor-skills-agent-catalog/v1",
            }
            scanned = d01._scan_descriptor_root(spec, set())
            self.assertIn(parent_skill, scanned)
            self.assertIn(nested_skill, scanned)
            self.assertEqual(len(scanned), 2)

    def test_non_ascii_capability_id_raises_controlled_error(self):
        self.assertEqual(d01._ascii_sort_key("abc"), b"abc")
        artifact = self._artifact()
        artifact["rows"][0]["capability_id"] = "cursor/cursor-user-skills/caf\u00e9"
        with self.assertRaises(d01.InventoryError):
            d01.validate_object(artifact)

    def test_skill_counts_surfaces_unexpected_e03_error(self):
        class FakeE03:
            def parse_frontmatter(self, raw, path):
                raise RuntimeError("unexpected parser failure")

            def normalize_description(self, value):
                return value

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text("---\ndescription: Present\n---\nbody\n", encoding="utf-8")
            with self.assertRaises(d01.InventoryError):
                d01._skill_counts(path, FakeE03())

    def test_nested_sub_skill_names_are_parent_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            for parent in ("alpha", "beta"):
                sub = root / parent / "sub-skills" / "web" / "SKILL.md"
                sub.parent.mkdir(parents=True)
                sub.write_text("---\ndescription: Web\n---\nbody\n", encoding="utf-8")
            spec = {
                "root_id": "cursor/cursor-user-skills",
                "client": "cursor",
                "root_scope": "cursor-user-skills",
                "root_path": str(root),
                "required": True,
                "exists": True,
                "discovery_source_class": "cursor-session-context",
                "classification_rule": "cursor-skills-agent-catalog/v1",
            }
            scanned = d01._scan_descriptor_root(spec, set())
            names = sorted(d01._descriptor_name(path) for path in scanned)
            self.assertEqual(names, ["alpha/web", "beta/web"])

    def test_validator_rejects_installed_only_root_count_mismatch(self):
        artifact = self._artifact()
        artifact["rows"].append({
            "capability_id": "cursor/cursor-user-skills/orphan",
            "client": "cursor",
            "root_scope": "cursor-user-skills",
            "owner_source_repo": "foreign-preserved-install",
            "exposure_class": "installed-not-client-exposed",
            "installed_path": "/tmp/orphan/SKILL.md",
            "installed_sha256": "a" * 64,
            "installed_kind": "regular-file",
            "description_chars": 0,
            "description_words": 0,
            "eligibility": "ineligible-not-client-exposed",
        })
        artifact["rows"].sort(key=lambda item: item["capability_id"].encode("ascii"))
        artifact["roots"][0]["installed_count"] = 2
        artifact["roots"][0]["installed_only_count"] = 0
        artifact["totals"] = {
            "by_client": {"cursor": 2},
            "by_owner_source_repo": {
                "KleinPerkins/skills": 1,
                "foreign-preserved-install": 1,
            },
            "by_exposure_class": {
                "cursor-skill-description": 1,
                "installed-not-client-exposed": 1,
            },
            "by_eligibility": {
                "eligible-skills-d02": 1,
                "ineligible-not-client-exposed": 1,
            },
        }
        with self.assertRaises(d01.InventoryError):
            d01.validate_object(artifact)


if __name__ == "__main__":
    unittest.main()
