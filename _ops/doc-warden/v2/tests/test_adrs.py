import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_warden.adrs import (preview_adr_draft, preview_adr_update, preview_adr_accept,
                             preview_adr_successor, frozen_semantic_postimages, _index_delta)
from doc_warden.artifacts import apply_preview, consent_for, draft_artifact
from doc_warden.artifact_discovery import artifact_paths
from doc_warden.canonical import canonical_json, digest_ref, parse_artifact
from doc_warden.dependencies import resolve_graph, PlanAssumption, _observe_assumption
from doc_warden.operation_store import store_preview, load_preview
from doc_warden.validators import active_approved_artifacts
from fixture_factory import FixtureFactory


class ADRTests(unittest.TestCase):
    def dotted_legacy_index(self):
        root = self.repo / "docs/adr"
        root.mkdir(parents=True, exist_ok=True)
        legacy = root / "0002-v2.27-operating-decisions.md"
        legacy.write_bytes(b"# ADR 0002: Legacy operating decisions\nStatus: accepted\n")
        index = root / "README.md"
        index.write_bytes(
            b"# Decisions\n\n| ADR | Status | One-line decision |\n|---|---|---|\n"
            b"| [0002](0002-v2.27-operating-decisions.md) | Accepted | Legacy history |\n"
        )
        return legacy, index

    def test_dotted_legacy_index_preview_and_apply_preserve_history(self):
        legacy, index = self.dotted_legacy_index()
        legacy_bytes, index_bytes = legacy.read_bytes(), index.read_bytes()
        draft = self.draft()
        self.assertEqual(draft.artifact_path, "docs/adr/0003-use-stable-decisions.md")
        proposed = next(a.content for a in draft.transaction.actions if a.path.endswith("README.md"))
        self.assertEqual(proposed, index_bytes + b"| [0003](0003-use-stable-decisions.md) | Draft | Use stable decisions |\n")
        self.assertIn(
            (str(legacy), digest_ref(legacy_bytes)),
            [(item.path, item.digest) for item in draft.transaction.observed_inputs],
        )
        self.assertEqual(index.read_bytes(), index_bytes)
        self.apply(draft)
        self.assertEqual(index.read_bytes(), proposed)
        self.assertEqual(legacy.read_bytes(), legacy_bytes)
        self.assertEqual(list(artifact_paths(self.repo)), [self.repo / draft.artifact_path])

    def test_dotted_legacy_body_drift_refuses_apply_before_any_write(self):
        legacy, index = self.dotted_legacy_index()
        original, index_bytes = legacy.read_bytes(), index.read_bytes()
        for changed in (b"# Changed legacy prose\n", b"---\n{}\n---\n"):
            with self.subTest(changed=changed):
                legacy.write_bytes(original)
                draft = self.draft()
                legacy.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, "observed_input_drift"):
                    self.apply(draft)
                self.assertFalse((self.repo / draft.artifact_path).exists())
                self.assertEqual(index.read_bytes(), index_bytes)
                self.assertEqual(legacy.read_bytes(), changed)

    def test_dotted_legacy_target_must_exist_and_remain_nonmetadata(self):
        legacy, index = self.dotted_legacy_index()
        before = index.read_bytes()
        for raw in (None, b"---\n{}\n---\n", b"# Disguised\ndoc-warden/artifact/v2\n"):
            with self.subTest(raw=raw):
                legacy.unlink(missing_ok=True)
                if raw is not None:
                    legacy.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.draft()
                self.assertEqual(index.read_bytes(), before)

    def test_dotted_legacy_index_keeps_labels_containment_and_numbers_closed(self):
        legacy, index = self.dotted_legacy_index()
        original = index.read_bytes()
        for cell in (
            "[wrong](0002-v2.27-operating-decisions.md)",
            "[0002](../0002-v2.27-operating-decisions.md)",
            "[0002](https://example.invalid/0002-v2.27-operating-decisions.md)",
        ):
            with self.subTest(cell=cell):
                text = original.decode().replace("[0002](0002-v2.27-operating-decisions.md)", cell)
                index.write_text(text)
                with self.assertRaisesRegex(ValueError, "adr_index_ambiguous"):
                    self.draft()
                self.assertEqual(index.read_text(), text)
        duplicate = original + b"| [0002](0002-other.md) | Accepted | Duplicate number |\n"
        index.write_bytes(duplicate)
        with self.assertRaisesRegex(ValueError, "adr_index_ambiguous"):
            self.draft()
        self.assertEqual(index.read_bytes(), duplicate)

    def test_dotted_legacy_compatibility_does_not_allow_dotted_new_names(self):
        _, index = self.dotted_legacy_index()
        before = index.read_bytes()
        with self.assertRaisesRegex(ValueError, "adr_index_ambiguous"):
            _index_delta(self.repo, "docs/adr/README.md", "0003-v2.1-new.md", "New", "Draft")
        self.assertEqual(index.read_bytes(), before)

    def test_dotted_legacy_symlink_refuses_preview(self):
        legacy, index = self.dotted_legacy_index()
        original = index.read_bytes()
        target = self.repo / "legacy-source.md"
        target.write_bytes(legacy.read_bytes())
        legacy.unlink()
        legacy.symlink_to(target)
        with self.assertRaises(ValueError):
            self.draft()
        self.assertEqual(index.read_bytes(), original)

    def legacy_index(self):
        root = self.repo / "docs/adr"
        root.mkdir(parents=True, exist_ok=True)
        data = (Path(__file__).parent / "fixtures/legacy-four-column-index.md").read_bytes()
        (root / "README.md").write_bytes(data)
        for name in ("0001-single-sanctioned-cpp-edge-writer.md", "0002-one-combined-cpp-pr-per-sync.md"):
            (root / name).write_bytes(b"# Legacy prose\nStatus: DRAFT\n")
        return root, data

    def test_exact_legacy_four_column_preview_preserves_every_existing_byte(self):
        root, original = self.legacy_index()
        self.assertEqual(digest_ref(original), "sha256:9faec405ff4d7ad8c2d3917b50f827887f99c6064a871f161205be2c472db046")
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        draft = self.draft()
        self.assertEqual(draft.artifact_path, "docs/adr/0003-use-stable-decisions.md")
        self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
        proposed = next(a.content for a in draft.transaction.actions if a.path.endswith("README.md"))
        row = b"| [0003](0003-use-stable-decisions.md) | Use stable decisions | Draft |  |\n"
        self.assertEqual(proposed, original.replace(b"\n## Conventions", row + b"\n## Conventions"))
        self.apply(draft)
        self.assertEqual((root / "README.md").read_bytes(), proposed)
        for name, data in before.items():
            if name != "README.md":
                self.assertEqual((root / name).read_bytes(), data)
        self.assertEqual(list(artifact_paths(self.repo)), [self.repo / draft.artifact_path])

    def test_four_column_lifecycle_preserves_identity_date_and_final_predecessor(self):
        root, original = self.legacy_index()
        draft = self.draft()
        self.apply(draft)
        index = root / "README.md"
        # Existing canonical rows can use the legacy bare identity and retain a date.
        old_row = "| 0003-use-stable-decisions.md | Use stable decisions | Draft | 2026-01-02 |\n"
        text = index.read_text().replace("| [0003](0003-use-stable-decisions.md) | Use stable decisions | Draft |  |\n", old_row)
        index.write_text(text)
        update = preview_adr_update(draft.artifact_id, {"title": "Revised", "body": "# Revised\n\nDecision."}, repo=self.repo)
        self.apply(update)
        self.assertEqual(index.read_text(), text.replace("| Use stable decisions |", "| Revised |"))
        self.apply(self.accept(draft))
        predecessor_bytes = (self.repo / draft.artifact_path).read_bytes()
        successor = preview_adr_successor(draft.artifact_id, {"title": "Replacement"}, repo=self.repo)
        self.apply(successor)
        self.assertNotIn("Superseded", index.read_text())
        previous = "| 0003-use-stable-decisions.md | Revised | Accepted | 2026-01-02 |\n"
        text = index.read_text().replace(previous, "").replace("\n## Conventions", previous + "\n## Conventions")
        index.write_text(text)
        self.apply(self.accept(successor))
        expected = text.replace("| Replacement | Draft |", "| Replacement | Accepted |").replace(
            previous, previous.replace("| Accepted |", "| Superseded by [0004](0004-replacement.md) |"))
        self.assertEqual(index.read_text(), expected)
        self.assertEqual((self.repo / draft.artifact_path).read_bytes(), predecessor_bytes)
        self.assertIn(original.split(b"## Conventions")[1], index.read_bytes())

    def test_index_cell_preservation_both_layouts_and_crlf(self):
        root = self.repo / "docs/adr"
        root.mkdir(parents=True)
        index = root / "README.md"
        for header, row, expected_row in (
            ("| ADR | Status | One-line decision |", "| [0001-old.md](0001-old.md) |\tDraft  | Old |",
             "| [0001-old.md](0001-old.md) |\tAccepted  | Revised |"),
            ("| ADR | Title | Status | Date |", "| 0001-old.md | Old |\tDraft  | 2026-01-01 |",
             "| 0001-old.md | Revised |\tAccepted  | 2026-01-01 |"),
        ):
            for newline in ("\n", "\r\n"):
                with self.subTest(header=header, newline=newline):
                    separator = "|" + " :---: |" * (len(header.split("|")) - 2)
                    original = newline.join(["Prefix.", "", header, separator, row, "", "Footer."])
                    index.write_bytes(original.encode())
                    actual = _index_delta(self.repo, "docs/adr/README.md", "0001-old.md", "Revised", "Accepted")
                    self.assertEqual(actual, original.replace(row, expected_row).encode())
                    self.assertEqual(index.read_bytes(), original.encode())

    def test_malformed_legacy_indexes_fail_without_writes(self):
        root, original = self.legacy_index()
        text = original.decode()
        header = "| ADR | Title | Status | Date |"
        first = "0001-single-sanctioned-cpp-edge-writer.md"
        variants = [text.replace("|---|---|---|---|", "|---|bad|---|---|"),
                    text.replace("|---|---|---|---|", "|---|---|---|"),
                    text.replace("| DRAFT | 2026-08-06 |", "| DRAFT |"),
                    text.replace("| DRAFT | 2026-08-06 |", "| DRAFT | extra | 2026-08-06 |"),
                    text.replace(header, "| ADR | Status | Title | Date |"),
                    text + "\n| ADR | Status | One-line decision |\n|---|---|---|\n",
                    text + "\n" + header + "\n|---|---|---|---|\n",
                    text.replace("0002-one-combined-cpp-pr-per-sync.md", first),
                    text.replace("0002-one-combined-cpp-pr-per-sync.md", "0001-other.md"),
                    text.replace("| | | |", "| changed | | |"),
                    text.replace(first, "prefix [0001](" + first + ") suffix")]
        for identity in (f"[0002]({first})", f"[unrelated]({first})", f"[0001](../{first})",
                         f"[0001](/{first})", f"[0001](./{first})", f"[0001](https://host/{first})",
                         f"[0001]({first}#anchor)", f"[0001](%2e%2e/{first})", f"[0001]({first} 'title')"):
            variants.append(text.replace(first, identity))
        for value in variants:
            with self.subTest(index=value):
                (root / "README.md").write_text(value)
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with self.assertRaises(ValueError):
                    self.draft()
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_escaped_pipes_preserve_cell_boundaries_in_both_layouts(self):
        root = self.repo / "docs/adr"
        root.mkdir(parents=True)
        index = root / "README.md"
        for width in (3, 4):
            for count in (1, 2, 3, 4):
                with self.subTest(width=width, backslashes=count):
                    escaped = "Old " + "\\" * count + "| useful"
                    header = ("| ADR | Status | One-line decision |" if width == 3
                              else "| ADR | Title | Status | Date |")
                    row = (f"| 0001-old.md | Draft | {escaped} |" if width == 3 else
                           f"| 0001-old.md | {escaped} | Draft | 2020\\|2021 |")
                    original = "\n".join([header, "|" + "---|" * width, row, "", "Footer."])
                    index.write_text(original)
                    if count % 2 == 0:
                        with self.assertRaisesRegex(ValueError, "adr_index_ambiguous"):
                            self.draft()
                        continue
                    (root / "0001-old.md").write_text("# Legacy\n")
                    draft = self.draft(title="New")
                    proposed = next(a.content.decode() for a in draft.transaction.actions if a.path.endswith("README.md"))
                    self.assertIn(row + "\n", proposed)
                    self.assertEqual(index.read_text(), original)
                    # Replacing a target title/status preserves its escaped Date.
                    updated = _index_delta(self.repo, "docs/adr/README.md", "0001-old.md", "Revised", "Accepted").decode()
                    self.assertEqual(updated, original.replace(escaped, "Revised").replace("| Draft |", "| Accepted |"))
                    # Supersession changes status only, retaining escaped titles/dates.
                    updated = _index_delta(self.repo, "docs/adr/README.md", "0002-new.md", "New", "Accepted", "0001-old.md").decode()
                    self.assertIn(row.replace("| Draft |", "| Superseded by [0002](0002-new.md) |"), updated)

    def test_compact_index_update_cannot_escape_following_delimiter(self):
        draft = self.draft(title="Initial")
        self.apply(draft)
        index = self.repo / "docs/adr/README.md"
        for width in (3, 4):
            for count in (1, 2, 3, 4):
                with self.subTest(width=width, trailing_backslashes=count):
                    header = ("|ADR|Status|One-line decision|" if width == 3 else "|ADR|Title|Status|Date|")
                    row = ("|[0001](0001-initial.md)|Draft|Initial|" if width == 3 else
                           "|[0001](0001-initial.md)|Initial|Draft|2020-01-01|")
                    original = "\n".join([header, "|" + "---|" * width, row, ""])
                    index.write_text(original)
                    title = "New" + "\\" * count
                    update = preview_adr_update(draft.artifact_id, {"title": title, "body": "# " + title + "\n"}, repo=self.repo)
                    self.apply(update)
                    safe_cell = title + (" " if count % 2 else "")
                    self.assertEqual(index.read_text(), original.replace("|Initial|", "|" + safe_cell + "|"))
                    # A subsequent public preview must still parse the applied row.
                    self.assertEqual(self.draft(title="Next").artifact_path, "docs/adr/0002-next.md")

    def test_index_rejects_stale_number_collision_and_symlink_identity(self):
        root, original = self.legacy_index()
        index = root / "README.md"
        index.write_bytes(original.replace(b"\n## Conventions", b"| 0003-other.md | Stale | DRAFT |  |\n\n## Conventions"))
        with self.assertRaises(ValueError):
            self.draft()
        index.write_bytes(original)
        target = root / "0001-single-sanctioned-cpp-edge-writer.md"
        target.unlink()
        target.symlink_to(self.repo / "README.md")
        with self.assertRaises(ValueError):
            self.draft()

    def setUp(self):
        self.fixture = FixtureFactory.create()
        self.repo = self.fixture.repo.resolve()
        self.state = tempfile.TemporaryDirectory(prefix="adr-operation-state-")
        self.environment = patch.dict(os.environ, {"XDG_STATE_HOME": self.state.name})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.state.cleanup()
        self.fixture.cleanup()

    def draft(self, **kwargs):
        return preview_adr_draft({"title": "Use stable decisions", **kwargs}, repo=self.repo)

    def apply(self, preview):
        return apply_preview(preview, consent_for(preview.transaction))

    def accept(self, draft):
        path = self.repo / draft.artifact_path
        return preview_adr_accept(draft.artifact_id,
            {"actor": "operator", "date": "2026-10-27", "review_sha256": digest_ref(path.read_bytes())[7:]}, repo=self.repo)

    def structural_classification(self, relative):
        library = Path(__file__).resolve().parents[3] / "bin/doc-warden-lib.sh"
        path = Path(relative)
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; dwl_classify_adr_file "$2" "$3" "$4"',
             "adr-structural-test", str(library), str(self.repo),
             path.parent.as_posix(), path.name],
            capture_output=True, text=True, check=True,
        )
        return result.stdout

    def test_structural_view_uses_v2_schema_and_freeze_without_legacy_headings(self):
        draft = self.draft(body="# Reviewed choice\n\nDecision and rationale in reviewed prose.\n")
        self.apply(draft)
        self.assertEqual(self.structural_classification(draft.artifact_path), "CONFORMANT")
        self.apply(self.accept(draft))
        self.assertEqual(self.structural_classification(draft.artifact_path), "CONFORMANT")
        path = self.repo / draft.artifact_path
        path.write_bytes(path.read_bytes() + b"unapproved change\n")
        self.assertEqual(self.structural_classification(draft.artifact_path), "DRIFTED")
        path.write_text("# Disguised as legacy\n\n## Decision\n\n## Why\n\n## Consequences\n")
        self.assertEqual(self.structural_classification(draft.artifact_path), "DRIFTED")

    def test_structural_view_requires_canonical_acceptance_evidence(self):
        draft = self.draft()
        self.apply(draft)
        accepted = self.accept(draft)
        self.apply(accepted)
        receipt = self.repo / f"_ops/doc-warden/state/v2/receipts/{accepted.transaction.operation_id}.json"
        receipt.unlink()
        self.assertEqual(self.structural_classification(draft.artifact_path), "DRIFTED")

    def test_structural_view_preserves_legacy_rules_and_rejects_bad_metadata(self):
        path = self.repo / "docs/adr/0001-legacy.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy = "# Legacy\n\n## Decision\n\nChosen.\n\n## Consequences\n\nBounded.\n"
        path.write_text(legacy)
        self.assertEqual(self.structural_classification("docs/adr/0001-legacy.md"), "DRIFTED")
        path.write_text(legacy + "\n## Why\n\nReason.\n")
        self.assertEqual(self.structural_classification("docs/adr/0001-legacy.md"), "CONFORMANT")
        path.write_text('---\n{"schema":"doc-warden/artifact/v2"}\n---\n' + path.read_text())
        self.assertEqual(self.structural_classification("docs/adr/0001-legacy.md"), "DRIFTED")

    def test_default_lifecycle_and_index_mutability(self):
        draft = self.draft()
        self.assertEqual(draft.artifact_path, "docs/adr/0001-use-stable-decisions.md")
        receipt = self.apply(draft)
        self.assertEqual(receipt["transition"], "creation_snapshot")
        update = preview_adr_update(draft.artifact_id, {"title": "Updated", "body": "# Updated\n\nDecision."}, repo=self.repo)
        self.apply(update)
        metadata = parse_artifact(self.repo / draft.artifact_path).metadata
        self.assertEqual((metadata["id"], metadata["version"]), (draft.artifact_id, 1))
        accepted = self.accept(draft)
        receipt = self.apply(accepted)
        self.assertEqual(set(frozen_semantic_postimages(receipt)), {draft.artifact_path})
        self.assertIsNone(receipt["delivery_commit"])
        with self.assertRaisesRegex(ValueError, "frozen"):
            preview_adr_update(draft.artifact_id, {"title": "No"}, repo=self.repo)
        another = self.draft(title="Another decision")
        self.apply(another)
        self.assertIn("0002", another.artifact_path)
        self.assertEqual(len(active_approved_artifacts(self.repo, "adr")), 1)

    def test_override_and_legacy_bytes_preserved(self):
        (self.repo / ".doc-warden.yml").write_text("plans_dir: _ops/plans\nadr_dir: _ops/adr\n")
        root = self.repo / "_ops/adr"
        root.mkdir()
        legacy = root / "0007-old.md"
        legacy.write_bytes(b"# ADR 0007: Old\nAccepted historical prose.\n")
        index = root / "README.md"
        original = "Intro remains.\n\n| ADR | Status | One-line decision |\n|---|---|---|\n| [0007](0007-old.md) | Accepted | Historical |\n\nFooter remains.\n"
        index.write_text(original)
        before = legacy.read_bytes()
        draft = self.draft()
        self.apply(draft)
        self.assertIn("_ops/adr/0008-", draft.artifact_path)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertIn("Intro remains.", index.read_text())
        self.assertIn("Footer remains.", index.read_text())
        self.assertEqual(list(artifact_paths(self.repo)), [self.repo / draft.artifact_path])

    def test_unsafe_override_and_symlinks(self):
        for value in ("/tmp/adr", "../adr", "docs/../adr", "docs//adr", "docs/adr/", "[docs/adr]", "&alias"):
            with self.subTest(value=value):
                (self.repo / ".doc-warden.yml").write_text("adr_dir: " + value + "\n")
                with self.assertRaises(ValueError):
                    self.draft()
        for value in ("adr_dir: docs/adr\nadr_dir: docs/other\n", " adr_dir: docs/adr\n", "adr_dir:\n - docs\n"):
            (self.repo / ".doc-warden.yml").write_text(value)
            with self.assertRaises(ValueError):
                self.draft()
        (self.repo / ".doc-warden.yml").unlink()
        (self.repo / "docs").symlink_to(self.state.name, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.draft()

    def test_missing_disabled_profile_and_duplicate_numbers(self):
        profile_path = self.repo / ".planning/doc-warden.json"
        profile = json.loads(profile_path.read_bytes())
        profile["enabled"] = False
        profile_path.write_bytes(canonical_json(profile))
        with self.assertRaisesRegex(ValueError, "profile_required"):
            self.draft()
        profile["enabled"] = True
        profile_path.write_bytes(canonical_json(profile))
        root = self.repo / "docs/adr"
        root.mkdir(parents=True)
        for name in ("0001-one.md", "0001-two.md"):
            (root / name).write_text("# Legacy\n")
        with self.assertRaisesRegex(ValueError, "number_duplicate"):
            self.draft()

    def test_concurrent_preview_raw_collision_and_override_insertion(self):
        first, second = self.draft(), self.draft(title="Other")
        self.apply(first)
        with self.assertRaises(ValueError):
            self.apply(second)
        preview = self.draft(title="Next")
        (self.repo / "docs/adr/0099-raw.md").write_text("# Legacy\n")
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            self.apply(preview)
        preview = self.draft(title="Next")
        (self.repo / ".doc-warden.yml").write_text("adr_dir: docs/other\n")
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            self.apply(preview)

    def test_exact_consent_approval_and_frozen_metadata_tamper(self):
        draft = self.draft()
        with self.assertRaisesRegex(ValueError, "consent"):
            apply_preview(draft, None)
        consent = consent_for(draft.transaction)
        consent["action_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "consent"):
            apply_preview(draft, consent)
        self.apply(draft)
        for approval in ({}, {"actor": "operator", "date": "2026-10-27", "review_sha256": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "approval_evidence"):
                preview_adr_accept(draft.artifact_id, approval, repo=self.repo)
        self.apply(self.accept(draft))
        path = self.repo / draft.artifact_path
        parsed = parse_artifact(path)
        metadata = dict(parsed.metadata, lifecycle="draft", approval=None)
        path.write_bytes(b"---\n" + canonical_json(metadata) + b"---\n" + parsed.body.encode())
        with self.assertRaisesRegex(ValueError, "frozen"):
            preview_adr_update(draft.artifact_id, {"title": "Tampered"}, repo=self.repo)

    def test_successor_only_effective_after_acceptance(self):
        first = self.draft()
        self.apply(first)
        self.apply(self.accept(first))
        before = (self.repo / first.artifact_path).read_bytes()
        successor = preview_adr_successor(first.artifact_id, {"title": "Replacement"}, repo=self.repo)
        self.apply(successor)
        self.assertEqual([row[1]["id"] for row in active_approved_artifacts(self.repo, "adr")], [first.artifact_id])
        index = self.repo / "docs/adr/README.md"
        self.assertNotIn("Superseded", index.read_text())
        assumption = PlanAssumption(schema="doc-warden/plan-assumption/v1", id="ASSUMPTION-ADR",
            kind="adr", source_id=None, target_id=first.artifact_id, target_kind="adr",
            version=1, digest=digest_ref(before), repository_key=self.fixture.repository_key,
            revision="a" * 40, provider_revision=None, path=None, symbol=None,
            relation=None, task_ids=(), requirement_ids=())
        self.assertEqual(_observe_assumption(self.repo, assumption)["target_id"], first.artifact_id)
        self.apply(self.accept(successor))
        self.assertEqual(_observe_assumption(self.repo, assumption)["target_id"], successor.artifact_id)
        self.assertEqual([row[1]["id"] for row in active_approved_artifacts(self.repo, "adr")], [successor.artifact_id])
        self.assertIn("Superseded by", index.read_text())
        self.assertEqual((self.repo / first.artifact_path).read_bytes(), before)
        graph = resolve_graph((self.repo,))
        self.assertIn(successor.artifact_id, graph.nodes)

    def test_load_recovery_and_replay_all_write_boundaries(self):
        for count in (0, 1, 2, 3, 4):
            with self.subTest(count=count):
                draft = self.draft(title=f"Decision {count}")
                store_preview(draft.transaction)
                if count == 4:
                    self.apply(draft)
                else:
                    for action in draft.transaction.actions[:count]:
                        path = self.repo / action.path
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(action.content)
                    if count == 3:
                        from doc_warden.transactions import _event_for
                        event = _event_for(draft.transaction)
                        path = self.repo / f"_ops/doc-warden/state/v2/events/{event['event_id']}.json"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(canonical_json(event))
                loaded = load_preview(draft.transaction.operation_id, draft.transaction.action_digest)
                receipt = apply_preview(loaded, consent_for(loaded))
                self.assertEqual(receipt, apply_preview(loaded, consent_for(loaded)))

    def test_shared_directory_replay_without_consent_and_existing_control_tree(self):
        import shutil
        from doc_warden.artifacts import _bindings
        from doc_warden.transactions import (MutationAction, MutationRequest, ObservedInput,
            directory_input_digest, preview_transaction, apply_transaction)
        shutil.rmtree(self.repo / "_ops")
        transaction = preview_transaction(MutationRequest(repo=self.repo,
            repository_key=self.fixture.repository_key, transition="projection_update",
            actions=(MutationAction("docs/output.md", b"output", "create"),),
            bindings=_bindings(self.repo), consequential=False,
            observed_inputs=(ObservedInput(str(self.repo), directory_input_digest(self.repo)),)))
        receipt = apply_transaction(transaction, None)
        self.assertEqual(apply_transaction(transaction, None), receipt)

    def test_freeze_helper_preserves_unrelated_readme_authority(self):
        receipt = {"transition": "accepted_freeze", "postimages": {
            "README.md": "original", "docs/adr/0001-decision.md": "semantic",
            "docs/adr/README.md": "projection"}}
        self.assertEqual(frozen_semantic_postimages(receipt), {
            "README.md": "original", "docs/adr/0001-decision.md": "semantic"})

    def test_foreign_empty_directory_is_not_recovery_output(self):
        draft = self.draft()
        store_preview(draft.transaction)
        action = draft.transaction.actions[0]
        path = self.repo / action.path
        path.parent.mkdir(parents=True)
        path.write_bytes(action.content)
        (self.repo / "docs/foreign").mkdir()
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            load_preview(draft.transaction.operation_id, draft.transaction.action_digest)

    def test_successor_acceptance_rechecks_frozen_predecessor(self):
        draft = self.draft()
        self.apply(draft)
        self.apply(self.accept(draft))
        successor = preview_adr_successor(draft.artifact_id, {"title": "Replacement"}, repo=self.repo)
        self.apply(successor)
        path = self.repo / draft.artifact_path
        path.write_bytes(path.read_bytes() + b"Tampered predecessor")
        with self.assertRaisesRegex(ValueError, "frozen_bytes_changed"):
            self.accept(successor)

    def test_freeze_evidence_remains_valid_after_root_relocation(self):
        import shutil
        draft = self.draft()
        self.apply(draft)
        self.apply(self.accept(draft))
        with tempfile.TemporaryDirectory(prefix="adr-relocated-") as temporary:
            destination = Path(temporary) / "repo"
            shutil.copytree(self.repo, destination)
            successor = preview_adr_successor(draft.artifact_id, {"title": "Replacement"}, repo=destination)
            self.assertEqual(successor.transaction.transition, "creation_snapshot")

    def test_schema_valid_freeze_receipt_tamper_refused(self):
        draft = self.draft()
        self.apply(draft)
        accepted = self.accept(draft)
        self.apply(accepted)
        path = self.repo / f"_ops/doc-warden/state/v2/receipts/{accepted.transaction.operation_id}.json"
        receipt = json.loads(path.read_bytes())
        receipt["action_digest"] = "sha256:" + "0" * 64
        path.write_bytes(canonical_json(receipt))
        with self.assertRaisesRegex(ValueError, "freeze_receipt_invalid"):
            preview_adr_successor(draft.artifact_id, {"title": "Replacement"}, repo=self.repo)

    def test_accept_rejects_index_delimiters_in_body_title(self):
        draft = self.draft(body="# Header | injected\n\nDecision.")
        self.apply(draft)
        with self.assertRaisesRegex(ValueError, "adr_title_invalid"):
            self.accept(draft)

    def test_stale_authority_head_preimage_and_input_type(self):
        import subprocess
        authority = self.repo / "_ops/doc-warden/POLICY.md"
        authority.write_text("original policy")
        draft = self.draft()
        authority.write_text("changed policy")
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            self.apply(draft)
        draft = self.draft()
        subprocess.run(["git", "-C", str(self.repo), "commit", "--allow-empty", "-qm", "new head"], check=True)
        with self.assertRaisesRegex(ValueError, "source_revision_changed"):
            self.apply(draft)
        draft = self.draft()
        authority.unlink()
        authority.mkdir()
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            self.apply(draft)
        authority.rmdir()
        authority.write_text("policy")
        self.apply(self.draft())
        draft = self.draft(title="Next")
        index = self.repo / "docs/adr/README.md"
        index.write_text(index.read_text() + "Extra prose")
        with self.assertRaisesRegex(ValueError, "preimage_changed"):
            self.apply(draft)

    def test_accept_and_default_update_preserve_crlf_body_bytes(self):
        body = "# Exact decision\r\n\r\nDecision with spaces.  \r\nNo final newline"
        draft = self.draft(body=body)
        self.apply(draft)
        update = preview_adr_update(draft.artifact_id, {"title": "Exact decision"}, repo=self.repo)
        self.apply(update)
        raw = (self.repo / draft.artifact_path).read_bytes()
        self.assertEqual(raw.split(b"\n---\n", 1)[1], body.encode())
        self.apply(self.accept(draft))
        raw = (self.repo / draft.artifact_path).read_bytes()
        self.assertEqual(raw.split(b"\n---\n", 1)[1], body.encode())

    def test_approved_body_bytes_preserved_exactly(self):
        for number, body in enumerate(("# Exact approved\n\nDecision.  \n\n", "# No final newline")):
            approval = {"actor": "operator", "date": "2026-10-27",
                        "review_sha256": digest_ref(body.encode())[7:]}
            draft = self.draft(title=f"Exact {number}", body=body, approval=approval)
            self.apply(draft)
            self.assertEqual(parse_artifact(self.repo / draft.artifact_path).body.encode(), body.encode())

    def test_explicit_approved_creation_freezes_only_semantic_record(self):
        body = "# Approved decision\n\nOperator approved this decision.\n"
        approval = {"actor": "operator", "date": "2026-10-27",
                    "review_sha256": digest_ref(body.encode())[7:]}
        draft = self.draft(body=body, approval=approval)
        self.assertEqual(draft.transaction.transition, "accepted_freeze")
        receipt = self.apply(draft)
        self.assertEqual(set(frozen_semantic_postimages(receipt)), {draft.artifact_path})
        self.apply(self.draft(title="Next decision"))
        with self.assertRaisesRegex(ValueError, "approval_evidence"):
            self.draft(body=body + "Changed", approval=approval)

    def test_typed_parents_bind_numbered_adr_through_preview_accept_and_replay(self):
        import contextlib
        import io
        from doc_warden.cli import main

        parent_body = "# Parent decision\n\nApproved parent.\n"
        parent = self.draft(title="Parent decision", body=parent_body, approval={
            "actor": "operator", "date": "2026-10-27",
            "review_sha256": digest_ref(parent_body.encode())[7:],
        })
        parent_receipt = self.apply(parent)
        path = self.repo / parent.artifact_path
        parents = Path(self.state.name) / "parents.json"
        parents.write_bytes(canonical_json({
            "observed_at": "2026-10-27T18:00:00Z",
            "parents": [{"kind": "adr", "id": parent.artifact_id, "version": 1,
                         "digest": digest_ref(path.read_bytes())}],
        }))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["adr", "draft", "--repo", str(self.repo),
                                   "--title", "Child decision", "--parents-file", str(parents), "--preview"]), 0)
        result = json.loads(output.getvalue())
        draft = load_preview(result["operation_id"], result["action_digest"])
        apply_preview(draft, consent_for(draft))
        child = self.repo / result["artifact_path"]
        relation, = parse_artifact(child).metadata["relations"]
        self.assertEqual(relation["target"], {"kind": "adr", "id": parent.artifact_id, "version": 1})
        self.assertEqual(relation["provenance"], [{"digest": digest_ref(path.read_bytes())}])
        accepted = preview_adr_accept(result["artifact_id"], {
            "actor": "operator", "date": "2026-10-27", "review_sha256": digest_ref(child.read_bytes())[7:],
        }, repo=self.repo)
        observed = {item.path for item in accepted.transaction.observed_inputs}
        self.assertIn(str(path), observed)
        for kind in ("receipts", "events"):
            identifier = parent_receipt["operation_id" if kind == "receipts" else "event_id"]
            self.assertIn(str(self.repo / f"_ops/doc-warden/state/v2/{kind}/{identifier}.json"), observed)
        store_preview(accepted.transaction)
        receipt = self.apply(accepted)
        retry = load_preview(accepted.transaction.operation_id, accepted.transaction.action_digest)
        self.assertEqual(apply_preview(retry, consent_for(retry)), receipt)

    def test_typed_prd_parent_requires_a_live_matching_freeze(self):
        prd = draft_artifact("prd", {"title": "Product", "lifecycle": "approved",
                                    "approval": {"actor": "operator"}}, repo=self.repo)
        target = self.repo / prd.artifact_path
        data = prd.transaction.actions[-1].content
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        request = {"observed_at": "2026-10-27T18:00:00Z", "parents": [{
            "kind": "prd", "id": prd.artifact_id, "version": 1, "digest": digest_ref(data),
        }]}
        with self.assertRaisesRegex(ValueError, "authority_freeze_required"):
            self.draft(parents=request)
        target.unlink()
        self.apply(prd)
        draft = self.draft(parents=request)
        target.write_bytes(data + b"Changed after preview.\n")
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            self.apply(draft)
        self.assertFalse((self.repo / draft.artifact_path).exists())

    def test_cli_approved_creation_preserves_exact_crlf_file(self):
        import contextlib
        import io
        from doc_warden.cli import main
        body = b"# Exact decision\r\n\r\nDecision.  \r\nNo final newline"
        body_file = Path(self.state.name) / "body.md"
        approval_file = Path(self.state.name) / "approval.json"
        body_file.write_bytes(body)
        approval_file.write_bytes(canonical_json({"actor": "operator", "date": "2026-10-27",
                                                  "review_sha256": digest_ref(body)[7:]}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["adr", "draft", "--repo", str(self.repo), "--title", "Exact decision",
                "--body-file", str(body_file), "--approval-file", str(approval_file), "--preview"]), 0)
        value = json.loads(output.getvalue())
        loaded = load_preview(value["operation_id"], value["action_digest"])
        self.assertEqual(loaded.transition, "accepted_freeze")
        apply_preview(loaded, consent_for(loaded))
        raw = (self.repo / value["artifact_path"]).read_bytes()
        self.assertEqual(raw.split(b"\n---\n", 1)[1], body)

    def test_cli_preview_and_generic_apply_store_contract(self):
        import contextlib
        import io
        from doc_warden.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["adr", "draft", "--repo", str(self.repo), "--title", "CLI decision", "--preview"]), 0)
        value = json.loads(output.getvalue())
        loaded = load_preview(value["operation_id"], value["action_digest"])
        self.assertEqual(loaded.transition, "creation_snapshot")
        self.assertEqual(value["artifact_path"], "docs/adr/0001-cli-decision.md")
        self.assertFalse((self.repo / value["artifact_path"]).exists())

    def test_malformed_metadata_and_ambiguous_index_fail_closed(self):
        root = self.repo / "docs/adr"
        root.mkdir(parents=True)
        malformed = root / "0001-broken.md"
        malformed.write_text('---\n{"schema":"doc-warden/artifact/v2",oops}\n---\n')
        with self.assertRaises(ValueError):
            list(artifact_paths(self.repo)) and self.draft()
        malformed.unlink()
        (root / "README.md").write_text("# Custom unrecognized index\n")
        with self.assertRaisesRegex(ValueError, "index_ambiguous"):
            self.draft()
