import unittest

from native_checkout_project import (
    NativeProjectBinding, Refused, read_desktop_linked_project, read_desktop_project, selection_digest,
)

PROJECT = "01b2dd20-ef5c-7dc9-887b-125176aeba52"
CHECKOUT = "/fixture/personal/src/Fixture/repo"
ROW = {"hostId": "local", "projectKind": "local", "projectId": PROJECT,
       "isGitRepository": True, "path": CHECKOUT, "label": "Fixture"}


class DesktopProjection(unittest.TestCase):
    def observe(self, rows, *, schema=2, observed=300, path=CHECKOUT):
        return read_desktop_project({"schemaVersion": schema, "projects": rows}, PROJECT, path,
                                    observed_at=observed)

    def test_direct_local_git_project_supplies_exact_identity(self):
        result = self.observe([ROW])
        self.assertEqual((result.project_id, result.checkout, result.observed_at), (PROJECT, CHECKOUT, 300))
        self.assertEqual(result.selection_digest, selection_digest(PROJECT, CHECKOUT))
        self.assertEqual(result.selection_digest, "f2f12299e83b4ce6459f1db264c5e82431e5f8cfa6779d65ae66e3be18b4075e")
        self.assertIsNone(result.updated_at)

    def test_title_difference_and_absence_do_not_change_the_selection(self):
        before = self.observe([ROW])
        after = self.observe([ROW | {"label": "New title"}])
        no_title = self.observe([ROW | {"label": None}])
        self.assertEqual(before.selection_digest, after.selection_digest)
        self.assertEqual(before.selection_digest, no_title.selection_digest)
        self.assertEqual(after.title, "New title")
        self.assertIsNone(no_title.title)

    def test_remote_project_with_same_id_does_not_substitute_for_local(self):
        wrong_host = ROW | {"hostId": "remote", "projectKind": "remote"}
        with self.assertRaisesRegex(Refused, "did not identify one local project"):
            self.observe([wrong_host])

    def test_duplicate_matching_local_projects_are_ambiguous(self):
        with self.assertRaisesRegex(Refused, "did not identify one local project"):
            self.observe([ROW, ROW])

    def test_non_git_project_cannot_supply_checkout_authority(self):
        with self.assertRaisesRegex(Refused, "not a local Git project"):
            self.observe([ROW | {"isGitRepository": False}])

    def test_selected_checkout_cannot_be_inferred_from_a_parent_or_alias(self):
        with self.assertRaisesRegex(Refused, "no longer binds the selected checkout"):
            self.observe([ROW], path=CHECKOUT + "/linked")

    def test_lexical_traversal_is_refused(self):
        with self.assertRaisesRegex(Refused, "not a canonical absolute path"):
            self.observe([ROW], path=CHECKOUT + "/../elsewhere")

    def test_alternate_constructors_cannot_digest_an_invalid_project_id(self):
        for identifier in ("", True, "wrong/project", "?" * 2, "a" * 129):
            with self.subTest(identifier=identifier):
                with self.assertRaisesRegex(Refused, "explicit Codex project ID"):
                    selection_digest(identifier, CHECKOUT)
                with self.assertRaisesRegex(Refused, "explicit Codex project ID"):
                    NativeProjectBinding(identifier, CHECKOUT, "Fixture", None, 300)

    def test_alternate_constructors_refuse_noncanonical_checkout_strings(self):
        for location in ("relative/path", CHECKOUT + "/../elsewhere", CHECKOUT + "//alias", CHECKOUT + "/"):
            with self.subTest(location=location):
                with self.assertRaisesRegex(Refused, "not a canonical absolute path"):
                    selection_digest(PROJECT, location)
                with self.assertRaisesRegex(Refused, "not a canonical absolute path"):
                    NativeProjectBinding(PROJECT, location, "Fixture", None, 300)

    def test_unrecognized_schema_and_invalid_observation_time_refuse(self):
        for schema, stamp in ((3, 300), (2.0, 300), (2, True), (2, -1)):
            with self.subTest(schema=schema, stamp=stamp), self.assertRaisesRegex(Refused, "current catalog"):
                self.observe([ROW], schema=schema, observed=stamp)


LINKED_PROJECT = "fixture-project"
THREAD = "fixture-thread"
PRIMARY = "/fixture/dev/personal/src/FixtureOwner/sample"
LINKED = "/fixture/codex/worktrees/work/sample"
row = {"projectId": LINKED_PROJECT, "projectKind": "local", "label": "Fixture", "hostId": "local",
       "path": PRIMARY, "isGitRepository": True}
member = {"id": THREAD, "projectId": LINKED_PROJECT, "kind": "codex", "hostId": "local", "cwd": LINKED}
detail = {"id": THREAD, "kind": "codex", "hostId": "local", "cwd": LINKED}


class DesktopLinkedSelection(unittest.TestCase):
    def setUp(self):
        self.primary = read_desktop_project({"schemaVersion": 2, "projects": [row]}, LINKED_PROJECT, PRIMARY,
                                            observed_at=1000)

    def observe(self, *, checkout=LINKED, linked=member, thread=detail, observed_at=1002):
        return read_desktop_linked_project(self.primary, checkout, THREAD, linked, thread, observed_at=observed_at)

    def test_agreeing_native_thread_records_supply_linked_checkout_identity(self):
        selected = self.observe()
        self.assertEqual((selected.project_id, selected.checkout, selected.thread_id, selected.observed_at),
                         (LINKED_PROJECT, LINKED, THREAD, 1002))
        self.assertEqual(selected.selection_digest, selection_digest(LINKED_PROJECT, LINKED, THREAD))
        self.assertEqual(selected.selection_digest, "593dc829328eeb6be73550424dae2683935743733cc7cce3c943002e483481e2")
        self.assertNotEqual(selected.selection_digest, selection_digest(LINKED_PROJECT, LINKED))

    def test_thread_with_the_same_path_from_another_project_is_held(self):
        with self.assertRaisesRegex(Refused, "does not belong"):
            self.observe(linked=member | {"projectId": "other-project"})

    def test_missing_or_different_current_thread_identity_refuses(self):
        for metadata in (None, detail | {"id": "other-thread"}, detail | {"hostId": "remote"}):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(Refused, "same local thread"):
                self.observe(thread=metadata)

    def test_older_project_membership_cannot_override_a_changed_working_directory(self):
        with self.assertRaisesRegex(Refused, "selected linked checkout on both reads"):
            self.observe(thread=detail | {"cwd": LINKED + "-moved"})

    def test_project_root_cannot_be_represented_as_a_linked_checkout(self):
        with self.assertRaisesRegex(Refused, "separate registered primary"):
            self.observe(checkout=PRIMARY)

    def test_thread_read_needs_a_timestamp_from_the_same_read_window(self):
        with self.assertRaisesRegex(Refused, "current Codex thread"):
            self.observe(observed_at=999)

    def test_different_thread_changes_the_authority_digest_without_changing_paths(self):
        current = self.observe()
        other = read_desktop_linked_project(self.primary, LINKED, "next-thread", member | {"id": "next-thread"},
                                           detail | {"id": "next-thread"}, observed_at=1003)
        self.assertNotEqual(current.selection_digest, other.selection_digest)

    def test_invalid_optional_native_thread_id_refuses_before_a_digest(self):
        with self.assertRaisesRegex(Refused, "valid Codex thread ID"):
            selection_digest(LINKED_PROJECT, LINKED, {"unexpected": "structure"})
        with self.assertRaisesRegex(Refused, "valid Codex thread ID"):
            NativeProjectBinding(LINKED_PROJECT, LINKED, "Fixture", None, 300, "invalid/thread")
