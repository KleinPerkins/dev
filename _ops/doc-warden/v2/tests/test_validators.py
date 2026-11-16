import copy
import re
import json
import hashlib
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from doc_warden.canonical import canonical_json, parse_json_object
from doc_warden.validators import (
    SCHEMA_ROOT,
    parse_validated_artifact,
    validate_egress,
    validate_record,
)


ROOT = Path(__file__).resolve().parents[4]



def synthetic_acceptance(milestone):
    """Schema fixtures are not historical acceptance or runtime evidence."""
    schema=json.loads((ROOT/f"_ops/doc-warden/schemas/v2/{milestone}-acceptance.schema.json").read_bytes())
    def sample(node, sequence=0):
        if "const" in node:return copy.deepcopy(node["const"])
        if "enum" in node:return copy.deepcopy(node["enum"][sequence % len(node["enum"])])
        if "anyOf" in node:return sample(node["anyOf"][0],sequence)
        kind=node.get("type")
        if isinstance(kind,list):kind=next(k for k in kind if k!='null')
        if kind=="object":return {k:sample(node['properties'][k], sequence) for k in node.get('required',[])}
        if kind=="array":return [sample(node['items'],i) for i in range(node.get('minItems',0))]
        if kind=="boolean":return False
        if kind in ('integer','number'):return max(1,node.get('minimum',1))+sequence
        if kind=="null":return None
        if kind=="string":
            choices=[f"synthetic-{sequence}",f'{sequence+1:064x}',f'{sequence+1:040x}',f'{sequence+1:08x}',f'sha256:{sequence+1:064x}','10000000-0000-4000-8000-000000000000','2026-01-01T00:00:00Z','2026-01-01T00:00:00+00:00',f'AC-{sequence+1:03d}','Fixture/repository','https://github.com/Fixture/repository/pull/1',f'test_fixture.Case.test_case_{sequence}']
            for value in choices:
                if len(value)>=node.get('minLength',0) and re.search(node.get('pattern','.*'),value):return value
        raise AssertionError(f"unhandled synthetic schema node: {node}")
    return schema,sample(schema)

