from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from _ops.verification import contracts, selector


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
MANIFEST_PATH = ROOT / "verification-manifest.json"
SCHEMA_PATH = ROOT / "verification-manifest.schema.json"
CASES_PATH = ROOT / "fixtures" / "selector-cases-v1.json"
ZERO_DIGEST = "sha256:" + "0" * 64
NEW_SELECTOR_PATHS = (
    "_ops/verification/fixtures/selector-cases-v1.json",
    "_ops/verification/selector.py",
    "_ops/verification/test_selector.py",
    "_ops/verification/verification-manifest.json",
)


def run(
    argv: list[str | bytes],
    *,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        argv,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {argv!r}\n"
            f"{completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed


def git_environment(
    index_file: Path | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(("GIT_", "BASH_FUNC_")) or key in {
            "BASH_ENV", "ENV", "GH_TOKEN", "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
        }:
            del env[key]
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    return env


def reidentify(value: dict) -> dict:
    result = copy.deepcopy(value)
    result["manifest_id"] = ""
    result["manifest_id"] = str(
        contracts.derive_identity(result, "manifest_id")
    )
    return result


def add_input_rule(value: dict, rule: dict) -> dict:
    result = copy.deepcopy(value)
    result["input_rules"].append(rule)
    result["input_rules"].sort(key=lambda item: item["id"].encode())
    return reidentify(result)


def input_rule(
    rule_id: str,
    path: bytes,
    owners: list[str],
    *,
    tags: list[str] | None = None,
    kind: str = "exact",
) -> dict:
    return {
        "id": rule_id,
        "matcher": {
            "kind": kind,
            "value_b64": base64.b64encode(path).decode("ascii"),
        },
        "owner_obligation_ids": sorted(owners),
        "classification_tags": sorted(
            tags or ["change.operating-model"]
        ),
    }


def candidate_entry(
    path: bytes,
    content: bytes = b"",
    *,
    mode: str = "100644",
) -> selector.CandidateEntry:
    return selector.CandidateEntry(
        selector.PathIdentity.from_bytes(path),
        mode,
        str(contracts.sha256_id(content)),
    )


def live_candidate_entries() -> tuple[selector.CandidateEntry, ...]:
    output = run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-s", "-z"],
        env=git_environment(),
    ).stdout
    entries: dict[bytes, selector.CandidateEntry] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, _oid, stage = header.split()
        if stage != b"0":
            raise AssertionError("real worktree index is unmerged")
        entries[raw_path] = selector.CandidateEntry(
            selector.PathIdentity.from_bytes(raw_path),
            mode.decode("ascii"),
            ZERO_DIGEST,
        )
    for relative in NEW_SELECTOR_PATHS:
        path = REPO_ROOT / relative
        if path.exists():
            raw = relative.encode("utf-8")
            entries[raw] = selector.CandidateEntry(
                selector.PathIdentity.from_bytes(raw),
                "100644",
                ZERO_DIGEST,
            )
    return tuple(entries[path] for path in sorted(entries))


def source_for_changes(
    manifest: dict,
    base_entries: tuple[selector.CandidateEntry, ...],
    specifications: list[
        tuple[str, bytes, bytes | None, bytes | None, str, str]
    ],
) -> tuple[selector.SourceBinding, tuple[selector.Change, ...]]:
    base = {entry.path.raw: entry for entry in base_entries}
    manifest_bytes = contracts.canonical_json(manifest)
    schema_bytes = SCHEMA_PATH.read_bytes()
    base[selector.MANIFEST_RELATIVE_PATH] = candidate_entry(
        selector.MANIFEST_RELATIVE_PATH, manifest_bytes
    )
    base[selector.MANIFEST_SCHEMA_RELATIVE_PATH] = candidate_entry(
        selector.MANIFEST_SCHEMA_RELATIVE_PATH, schema_bytes
    )
    candidate = dict(base)
    changes: list[selector.Change] = []
    for status, path, old_blob, new_blob, old_mode, new_mode in specifications:
        old_entry = None
        new_entry = None
        if old_blob is not None:
            old_entry = candidate_entry(path, old_blob, mode=old_mode)
            base[path] = old_entry
        else:
            base.pop(path, None)
        if new_blob is not None:
            new_entry = candidate_entry(path, new_blob, mode=new_mode)
            candidate[path] = new_entry
        else:
            candidate.pop(path, None)
        changes.append(
            selector.Change(
                status=status,
                old_path=old_entry.path if old_entry else None,
                new_path=new_entry.path if new_entry else None,
                old_mode=old_entry.mode if old_entry else None,
                new_mode=new_entry.mode if new_entry else None,
                old_blob_sha256=(
                    old_entry.blob_sha256 if old_entry else None
                ),
                new_blob_sha256=(
                    new_entry.blob_sha256 if new_entry else None
                ),
                _old_blob=old_blob,
                _new_blob=new_blob,
            )
        )
    candidate_values = tuple(candidate[path] for path in sorted(candidate))
    base_values = tuple(base[path] for path in sorted(base))
    digest = str(
        contracts.candidate_tree_digest(
            [entry.to_digest_object() for entry in candidate_values]
        )
    )
    source = selector.SourceBinding(
        repository_id=contracts.REPOSITORY_ID,
        source_kind="staged_index",
        candidate_tree_sha256=digest,
        manifest_id=manifest["manifest_id"],
        selector_version="1",
        base_commit_sha="1" * 40,
        head_commit_sha=None,
        merge_base_sha=None,
        index_tree_sha="2" * 40,
        commit_sha=None,
        _candidate_entries=candidate_values,
        _base_entries=base_values,
        _manifest_bytes=manifest_bytes,
        _manifest_schema_bytes=schema_bytes,
        _base_manifest_bytes=manifest_bytes,
        _base_manifest_schema_bytes=schema_bytes,
        _platform="darwin",
    )
    return source, tuple(
        sorted(changes, key=lambda item: item.sort_key)
    )


class StagedRepo:
    def __init__(self, *, unborn: bool = False) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="selector-test-repo-"
        )
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write(b"README.md", b"base\n")
        entrypoints = {
            path
            for spec in selector.HARNESS_INVENTORY_V1.values()
            for path in spec.entrypoints
        }
        for raw_path in sorted(entrypoints):
            if raw_path == selector.MANIFEST_RELATIVE_PATH:
                content = MANIFEST_PATH.read_bytes()
            elif raw_path == selector.MANIFEST_SCHEMA_RELATIVE_PATH:
                content = SCHEMA_PATH.read_bytes()
            else:
                content = b"fixture entrypoint\n"
            self.write(raw_path, content)
        self.write(
            selector.MANIFEST_RELATIVE_PATH,
            MANIFEST_PATH.read_bytes(),
        )
        # The schema is required by exact source loading but is not itself an
        # obligation entrypoint.
        self.write(
            selector.MANIFEST_SCHEMA_RELATIVE_PATH,
            SCHEMA_PATH.read_bytes(),
        )
        self.index = self.root / "candidate.index"
        if unborn:
            self.git("add", "-A", index=True)
        else:
            self.git("add", "-A")
            self.git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-q",
                "-m",
                "fixture base",
            )
            shutil.copy2(self.repo / ".git" / "index", self.index)

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> "StagedRepo":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def git(
        self,
        *arguments: str | bytes,
        index: bool = False,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        argv: list[str | bytes] = [
            os.fsencode(shutil.which("git") or "git"),
            b"-C",
            os.fsencode(self.repo),
        ]
        argv.extend(
            item if isinstance(item, bytes) else os.fsencode(item)
            for item in arguments
        )
        return run(
            argv,
            env=git_environment(self.index if index else None),
            input_bytes=input_bytes,
            check=check,
        )

    def write(self, relative: bytes, content: bytes) -> None:
        full = os.path.join(os.fsencode(self.repo), relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(content)

    def stage(self, *paths: bytes) -> None:
        self.git(b"add", b"--", *paths, index=True)

    def object_directory(self) -> Path:
        raw = self.git(
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "objects",
        ).stdout.rstrip(b"\n")
        return Path(os.fsdecode(raw))


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = selector.load_manifest(MANIFEST_PATH)
        cls.value = copy.deepcopy(cls.manifest.value)
        cls.entries = live_candidate_entries()
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_manifest_is_canonical_schema_valid_and_identity_bound(self) -> None:
        raw = MANIFEST_PATH.read_bytes()
        self.assertFalse(raw.endswith(b"\n"))
        self.assertEqual(
            contracts.validate_canonical_input(raw), self.manifest.value
        )
        schema = contracts.parse_json_document(SCHEMA_PATH.read_bytes())
        contracts.validate_against_schema(self.manifest.value, schema)
        contracts.validate_manifest(dict(self.manifest.value))
        self.assertEqual(
            contracts.derive_identity(
                self.manifest.value, "manifest_id"
            ),
            self.manifest.manifest_id,
        )

    def test_manifest_remains_m1_shadow_without_graduated_tags(self) -> None:
        activation = self.manifest.value["activation"]
        self.assertEqual(activation["generation"], 1)
        self.assertEqual(
            activation["full_profile"], "preserved_aggregate"
        )
        self.assertEqual(
            [
                (
                    lane["lane"],
                    lane["policy"],
                    lane["graduated_tags"],
                )
                for lane in activation["lanes"]
            ],
            [
                ("local", "shadow", []),
                ("runnerless_pr", "shadow", []),
            ],
        )

    def test_every_candidate_path_is_owned_without_inert_overlap(self) -> None:
        selector.validate_manifest_for_candidate(
            self.manifest,
            self.entries,
            schema_bytes=SCHEMA_PATH.read_bytes(),
        )
        self.assertFalse(self.manifest.value["inert_rules"])

    def test_bounded_harness_inventory_matches_candidate_entrypoints(self) -> None:
        obligation_ids = {
            item["id"] for item in self.manifest.value["obligations"]
        }
        self.assertEqual(
            obligation_ids, set(selector.HARNESS_INVENTORY_V1)
        )
        selector._validate_harness_inventory(
            self.manifest.value, self.entries
        )
        verify = next(
            item
            for item in self.manifest.value["obligations"]
            if item["id"] == "verify.selector"
        )
        self.assertEqual(
            verify["argv"],
            [
                "python3",
                "-m",
                "unittest",
                "-v",
                "verification.test_contracts",
                "verification.test_selector",
            ],
        )
        self.assertIn("PYTHONPATH", verify["environment_allowlist"])

    def test_exact_prefix_and_suffix_matchers_are_byte_exact(self) -> None:
        for case in self.cases["matcher_cases"]:
            with self.subTest(case=case):
                matcher = {
                    "kind": case["kind"],
                    "value_b64": case["value_b64"],
                }
                path = base64.b64decode(case["path_b64"], validate=True)
                self.assertEqual(
                    contracts.matcher_matches(matcher, path),
                    case["expected"],
                )

    def test_unsafe_matchers_refuse(self) -> None:
        for matcher in (
            {
                "kind": "prefix",
                "value_b64": base64.b64encode(b"_ops").decode(),
            },
            {
                "kind": "suffix",
                "value_b64": base64.b64encode(b"md").decode(),
            },
            {
                "kind": "suffix",
                "value_b64": base64.b64encode(b".x/y").decode(),
            },
        ):
            with self.subTest(matcher=matcher):
                with self.assertRaises(contracts.ContractError):
                    contracts.matcher_matches(matcher, b"_ops/file.md")

    def test_noncanonical_manifest_bytes_refuse(self) -> None:
        with self.assertRaises(contracts.ContractError):
            selector.load_manifest_bytes(
                MANIFEST_PATH.read_bytes() + b"\n",
                schema_bytes=SCHEMA_PATH.read_bytes(),
            )

    def test_unmatched_candidate_path_refuses_completeness(self) -> None:
        entries = self.entries + (
            candidate_entry(b"unknown/path.bin"),
        )
        with self.assertRaises(selector.SelectorError):
            selector.validate_manifest_for_candidate(
                self.manifest, entries
            )

    def test_current_source_coverage_requires_each_new_owner_rule(self) -> None:
        # Current-source ownership is separate from the frozen rollout ledger.
        # Each rule must cover a real path; removing it must still fail closed.
        cases = (
            ("area.ops.interoperability", b"_ops/interoperability/native_rules.py"),
            ("area.ops.portability", b"_ops/portability/engine.py"),
            ("area.planning.doc-warden", b".planning/doc-warden.json"),
            ("area.scripts", b"scripts/verify.py"),
            ("area.tests", b"tests/test_ci.py"),
        )
        paths = {entry.path.raw for entry in self.entries}
        for rule_id, path in cases:
            with self.subTest(rule=rule_id):
                self.assertIn(path, paths)
                selector._validate_rule_coverage(self.value, [path])
                value = copy.deepcopy(self.value)
                value["input_rules"] = [
                    rule for rule in value["input_rules"]
                    if rule["id"] != rule_id
                ]
                with self.assertRaisesRegex(
                    selector.SelectorError, "path must have owners"
                ):
                    selector.validate_manifest_for_candidate(
                        reidentify(value), self.entries
                    )

    def test_current_source_coverage_does_not_admit_unknown_neighbors(self) -> None:
        for path in (
            b".planning/unreviewed.json",
            b"_ops/unknown/file.py",
            b"scripts-extra/file.py",
            b"tests-extra/file.py",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    selector.SelectorError, "path must have owners"
                ):
                    selector.validate_manifest_for_candidate(
                        self.manifest, self.entries + (candidate_entry(path),)
                    )

    def test_fixture_git_environment_excludes_shell_hooks_and_credentials(self) -> None:
        unsafe = {
            "BASH_ENV": "/fixture/forbidden-hook",
            "ENV": "/fixture/forbidden-hook",
            "BASH_FUNC_git%%": "() { false; }",
            "GH_TOKEN": "fixture-token",
            "GITHUB_TOKEN": "fixture-token",
            "GH_ENTERPRISE_TOKEN": "fixture-token",
            "GITHUB_ENTERPRISE_TOKEN": "fixture-token",
            "GIT_DIR": "/fixture/foreign-git",
        }
        with mock.patch.dict(os.environ, unsafe):
            env = git_environment(Path("/fixture/candidate.index"))
        self.assertFalse(set(unsafe) & set(env))
        self.assertEqual(env["GIT_INDEX_FILE"], "/fixture/candidate.index")

    def test_input_and_inert_overlap_refuses(self) -> None:
        value = add_input_rule(
            self.value,
            input_rule(
                "fixture.owner",
                b"fixture/overlap.txt",
                ["doc.full-compat"],
            ),
        )
        value["inert_rules"] = [
            {
                "id": "fixture.inert",
                "matcher": {
                    "kind": "exact",
                    "value_b64": base64.b64encode(
                        b"fixture/overlap.txt"
                    ).decode(),
                },
                "reason_code": "inert",
            }
        ]
        value = reidentify(value)
        entries = self.entries + (
            candidate_entry(b"fixture/overlap.txt"),
        )
        with self.assertRaises(selector.SelectorError):
            selector.validate_manifest_for_candidate(value, entries)

    def test_exactly_one_inert_rule_is_accepted(self) -> None:
        value = copy.deepcopy(self.value)
        value["inert_rules"] = [
            {
                "id": "fixture.inert",
                "matcher": {
                    "kind": "exact",
                    "value_b64": base64.b64encode(
                        b"fixture/inert.txt"
                    ).decode(),
                },
                "reason_code": "inert",
            }
        ]
        value = reidentify(value)
        entries = self.entries + (
            candidate_entry(b"fixture/inert.txt"),
        )
        selector.validate_manifest_for_candidate(value, entries)

    def test_duplicate_inert_match_refuses(self) -> None:
        value = copy.deepcopy(self.value)
        value["inert_rules"] = [
            {
                "id": f"fixture.inert-{suffix}",
                "matcher": {
                    "kind": "exact",
                    "value_b64": base64.b64encode(
                        b"fixture/inert.txt"
                    ).decode(),
                },
                "reason_code": "inert",
            }
            for suffix in ("a", "b")
        ]
        value = reidentify(value)
        with self.assertRaises(selector.SelectorError):
            selector.validate_manifest_for_candidate(
                value,
                self.entries
                + (candidate_entry(b"fixture/inert.txt"),),
            )

    def test_stale_argv_or_unregistered_harness_refuses(self) -> None:
        for mutation in ("argv", "obligation"):
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(self.value)
                if mutation == "argv":
                    value["obligations"][0]["argv"].append("--surprise")
                else:
                    value["obligations"].append(
                        copy.deepcopy(value["obligations"][0])
                    )
                    value["obligations"][-1]["id"] = "unknown.harness"
                    value["obligations"].sort(
                        key=lambda item: item["id"]
                    )
                value = reidentify(value)
                with self.assertRaises(selector.SelectorError):
                    selector.validate_manifest_for_candidate(
                        value, self.entries
                    )

    def test_missing_or_retargeted_control_input_refuses(self) -> None:
        for mutation in ("missing", "retargeted"):
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(self.value)
                if mutation == "missing":
                    value["control_rule_ids"].remove(
                        "control.ops.policy"
                    )
                else:
                    rule = next(
                        item
                        for item in value["input_rules"]
                        if item["id"] == "control.ops.policy"
                    )
                    rule["matcher"]["value_b64"] = base64.b64encode(
                        b"_ops/README.md"
                    ).decode("ascii")
                value = reidentify(value)
                with self.assertRaises(selector.SelectorError):
                    selector.validate_manifest_for_candidate(
                        value, self.entries
                    )


class StagedSourceTests(unittest.TestCase):
    def assertRefusal(
        self, diagnostic: str, callable_, *args
    ) -> selector.SourceRefusal:
        with self.assertRaises(selector.SourceRefusal) as raised:
            callable_(*args)
        self.assertEqual(raised.exception.diagnostic_code, diagnostic)
        self.assertTrue(raised.exception.fallback_required)
        self.assertEqual(raised.exception.effective_mode, "full")
        return raised.exception

    def test_partial_staging_ignores_unstaged_and_untracked_decoys(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"staged\n")
            fixture.stage(b"README.md")
            fixture.write(b"README.md", b"unstaged decoy\n")
            fixture.write(b"docs/untracked.md", b"untracked decoy\n")
            first_source, first_changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            fixture.write(b"README.md", b"different decoy\n")
            fixture.write(
                b"docs/untracked.md", b"different untracked decoy\n"
            )
            second_source, second_changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            self.assertEqual(first_source, second_source)
            self.assertEqual(
                [item.to_object() for item in first_changes],
                [item.to_object() for item in second_changes],
            )
            readme = next(
                item
                for item in first_changes
                if item.new_path and item.new_path.raw == b"README.md"
            )
            self.assertEqual(
                readme.new_blob_sha256,
                str(contracts.sha256_id(b"staged\n")),
            )
            self.assertNotEqual(
                readme.new_blob_sha256,
                str(contracts.sha256_id(b"unstaged decoy\n")),
            )

    def test_exact_staged_source_feeds_inert_shadow_selection(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            source, changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            manifest = selector.load_manifest_bytes(
                source._manifest_bytes or b"",
                schema_bytes=source._manifest_schema_bytes,
            )
            result = selector.select(
                manifest,
                source,
                changes,
                "local",
                "focused_local",
            )
            self.assertTrue(result.selector_control_ok)
            self.assertFalse(result.focus_eligible)
            self.assertEqual(result.effective_mode, "full")
            self.assertEqual(result.fallback_executor, "preserved.full")
            self.assertIn(
                "doc.full-compat", result.focused_obligation_ids
            )

    def test_candidate_bound_validation_refusals_preserve_source_and_reason(
        self,
    ) -> None:
        cases = (
            (
                "missing-entrypoint",
                "candidate entrypoint missing",
            ),
            (
                "uncovered-path",
                "path must have owners or exactly one inert rule",
            ),
            (
                "stale-command",
                "stale or ambiguous literal argv",
            ),
        )
        for case, reason in cases:
            with self.subTest(case=case), StagedRepo() as fixture:
                if case == "missing-entrypoint":
                    fixture.git(
                        "rm",
                        "-q",
                        "--",
                        "_ops/verification/selector.py",
                        index=True,
                    )
                elif case == "uncovered-path":
                    fixture.write(b"uncovered.bin", b"uncovered\n")
                    fixture.stage(b"uncovered.bin")
                else:
                    value = json.loads(
                        MANIFEST_PATH.read_text(encoding="utf-8")
                    )
                    obligation = next(
                        item
                        for item in value["obligations"]
                        if item["id"] == "verify.selector"
                    )
                    obligation["argv"].append("--stale")
                    fixture.write(
                        selector.MANIFEST_RELATIVE_PATH,
                        contracts.canonical_json(reidentify(value)),
                    )
                    fixture.stage(selector.MANIFEST_RELATIVE_PATH)

                refusal = self.assertRefusal(
                    "source.manifest-invalid",
                    selector.staged_source,
                    fixture.repo,
                    fixture.index,
                )
                self.assertIn(reason, str(refusal))
                self.assertTrue(refusal.source_bound)
                self.assertIsNotNone(refusal.source)
                self.assertTrue(refusal.candidate_tree_sha256)
                self.assertTrue(refusal.fallback_required)
                self.assertEqual(refusal.effective_mode, "full")
                fallback = selector._fallback_selection(
                    selector.load_manifest_bytes(
                        refusal.source._manifest_bytes or b"",
                        schema_bytes=(
                            refusal.source._manifest_schema_bytes
                        ),
                    ),
                    refusal.source,
                    "local",
                    "focused_local",
                    (refusal.diagnostic_code,),
                )
                self.assertFalse(fallback.selector_control_ok)
                self.assertFalse(fallback.focus_eligible)
                self.assertEqual(fallback.effective_mode, "full")
                self.assertEqual(
                    fallback.fallback_executor,
                    "preserved.full",
                )
                self.assertNotIn(
                    "skip",
                    {
                        decision.focused_disposition
                        for decision in fallback.decisions
                    },
                )

    def test_unparseable_candidate_manifest_refusal_remains_unbound(
        self,
    ) -> None:
        with StagedRepo() as fixture:
            fixture.write(selector.MANIFEST_RELATIVE_PATH, b"{")
            fixture.stage(selector.MANIFEST_RELATIVE_PATH)
            refusal = self.assertRefusal(
                "source.manifest-invalid",
                selector.staged_source,
                fixture.repo,
                fixture.index,
            )
            self.assertFalse(refusal.source_bound)
            self.assertIsNone(refusal.source)
            self.assertTrue(refusal.candidate_tree_sha256)

    def test_add_modify_delete_type_and_mode_changes(self) -> None:
        cases = ("add", "modify", "delete", "type_change", "mode")
        for case in cases:
            with self.subTest(case=case), StagedRepo() as fixture:
                expected_status = case
                expected_path = b"README.md"
                if case == "add":
                    expected_path = b"docs/new.md"
                    fixture.write(expected_path, b"new\n")
                    fixture.stage(expected_path)
                elif case == "modify":
                    fixture.write(expected_path, b"changed\n")
                    fixture.stage(expected_path)
                elif case == "delete":
                    fixture.git(
                        b"rm",
                        b"-q",
                        b"--",
                        expected_path,
                        index=True,
                    )
                elif case == "type_change":
                    os.unlink(os.path.join(os.fsencode(fixture.repo), expected_path))
                    os.symlink(
                        b"target",
                        os.path.join(os.fsencode(fixture.repo), expected_path),
                    )
                    fixture.stage(expected_path)
                else:
                    os.chmod(fixture.repo / "README.md", 0o755)
                    fixture.stage(expected_path)
                    expected_status = "modify"
                _source, changes = selector.staged_source(
                    fixture.repo, fixture.index
                )
                matching = [
                    item
                    for item in changes
                    if (
                        item.new_path.raw
                        if item.new_path
                        else item.old_path.raw
                    )
                    == expected_path
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].status, expected_status)
                if case == "mode":
                    self.assertEqual(matching[0].old_mode, "100644")
                    self.assertEqual(matching[0].new_mode, "100755")
                    self.assertEqual(
                        matching[0].old_blob_sha256,
                        matching[0].new_blob_sha256,
                    )

    def test_binary_blob_hashes_exact_staged_bytes(self) -> None:
        with StagedRepo() as fixture:
            raw_path = b"_ops/evidence/binary.bin"
            content = b"\x00\xff\x10binary\x00"
            fixture.write(raw_path, content)
            fixture.stage(raw_path)
            _source, changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            change = next(
                item
                for item in changes
                if item.new_path and item.new_path.raw == raw_path
            )
            self.assertEqual(
                change.new_blob_sha256,
                str(contracts.sha256_id(content)),
            )

    def test_utf8_and_non_utf8_path_bytes_remain_distinct(self) -> None:
        with StagedRepo() as fixture:
            utf8_path = "_ops/evidence/café.txt".encode("utf-8")
            raw_path = b"_ops/evidence/nonutf8-\xff.txt"
            fixture.write(utf8_path, b"utf8\n")
            fixture.stage(utf8_path)
            raw_oid = fixture.git(
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"bytes\n",
            ).stdout.rstrip(b"\n")
            fixture.git(
                "update-index",
                "-z",
                "--index-info",
                index=True,
                input_bytes=(
                    b"100644 " + raw_oid + b"\t" + raw_path + b"\0"
                ),
            )
            _source, changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            paths = {
                item.new_path.raw: item.new_path
                for item in changes
                if item.new_path is not None
            }
            self.assertEqual(paths[utf8_path].path_utf8, "café.txt".join(
                ["_ops/evidence/", ""]
            ))
            self.assertIsNone(paths[raw_path].path_utf8)
            self.assertNotEqual(
                paths[utf8_path].path_b64, paths[raw_path].path_b64
            )

    def test_unborn_head_uses_null_base_and_exact_tree(self) -> None:
        with StagedRepo(unborn=True) as fixture:
            source, changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            self.assertIsNone(source.base_commit_sha)
            self.assertTrue(source.index_tree_sha)
            self.assertTrue(changes)
            self.assertTrue(
                all(change.status == "add" for change in changes)
            )

    def test_unmerged_index_refuses_narrow_completeness(self) -> None:
        with StagedRepo() as fixture:
            fixture.git(
                "update-index",
                "--force-remove",
                "README.md",
                index=True,
            )
            oids = [
                fixture.git(
                    "hash-object",
                    "-w",
                    "--stdin",
                    input_bytes=value,
                ).stdout.rstrip(b"\n")
                for value in (b"base\n", b"ours\n", b"theirs\n")
            ]
            index_info = b"".join(
                b"100644 "
                + oid
                + b" "
                + str(stage).encode()
                + b"\tREADME.md\n"
                for stage, oid in enumerate(oids, 1)
            )
            fixture.git(
                "update-index",
                "--index-info",
                index=True,
                input_bytes=index_info,
            )
            refusal = self.assertRefusal(
                "source.index-unmerged",
                selector.staged_source,
                fixture.repo,
                fixture.index,
            )
            self.assertFalse(refusal.source_bound)

    def test_intent_to_add_refuses_narrow_completeness(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"docs/intent.md", b"intent\n")
            fixture.git(
                "add",
                "-N",
                "--",
                "docs/intent.md",
                index=True,
            )
            refusal = self.assertRefusal(
                "source.intent-to-add",
                selector.staged_source,
                fixture.repo,
                fixture.index,
            )
            self.assertTrue(refusal.source_bound)
            self.assertTrue(refusal.candidate_tree_sha256)

    def test_zero_oid_intent_refusal_retains_source_and_ignores_decoys(
        self,
    ) -> None:
        with StagedRepo() as fixture:
            intent_path = b"docs/intent.md"
            fixture.write(intent_path, b"intent\n")
            fixture.git(
                "add",
                "-N",
                "--",
                "docs/intent.md",
                index=True,
            )
            original = selector._run_git

            def zero_oid_stage(*args, **kwargs):
                result = original(*args, **kwargs)
                if tuple(args[1]) == ("ls-files", "--stage", "-z"):
                    records = result.stdout.split(b"\0")
                    for index, record in enumerate(records):
                        if record.endswith(b"\t" + intent_path):
                            header, path = record.split(b"\t", 1)
                            mode, _oid, stage = header.split(b" ")
                            records[index] = (
                                mode
                                + b" "
                                + b"0" * 40
                                + b" "
                                + stage
                                + b"\t"
                                + path
                            )
                    return subprocess.CompletedProcess(
                        result.args,
                        result.returncode,
                        b"\0".join(records),
                        result.stderr,
                    )
                return result

            with mock.patch.object(
                selector, "_run_git", side_effect=zero_oid_stage
            ):
                first = self.assertRefusal(
                    "source.intent-to-add",
                    selector.staged_source,
                    fixture.repo,
                    fixture.index,
                )
            self.assertTrue(first.source_bound)
            self.assertIsNotNone(first.source)
            self.assertTrue(first.candidate_tree_sha256)
            self.assertTrue(first.fallback_required)
            self.assertEqual(first.effective_mode, "full")
            self.assertIsNotNone(first.source._manifest_bytes)
            self.assertIsNotNone(first.source._manifest_schema_bytes)
            fallback = selector._fallback_selection(
                selector.load_manifest_bytes(
                    first.source._manifest_bytes,
                    schema_bytes=first.source._manifest_schema_bytes,
                ),
                first.source,
                "local",
                "focus",
                (first.diagnostic_code,),
            )
            self.assertFalse(fallback.selector_control_ok)
            self.assertFalse(fallback.focus_eligible)
            self.assertEqual(fallback.effective_mode, "full")
            self.assertNotIn(
                "skip",
                {
                    decision.focused_disposition
                    for decision in fallback.decisions
                },
            )

            fixture.write(intent_path, b"unstaged intent decoy\n")
            fixture.write(b"docs/untracked.md", b"untracked decoy\n")
            with mock.patch.object(
                selector, "_run_git", side_effect=zero_oid_stage
            ):
                second = self.assertRefusal(
                    "source.intent-to-add",
                    selector.staged_source,
                    fixture.repo,
                    fixture.index,
                )
            self.assertEqual(
                first.candidate_tree_sha256,
                second.candidate_tree_sha256,
            )
            self.assertEqual(first.source, second.source)

    def test_index_drift_refuses_after_source_binding(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            original = selector._run_git
            mutated = False

            def drifting(*args, **kwargs):
                nonlocal mutated
                result = original(*args, **kwargs)
                arguments = args[1]
                if arguments[0] == "diff-tree" and not mutated:
                    fixture.index.write_bytes(
                        fixture.index.read_bytes() + b"drift"
                    )
                    mutated = True
                return result

            with mock.patch.object(
                selector, "_run_git", side_effect=drifting
            ):
                refusal = self.assertRefusal(
                    "source.index-drift",
                    selector.staged_source,
                    fixture.repo,
                    fixture.index,
                )
            self.assertTrue(refusal.source_bound)
            self.assertTrue(refusal.candidate_tree_sha256)

    def test_malformed_raw_git_output_refuses_source_bound(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            original = selector._run_git

            def malformed(*args, **kwargs):
                arguments = args[1]
                if arguments[0] == "diff-tree":
                    return subprocess.CompletedProcess(
                        [], 0, b"malformed\0README.md\0", b""
                    )
                return original(*args, **kwargs)

            with mock.patch.object(
                selector, "_run_git", side_effect=malformed
            ):
                refusal = self.assertRefusal(
                    "source.diff-malformed",
                    selector.staged_source,
                    fixture.repo,
                    fixture.index,
                )
            self.assertTrue(refusal.source_bound)

    def test_raw_diff_object_mismatch_refuses_source_bound(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            original = selector._run_git

            def mismatched(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[1][0] == "diff-tree":
                    fields = result.stdout.split(b"\0")
                    header = fields[0].split(b" ")
                    header[2] = b"1" * 40
                    fields[0] = b" ".join(header)
                    return subprocess.CompletedProcess(
                        result.args,
                        result.returncode,
                        b"\0".join(fields),
                        result.stderr,
                    )
                return result

            with mock.patch.object(
                selector, "_run_git", side_effect=mismatched
            ):
                refusal = self.assertRefusal(
                    "source.diff-ambiguous",
                    selector.staged_source,
                    fixture.repo,
                    fixture.index,
                )
            self.assertTrue(refusal.source_bound)

    def test_sanitized_git_environment_and_diff_flags(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            sentinel = fixture.root / "external-diff-ran"
            external = fixture.root / "external-diff.sh"
            external.write_text(
                f"#!/bin/sh\n: > {sentinel!s}\n", encoding="utf-8"
            )
            external.chmod(0o700)
            fixture.git("config", "diff.external", str(external))
            attributes = fixture.root / "attributes"
            attributes.write_text(
                "README.md diff=fixture\n", encoding="utf-8"
            )
            fixture.git(
                "config", "core.attributesFile", str(attributes)
            )
            fixture.git(
                "config", "diff.fixture.textconv", str(external)
            )
            observed: list[tuple[tuple[str, ...], set[str]]] = []
            original = selector._run_git

            def observing(*args, **kwargs):
                arguments = tuple(args[1])
                env = kwargs["env"]
                observed.append(
                    (
                        arguments,
                        {
                            key
                            for key in env
                            if key.startswith("GIT_")
                        },
                    )
                )
                return original(*args, **kwargs)

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_EXTERNAL_DIFF": str(external),
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "diff.external",
                    "GIT_CONFIG_VALUE_0": str(external),
                },
            ), mock.patch.object(
                selector, "_run_git", side_effect=observing
            ):
                selector.staged_source(fixture.repo, fixture.index)
            self.assertFalse(sentinel.exists())
            for _arguments, keys in observed:
                self.assertLessEqual(
                    keys, selector.ALLOWED_GIT_ENVIRONMENT
                )
                self.assertNotIn("GIT_EXTERNAL_DIFF", keys)
                self.assertNotIn("GIT_CONFIG_COUNT", keys)
            diff_args = next(
                arguments
                for arguments, _keys in observed
                if arguments[0] == "diff-tree"
            )
            self.assertIn("--no-renames", diff_args)
            self.assertIn("--no-ext-diff", diff_args)
            self.assertIn("--no-textconv", diff_args)

    def test_movement_and_copy_without_similarity_detection(self) -> None:
        # Movement case uses a fresh candidate index after adding the source
        # to the fixture's real base.
        with StagedRepo() as fixture:
            fixture.write(b"docs/source.md", b"same\n")
            fixture.git("add", "docs/source.md")
            fixture.git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-q",
                "-m",
                "source",
            )
            shutil.copy2(
                fixture.repo / ".git" / "index", fixture.index
            )
            os.rename(
                fixture.repo / "docs" / "source.md",
                fixture.repo / "docs" / "moved.md",
            )
            fixture.git("add", "-A", index=True)
            _source, changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            movement = [
                (
                    change.status,
                    (
                        change.new_path.raw
                        if change.new_path
                        else change.old_path.raw
                    ),
                )
                for change in changes
                if (
                    (change.new_path and b"moved.md" in change.new_path.raw)
                    or (
                        change.old_path
                        and b"source.md" in change.old_path.raw
                    )
                )
            ]
            self.assertEqual(
                movement,
                [
                    ("delete", b"docs/source.md"),
                    ("add", b"docs/moved.md"),
                ],
            )

        with StagedRepo() as fixture:
            fixture.write(b"docs/copy.md", b"base\n")
            fixture.stage(b"docs/copy.md")
            _source, changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            copy_change = next(
                item
                for item in changes
                if item.new_path and item.new_path.raw == b"docs/copy.md"
            )
            self.assertEqual(copy_change.status, "add")

    def test_candidate_tree_digest_is_exact_and_display_independent(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"docs/new.md", b"new\n")
            fixture.stage(b"docs/new.md")
            source, _changes = selector.staged_source(
                fixture.repo, fixture.index
            )
            rows = [
                item.to_digest_object()
                for item in source._candidate_entries or ()
            ]
            expected = (
                "sha256:"
                + hashlib.sha256(contracts.canonical_json(rows)).hexdigest()
            )
            self.assertEqual(source.candidate_tree_sha256, expected)
            with_display = [
                {
                    **item.to_digest_object(),
                    "path_utf8": item.path.path_utf8,
                }
                for item in source._candidate_entries or ()
            ]
            without_display = [
                {
                    key: value
                    for key, value in item.items()
                    if key != "path_utf8"
                }
                for item in with_display
            ]
            self.assertEqual(rows, without_display)

    def test_forbidden_absolute_external_and_private_paths_refuse(self) -> None:
        for raw in (
            b"/absolute",
            b"/Users/private/file",
            b"/private/tmp/file",
            b"../external",
            b"a/../../external",
            b"a//b",
            b"./relative",
        ):
            with self.subTest(path=raw):
                with self.assertRaises(contracts.ContractError):
                    selector.PathIdentity.from_bytes(raw)

    def test_real_object_store_is_byte_unchanged_and_temp_is_clean(self) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            objects = fixture.object_directory()
            before = selector.object_store_digest(objects)
            temp_parent = fixture.root / "owned-temp"
            temp_parent.mkdir()
            prior = tempfile.tempdir
            tempfile.tempdir = str(temp_parent)
            try:
                source, _changes = selector.staged_source(
                    fixture.repo, fixture.index
                )
            finally:
                tempfile.tempdir = prior
            after = selector.object_store_digest(objects)
            self.assertEqual(before, after)
            self.assertTrue(source.index_tree_sha)
            self.assertEqual(list(temp_parent.iterdir()), [])
            self.assertFalse(
                list(fixture.repo.rglob("__pycache__"))
            )
            self.assertFalse(list(fixture.repo.rglob("*.pyc")))

    def test_candidate_write_tree_uses_owned_objects_and_read_only_alternate(
        self,
    ) -> None:
        with StagedRepo() as fixture:
            fixture.write(b"README.md", b"changed\n")
            fixture.stage(b"README.md")
            real_objects = fixture.object_directory().resolve()
            writes: list[tuple[Path, Path]] = []
            original = selector._run_git

            def observing(*args, **kwargs):
                arguments = args[1]
                env = kwargs["env"]
                if arguments[0] in ("write-tree", "mktree"):
                    writes.append(
                        (
                            Path(env["GIT_OBJECT_DIRECTORY"]).resolve(),
                            Path(
                                env["GIT_ALTERNATE_OBJECT_DIRECTORIES"]
                            ).resolve(),
                        )
                    )
                return original(*args, **kwargs)

            with mock.patch.object(
                selector, "_run_git", side_effect=observing
            ):
                selector.staged_source(fixture.repo, fixture.index)
            self.assertTrue(writes)
            for object_directory, alternate in writes:
                self.assertNotEqual(object_directory, real_objects)
                self.assertEqual(alternate, real_objects)


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.value = copy.deepcopy(
            selector.load_manifest(MANIFEST_PATH).value
        )
        cls.entries = live_candidate_entries()
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def selection(
        self,
        value: dict,
        specs: list[
            tuple[str, bytes, bytes | None, bytes | None, str, str]
        ],
        *,
        requested_mode: str = "focused_local",
    ) -> selector.Selection:
        source, changes = source_for_changes(
            value, self.entries, specs
        )
        return selector.select(
            value, source, changes, "local", requested_mode
        )

    def test_focus_predicate_is_pure_and_conservative(self) -> None:
        for case in self.cases["focus_cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    selector.focus_eligible(
                        case["tags"],
                        case["graduated_tags"],
                        ambiguous=case["ambiguous"],
                        control_change=case["control_change"],
                    ),
                    case["expected"],
                )

    def test_m1_manifest_never_grants_focused_authority(self) -> None:
        result = self.selection(
            self.value,
            [
                (
                    "modify",
                    b"README.md",
                    b'{"old":1}',
                    b'{"old":2}',
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(result.focus_eligible)
        self.assertEqual(result.effective_mode, "full")
        self.assertEqual(result.fallback_executor, "preserved.full")
        self.assertIn("selector.lane-shadow", result.diagnostic_codes)
        self.assertIn(
            "selector.tags-ungraduated", result.diagnostic_codes
        )

    def test_current_source_changes_keep_full_shadow_authority(self) -> None:
        for path in (
            b".planning/doc-warden.json",
            b"_ops/interoperability/native_rules.py",
            b"_ops/portability/engine.py",
            b"scripts/verify.py",
            b"tests/test_ci.py",
        ):
            with self.subTest(path=path):
                result = self.selection(
                    self.value,
                    [("modify", path, b"before", b"after", "100644", "100644")],
                )
                self.assertTrue(result.selector_control_ok)
                self.assertIn("dev.structure", result.focused_obligation_ids)
                self.assertFalse(result.focus_eligible)
                self.assertEqual(result.effective_mode, "full")
                self.assertEqual(result.fallback_executor, "preserved.full")
                self.assertIn("selector.lane-shadow", result.diagnostic_codes)

    def test_unproven_enforce_manifest_still_cannot_grant_m1_focus(
        self,
    ) -> None:
        value = copy.deepcopy(self.value)
        value["activation"]["lanes"][0] = {
            "lane": "local",
            "policy": "enforce",
            "graduated_tags": ["change.docs-ordinary"],
        }
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(result.selector_control_ok)
        self.assertFalse(result.focus_eligible)
        self.assertEqual(result.effective_mode, "full")
        self.assertEqual(result.fallback_executor, "preserved.full")

    def test_matching_input_rules_conservatively_union_owners(self) -> None:
        value = add_input_rule(
            self.value,
            input_rule(
                "fixture.readme-shared",
                b"README.md",
                ["context.measurement"],
                tags=["change.docs-ordinary"],
            ),
        )
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertIn("doc.full-compat", result.focused_obligation_ids)
        self.assertIn("context.measurement", result.focused_obligation_ids)
        context = next(
            item
            for item in result.decisions
            if item.obligation_id == "context.measurement"
        )
        self.assertIn("direct", context.selection_causes)

    def test_base_and_candidate_manifests_union_old_new_owners(
        self,
    ) -> None:
        candidate = copy.deepcopy(self.value)
        readme_rule = next(
            item
            for item in candidate["input_rules"]
            if item["id"] == "area.root.readme"
        )
        readme_rule["owner_obligation_ids"] = [
            "context.measurement"
        ]
        candidate = reidentify(candidate)
        base_bytes = contracts.canonical_json(self.value)
        candidate_bytes = contracts.canonical_json(candidate)
        source, changes = source_for_changes(
            candidate,
            self.entries,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                ),
                (
                    "modify",
                    selector.MANIFEST_RELATIVE_PATH,
                    base_bytes,
                    candidate_bytes,
                    "100644",
                    "100644",
                ),
            ],
        )
        source = replace(
            source,
            _base_manifest_bytes=base_bytes,
            _base_manifest_schema_bytes=SCHEMA_PATH.read_bytes(),
        )
        result = selector.select(
            candidate, source, changes, "local", "focused_local"
        )
        direct = {
            item.obligation_id
            for item in result.decisions
            if "direct" in item.selection_causes
        }
        self.assertIn("doc.full-compat", direct)
        self.assertIn("context.measurement", direct)
        self.assertEqual(result.effective_mode, "full")

    def test_inert_only_change_has_explicit_inert_tag_and_cause(self) -> None:
        value = copy.deepcopy(self.value)
        value["inert_rules"] = [
            {
                "id": "fixture.inert",
                "matcher": {
                    "kind": "exact",
                    "value_b64": base64.b64encode(
                        b"fixture/inert.txt"
                    ).decode(),
                },
                "reason_code": "inert",
            }
        ]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "add",
                    b"fixture/inert.txt",
                    None,
                    b"inert",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertEqual(result.change_tags, ("inert",))
        self.assertTrue(
            any(
                "inert" in item.selection_causes
                for item in result.decisions
            )
        )
        self.assertEqual(result.effective_mode, "full")

    def test_unmatched_and_owner_inert_overlap_force_full_red(self) -> None:
        unmatched = self.selection(
            self.value,
            [
                (
                    "add",
                    b"fixture/unmatched.txt",
                    None,
                    b"x",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(unmatched.selector_control_ok)
        self.assertEqual(unmatched.effective_mode, "full")
        self.assertIn(
            "selector.control-failed", unmatched.diagnostic_codes
        )

        value = add_input_rule(
            self.value,
            input_rule(
                "fixture.overlap",
                b"fixture/overlap.txt",
                ["doc.full-compat"],
            ),
        )
        value["inert_rules"] = [
            {
                "id": "fixture.inert",
                "matcher": {
                    "kind": "exact",
                    "value_b64": base64.b64encode(
                        b"fixture/overlap.txt"
                    ).decode(),
                },
                "reason_code": "inert",
            }
        ]
        value = reidentify(value)
        overlap = self.selection(
            value,
            [
                (
                    "add",
                    b"fixture/overlap.txt",
                    None,
                    b"x",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(overlap.selector_control_ok)
        self.assertEqual(overlap.effective_mode, "full")

    def test_control_change_forces_self_protected_full(self) -> None:
        result = self.selection(
            self.value,
            [
                (
                    "modify",
                    b"Makefile",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(result.focus_eligible)
        self.assertTrue(result.selector_control_ok)
        self.assertEqual(result.effective_mode, "full")
        self.assertIn(
            "selector.self-protection", result.diagnostic_codes
        )
        self.assertTrue(
            all(
                "self_protection" in item.selection_causes
                for item in result.decisions
                if item.obligation_id
                in result.effective_obligation_ids
            )
        )

    def test_classification_tags_never_select_obligations(self) -> None:
        baseline = self.selection(
            self.value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        value = copy.deepcopy(self.value)
        rule = next(
            item
            for item in value["input_rules"]
            if item["id"] == "area.root.readme"
        )
        rule["classification_tags"] = ["totally.different"]
        value = reidentify(value)
        changed = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertEqual(
            baseline.focused_obligation_ids,
            changed.focused_obligation_ids,
        )
        self.assertNotEqual(baseline.change_tags, changed.change_tags)

    def test_delete_reverse_consumers_then_forward_prerequisites(self) -> None:
        value = copy.deepcopy(self.value)
        context = next(
            item
            for item in value["obligations"]
            if item["id"] == "context.measurement"
        )
        context["depends_on"] = [
            "dev.structure",
            "doc.full-compat",
        ]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "delete",
                    b"README.md",
                    b"old",
                    None,
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertIn("context.measurement", result.focused_obligation_ids)
        decision = next(
            item
            for item in result.decisions
            if item.obligation_id == "context.measurement"
        )
        self.assertIn("reverse_impact", decision.selection_causes)
        self.assertLess(
            result.focused_obligation_ids.index("dev.structure"),
            result.focused_obligation_ids.index("doc.full-compat"),
        )
        self.assertLess(
            result.focused_obligation_ids.index("doc.full-compat"),
            result.focused_obligation_ids.index(
                "context.measurement"
            ),
        )

    def test_shared_input_reverse_consumers_are_conservative(self) -> None:
        value = add_input_rule(
            self.value,
            input_rule(
                "fixture.readme-shared",
                b"README.md",
                ["doc.full-compat", "pr.legacy"],
                tags=["change.docs-ordinary"],
            ),
        )
        value = copy.deepcopy(value)
        pr_v3 = next(
            item
            for item in value["obligations"]
            if item["id"] == "pr.v3"
        )
        pr_v3["depends_on"] = ["dev.structure", "pr.legacy"]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertIn("pr.v3", result.focused_obligation_ids)
        decision = next(
            item
            for item in result.decisions
            if item.obligation_id == "pr.v3"
        )
        self.assertIn("reverse_impact", decision.selection_causes)

    def test_delete_add_movement_unions_old_and_new_owners(self) -> None:
        result = self.selection(
            self.value,
            [
                (
                    "delete",
                    b"README.md",
                    b"same",
                    None,
                    "100644",
                    "100644",
                ),
                (
                    "add",
                    b"capabilities/moved.sh",
                    None,
                    b"same",
                    "100644",
                    "100644",
                ),
            ],
        )
        self.assertIn("doc.full-compat", result.focused_obligation_ids)
        self.assertIn(
            "snowkit.host-lifecycle", result.focused_obligation_ids
        )
        self.assertIn("dev.structure", result.focused_obligation_ids)

    def test_copy_is_add_and_selects_new_path_owner(self) -> None:
        result = self.selection(
            self.value,
            [
                (
                    "add",
                    b"docs/copy.md",
                    None,
                    b"copied",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertIn("doc.full-compat", result.focused_obligation_ids)
        self.assertNotIn(
            "snowkit.host-lifecycle",
            [
                item.obligation_id
                for item in result.decisions
                if "direct" in item.selection_causes
            ],
        )

    def test_unknown_cycle_and_ineligible_dependency_force_full(self) -> None:
        variants: dict[str, dict] = {}
        unknown = copy.deepcopy(self.value)
        next(
            item
            for item in unknown["obligations"]
            if item["id"] == "doc.full-compat"
        )["depends_on"] = ["unknown.obligation"]
        variants["unknown"] = reidentify(unknown)

        cycle = copy.deepcopy(self.value)
        next(
            item
            for item in cycle["obligations"]
            if item["id"] == "dev.structure"
        )["depends_on"] = ["doc.full-compat"]
        variants["cycle"] = reidentify(cycle)

        ineligible = copy.deepcopy(self.value)
        next(
            item
            for item in ineligible["obligations"]
            if item["id"] == "doc.full-compat"
        )["eligible_in"] = list(contracts.MANIFEST_MODES)
        variants["ineligible"] = reidentify(ineligible)

        for name, value in variants.items():
            with self.subTest(case=name):
                result = self.selection(
                    value,
                    [
                        (
                            "modify",
                            b"README.md",
                            b"old",
                            b"new",
                            "100644",
                            "100644",
                        )
                    ],
                )
                self.assertFalse(result.selector_control_ok)
                self.assertEqual(result.effective_mode, "full")
                self.assertIn(
                    "selector.control-failed",
                    result.diagnostic_codes,
                )

    def test_missing_capability_blocks_and_forces_full(self) -> None:
        value = copy.deepcopy(self.value)
        doc = next(
            item
            for item in value["obligations"]
            if item["id"] == "doc.full-compat"
        )
        doc["applicability"]["required_capabilities"] = [
            "missing.runtime"
        ]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(result.selector_control_ok)
        self.assertEqual(result.effective_mode, "full")
        self.assertIn(
            "selector.capability-blocked", result.diagnostic_codes
        )
        decision = next(
            item
            for item in result.decisions
            if item.obligation_id == "doc.full-compat"
        )
        self.assertEqual(decision.focused_disposition, "blocked")
        self.assertIn("fallback", decision.selection_causes)

    def test_empty_change_set_never_claims_narrow_completeness(self) -> None:
        source, changes = source_for_changes(
            self.value, self.entries, []
        )
        result = selector.select(
            self.value, source, changes, "local", "focused_local"
        )
        self.assertFalse(result.selector_control_ok)
        self.assertFalse(result.focus_eligible)
        self.assertEqual(result.effective_mode, "full")
        self.assertIn(
            "selector.empty-change-set", result.diagnostic_codes
        )

    def test_empty_change_tag_set_forces_full_red(self) -> None:
        value = copy.deepcopy(self.value)
        next(
            item
            for item in value["input_rules"]
            if item["id"] == "area.root.readme"
        )["classification_tags"] = []
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(result.selector_control_ok)
        self.assertFalse(result.focus_eligible)
        self.assertEqual(result.effective_mode, "full")
        self.assertIn(
            "selector.empty-change-tags", result.diagnostic_codes
        )

    def test_incomplete_change_set_forces_full_red(self) -> None:
        source, _changes = source_for_changes(
            self.value,
            self.entries,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        result = selector.select(
            self.value, source, (), "local", "focused_local"
        )
        self.assertFalse(result.selector_control_ok)
        self.assertEqual(result.effective_mode, "full")
        self.assertIn(
            "selector.control-failed", result.diagnostic_codes
        )

    def test_invalid_source_never_claims_source_bound_fallback(self) -> None:
        source, changes = source_for_changes(
            self.value,
            self.entries,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        source = replace(source, candidate_tree_sha256=ZERO_DIGEST)
        result = selector.select(
            self.value,
            source,
            changes,
            "local",
            "focused_local",
        )
        self.assertFalse(result.selector_control_ok)
        self.assertEqual(result.effective_mode, "full")
        self.assertIsNone(result.fallback_executor)

    def test_optional_path_display_is_never_serialized_for_identity(
        self,
    ) -> None:
        with_display = selector.PathIdentity.from_bytes(b"README.md")
        without_display = selector.PathIdentity(
            with_display.path_b64, None
        )
        common = {
            "status": "add",
            "old_path": None,
            "old_mode": None,
            "new_mode": "100644",
            "old_blob_sha256": None,
            "new_blob_sha256": str(contracts.sha256_id(b"x")),
        }
        displayed = selector.Change(
            new_path=with_display,
            **common,
        )
        authoritative = selector.Change(
            new_path=without_display,
            **common,
        )
        self.assertEqual(displayed.to_object(), authoritative.to_object())
        self.assertEqual(
            displayed.to_object()["new_path"],
            {"path_b64": with_display.path_b64},
        )

    def test_semantic_selector_any_baseline_match_adds_only(self) -> None:
        value = copy.deepcopy(self.value)
        value["semantic_selectors"] = [
            {
                "id": "fixture.json",
                "baseline_input_rule_ids": [
                    "area.root.manual",
                    "area.root.readme",
                ],
                "parser": "json_pointer_changes_v1",
                "limits": dict(contracts.LIMITS),
                "pointer_rules": [
                    {
                        "pointer": "/feature",
                        "match": "descendant_prefix",
                        "add_obligation_ids": [
                            "context.measurement"
                        ],
                    }
                ],
            }
        ]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b'{"feature":{"enabled":false},"other":1}',
                    b'{"feature":{"enabled":true},"other":1}',
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertIn("doc.full-compat", result.focused_obligation_ids)
        self.assertIn(
            "context.measurement", result.focused_obligation_ids
        )
        direct = {
            item.obligation_id
            for item in result.decisions
            if "direct" in item.selection_causes
        }
        self.assertIn("doc.full-compat", direct)
        self.assertIn("context.measurement", direct)

    def test_semantic_selector_nonmatching_pointer_preserves_baseline_owner(
        self,
    ) -> None:
        value = copy.deepcopy(self.value)
        value["semantic_selectors"] = [
            {
                "id": "fixture.json",
                "baseline_input_rule_ids": ["area.root.readme"],
                "parser": "json_pointer_changes_v1",
                "limits": dict(contracts.LIMITS),
                "pointer_rules": [
                    {
                        "pointer": "/feature",
                        "match": "exact",
                        "add_obligation_ids": [
                            "context.measurement"
                        ],
                    }
                ],
            }
        ]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b'{"other":1}',
                    b'{"other":2}',
                    "100644",
                    "100644",
                )
            ],
        )
        direct = {
            item.obligation_id
            for item in result.decisions
            if "direct" in item.selection_causes
        }
        self.assertIn("doc.full-compat", direct)
        self.assertNotIn("context.measurement", direct)

    def test_invalid_baseline_rule_id_shapes_force_full_red(self) -> None:
        valid_selector = {
            "id": "fixture.json",
            "baseline_input_rule_ids": ["area.root.readme"],
            "parser": "json_pointer_changes_v1",
            "limits": dict(contracts.LIMITS),
            "pointer_rules": [],
        }
        variants = {
            "missing": lambda item: item.pop(
                "baseline_input_rule_ids"
            ),
            "empty": lambda item: item.__setitem__(
                "baseline_input_rule_ids", []
            ),
            "duplicate": lambda item: item.__setitem__(
                "baseline_input_rule_ids",
                ["area.root.readme", "area.root.readme"],
            ),
            "unsorted": lambda item: item.__setitem__(
                "baseline_input_rule_ids",
                ["area.root.readme", "area.root.manual"],
            ),
            "unknown": lambda item: item.__setitem__(
                "baseline_input_rule_ids", ["unknown.input"]
            ),
        }
        for name, mutate in variants.items():
            with self.subTest(case=name):
                value = copy.deepcopy(self.value)
                semantic = copy.deepcopy(valid_selector)
                mutate(semantic)
                value["semantic_selectors"] = [semantic]
                value = reidentify(value)
                result = self.selection(
                    value,
                    [
                        (
                            "modify",
                            b"README.md",
                            b'{"a":1}',
                            b'{"a":2}',
                            "100644",
                            "100644",
                        )
                    ],
                )
                self.assertFalse(result.selector_control_ok)
                self.assertEqual(result.effective_mode, "full")

    def test_json_refusal_and_every_frozen_limit_force_full_red(self) -> None:
        value = copy.deepcopy(self.value)
        value["semantic_selectors"] = [
            {
                "id": "fixture.json",
                "baseline_input_rule_ids": ["area.root.readme"],
                "parser": "json_pointer_changes_v1",
                "limits": dict(contracts.LIMITS),
                "pointer_rules": [],
            }
        ]
        value = reidentify(value)
        too_deep = b"[" * 65 + b"0" + b"]" * 65
        too_many_nodes = (
            b"["
            + b",".join([b"0"] * contracts.LIMITS["max_nodes"])
            + b"]"
        )
        too_many_pointers_old = (
            b"{"
            + b",".join(
                f'\"k{i}\":0'.encode()
                for i in range(
                    contracts.LIMITS["max_changed_pointers"]
                )
            )
            + b"}"
        )
        too_many_pointers_new = too_many_pointers_old.replace(
            b":0", b":1"
        )
        cases = {
            "bom": (b'{"a":1}', b'\xef\xbb\xbf{"a":2}'),
            "invalid-utf8": (b'{"a":1}', b'{"a":"\xff"}'),
            "duplicate": (b'{"a":1}', b'{"a":1,"a":2}'),
            "invalid-number": (b'{"a":1}', b'{"a":NaN}'),
            "blob-bytes": (
                b"{}",
                b" " * (contracts.LIMITS["max_blob_bytes"] + 1),
            ),
            "depth": (b"[]", too_deep),
            "decoder-recursion": (
                b"[]",
                b"[" * 2000 + b"0" + b"]" * 2000,
            ),
            "nodes": (b"[]", too_many_nodes),
            "pointers": (
                too_many_pointers_old,
                too_many_pointers_new,
            ),
            "number-token": (
                b'{"a":0}',
                b'{"a":'
                + b"1" * (contracts.LIMITS["max_number_chars"] + 1)
                + b"}",
            ),
        }
        for name, (old, new) in cases.items():
            with self.subTest(case=name):
                result = self.selection(
                    value,
                    [
                        (
                            "modify",
                            b"README.md",
                            old,
                            new,
                            "100644",
                            "100644",
                        )
                    ],
                )
                self.assertFalse(result.selector_control_ok)
                self.assertEqual(result.effective_mode, "full")
                self.assertIn(
                    "selector.classification-failed",
                    result.diagnostic_codes,
                )

    def test_json_pointer_add_delete_modify_arrays_and_escaping(self) -> None:
        cases = [
            (
                None,
                b'{"a":1}',
                [""],
            ),
            (
                b'{"a":1}',
                None,
                [""],
            ),
            (
                b'{"a":{"b":1}}',
                b'{"a":{"b":2}}',
                ["", "/a", "/a/b"],
            ),
            (
                b'{"a":[1,2]}',
                b'{"a":[1,3]}',
                ["", "/a"],
            ),
            (
                b'{"a":1}',
                b'{"a":{"b":1}}',
                ["", "/a"],
            ),
            (
                b'{"a/b":{"~key":1}}',
                b'{"a/b":{"~key":2}}',
                ["", "/a~1b", "/a~1b/~0key"],
            ),
        ]
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                self.assertEqual(
                    contracts.classify_json_pointer_changes(old, new),
                    expected,
                )

    def test_json_pointer_exact_and_descendant_prefix_matching(self) -> None:
        self.assertTrue(
            contracts.pointer_rule_matches(
                "/a", "exact", "/a"
            )
        )
        self.assertFalse(
            contracts.pointer_rule_matches(
                "/a", "exact", "/a/b"
            )
        )
        self.assertTrue(
            contracts.pointer_rule_matches(
                "/a", "descendant_prefix", "/a/b"
            )
        )
        self.assertFalse(
            contracts.pointer_rule_matches(
                "/a", "descendant_prefix", "/ab"
            )
        )
        self.assertTrue(
            contracts.pointer_rule_matches(
                "", "descendant_prefix", "/anything"
            )
        )

    def test_unsupported_parser_forces_full_red(self) -> None:
        value = copy.deepcopy(self.value)
        value["semantic_selectors"] = [
            {
                "id": "fixture.unsupported",
                "baseline_input_rule_ids": ["area.root.readme"],
                "parser": "yaml.magic",
                "limits": dict(contracts.LIMITS),
                "pointer_rules": [],
            }
        ]
        value = reidentify(value)
        result = self.selection(
            value,
            [
                (
                    "modify",
                    b"README.md",
                    b"old",
                    b"new",
                    "100644",
                    "100644",
                )
            ],
        )
        self.assertFalse(result.selector_control_ok)
        self.assertEqual(result.effective_mode, "full")

    def test_plan_order_and_repeated_run_identity_are_deterministic(self) -> None:
        specs = [
            (
                "modify",
                b"README.md",
                b"old",
                b"new",
                "100644",
                "100644",
            )
        ]
        first = self.selection(self.value, specs)
        second = self.selection(self.value, specs)
        self.assertEqual(first.to_plan(), second.to_plan())
        self.assertEqual(
            contracts.canonical_json(first.to_plan()),
            contracts.canonical_json(second.to_plan()),
        )
        self.assertLess(
            first.focused_obligation_ids.index("dev.structure"),
            first.focused_obligation_ids.index("doc.full-compat"),
        )

    def test_full_and_deep_modes_select_applicable_inventory_once(self) -> None:
        specs = [
            (
                "modify",
                b"README.md",
                b"old",
                b"new",
                "100644",
                "100644",
            )
        ]
        for mode in ("full", "full_release", "deep_periodic"):
            with self.subTest(mode=mode):
                result = self.selection(
                    self.value, specs, requested_mode=mode
                )
                self.assertEqual(result.effective_mode, mode)
                self.assertEqual(
                    len(result.effective_obligation_ids),
                    len(set(result.effective_obligation_ids)),
                )
                self.assertTrue(result.effective_obligation_ids)

        value = copy.deepcopy(self.value)
        next(
            item
            for item in value["obligations"]
            if item["id"] == "doc.full-compat"
        )["deep_only"] = True
        value = reidentify(value)
        full = self.selection(value, specs, requested_mode="full")
        deep = self.selection(
            value, specs, requested_mode="deep_periodic"
        )
        self.assertNotIn(
            "doc.full-compat", full.effective_obligation_ids
        )
        self.assertIn(
            "doc.full-compat", deep.effective_obligation_ids
        )


if __name__ == "__main__":
    unittest.main()
