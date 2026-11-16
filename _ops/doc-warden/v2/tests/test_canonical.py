import os
import tempfile
import unittest
from pathlib import Path

from doc_warden.canonical import (
    CanonicalError,
    atomic_write,
    canonical_json,
    contained_path,
    parse_artifact,
)


class CanonicalTests(unittest.TestCase):
    def test_canonical_json_is_order_independent_and_byte_stable(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))
        self.assertEqual(canonical_json({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')
        with self.assertRaises(CanonicalError):
            canonical_json({"float": 1.5})

    def test_front_matter_rejects_duplicate_and_noncanonical_values(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "artifact.md"
            path.write_text('---\n{"schema":"x","schema":"x"}\n---\nbody\n')
            with self.assertRaises(CanonicalError):
                parse_artifact(path)
            path.write_text('before\n---\n{"schema":"x"}\n---\nbody\n')
            with self.assertRaises(CanonicalError):
                parse_artifact(path)
            path.write_text('---\n {"schema":"x"}\n---\nbody\n')
            with self.assertRaises(CanonicalError):
                parse_artifact(path)

    def test_containment_rejects_traversal_symlink_swap_fifo_and_changed_root(self):
        with tempfile.TemporaryDirectory() as root_text, tempfile.TemporaryDirectory() as outside:
            root = Path(root_text)
            with self.assertRaises(CanonicalError):
                contained_path(root, "../escape")
            (root / "link").symlink_to(outside)
            with self.assertRaises(CanonicalError):
                contained_path(root, "link/file")
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(CanonicalError):
                contained_path(root, "fifo")

    def test_interrupted_atomic_write_leaves_preimage_or_complete_postimage(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            atomic_write(root, "state/value.json", b"before\n")
            atomic_write(root, "state/value.json", b"after\n")
            self.assertEqual((root / "state/value.json").read_bytes(), b"after\n")
            self.assertEqual(list((root / "state").glob(".value.json.*")), [])


if __name__ == "__main__":
    unittest.main()
