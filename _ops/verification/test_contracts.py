from __future__ import annotations

import base64
import copy
import json
import unittest
from pathlib import Path

from _ops.verification import contracts


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "wire-goldens-v1.json"
REPO_ROOT = ROOT.parent.parent

M0_T01_PR_EVIDENCE = {
    "head_commit_sha": "d55f26bd47b0b148d8263c5db935d380b45448bd",
    "merge_commit_sha": "647f6081bdbedd10df039264de0ea193d3422672",
    "pull_request": "pr/335",
}
M0_T02_COMMAND = {
    "argv": ["python3", "-m", "unittest", "-v", "verification.test_contracts"],
    "cwd_b64": "X29wcw==",
    "environment_allowlist": ["PYTHONDONTWRITEBYTECODE", "PYTHONPATH"],
}
PYTHON_INVENTORY_PATHS = (
    "scripts/verify.py",
    "_ops/baseline/profiles/pr-automation/v3/profile.py",
    "_ops/baseline/profiles/pr-automation/v3/test.sh",
    "_ops/checks/doc-warden-verify.sh",
    "_ops/checks/verify-operating-model.sh",
    "_ops/checks/worktree-verify.sh",
)
PYTHON_GOVERNANCE_PATHS = ("OPERATING-MANUAL.md", "_ops/POLICY.md")
# This ledger is frozen predecessor provenance. Its accepted evidence refers to
# predecessor bytes, not today's successor files or an active controller lock.
HISTORICAL_LEDGER_SHA256 = "sha256:5a72bfb320fe6eb71f0d0b9b5088e7745abce4f65c20190c0a64af768798240f"
HISTORICAL_INVENTORY_EVIDENCE = "sha256:0e5b612039ff1b8692d1aacf843ff85c6da324b7e39205bc069781565654f6a1"
HISTORICAL_GOVERNANCE_EVIDENCE = "sha256:80902ae31c7c6f31ea99126202692e18197c73d346c3e8a3ff48dcd6e4ee3bb1"


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.goldens = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.manifest = cls.goldens["manifest"]["valid"]["value"]
        cls.invalid_manifest = cls.goldens["manifest"]["invalid"]["value"]
        cls.receipts = {
            name: item["value"] for name, item in cls.goldens["receipts"].items()
        }
        cls.receipt_store = {
            receipt["receipt_id"]: receipt for receipt in cls.receipts.values()
        }
        cls.manifests = {cls.manifest["manifest_id"]: cls.manifest}
        cls.ledger = cls.goldens["ledger"]["value"]
        cls.schema_paths = {
            "manifest": ROOT / "verification-manifest.schema.json",
            "receipt": ROOT / "verification-receipt.schema.json",
            "ledger": ROOT / "verification-rollout-ledger.schema.json",
        }
        cls.schemas = {
            key: contracts.parse_json_document(path.read_bytes())
            for key, path in cls.schema_paths.items()
        }
        cls.schema_digests = cls.goldens["schema_digests"]

    def assertRejected(self, callable_, *args, **kwargs) -> None:
        with self.assertRaises(contracts.ContractError):
            callable_(*args, **kwargs)

    @staticmethod
    def reidentify(value: dict, field: str) -> dict:
        result = copy.deepcopy(value)
        result[field] = ""
        result[field] = str(contracts.derive_identity(result, field))
        return result

    @classmethod
    def rehash_chain(cls, ledger: dict) -> dict:
        result = copy.deepcopy(ledger)
        replacements: dict[str, str] = {}

        def replace(value):
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [replace(item) for item in value]
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            return value

        previous = None
        for index, event in enumerate(result["events"]):
            old_id = event["event_id"]
            event = replace(event)
            event["previous_event_id"] = previous
            event = cls.reidentify(event, "event_id")
            result["events"][index] = event
            replacements[old_id] = event["event_id"]
            previous = event["event_id"]
        return result

    def test_fixture_contract_and_schema_digests_are_pinned(self) -> None:
        self.assertEqual(self.goldens["schema"], "dev-verification-wire-goldens")
        self.assertEqual(self.goldens["schema_version"], 1)
        for key, path in self.schema_paths.items():
            self.assertEqual(
                str(contracts.schema_digest(path.read_bytes())),
                self.schema_digests[key],
            )
            contracts.validate_schema_document(self.schemas[key])

    def test_all_contract_object_schemas_are_closed(self) -> None:
        for schema in self.schemas.values():
            pending = [schema]
            while pending:
                value = pending.pop()
                if isinstance(value, list):
                    pending.extend(value)
                elif isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertIs(
                            value.get("additionalProperties"),
                            False,
                            msg=f"open object schema: {value}",
                        )
                    pending.extend(value.values())

    def test_manifest_golden_has_exact_bytes_and_identity(self) -> None:
        item = self.goldens["manifest"]["valid"]
        expected = base64.b64decode(item["canonical_b64"], validate=True)
        self.assertEqual(contracts.canonical_json(item["value"]), expected)
        self.assertEqual(contracts.validate_canonical_input(expected), item["value"])
        self.assertEqual(
            str(contracts.derive_identity(item["value"], "manifest_id")),
            item["manifest_id"],
        )
        contracts.validate_against_schema(item["value"], self.schemas["manifest"])
        contracts.validate_manifest(item["value"])
        self.assertEqual(
            item["value"]["semantic_selectors"][0]["baseline_input_rule_ids"],
            ["config.digest", "config.refs"],
        )
        self.assertEqual(
            item["value"]["activation"]["full_profile"], "preserved_aggregate"
        )

    def test_invalid_manifest_golden_is_exact_and_rejected(self) -> None:
        item = self.goldens["manifest"]["invalid"]
        expected = base64.b64decode(item["canonical_b64"], validate=True)
        self.assertEqual(contracts.canonical_json(item["value"]), expected)
        self.assertRejected(contracts.validate_manifest, item["value"])

    def test_receipt_goldens_have_exact_bytes_ids_and_source_variants(self) -> None:
        observed_kinds = set()
        for name, item in self.goldens["receipts"].items():
            value = item["value"]
            expected = base64.b64decode(item["canonical_b64"], validate=True)
            self.assertEqual(contracts.canonical_json(value), expected, name)
            self.assertEqual(contracts.validate_canonical_input(expected), value, name)
            self.assertEqual(
                str(contracts.derive_identity(value, "receipt_id")),
                item["receipt_id"],
                name,
            )
            contracts.validate_against_schema(value, self.schemas["receipt"])
            contracts.validate_receipt(
                value, manifests=self.manifests, receipt_store=self.receipt_store
            )
            observed_kinds.add(value["source"]["source_kind"])
        self.assertEqual(observed_kinds, {"staged_index", "pull_request", "commit"})
        self.assertEqual(self.receipts["pr_shadow"]["mode"], "shadow")
        self.assertEqual(self.receipts["enforce"]["mode"], "enforce")
        self.assertEqual(self.receipts["enforce_fallback"]["effective_mode"], "full")

    def test_every_event_variant_and_canonical_identity_is_pinned(self) -> None:
        event_types = set()
        for name, item in self.goldens["events"].items():
            value = item["value"]
            expected = base64.b64decode(item["canonical_b64"], validate=True)
            self.assertEqual(contracts.canonical_json(value), expected, name)
            self.assertEqual(contracts.validate_canonical_input(expected), value, name)
            self.assertEqual(
                str(contracts.derive_identity(value, "event_id")),
                item["event_id"],
                name,
            )
            event_types.add(value["event_type"])
        self.assertEqual(event_types, set(contracts.EVENT_TYPES))

    def test_full_ledger_golden_schema_chain_and_consumer_bindings(self) -> None:
        expected = base64.b64decode(
            self.goldens["ledger"]["canonical_b64"], validate=True
        )
        self.assertEqual(contracts.canonical_json(self.ledger), expected)
        contracts.validate_against_schema(self.ledger, self.schemas["ledger"])
        contracts.validate_ledger(
            self.ledger,
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )

    def test_checked_in_ledger_is_canonical_and_preserves_genesis(self) -> None:
        raw = (ROOT / "verification-rollout-ledger.json").read_bytes()
        checked_in = contracts.validate_canonical_input(raw)
        self.assertEqual(len(checked_in["events"]), 3)
        self.assertEqual(
            checked_in["events"][0],
            self.goldens["events"]["authority_genesis"]["value"],
        )
        contracts.validate_against_schema(checked_in, self.schemas["ledger"])
        contracts.validate_ledger(
            checked_in, schema_digests=self.schema_digests
        )
        base = copy.deepcopy(checked_in)
        base["events"] = base["events"][:1]
        base_bytes = contracts.canonical_json(base)
        contracts.validate_anchored_append(
            base_bytes,
            raw,
            str(contracts.sha256_id(base_bytes)),
            base["events"][0]["event_id"],
            schema_digests=self.schema_digests,
        )

        pr_evidence_id = str(
            contracts.sha256_id(contracts.canonical_json(M0_T01_PR_EVIDENCE))
        )
        self.assertEqual(str(contracts.sha256_id(raw)), HISTORICAL_LEDGER_SHA256)
        inventory_evidence_id = HISTORICAL_INVENTORY_EVIDENCE
        governance_evidence_id = HISTORICAL_GOVERNANCE_EVIDENCE
        m0_t02_command_digest = str(
            contracts.command_digest(
                M0_T02_COMMAND["argv"],
                M0_T02_COMMAND["cwd_b64"],
                M0_T02_COMMAND["environment_allowlist"],
            )
        )
        self.assertEqual(
            checked_in["events"][1]["provenance"],
            {
                "kind": "pull_request",
                "reference": "pr/335",
                "reference_sha256": pr_evidence_id,
            },
        )
        self.assertEqual(
            checked_in["events"][1]["payload"],
            {
                "bundle_scope": "M0-T01",
                "criteria": [
                    {
                        "ac_id": f"AC-{number:03d}",
                        "evidence_ids": [pr_evidence_id],
                        "status": "passed",
                    }
                    for number in range(1, 5)
                ],
                "milestone": "M0",
            },
        )
        self.assertEqual(
            checked_in["events"][2]["provenance"],
            {
                "kind": "local_command",
                "reference": m0_t02_command_digest,
                "reference_sha256": m0_t02_command_digest,
            },
        )
        self.assertEqual(
            checked_in["events"][2]["payload"],
            {
                "bundle_scope": "M0-T02",
                "criteria": [
                    {
                        "ac_id": "AC-005",
                        "evidence_ids": [inventory_evidence_id],
                        "status": "passed",
                    },
                    {
                        "ac_id": "AC-006",
                        "evidence_ids": [governance_evidence_id],
                        "status": "passed",
                    },
                ],
                "milestone": "M0",
            },
        )
        self.assertEqual(
            set(contracts.reduce_logical_credits(checked_in["events"])),
            {("acceptance", f"AC-{number:03d}") for number in range(1, 7)},
        )

    def test_python_governance_matches_current_verification(self) -> None:
        inventory = {
            path: (REPO_ROOT / path).read_text(encoding="utf-8")
            for path in PYTHON_INVENTORY_PATHS
        }
        self.assertIn("python3", inventory["_ops/checks/doc-warden-verify.sh"])
        self.assertIn("unittest", inventory["_ops/checks/doc-warden-verify.sh"])
        self.assertIn("python3", inventory["_ops/checks/worktree-verify.sh"])
        self.assertIn("python3", inventory["_ops/checks/verify-operating-model.sh"])
        self.assertIn('$ROOT/scripts/verify.py', inventory["_ops/checks/verify-operating-model.sh"])
        self.assertIn(
            "python3", inventory["_ops/baseline/profiles/pr-automation/v3/test.sh"]
        )
        self.assertIn(
            "unittest", inventory["_ops/baseline/profiles/pr-automation/v3/test.sh"]
        )
        self.assertIn(
            "python3", inventory["_ops/baseline/profiles/pr-automation/v3/profile.py"]
        )
        self.assertIn("unittest", inventory["scripts/verify.py"])
        workflow = json.loads((REPO_ROOT / ".github/workflows/ci.yml").read_text())
        source_contract = json.loads((REPO_ROOT / ".github/ci-contract.json").read_text())
        for shard in source_contract["shards"]:
            steps = workflow["jobs"][shard]["steps"]
            setup = [s for s in steps if s.get("uses", "").startswith("actions/setup-python@")]
            if shard == "interop-portability":
                self.assertEqual(setup, [])
                runtime = [s for s in steps if s.get("name") == "Install pinned Darwin Python 3.12.12"]
                self.assertEqual(len(runtime), 1)
                self.assertIn("cpython-3.12.12%2B20260127-aarch64-apple-darwin-install_only_stripped.tar.gz", runtime[0]["run"])
                self.assertIn("ce209e54ac17f731b5f257ff419b55a445fcf65035e303bbbc5708d67dfe59d8", runtime[0]["run"])
                self.assertIn("sys.version_info[:3] == (3, 12, 12)", runtime[0]["run"])
            else:
                self.assertEqual(len(setup), 1)
                self.assertEqual(setup[0]["with"]["python-version"], "3.12.12")
            self.assertTrue(any("--require-hashes" in s.get("run", "") for s in steps))
        self.assertFalse((REPO_ROOT / ".github/pr-automation.lock.json").exists())
        for path in PYTHON_GOVERNANCE_PATHS:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("dependency-light local gate", text, path)
            self.assertIn("docs/github-delivery.md", text, path)
        record = json.loads((REPO_ROOT / "_ops/policy/dev-successor.json").read_text())
        historical = {row["path"]: row["sha256"] for row in record["historical_provenance"]}
        self.assertEqual(historical["_ops/verification/verification-rollout-ledger.json"],
                         HISTORICAL_LEDGER_SHA256.removeprefix("sha256:"))
        self.assertFalse(record["runtime_authority"])

    def test_artifact_digests_decisions_and_interpretation_preimages(self) -> None:
        genesis = self.ledger["events"][0]
        artifacts = {
            item["path"]: (item["sha256"], item["byte_length"])
            for item in genesis["payload"]["artifact_digests"]
        }
        self.assertEqual(
            artifacts,
            {
                "_ops/adr/0011-manifest-driven-verification-selector.md": (
                    "sha256:76d6039acb5eb604de010a090f2e5128e19874296bf838423237ddf835c08883",
                    18500,
                ),
                "_ops/plans/manifest-driven-verification-execution-v1.md": (
                    "sha256:8454a1bbfe2c59cb9b5f59dda836514c315cf92154034f25f70f46082a602850",
                    67647,
                ),
                "_ops/plans/manifest-driven-verification-target-design-v1.md": (
                    "sha256:cc3e3470fe759729716969da3690d95179b643c611f43051a5f9e7e85debf2ed",
                    73217,
                ),
            },
        )
        self.assertEqual(
            genesis["payload"]["d2_d5_decisions"],
            [
                {"id": f"D{number}", "disposition": "accept", "replacement_sha256": None}
                for number in range(2, 6)
            ],
        )
        for item in self.goldens["interpretation_preimages"].values():
            canonical = base64.b64decode(item["canonical_b64"], validate=True)
            self.assertEqual(contracts.canonical_json(item["value"]), canonical)
            self.assertEqual(str(contracts.sha256_id(canonical)), item["digest"])

    def test_command_and_candidate_tree_digests_are_exact(self) -> None:
        command = self.goldens["command"]
        self.assertEqual(
            contracts.canonical_json(command["value"]),
            base64.b64decode(command["canonical_b64"], validate=True),
        )
        self.assertEqual(
            str(
                contracts.command_digest(
                    command["value"]["argv"],
                    command["value"]["cwd_b64"],
                    command["value"]["environment_allowlist"],
                )
            ),
            command["digest"],
        )
        candidate = self.goldens["candidate_tree"]
        self.assertEqual(
            contracts.canonical_json(candidate["entries"]),
            base64.b64decode(candidate["canonical_b64"], validate=True),
        )
        self.assertEqual(
            str(contracts.candidate_tree_digest(candidate["entries"])),
            candidate["digest"],
        )

    def test_unicode_and_non_utf8_paths_round_trip(self) -> None:
        unicode_value = self.goldens["paths"]["unicode"]
        unicode_path = contracts.PathValue.from_object(unicode_value)
        self.assertEqual(unicode_path.to_object(), unicode_value)
        non_utf8_value = self.goldens["paths"]["non_utf8"]
        non_utf8_path = contracts.PathValue.from_object(non_utf8_value)
        self.assertEqual(non_utf8_path.to_object(), non_utf8_value)
        self.assertIsNone(non_utf8_path.path_utf8)

    def test_strict_json_pointer_classification_golden(self) -> None:
        golden = self.goldens["json_pointer"]
        old = base64.b64decode(golden["old_b64"], validate=True)
        new = base64.b64decode(golden["new_b64"], validate=True)
        self.assertEqual(
            contracts.classify_json_pointer_changes(old, new), golden["changed"]
        )
        self.assertEqual(golden["changed"], ["", "/arr", "/refs", "/refs/a~1b"])
        self.assertTrue(
            contracts.pointer_rule_matches("/refs", "descendant_prefix", "/refs/a~1b")
        )
        self.assertFalse(
            contracts.pointer_rule_matches("/refs", "exact", "/refs/a~1b")
        )
        self.assertEqual(
            contracts.classify_json_pointer_changes(b'{"n":1e1}', b'{"n":10.0}'),
            [],
        )
        self.assertEqual(
            contracts.classify_json_pointer_changes(b'{"a":[1,2]}', b'{"a":[1,3]}'),
            ["", "/a"],
        )
        for pointer in ("refs", "/bad~", "/bad~2"):
            self.assertRejected(contracts.validate_json_pointer, pointer)
        self.assertRejected(
            contracts.classify_json_pointer_changes, b'{"x":1,"x":2}', b'{}'
        )
        self.assertRejected(
            contracts.classify_json_pointer_changes, b"\xef\xbb\xbf{}", b"{}"
        )

    def test_canonical_input_rejects_lexical_and_numeric_variants(self) -> None:
        accepted = '{"a":"\u007f雪","b":0,"c":"\\u0001\\n"}'.encode("utf-8")
        self.assertEqual(contracts.validate_canonical_input(accepted)["b"], 0)
        rejected = [
            b'{"a":1,"a":2}',
            b'{"n":1.0}',
            b'{"n":1e0}',
            b'{"n":NaN}',
            b'{"n":Infinity}',
            b'{"n":9223372036854775808}',
            b'{"n":-9223372036854775809}',
            b'{"n":-0}',
            b'{"b":1,"a":2}',
            b'{"a" :1}',
            b'{"a": 1}',
            b'{"a":1}\n',
            b'{"s":"\\/"}',
            b'{"s":"\\u002f"}',
            b'{"s":"\\u000A"}',
            b'{"s":"\\u000a"}',
            b'{"s":"\\ud800"}',
            b"\xef\xbb\xbf{}",
            b'"\xff"',
        ]
        for raw in rejected:
            with self.subTest(raw=raw):
                self.assertRejected(contracts.validate_canonical_input, raw)
        self.assertRejected(contracts.canonical_json, {"n": 1.0})
        self.assertRejected(contracts.canonical_json, {"n": 2**63})
        self.assertRejected(contracts.canonical_json, {"s": "\ud800"})

    def test_closed_objects_and_unknown_enums_are_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["unknown"] = True
        self.assertRejected(contracts.validate_manifest, manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["obligations"][0]["network"] = "sometimes"
        manifest = self.reidentify(manifest, "manifest_id")
        self.assertRejected(contracts.validate_manifest, manifest)
        receipt = copy.deepcopy(self.receipts["enforce"])
        receipt["mode"] = "unknown"
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(contracts.validate_receipt, receipt)
        ledger = copy.deepcopy(self.ledger)
        ledger["events"][1]["event_type"] = "unknown"
        ledger = self.rehash_chain(ledger)
        self.assertRejected(contracts.validate_ledger, ledger)

    def test_base64_and_path_refusals(self) -> None:
        bad_values = [
            {"path_b64": "%%%"},
            {"path_b64": ""},
            {"path_b64": base64.b64encode(b"/absolute").decode()},
            {"path_b64": base64.b64encode(b"a//b").decode()},
            {"path_b64": base64.b64encode(b"a/./b").decode()},
            {"path_b64": base64.b64encode(b"a/../b").decode()},
            {"path_b64": base64.b64encode(b"a/").decode()},
            {"path_b64": base64.b64encode(b"a\x00b").decode()},
            {
                "path_b64": base64.b64encode(b"valid").decode(),
                "path_utf8": "different",
            },
            {
                "path_b64": base64.b64encode(b"valid").decode(),
                "path_utf8": None,
            },
            {
                "path_b64": base64.b64encode(b"\xff").decode(),
                "path_utf8": "display",
            },
        ]
        for value in bad_values:
            with self.subTest(value=value):
                self.assertRejected(contracts.PathValue.from_object, value)
        self.assertRejected(
            contracts.candidate_tree_digest,
            list(reversed(self.goldens["candidate_tree"]["entries"])),
        )

    def test_baseline_input_rule_id_failures(self) -> None:
        mutations = []
        for ids in (
            [],
            ["config.digest", "config.digest"],
            ["config.refs", "config.digest"],
            ["config.digest", "unknown.rule"],
        ):
            manifest = copy.deepcopy(self.manifest)
            manifest["semantic_selectors"][0]["baseline_input_rule_ids"] = ids
            mutations.append(self.reidentify(manifest, "manifest_id"))
        for manifest in mutations:
            self.assertRejected(contracts.validate_manifest, manifest)

    def test_identity_mismatches_are_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["manifest_version"] += 1
        self.assertRejected(contracts.validate_manifest, manifest)
        receipt = copy.deepcopy(self.receipts["enforce"])
        receipt["created_at"] = "2026-09-02T17:52:00Z"
        self.assertRejected(contracts.validate_receipt, receipt)
        ledger = copy.deepcopy(self.ledger)
        ledger["events"][1]["occurred_at"] = "2026-09-02T17:52:01Z"
        self.assertRejected(contracts.validate_ledger, ledger)

    def test_empty_rows_require_preserved_aggregate_profile(self) -> None:
        decomposed = copy.deepcopy(self.manifest)
        decomposed["activation"]["full_profile"] = "decomposed"
        decomposed = self.reidentify(decomposed, "manifest_id")
        receipt = copy.deepcopy(self.receipts["staged_full"])
        receipt["manifest_id"] = decomposed["manifest_id"]
        receipt["source"]["manifest_id"] = decomposed["manifest_id"]
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(
            contracts.validate_receipt,
            receipt,
            manifests={decomposed["manifest_id"]: decomposed},
            receipt_store={receipt["receipt_id"]: receipt},
        )

    def test_enforce_fallback_requires_cause_and_authoritative_aggregate(self) -> None:
        receipt = copy.deepcopy(self.receipts["enforce_fallback"])
        receipt["rows"][0]["selection_causes"] = ["full_mode"]
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(
            contracts.validate_receipt,
            receipt,
            manifests=self.manifests,
            receipt_store=self.receipt_store,
        )
        receipt = copy.deepcopy(self.receipts["enforce_fallback"])
        receipt["aggregate_execution"]["diagnostic_code"] = "focused.authoritative"
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(contracts.validate_receipt, receipt)

    def test_shadow_full_linkage_is_content_addressed_and_source_bound(self) -> None:
        shadow = copy.deepcopy(self.receipts["pr_shadow"])
        shadow["authoritative_receipt_id"] = contracts.sha256_id(b"missing")
        shadow = self.reidentify(shadow, "receipt_id")
        self.assertRejected(
            contracts.validate_receipt,
            shadow,
            manifests=self.manifests,
            receipt_store=self.receipt_store,
        )
        linked = copy.deepcopy(self.receipts["pr_full"])
        linked["source"]["head_commit_sha"] = "3" * 40
        linked = self.reidentify(linked, "receipt_id")
        shadow = copy.deepcopy(self.receipts["pr_shadow"])
        shadow["authoritative_receipt_id"] = linked["receipt_id"]
        shadow = self.reidentify(shadow, "receipt_id")
        store = dict(self.receipt_store)
        store[linked["receipt_id"]] = linked
        self.assertRejected(
            contracts.validate_receipt,
            shadow,
            manifests=self.manifests,
            receipt_store=store,
        )

    def test_genesis_predecessor_broken_and_forked_chains_are_rejected(self) -> None:
        genesis_predecessor = copy.deepcopy(self.ledger)
        genesis_predecessor["events"][0]["previous_event_id"] = str(
            contracts.sha256_id(b"predecessor")
        )
        genesis_predecessor = self.rehash_chain(genesis_predecessor)
        genesis_predecessor["events"][0]["previous_event_id"] = str(
            contracts.sha256_id(b"predecessor")
        )
        genesis_predecessor["events"][0] = self.reidentify(
            genesis_predecessor["events"][0], "event_id"
        )
        self.assertRejected(contracts.validate_ledger, genesis_predecessor)

        broken = copy.deepcopy(self.ledger)
        broken["events"][1]["previous_event_id"] = str(contracts.sha256_id(b"wrong"))
        broken["events"][1] = self.reidentify(broken["events"][1], "event_id")
        self.assertRejected(contracts.validate_ledger, broken)

        forked = copy.deepcopy(self.ledger)
        forked["events"][2]["previous_event_id"] = forked["events"][0]["event_id"]
        forked["events"][2] = self.reidentify(forked["events"][2], "event_id")
        self.assertRejected(contracts.validate_ledger, forked)

    def test_prefix_anchor_tip_and_truncated_rehash_refusals(self) -> None:
        anchor = self.goldens["ledger"]["prefix_anchor"]
        base = base64.b64decode(anchor["base_canonical_b64"], validate=True)
        candidate = base64.b64decode(
            anchor["candidate_canonical_b64"], validate=True
        )
        contracts.validate_anchored_append(
            base,
            candidate,
            anchor["base_sha256"],
            anchor["tip_event_id"],
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )
        self.assertRejected(
            contracts.validate_anchored_append,
            base,
            candidate,
            str(contracts.sha256_id(b"wrong-base")),
            anchor["tip_event_id"],
        )
        self.assertRejected(
            contracts.validate_anchored_append,
            base,
            candidate,
            anchor["base_sha256"],
            str(contracts.sha256_id(b"wrong-tip")),
        )

        rewritten = copy.deepcopy(self.ledger)
        rewritten["events"][0]["payload"]["direct_classifications"][0][
            "result"
        ] = "nonconformant"
        rewritten = self.rehash_chain(rewritten)
        self.assertRejected(
            contracts.validate_anchored_append,
            base,
            contracts.canonical_json(rewritten),
            anchor["base_sha256"],
            anchor["tip_event_id"],
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )

        truncated = copy.deepcopy(self.ledger)
        del truncated["events"][2]
        truncated = self.rehash_chain(truncated)
        self.assertRejected(
            contracts.validate_anchored_append,
            base,
            contracts.canonical_json(truncated),
            anchor["base_sha256"],
            anchor["tip_event_id"],
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )

    def test_duplicate_logical_credit_key_is_a_ledger_failure(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        duplicate = copy.deepcopy(ledger["events"][1])
        duplicate["previous_event_id"] = ledger["events"][1]["event_id"]
        duplicate = self.reidentify(duplicate, "event_id")
        ledger["events"] = ledger["events"][:2] + [duplicate]
        self.assertRejected(
            contracts.validate_ledger,
            ledger,
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )

    def test_non_consumer_bound_surveillance_reference_is_rejected(self) -> None:
        ledger = copy.deepcopy(self.ledger)
        graduation_index = next(
            index
            for index, event in enumerate(ledger["events"])
            if event["event_type"] == "graduation"
        )
        ledger["events"][graduation_index]["payload"]["lane"] = "runnerless_pr"
        ledger = self.rehash_chain(ledger)
        self.assertRejected(
            contracts.validate_ledger,
            ledger,
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )

    def test_surveillance_periods_grace_and_non_sliding_deadline(self) -> None:
        weekly = next(
            event
            for event in self.ledger["events"]
            if event["event_type"] == "observation"
            and event["payload"]["schedule"] == "weekly_full"
            and event["payload"]["bootstrap"] is False
        )
        monthly = next(
            event
            for event in self.ledger["events"]
            if event["event_type"] == "observation"
            and event["payload"]["schedule"] == "monthly_deep"
            and event["payload"]["bootstrap"] is False
        )
        self.assertEqual(
            (
                weekly["payload"]["period_id"],
                weekly["payload"]["grace_seconds"],
                weekly["payload"]["deadline_at"],
            ),
            ("2026-W36", 86400, "2026-09-08T00:00:00Z"),
        )
        self.assertEqual(
            (
                monthly["payload"]["period_id"],
                monthly["payload"]["grace_seconds"],
                monthly["payload"]["deadline_at"],
            ),
            ("2026-09", 172800, "2026-10-03T00:00:00Z"),
        )
        late = copy.deepcopy(self.ledger)
        weekly_index = late["events"].index(
            next(
                event
                for event in late["events"]
                if event["event_type"] == "observation"
                and event["payload"]["schedule"] == "weekly_full"
                and event["payload"]["bootstrap"] is False
            )
        )
        late["events"][weekly_index]["payload"]["completed_at"] = (
            "2026-09-08T00:00:01Z"
        )
        late = self.rehash_chain(late)
        self.assertRejected(
            contracts.validate_ledger,
            late,
            schema_digests=self.schema_digests,
            manifests=self.manifests,
            receipts=self.receipt_store,
        )
        shifted = copy.deepcopy(self.ledger)
        shifted["events"][weekly_index]["payload"]["deadline_at"] = (
            "2026-09-09T00:00:00Z"
        )
        shifted = self.rehash_chain(shifted)
        self.assertRejected(contracts.validate_ledger, shifted)

    def test_surveillance_just_before_at_and_after_deadline_boundaries(self) -> None:
        weekly = copy.deepcopy(
            next(
                event
                for event in self.ledger["events"]
                if event["event_type"] == "observation"
                and event["payload"]["schedule"] == "weekly_full"
                and event["payload"]["bootstrap"] is False
            )
        )
        bootstrap = copy.deepcopy(weekly)
        bootstrap["payload"]["bootstrap"] = True
        bootstrap = self.reidentify(bootstrap, "event_id")
        common = {
            "schedule": "weekly_full",
            "lane": "local",
            "manifest_id": self.manifest["manifest_id"],
            "activation_generation": 1,
            "schema_links": weekly["schema_links"],
            "source": weekly["source"],
            "manifests": self.manifests,
        }
        self.assertEqual(
            contracts.validate_surveillance_authority(
                [bootstrap, weekly], now="2026-09-07T23:59:59Z", **common
            ),
            bootstrap["event_id"],
        )
        self.assertEqual(
            contracts.validate_surveillance_authority(
                [bootstrap, weekly], now="2026-09-08T00:00:00Z", **common
            ),
            weekly["event_id"],
        )
        self.assertEqual(
            next(iter(contracts.reduce_logical_credits([bootstrap, weekly]).values())),
            weekly["event_id"],
        )
        self.assertEqual(
            contracts.validate_surveillance_authority(
                [bootstrap, weekly], now="2026-09-08T00:00:01Z", **common
            ),
            weekly["event_id"],
        )
        self.assertRejected(
            contracts.validate_surveillance_authority,
            [bootstrap],
            now="2026-09-08T00:00:00Z",
            **common,
        )
        self.assertIsNone(
            contracts.latest_required_surveillance_period(
                "weekly_full", "2026-09-02T17:51:34Z", "2026-09-07T23:59:59Z"
            )
        )
        self.assertEqual(
            contracts.latest_required_surveillance_period(
                "weekly_full", "2026-09-02T17:51:34Z", "2026-09-08T00:00:00Z"
            ),
            "2026-W36",
        )
        self.assertEqual(
            contracts.latest_required_surveillance_period(
                "monthly_deep", "2026-09-02T17:51:34Z", "2026-10-03T00:00:00Z"
            ),
            "2026-09",
        )

    def test_provenance_per_kind_grammar_and_digest_binding(self) -> None:
        event = self.ledger["events"][1]
        invalid = [
            {
                "kind": "operator_record",
                "reference": "operator words",
                "reference_sha256": str(contracts.sha256_id(b"x")),
            },
            {
                "kind": "local_command",
                "reference": str(contracts.sha256_id(b"a")),
                "reference_sha256": str(contracts.sha256_id(b"b")),
            },
            {
                "kind": "runnerless_check",
                "reference": "https://example.test/check",
                "reference_sha256": str(contracts.sha256_id(b"x")),
            },
            {
                "kind": "pull_request",
                "reference": "https://github.com/KleinPerkins/dev/pull/332",
                "reference_sha256": str(contracts.sha256_id(b"x")),
            },
        ]
        for provenance in invalid:
            ledger = copy.deepcopy(self.ledger)
            ledger["events"][1]["provenance"] = provenance
            ledger = self.rehash_chain(ledger)
            with self.subTest(kind=provenance["kind"]):
                self.assertRejected(contracts.validate_ledger, ledger)
        self.assertEqual(event["provenance"]["reference"], "pr/332")

    def test_omitted_provenance_source_and_schema_links_are_rejected(self) -> None:
        for field in ("provenance", "source", "schema_links"):
            ledger = copy.deepcopy(self.ledger)
            del ledger["events"][1][field]
            with self.subTest(field=field):
                self.assertRejected(contracts.validate_ledger, ledger)
        ledger = copy.deepcopy(self.ledger)
        del ledger["events"][1]["schema_links"]["receipt"]
        self.assertRejected(contracts.validate_ledger, ledger)

    def test_every_named_set_ordering_is_rejected(self) -> None:
        pinned = self.goldens["set_order_rejections"]
        self.assertEqual(len(pinned), 32)
        for item in pinned:
            self.assertEqual(
                contracts.canonical_json(item["value"]),
                base64.b64decode(item["canonical_b64"], validate=True),
                item["name"],
            )
            object_keys = {
                "acceptance.criteria": lambda value: value["ac_id"],
                "manifest.cost_classes": lambda value: value["id"],
                "manifest.inert_rules": lambda value: value["id"],
                "manifest.input_rules": lambda value: value["id"],
                "manifest.obligations": lambda value: value["id"],
                "manifest.semantic_selectors": lambda value: value["id"],
                "manifest.semantic_selectors.pointer_rules": lambda value: (
                    value["pointer"].encode("utf-8"),
                    value["match"].encode("utf-8"),
                    contracts.canonical_json(value["add_obligation_ids"]),
                ),
            }
            with self.subTest(pinned_set=item["name"]):
                if item["name"] in object_keys:
                    self.assertRejected(
                        contracts._validate_object_set_by_key,
                        item["value"],
                        item["name"],
                        object_keys[item["name"]],
                        lambda _value, _where: None,
                    )
                elif item["name"] == "manifest.obligations.success_exit_codes":
                    obligation = copy.deepcopy(self.manifest["obligations"][0])
                    obligation["success_exit_codes"] = item["value"]
                    self.assertRejected(
                        contracts._validate_obligation,
                        obligation,
                        item["name"],
                    )
                else:
                    self.assertRejected(
                        contracts._validate_string_set,
                        item["value"],
                        item["name"],
                    )

        cases = []
        manifest = copy.deepcopy(self.manifest)
        manifest["modes"] = list(reversed(manifest["modes"]))
        cases.append(("manifest.modes", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        manifest = copy.deepcopy(self.manifest)
        manifest["cause_codes"] = list(reversed(manifest["cause_codes"]))
        cases.append(("manifest.cause_codes", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        manifest = copy.deepcopy(self.manifest)
        manifest["input_rules"] = list(reversed(manifest["input_rules"]))
        cases.append(("manifest.input_rules", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        manifest = copy.deepcopy(self.manifest)
        manifest["semantic_selectors"][0]["baseline_input_rule_ids"] = [
            "config.refs",
            "config.digest",
        ]
        cases.append(("baseline_input_rule_ids", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        manifest = copy.deepcopy(self.manifest)
        first = copy.deepcopy(manifest["semantic_selectors"][0]["pointer_rules"][0])
        first["pointer"] = "/z"
        second = copy.deepcopy(first)
        second["pointer"] = "/a"
        manifest["semantic_selectors"][0]["pointer_rules"] = [first, second]
        cases.append(("pointer_rules", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        manifest = copy.deepcopy(self.manifest)
        manifest["obligations"][0]["eligible_in"] = list(
            reversed(manifest["obligations"][0]["eligible_in"])
        )
        cases.append(("eligible_in", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        manifest = copy.deepcopy(self.manifest)
        manifest["obligations"][0]["environment_allowlist"] = [
            "TZ",
            "PYTHONDONTWRITEBYTECODE",
        ]
        cases.append(("environment_allowlist", contracts.validate_manifest, self.reidentify(manifest, "manifest_id")))

        for name, validator, value in cases:
            with self.subTest(name=name):
                self.assertRejected(validator, value)

        receipt = copy.deepcopy(self.receipts["enforce_fallback"])
        receipt["rows"][0]["selection_causes"] = ["full_mode", "fallback"]
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(contracts.validate_receipt, receipt)

        receipt = copy.deepcopy(self.receipts["enforce"])
        row_a = copy.deepcopy(receipt["rows"][0])
        row_a["obligation_id"] = "z"
        row_b = copy.deepcopy(row_a)
        row_b["obligation_id"] = "a"
        receipt["rows"] = [row_a, row_b]
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(contracts.validate_receipt, receipt)

        ledger = copy.deepcopy(self.ledger)
        event = ledger["events"][1]
        event["receipt_ids"] = [
            str(contracts.sha256_id(b"z")),
            str(contracts.sha256_id(b"a")),
        ]
        ledger = self.rehash_chain(ledger)
        self.assertRejected(contracts.validate_ledger, ledger)

        ledger = copy.deepcopy(self.ledger)
        graduation = next(
            event for event in ledger["events"] if event["event_type"] == "graduation"
        )
        graduation["payload"]["tags"] = ["z", "a"]
        ledger = self.rehash_chain(ledger)
        self.assertRejected(contracts.validate_ledger, ledger)

        ledger = copy.deepcopy(self.ledger)
        graduation = next(
            event for event in ledger["events"] if event["event_type"] == "graduation"
        )
        graduation["payload"]["required_surveillance_event_ids"].reverse()
        ledger = self.rehash_chain(ledger)
        self.assertRejected(contracts.validate_ledger, ledger)

    def test_set_duplicates_are_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["control_rule_ids"].append(manifest["control_rule_ids"][0])
        manifest = self.reidentify(manifest, "manifest_id")
        self.assertRejected(contracts.validate_manifest, manifest)
        receipt = copy.deepcopy(self.receipts["enforce"])
        receipt["rows"][0]["selection_causes"] = ["direct", "direct"]
        receipt = self.reidentify(receipt, "receipt_id")
        self.assertRejected(contracts.validate_receipt, receipt)

    def test_schema_unknown_fields_and_variant_constraints(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["receipt_contract"]["unknown"] = 1
        self.assertRejected(
            contracts.validate_against_schema, manifest, self.schemas["manifest"]
        )
        receipt = copy.deepcopy(self.receipts["pr_shadow"])
        receipt["authoritative_receipt_id"] = None
        self.assertRejected(
            contracts.validate_against_schema, receipt, self.schemas["receipt"]
        )
        ledger = copy.deepcopy(self.ledger)
        ledger["events"][0]["previous_event_id"] = str(contracts.sha256_id(b"x"))
        self.assertRejected(
            contracts.validate_against_schema, ledger, self.schemas["ledger"]
        )

    def test_logical_credit_keys_are_pinned_and_reducer_is_deterministic(self) -> None:
        expected = {
            item["event_id"]: [tuple(key) for key in item["keys"]]
            for item in self.goldens["logical_credit_keys"]
        }
        for event in self.ledger["events"][1:]:
            self.assertEqual(
                contracts.event_logical_credit_keys(event), expected[event["event_id"]]
            )
        first = contracts.reduce_logical_credits(self.ledger["events"])
        second = contracts.reduce_logical_credits(self.ledger["events"])
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
