"""Existing legacy ADR identities stay prose; new artifacts keep canonical names."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_warden.adrs import _index_delta, preview_adr_draft
from doc_warden.artifact_discovery import ADR_NAME, artifact_paths
from fixture_factory import FixtureFactory


LEGACY = "0002-v2.27-operating-decisions.md"
PROSE = b"# ADR 0002: Operating decisions\r\n\r\nAccepted 2026-07-14.  \r\nNo final newline"


class LegacyBasenameTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create("legacy-dotted-adr")
        self.addCleanup(self.fixture.cleanup)
        self.repo = self.fixture.repo.resolve()
        state = tempfile.TemporaryDirectory(prefix="legacy-adr-state-")
        self.addCleanup(state.cleanup)
        environment = patch.dict(os.environ, {"XDG_STATE_HOME": state.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.root = self.repo / "docs/adr"
        self.root.mkdir(parents=True)
        self.index = self.root / "README.md"
        self.target = self.root / LEGACY
        self.target.write_bytes(PROSE)

    def index_bytes(self, identity=None, *, width=3, newline="\n"):
        identity = identity or f"[0002]({LEGACY})"
        if width == 3:
            header = "| ADR | Status | One-line decision |"
            row = f"| {identity} | Accepted | Original \\| decision.  |"
        else:
            header = "| ADR | Title | Status | Date |"
            row = f"| {identity} | Original \\| decision.  | Accepted | 2026-07-14 |"
        return newline.join(["Prefix remains.  ", "", header,
                             "|" + "---|" * width, row, "", "Footer remains."]).encode()

    def draft(self):
        return preview_adr_draft({"title": "Next decision v2.28"}, repo=self.repo)

    def assert_refused_unchanged(self):
        before = self.index.read_bytes()
        with self.assertRaises(ValueError):
            self.draft()
        self.assertEqual(self.index.read_bytes(), before)
        self.assertFalse((self.root / "0003-next-decision-v2-28.md").exists())

    def test_public_preview_preserves_whole_legacy_row_and_file(self):
        for width in (3, 4):
            for newline in ("\n", "\r\n"):
                for identity in (f"[0002]({LEGACY})", f"[{LEGACY}]({LEGACY})", LEGACY):
                    with self.subTest(width=width, newline=newline, identity=identity):
                        original = self.index_bytes(identity, width=width, newline=newline)
                        self.index.write_bytes(original)
                        preview = self.draft()
                        self.assertEqual(preview.artifact_path, "docs/adr/0003-next-decision-v2-28.md")
                        actions = {a.path: a.content for a in preview.transaction.actions}
                        self.assertEqual(set(actions), {preview.artifact_path, "docs/adr/README.md"})
                        added = ("| [0003](0003-next-decision-v2-28.md) | Draft | Next decision v2.28 |" if width == 3 else
                                 "| [0003](0003-next-decision-v2-28.md) | Next decision v2.28 | Draft |  |")
                        expected = original.replace((newline + newline + "Footer remains.").encode(),
                                                    (newline + added + newline + newline + "Footer remains.").encode())
                        self.assertEqual(actions["docs/adr/README.md"], expected)
                        self.assertEqual(self.index.read_bytes(), original)
                        self.assertEqual(self.target.read_bytes(), PROSE)
                        self.assertFalse((self.repo / preview.artifact_path).exists())
                        self.assertEqual(list(artifact_paths(self.repo)), [])
                        self.assertIsNone(ADR_NAME.fullmatch(LEGACY))

    def test_invalid_targets_and_labels_refused_without_writes(self):
        targets = ("../" + LEGACY, "/" + LEGACY, "./" + LEGACY, "docs/" + LEGACY,
                   "https://host/" + LEGACY, LEGACY + "#anchor", LEGACY + "?query",
                   "%30" + LEGACY[1:], LEGACY.replace(".", "%2e", 1), LEGACY + " 'title'",
                   "0002-v2..27.md", "0002-v2.-27.md", "0002-v2--27.md", "0002-.v2.md",
                   "0002-v2-.md", "0002-v2_27.md", "0002-V2.27.md", "0002-v2.27.MD")
        identities = [f"[0002]({target})" for target in targets]
        identities += [f"[{label}]({LEGACY})" for label in ("0003", "2", "ADR 0002", "unrelated", "0002-other.md")]
        for identity in identities:
            with self.subTest(identity=identity):
                self.index.write_bytes(self.index_bytes(identity))
                self.assert_refused_unchanged()
                self.assertEqual(self.target.read_bytes(), PROSE)

    def test_existing_malformed_basename_refused(self):
        self.target.unlink()
        for name in ("0002-v2..27.md", "0002-v2.-27.md", "0002-v2--27.md", "0002-.v2.md",
                     "0002-v2-.md", "0002-v2_27.md", "0002-V2.27.md", "0002-v2.27.MD"):
            with self.subTest(name=name):
                target = self.root / name
                target.write_bytes(PROSE)
                self.index.write_bytes(self.index_bytes(f"[0002]({name})"))
                self.assert_refused_unchanged()
                self.assertEqual(target.read_bytes(), PROSE)
                target.unlink()

    def test_missing_legacy_target_refused(self):
        self.target.unlink()
        self.index.write_bytes(self.index_bytes())
        self.assert_refused_unchanged()

    def test_metadata_bearing_legacy_target_refused(self):
        for raw in (b'---\n{"schema":"doc-warden/artifact/v2",oops}\n---\n',
                    b'---\ninvalid metadata\n', b'# Prose\ndoc-warden/artifact/v2\n'):
            with self.subTest(raw=raw):
                self.target.write_bytes(raw)
                self.index.write_bytes(self.index_bytes())
                # Exercise the adapter directly as well as canonical discovery.
                with self.assertRaises(ValueError):
                    _index_delta(self.repo, "docs/adr/README.md", "0003-next.md", "Next", "Draft")
                self.assert_refused_unchanged()
                self.assertEqual(self.target.read_bytes(), raw)

    def test_duplicate_identity_and_number_refused(self):
        for other in (LEGACY, "0002-other.27.md", "0002-canonical.md"):
            with self.subTest(other=other):
                original = self.index_bytes()
                row = f"| [0002]({other}) | Accepted | Duplicate |\n".encode()
                self.index.write_bytes(original.replace(b"\n\nFooter", b"\n" + row + b"\nFooter"))
                if other != LEGACY:
                    (self.root / other).write_bytes(b"# Another legacy decision\n")
                self.assert_refused_unchanged()
                if other != LEGACY:
                    (self.root / other).unlink()

    def test_symlink_and_special_legacy_targets_refused(self):
        self.index.write_bytes(self.index_bytes())
        self.target.unlink()
        self.target.symlink_to(self.repo / "README.md")
        self.assert_refused_unchanged()
        self.target.unlink()
        os.mkfifo(self.target)
        self.assert_refused_unchanged()
        self.target.unlink()
        self.target.mkdir()
        self.assert_refused_unchanged()

    def test_incoming_new_filename_stays_strict_even_if_legacy_file_exists(self):
        self.index.write_bytes(self.index_bytes())
        incoming = "0003-new.v2.md"
        (self.root / incoming).write_bytes(b"# Legacy prose\n")
        with self.assertRaisesRegex(ValueError, "adr_index_ambiguous"):
            _index_delta(self.repo, "docs/adr/README.md", incoming, "New", "Draft")

    def test_canonical_existing_identity_behavior_unchanged(self):
        # Existing canonical index identities historically do not require a target.
        for identity in ("0001-old.md", "[0001](0001-old.md)", "[0001-old.md](0001-old.md)"):
            with self.subTest(identity=identity):
                original = self.index_bytes(identity)
                self.index.write_bytes(original)
                proposed = _index_delta(self.repo, "docs/adr/README.md", "0003-next.md", "Next", "Draft")
                self.assertIn(original.splitlines()[4], proposed)
                self.assertEqual(self.index.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