class ValidatorTests(unittest.TestCase):
    def test_all_schema_documents_are_json_and_closed(self):
        paths = list(SCHEMA_ROOT.glob("*.schema.json"))
        self.assertGreaterEqual(len(paths), 16)
        for path in paths:
            value = json.loads(path.read_text())
            self.assertEqual(value["type"], "object", path.name)
            self.assertFalse(value["additionalProperties"], path.name)

    def test_closed_schema_rejects_unknown_field(self):
        value = {
            "schema": "doc-warden/reconciliation/v2",
            "repository_key": str(uuid.uuid4()),
            "source_revision": "no-head",
            "classification": "conformant",
            "code": "ok",
            "artifact_id": None,
            "evidence": [],
            "raw_log": "not allowed",
        }
        self.assertTrue(any(i.code == "unknown_field" for i in validate_record("reconciliation", value)))

    def test_artifact_front_matter_is_schema_validated(self):
        key = str(uuid.uuid4())
        artifact_id = f"PRD-{key}-{uuid.uuid4()}"
        metadata = {
            "schema": "doc-warden/artifact/v2",
            "id": artifact_id,
            "type": "prd",
            "version": 1,
            "repository_key": key,
            "github_repository_id": None,
            "authority": "semantic",
            "mutability": "frozen_after_approval",
            "lifecycle": "draft",
            "supersedes": None,
            "relations": [],
            "provenance": [],
            "approval": None,
        }
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "prd.md"
            path.write_bytes(b"---\n" + canonical_json(metadata) + b"---\n# PRD\n")
            self.assertEqual(parse_validated_artifact(path)["id"], artifact_id)
            metadata["relations"] = [{"relation": "invented"}]
            path.write_bytes(b"---\n" + canonical_json(metadata) + b"---\n# PRD\n")
            with self.assertRaises(ValueError):
                parse_validated_artifact(path)

    def test_each_persisted_projection_rejects_unknown_or_sensitive_fields(self):
        base = {
            "schema": "doc-warden/external-asset/v2",
            "provider": "figma",
            "canonical_url": "https://figma.com/file/example",
            "immutable_revision": "revision-1",
            "source_repository_key": str(uuid.uuid4()),
            "source_github_repository_id": None,
            "source_commit": None,
            "export_sha256": "a" * 64,
            "captured_at": "2026-08-28T00:00:00Z",
            "owner": "owner-id",
            "license": "internal-use",
            "egress_projection": "external_asset_pointer/v1",
        }
        validate_egress("external_asset", base)
        for field in ("secret", "transcript", "raw_log", "unknown"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_egress("external_asset", {**base, field: "value"})
        with self.assertRaisesRegex(ValueError, "save_game_egress_not_activated"):
            validate_egress("save_game", {})
        with self.assertRaises(ValueError):
            validate_egress(
                "canvas",
                {
                    "schema": "doc-warden/canvas/v1",
                    "repository_key": str(uuid.uuid4()),
                    "source_revision": "a" * 40,
                    "refreshed_at": "2026-08-28T00:00:00Z",
                    "roadmap": [{"id": "ROAD-1", "secret": "nested"}],
                    "state": {},
                    "findings": [],
                },
            )
        with self.assertRaises(ValueError):
            validate_egress(
                "hook",
                {
                    "schema": "doc-warden/hook/v1",
                    "event": "check",
                    "status": "blocked",
                    "code": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
                    "repository_key": str(uuid.uuid4()),
                    "source_revision": "a" * 40,
                },
            )


    def test_digest_entropy_exemption_requires_digest_semantics(self):
        digest = "sha256:" + hashlib.sha256(b"receipt").hexdigest()
        event = {
            "schema": "doc-warden/operation-event/v2",
            "event_id": str(uuid.uuid4()),
            "operation_id": str(uuid.uuid4()),
            "transition": "creation_snapshot",
            "action_digest": digest,
            "source_revision": "a" * 40,
            "prior_event_digest": None,
            "outcome": "applied",
            "details": {"postimages": {"_ops/doc-warden/state/v2/value.json": digest}},
        }
        validate_egress("event", event)
        event["details"] = {"note": digest}
        with self.assertRaisesRegex(ValueError, "unbounded or sensitive egress string refused"):
            validate_egress("event", event)

    def test_m1_acceptance_receipt_is_canonical_and_closed_schema_valid(self):
        # Historical receipt-instance assertions live with private preservation.
        # Preserve closed schema validation using explicitly synthetic values.
        schema, record = synthetic_acceptance("m1")
        raw = canonical_json(record)
        self.assertEqual(parse_json_object(raw), record)
        self.assertEqual([], validate_record("m1-acceptance", record))
        for key in schema['required']:
            changed=copy.deepcopy(record);del changed[key]
            with self.subTest(missing=key):self.assertTrue(validate_record("m1-acceptance",changed))
        changed=copy.deepcopy(record);changed['unreviewed_extra']=True
        self.assertTrue(validate_record("m1-acceptance",changed))
        for key,node in schema['properties'].items():
            if 'const' in node and key in record:
                changed=copy.deepcopy(record);changed[key]={'invalid':'synthetic mutation'}
                with self.subTest(constant=key):self.assertTrue(validate_record("m1-acceptance",changed))

    def test_m2_acceptance_receipt_is_canonical_closed_and_evidence_bound(self):
        # Historical receipt-instance assertions live with private preservation.
        # Preserve closed schema validation using explicitly synthetic values.
        schema, record = synthetic_acceptance("m2")
        raw = canonical_json(record)
        self.assertEqual(parse_json_object(raw), record)
        self.assertEqual([], validate_record("m2-acceptance", record))
        for key in schema['required']:
            changed=copy.deepcopy(record);del changed[key]
            with self.subTest(missing=key):self.assertTrue(validate_record("m2-acceptance",changed))
        changed=copy.deepcopy(record);changed['unreviewed_extra']=True
        self.assertTrue(validate_record("m2-acceptance",changed))
        for key,node in schema['properties'].items():
            if 'const' in node and key in record:
                changed=copy.deepcopy(record);changed[key]={'invalid':'synthetic mutation'}
                with self.subTest(constant=key):self.assertTrue(validate_record("m2-acceptance",changed))

    def test_m3_acceptance_receipt_is_canonical_closed_and_evidence_bound(self):
        # Historical receipt-instance assertions live with private preservation.
        # Preserve closed schema validation using explicitly synthetic values.
        schema, record = synthetic_acceptance("m3")
        raw = canonical_json(record)
        self.assertEqual(parse_json_object(raw), record)
        self.assertEqual([], validate_record("m3-acceptance", record))
        for key in schema['required']:
            changed=copy.deepcopy(record);del changed[key]
            with self.subTest(missing=key):self.assertTrue(validate_record("m3-acceptance",changed))
        changed=copy.deepcopy(record);changed['unreviewed_extra']=True
        self.assertTrue(validate_record("m3-acceptance",changed))
        for key,node in schema['properties'].items():
            if 'const' in node and key in record:
                changed=copy.deepcopy(record);changed[key]={'invalid':'synthetic mutation'}
                with self.subTest(constant=key):self.assertTrue(validate_record("m3-acceptance",changed))

    def test_array_maxItems_is_enforced(self):
        _schema, record = synthetic_acceptance("m3")
        # blockers has maxItems: 0; any item must be rejected
        tampered = json.loads(json.dumps(record))
        tampered["criteria_disposition"]["blockers"] = ["AC-999"]
        issues = validate_record("m3-acceptance", tampered)
        self.assertTrue(any(i.code == "maxItems" for i in issues))
        self.assertTrue(
            any(
                "criteria_disposition/blockers" in i.path
                for i in issues
                if i.code == "maxItems"
            )
        )


if __name__ == "__main__":
    unittest.main()
