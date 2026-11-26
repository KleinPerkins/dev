import json
import socket
import time
import unittest
from unittest.mock import call, patch

from native_checkout_project import (
    NativeProjectBinding, NativeProjectReader, Refused, read_desktop_linked_project, read_desktop_project, selection_digest,
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


class NativeCatalogLinkedProject(unittest.TestCase):
    def setUp(self):
        self.reader = NativeProjectReader(None, None)
        self.reader.initialized = True
        self.project = {"project": {"id": LINKED_PROJECT, "roots": [{"path": PRIMARY}],
                                    "name": "Fixture", "updatedAt": 10}}
        self.thread = {"id": THREAD, "projectId": LINKED_PROJECT, "cwd": LINKED, "ephemeral": False}
        self.membership = {"data": [self.thread], "nextCursor": None}

    def read_linked(self, **options):
        return self.reader.read(LINKED_PROJECT, LINKED, **(
            {"deadline": 100, "thread_id": THREAD, "primary_checkout": PRIMARY} | options
        ))

    def test_primary_preserves_the_single_project_read(self):
        with patch.object(self.reader, "_call", return_value=self.project) as native:
            selected = self.reader.read(LINKED_PROJECT, PRIMARY, deadline=100)
        self.assertEqual(selected.selection_digest, selection_digest(LINKED_PROJECT, PRIMARY))
        native.assert_called_once_with("project/read", {"projectId": LINKED_PROJECT}, 100)

    def test_linked_checkout_checks_owner_root_and_two_independent_thread_reads(self):
        with patch.object(self.reader, "_call",
                          side_effect=[self.project, self.membership, {"thread": self.thread}]) as native:
            selected = self.read_linked()
        self.assertEqual(selected.selection_digest, selection_digest(LINKED_PROJECT, LINKED, THREAD))
        self.assertEqual(selected.thread_id, THREAD)
        self.assertEqual(native.call_args_list, [
            call("project/read", {"projectId": LINKED_PROJECT}, 100),
            call("thread/list", {"projectId": LINKED_PROJECT, "includedThreadIds": [THREAD], "limit": 2,
                                 "useStateDbOnly": True, "modelProviders": []}, 100),
            call("thread/read", {"threadId": THREAD, "includeTurns": False}, 100),
        ])

    def test_missing_owner_root_or_bad_thread_id_refuses_without_native_access(self):
        for options in ({"primary_checkout": None}, {"primary_checkout": LINKED},
                        {"primary_checkout": PRIMARY + "/../sample"}, {"thread_id": "a/b"}):
            with self.subTest(options=options), patch.object(self.reader, "_call") as native:
                with self.assertRaises(Refused):
                    self.read_linked(**options)
                native.assert_not_called()

    def test_changed_primary_refuses_before_thread_access(self):
        with patch.object(self.reader, "_call", return_value=self.project) as native:
            with self.assertRaisesRegex(Refused, "admitted primary project root"):
                self.read_linked(primary_checkout=PRIMARY + "-other")
            native.assert_called_once()

    def test_empty_duplicate_or_incomplete_membership_cannot_substitute_for_an_exact_match(self):
        for result in ({"data": [], "nextCursor": None}, {"data": [self.thread, self.thread], "nextCursor": None},
                       {"data": [self.thread], "nextCursor": "next-page"}, {"data": [self.thread]}):
            with self.subTest(result=result), patch.object(self.reader, "_call",
                                                           side_effect=[self.project, result]) as native:
                with self.assertRaisesRegex(Refused, "one current thread member"):
                    self.read_linked()
                self.assertEqual(native.call_count, 2)

    def test_thread_with_changed_project_directory_or_lifetime_refuses_on_either_read(self):
        changes = ({"projectId": "other-project"}, {"cwd": PRIMARY}, {"id": "other-thread"}, {"ephemeral": True})
        for changeset in changes:
            for bad in ("membership", "detail"):
                with self.subTest(changes=changeset, source=bad):
                    records = {"membership": self.thread, "detail": self.thread}
                    records[bad] = self.thread | changeset
                    with patch.object(self.reader, "_call", side_effect=[
                        self.project, {"data": [records["membership"]], "nextCursor": None},
                        {"thread": records["detail"]},
                    ]):
                        with self.assertRaises(Refused):
                            self.read_linked()

    def test_malformed_thread_results_refuse_through_the_wire_reader(self):
        for index in (1, 2):
            for malformed in (None, [], "not an object"):
                client, peer = socket.socketpair()
                with self.subTest(reply=index, malformed=malformed), client, peer:
                    replies = [self.project, self.membership, {"thread": self.thread}]
                    replies[index] = malformed
                    peer.sendall(b"".join((json.dumps({"id": i, "result": response}) + "\n").encode()
                                         for i, response in enumerate(replies, 1)))
                    reader = NativeProjectReader(client.fileno(), client.fileno())
                    reader.initialized = True
                    with self.assertRaisesRegex(Refused, "non-object result"):
                        reader.read(LINKED_PROJECT, LINKED, deadline=time.monotonic() + 2,
                                    thread_id=THREAD, primary_checkout=PRIMARY)
