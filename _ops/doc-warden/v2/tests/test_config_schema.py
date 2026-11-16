import json
import unittest
import uuid

from doc_warden.transactions import MutationAction, MutationRequest, preview_transaction
from doc_warden.validators import read_repository_config, validate_record
from fixture_factory import FixtureFactory


class ConfigSchemaTests(unittest.TestCase):
    def test_repository_key_and_artifact_uuid_survive_remote_id_observation(self):
        fixture = FixtureFactory.create()
        try:
            before = read_repository_config(fixture.repo)
            value = dict(before)
            value["github_repository_id"] = 123456789
            self.assertEqual(validate_record("doc-warden-config", value), [])
            self.assertEqual(value["repository_key"], before["repository_key"])
            artifact_uuid = uuid.uuid4()
            before_id = f"PRD-{before['repository_key']}-{artifact_uuid}"
            after_id = f"PRD-{value['repository_key']}-{artifact_uuid}"
            self.assertEqual(before_id, after_id)
        finally:
            fixture.cleanup()

    def test_schema_invalid_repository_config_is_reported_without_writing(self):
        fixture = FixtureFactory.create()
        try:
            path = fixture.repo / ".planning/doc-warden.json"
            path.write_text(json.dumps({"repository_key": "invalid"}))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "repository_key_unreadable"):
                preview_transaction(
                    MutationRequest(
                        repo=fixture.repo,
                        repository_key=str(uuid.uuid4()),
                        transition="draft_update",
                        actions=(MutationAction(".planning/new", b"value"),),
                        bindings={},
                    )
                )
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((fixture.repo / ".planning/new").exists())
        finally:
            fixture.cleanup()

    def test_config_unknown_fields_are_refused(self):
        fixture = FixtureFactory.create()
        try:
            value = read_repository_config(fixture.repo)
            value["surprise"] = True
            issues = validate_record("doc-warden-config", value)
            self.assertTrue(any(issue.code == "unknown_field" for issue in issues))
        finally:
            fixture.cleanup()

    def test_persisted_repository_key_mismatch_is_refused(self):
        fixture = FixtureFactory.create()
        try:
            with self.assertRaisesRegex(ValueError, "repository_key_mismatch"):
                preview_transaction(
                    MutationRequest(
                        repo=fixture.repo,
                        repository_key=str(uuid.uuid4()),
                        transition="draft_update",
                        actions=(MutationAction(".planning/new", b"value"),),
                        bindings={},
                    )
                )
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
