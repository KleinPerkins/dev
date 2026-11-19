from __future__ import annotations

from contextlib import contextmanager
from enum import StrEnum
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest import mock


HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures/mcp-migration.v1.json"
SPEC = importlib.util.spec_from_file_location("int014_mcp_migration", HERE / "mcp_migration.py")
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)


class OriginalSourceErrors(unittest.TestCase):
    def test_git_operational_failures_preserve_migration_error_channel(self):
        for error in (OSError('synthetic unavailable'), migration.subprocess.TimeoutExpired('git', 15)):
            with self.subTest(error=type(error).__name__), \
                 mock.patch.object(migration.original_sources, 'git_result', side_effect=error):
                with self.assertRaises(migration.MigrationError) as caught:
                    migration._verify_original_source(Path('/synthetic-unavailable-source'))
                self.assertEqual(str(caught.exception), 'mcp-migration:source_identity_mismatch')


class FakeReason(StrEnum):
    OWNERSHIP_UNKNOWN = "ownership_unknown"
    UNSUPPORTED_TRANSPORT = "unsupported_transport"


class FakeOwnership(StrEnum):
    ABSENT = "absent"
    UNKNOWN = "unknown"


class FakeRegistrarError(Exception):
    def __init__(self, *reason_codes: FakeReason):
        self.reason_codes = reason_codes
        self.code = reason_codes[0]
        super().__init__("bounded-fake-error")


class FakeIdentity:
    def __init__(self, *, source_owner, connection_id, source_revision, native_name):
        self.source_owner = source_owner
        self.connection_id = connection_id
        self.source_revision = source_revision
        self.native_name = native_name


class FakeDefinition:
    def __init__(self, identity, transport):
        self.identity = identity
        self.transport = transport
        self.digest = migration.digest_value(
            {
                "source_owner": identity.source_owner,
                "connection_id": identity.connection_id,
                "source_revision": identity.source_revision,
                "native_name": identity.native_name,
                "transport": transport.record,
            }
        )
        self.target_origin_digest = migration.digest_value(
            {"kind": transport.kind, "origin": transport.origin}
        )

    @classmethod
    def stdio(cls, identity, *, command, args=(), env=None):
        return cls(
            identity,
            SimpleNamespace(
                kind="stdio",
                origin=command,
                record={"kind": "stdio", "command": command, "args": list(args), "env": dict(env or {})},
            ),
        )

    @classmethod
    def streamable_http(cls, identity, *, url):
        return cls(
            identity,
            SimpleNamespace(
                kind="streamable-http",
                origin=url,
                record={"kind": "streamable-http", "url": url},
            ),
        )


class FakeAuthBinding:
    @classmethod
    def none(cls, **kwargs):
        return SimpleNamespace(**kwargs)


class FakeRegistrar:
    SURFACE = "cursor"
    write_during_preview = False

    def inspect_registration(self, path, *, context):
        if path.exists():
            return SimpleNamespace(
                ownership=FakeOwnership.UNKNOWN,
                reason_codes=(FakeReason.OWNERSHIP_UNKNOWN,),
            )
        return SimpleNamespace(ownership=FakeOwnership.ABSENT, reason_codes=())

    def preview(self, path, definition, *, context):
        if self.write_during_preview:
            (context.state_directory / "forbidden-write").write_text("mutation")
        if self.SURFACE == "claude" and definition.transport.kind == "streamable-http":
            raise FakeRegistrarError(FakeReason.UNSUPPORTED_TRANSPORT)
        proposed = (
            ["/command", "/args", "/env/INT014_PROFILE"]
            if definition.transport.kind == "stdio"
            else ["/url"]
        )
        existing = path.exists()
        return SimpleNamespace(
            conflicts=(FakeReason.OWNERSHIP_UNKNOWN,) if existing else (),
            owned_leaf_actions=tuple(SimpleNamespace(path=item) for item in proposed),
            preserved_paths=(
                "/enabled",
                "/tool_policy/allow",
                "/approval_policy",
                "/timeout",
                "/future/mode",
            ) if existing else (),
        )


class FakeCursorRegistrar(FakeRegistrar):
    SURFACE = "cursor"


class FakeCodexRegistrar(FakeRegistrar):
    SURFACE = "codex"


class FakeClaudeRegistrar(FakeRegistrar):
    SURFACE = "claude"


@contextmanager
def fake_fixture_context(registrar, definition, *, fixture_root, auth_binding):
    root = Path(tempfile.mkdtemp(prefix="fake-owner-fixture-", dir=fixture_root))
    try:
        root.chmod(0o700)
        state = root / "state"
        state.mkdir(mode=0o700)
        config = root / {"cursor": "mcp.json", "codex": "config.toml", "claude": ".claude.json"}[registrar.SURFACE]
        context = SimpleNamespace(state_directory=state)
        yield SimpleNamespace(root=root, config_path=config, state_directory=state, context=context)
    finally:
        shutil.rmtree(root)


def fake_api(*, writing=False):
    class Cursor(FakeCursorRegistrar):
        write_during_preview = writing

    class Codex(FakeCodexRegistrar):
        write_during_preview = writing

    class Claude(FakeClaudeRegistrar):
        write_during_preview = writing

    return migration.BoundOwnerAPI(
        registrar_classes=MappingProxyType({"cursor": Cursor, "codex": Codex, "claude": Claude}),
        SourceIdentity=FakeIdentity,
        RegistrationDefinition=FakeDefinition,
        AuthBinding=FakeAuthBinding,
        RegistrarError=FakeRegistrarError,
        fixture_context=fake_fixture_context,
    )


class CatalogAndBindingTests(unittest.TestCase):
    def test_fixture_is_closed_explicit_and_complete(self):
        request = migration.load_request(FIXTURE.resolve())
        self.assertEqual(request.fixture_id, "int014-mcp-migration-v1")
        self.assertEqual(len(request.catalog), 4)
        self.assertEqual(len(request.selection), 4)
        self.assertRegex(request.request_digest, r"^[0-9a-f]{64}$")

    def test_validated_request_stays_bound_after_caller_mutation(self):
        value = json.loads(FIXTURE.read_text())
        request = migration.validate_request(value)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            parent = Path(directory)
            before = migration.preview_migration(request, fake_api(), fixture_parent=parent)
            for row in value["catalog"]:
                transport = row.get("transport")
                if transport is None:
                    continue
                if transport["kind"] == "stdio":
                    transport["command"] = "/synthetic/changed-after-validation"
                    transport["args"].append("changed-after-validation")
                    transport["env"]["INT014_PROFILE"] = "changed-after-validation"
                else:
                    transport["url"] = "https://changed-after-validation.example.test/mcp"
            after = migration.preview_migration(request, fake_api(), fixture_parent=parent)
        self.assertEqual(before, after)
        for entry in request.catalog:
            if entry.transport is None:
                continue
            with self.assertRaises(TypeError):
                entry.transport["kind"] = "changed-after-validation"
            if entry.transport["kind"] == "stdio":
                with self.assertRaises(TypeError):
                    entry.transport["env"]["INT014_PROFILE"] = "changed-after-validation"
                with self.assertRaises((AttributeError, TypeError)):
                    entry.transport["args"].append("changed-after-validation")

    def test_non_string_management_values_refuse_with_bounded_error(self):
        for management in ([], {}, None, 1, False):
            with self.subTest(management=management):
                value = json.loads(FIXTURE.read_text())
                value["catalog"][0]["management"] = management
                with self.assertRaises(migration.MigrationError) as caught:
                    migration.validate_request(value)
                self.assertEqual(caught.exception.reason_codes, ("catalog_invalid",))

    def test_unknown_fields_duplicates_and_implicit_targets_refuse(self):
        value = json.loads(FIXTURE.read_text())
        with self.subTest("unknown field"), self.assertRaises(migration.MigrationError) as caught:
            migration.validate_request(dict(value, live_home="forbidden"))
        self.assertEqual(caught.exception.reason_codes, ("catalog_invalid",))

        duplicate = json.loads(FIXTURE.read_text())
        duplicate["catalog"].append(dict(duplicate["catalog"][0]))
        with self.subTest("duplicate identity"), self.assertRaises(migration.MigrationError):
            migration.validate_request(duplicate)

        implicit = json.loads(FIXTURE.read_text())
        implicit["selection"][0]["targets"] = []
        with self.subTest("implicit target"), self.assertRaises(migration.MigrationError) as caught:
            migration.validate_request(implicit)
        self.assertEqual(caught.exception.reason_codes, ("selection_invalid",))

    def test_catalog_owner_and_revision_must_match_exact_source_binding(self):
        owner_drift = json.loads(FIXTURE.read_text())
        owner_drift["catalog"][0]["owner"] = "KleinPerkins/not-kp-mcp"
        with self.assertRaises(migration.MigrationError) as caught:
            migration.validate_request(owner_drift)
        self.assertEqual(caught.exception.reason_codes, ("source_identity_mismatch",))

        revision_drift = json.loads(FIXTURE.read_text())
        revision_drift["catalog"][0]["source_revision"] = "0" * 40
        with self.assertRaises(migration.MigrationError) as caught:
            migration.validate_request(revision_drift)
        self.assertEqual(caught.exception.reason_codes, ("source_drift",))

    def test_duplicate_json_key_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text('{"schema":"one","schema":"two"}')
            with self.assertRaises(migration.MigrationError) as caught:
                migration.load_request(path.resolve())
        self.assertEqual(caught.exception.reason_codes, ("catalog_invalid",))

    def test_unavailable_and_drifted_package_refuse_before_import(self):
        missing = Path("/private/tmp/int014-missing-wheel.whl")
        with self.assertRaises(migration.MigrationError) as caught:
            migration.load_owner_api(missing, Path("/private/tmp/int014-missing-source"))
        self.assertEqual(caught.exception.reason_codes, ("package_unavailable",))

        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            wheel = Path(directory) / "kp_mcp_bootstrap-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"drifted package")
            with self.assertRaises(migration.MigrationError) as caught:
                migration.load_owner_api(wheel.resolve(), Path(directory).resolve())
        self.assertEqual(caught.exception.reason_codes, ("package_drift",))
        self.assertNotIn("kp_mcp_bootstrap", sys.modules)

    def test_missing_or_changed_source_identity_and_revision_refuse(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            wheel = root / "fixture.whl"
            wheel.write_bytes(b"synthetic exact-for-test")
            digest = migration.hashlib.sha256(wheel.read_bytes()).hexdigest()
            with mock.patch.object(migration, "WHEEL_SHA256", digest):
                with self.assertRaises(migration.MigrationError) as caught:
                    migration._verify_source_and_wheel(wheel.resolve(), root.resolve())
                self.assertEqual(caught.exception.reason_codes, ("source_unavailable",))

                responses = {
                    ("remote", "get-url", "origin"): b"git@github.com:KleinPerkins/not-kp-mcp.git\n",
                }
                with mock.patch.object(
                    migration,
                    "_git",
                    side_effect=lambda _repository, *args: responses[args],
                ):
                    with self.assertRaises(migration.MigrationError) as caught:
                        migration._verify_source_and_wheel(wheel.resolve(), root.resolve())
                self.assertEqual(caught.exception.reason_codes, ("source_identity_mismatch",))

                def drifted_git(_repository, *args):
                    if args == ("remote", "get-url", "origin"):
                        return b"git@github.com:KleinPerkins/kp-mcp.git\n"
                    if args[0] == "rev-parse":
                        return ("0" * 40 + "\n").encode()
                    raise AssertionError(args)

                with mock.patch.object(migration, "_git", side_effect=drifted_git), \
                     mock.patch.object(migration, "_verify_original_source"):
                    with self.assertRaises(migration.MigrationError) as caught:
                        migration._verify_source_and_wheel(wheel.resolve(), root.resolve())
                self.assertEqual(caught.exception.reason_codes, ("source_drift",))

    def test_changed_public_api_refuses(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            wheel = (Path(directory) / "fixture.whl").resolve()
            wheel.write_bytes(b"synthetic")
            package = SimpleNamespace(
                __version__=migration.PACKAGE_VERSION,
                __file__=str(wheel) + "/kp_mcp_bootstrap/__init__.py",
            )
            registrars = SimpleNamespace(
                __file__=str(wheel) + "/kp_mcp_bootstrap/registrars/__init__.py",
                SourceIdentity=FakeIdentity,
                RegistrationDefinition=FakeDefinition,
                AuthBinding=FakeAuthBinding,
                RegistrarError=FakeRegistrarError,
                fixture_context=fake_fixture_context,
                CursorRegistrar=FakeCursorRegistrar,
                CodexRegistrar=FakeCodexRegistrar,
                ClaudeRegistrar=FakeClaudeRegistrar,
            )
            with mock.patch.object(migration, "_verify_source_and_wheel"), mock.patch.object(
                migration.importlib,
                "import_module",
                side_effect=[package, registrars],
            ):
                with self.assertRaises(migration.MigrationError) as caught:
                    migration.load_owner_api(wheel, Path(directory).resolve())
        self.assertEqual(caught.exception.reason_codes, ("api_drift",))


class PreviewContractTests(unittest.TestCase):
    def setUp(self):
        self.request = migration.load_request(FIXTURE.resolve())

    def test_deterministic_redacted_preview_and_external_preservation(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            first = migration.preview_migration(
                self.request, fake_api(), fixture_parent=Path(parent).resolve()
            )
            second = migration.preview_migration(
                self.request, fake_api(), fixture_parent=Path(parent).resolve()
            )
        self.assertEqual(first, second)
        self.assertEqual(len(first["entries"]), 8)
        self.assertEqual(first["conflicts"], ["owner_conflict"])
        encoded = json.dumps(first, sort_keys=True)
        for forbidden in (
            "/opt/fixtures/never-executed",
            "https://mcp.example.invalid/mcp",
            "synthetic-profile",
        ):
            self.assertNotIn(forbidden, encoded)
        notion = next(row for row in first["entries"] if row["ids"]["connection_id"] == "app:notion")
        self.assertIn("external_owner", notion["reason_codes"])
        self.assertIn("owner_conflict", notion["reason_codes"])
        self.assertIn("local_registration_not_proposed", notion["reason_codes"])
        self.assertEqual(notion["proposed_owned_paths"], [])
        local_notion = next(
            row for row in first["entries"]
            if row["ids"]["connection_id"] == "kp-mcp:fixture-notion-local"
        )
        self.assertEqual(local_notion["conflicts"], ["owner_conflict"])
        self.assertIn("external_owner", local_notion["reason_codes"])
        self.assertIn("local_registration_not_proposed", local_notion["reason_codes"])
        self.assertEqual(local_notion["proposed_owned_paths"], [])
        remote_claude = next(
            row for row in first["entries"]
            if row["ids"]["connection_id"] == "kp-mcp:fixture-remote"
            and row["ids"]["adapter"] == "claude"
        )
        self.assertIn("unsupported_transport", remote_claude["reason_codes"])
        self.assertNotIn("preview_ready", remote_claude["reason_codes"])

    def test_unreceipted_matching_entries_stay_unowned_and_policy_paths_preserved(self):
        selected = json.loads(FIXTURE.read_text())
        selected["catalog"] = [selected["catalog"][0]]
        selected["selection"] = [selected["selection"][0]]
        request = migration.validate_request(selected)
        seeds = {
            ("kp-mcp:fixture-stdio", target): (
                "synthetic-" + target + "-disabled-tools-approval-timeout-unknown"
            ).encode()
            for target in ("cursor", "codex", "claude")
        }
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            result = migration.preview_migration(
                request,
                fake_api(),
                fixture_parent=Path(parent).resolve(),
                fixture_preimages=seeds,
            )
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("synthetic-cursor", encoded)
        for row in result["entries"]:
            self.assertIn("ownership_unknown", row["reason_codes"])
            self.assertIn("ownership_unknown", row["conflicts"])
            self.assertIn("preview_conflict", row["reason_codes"])
            self.assertIn("fixture_zero_writes", row["reason_codes"])
            self.assertEqual(
                set(row["preserved_paths"]),
                {"/enabled", "/tool_policy/allow", "/approval_policy", "/timeout", "/future/mode"},
            )

    def test_unselected_external_owner_still_blocks_selected_local_proposal(self):
        value = json.loads(FIXTURE.read_text())
        value["selection"] = [
            row
            for row in value["selection"]
            if row["connection_id"] == "kp-mcp:fixture-notion-local"
        ]
        request = migration.validate_request(value)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            result = migration.preview_migration(
                request, fake_api(), fixture_parent=Path(parent).resolve()
            )
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["conflicts"], ["owner_conflict"])
        local = result["entries"][0]
        self.assertEqual(local["ids"]["connection_id"], "kp-mcp:fixture-notion-local")
        self.assertEqual(local["conflicts"], ["owner_conflict"])
        self.assertIn("external_owner", local["reason_codes"])
        self.assertIn("local_registration_not_proposed", local["reason_codes"])
        self.assertEqual(local["proposed_owned_paths"], [])

    def test_transient_config_writes_refuse_even_when_bytes_are_restored(self):
        value = json.loads(FIXTURE.read_text())
        value["catalog"] = [value["catalog"][0]]
        value["selection"] = [{"connection_id": value["catalog"][0]["connection_id"], "targets": ["cursor"]}]
        request = migration.validate_request(value)
        original_preview = FakeRegistrar.preview

        def transient_preview(registrar, path, definition, *, context):
            preimage = path.read_bytes() if path.exists() else None
            path.write_bytes(b"synthetic-transient-write")
            if preimage is None:
                path.unlink()
            else:
                path.write_bytes(preimage)
            return original_preview(registrar, path, definition, context=context)

        for seeded in (False, True):
            with self.subTest(seeded=seeded), tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
                seeds = {(value["catalog"][0]["connection_id"], "cursor"): b"synthetic-preimage"} if seeded else None
                with mock.patch.object(FakeRegistrar, "preview", transient_preview):
                    with self.assertRaises(migration.MigrationError) as caught:
                        migration.preview_migration(
                            request, fake_api(), fixture_parent=Path(parent), fixture_preimages=seeds
                        )
                self.assertEqual(caught.exception.reason_codes, ("fixture_write_detected",))

    def test_unavailable_fixture_storage_returns_bounded_api_and_cli_error(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            private_parent = Path(directory)
            failure = PermissionError("synthetic-private-path:" + directory)
            with mock.patch.object(migration.tempfile, "TemporaryDirectory", side_effect=failure):
                with self.assertRaises(migration.MigrationError) as caught:
                    migration.preview_migration(self.request, fake_api(), fixture_parent=private_parent)
                self.assertEqual(caught.exception.reason_codes, ("fixture_unavailable",))
                output = io.StringIO()
                with mock.patch.object(migration, "load_request", return_value=self.request), mock.patch.object(
                    migration, "load_owner_api", return_value=fake_api()
                ), mock.patch.object(sys, "stdout", output):
                    exit_code = migration.main([
                        "--request", "/synthetic/request.json",
                        "--wheel", "/synthetic/owner.whl",
                        "--source-repository", "/synthetic/source",
                        "--fixture-parent", str(private_parent),
                    ])
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.getvalue())["reason_codes"], ["fixture_unavailable"])
        self.assertNotIn(directory, output.getvalue())
        self.assertNotIn("PermissionError", output.getvalue())

    def test_any_preview_write_refuses(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as parent:
            with self.assertRaises(migration.MigrationError) as caught:
                migration.preview_migration(
                    self.request,
                    fake_api(writing=True),
                    fixture_parent=Path(parent).resolve(),
                )
        self.assertEqual(caught.exception.reason_codes, ("fixture_write_detected",))


@unittest.skipUnless(
    os.environ.get("INT014_REQUIRE_OWNER_INTEGRATION") == "1",
    "exact owner wheel/Git integration requires explicit retained binding paths",
)
class ExactOwnerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (
            "INT014_KP_MCP_WHEEL",
            "INT014_KP_MCP_REPOSITORY",
            "INT014_FIXTURE_PARENT",
        )
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise AssertionError("explicit owner integration binding is incomplete")
        cls.wheel = Path(os.environ["INT014_KP_MCP_WHEEL"])
        cls.repository = Path(os.environ["INT014_KP_MCP_REPOSITORY"])
        cls.fixture_parent = Path(os.environ["INT014_FIXTURE_PARENT"])
        cls.api = migration.load_owner_api(cls.wheel, cls.repository)
        cls.request = migration.load_request(FIXTURE.resolve())

    def test_exact_binding_remote_support_external_owner_and_repeat_determinism(self):
        first = migration.preview_migration(
            self.request, self.api, fixture_parent=self.fixture_parent
        )
        second = migration.preview_migration(
            self.request, self.api, fixture_parent=self.fixture_parent
        )
        self.assertEqual(first, second)
        self.assertEqual(
            first["digests"],
            {
                "request": self.request.request_digest,
                "source_revision": migration.SOURCE_REVISION,
                "source_tree": migration.SOURCE_TREE,
                "package_tree": migration.PACKAGE_TREE,
                "wheel": migration.WHEEL_SHA256,
                "adapter_source": migration.ADAPTER_SOURCE_DIGEST,
            },
        )
        encoded = json.dumps(first, sort_keys=True)
        for forbidden in (
            "/opt/fixtures/never-executed",
            "https://mcp.example.invalid/mcp",
            "synthetic-profile",
        ):
            self.assertNotIn(forbidden, encoded)
        rows = {
            (row["ids"]["connection_id"], row["ids"]["adapter"]): row
            for row in first["entries"]
        }
        self.assertIn("preview_ready", rows[("kp-mcp:fixture-remote", "cursor")]["reason_codes"])
        self.assertIn("preview_ready", rows[("kp-mcp:fixture-remote", "codex")]["reason_codes"])
        self.assertIn(
            "unsupported_transport",
            rows[("kp-mcp:fixture-remote", "claude")]["reason_codes"],
        )
        external = rows[("app:notion", "codex")]
        local = rows[("kp-mcp:fixture-notion-local", "codex")]
        self.assertIn("external_owner", external["reason_codes"])
        self.assertEqual(external["conflicts"], ["owner_conflict"])
        self.assertEqual(local["conflicts"], ["owner_conflict"])
        self.assertIn("external_owner", local["reason_codes"])
        self.assertIn("local_registration_not_proposed", local["reason_codes"])
        self.assertEqual(local["proposed_owned_paths"], [])

    def test_exact_owner_preserves_unreceipted_policy_without_adoption_or_writes(self):
        value = json.loads(FIXTURE.read_text())
        value["catalog"] = [value["catalog"][0]]
        value["selection"] = [value["selection"][0]]
        request = migration.validate_request(value)
        command = "/opt/fixtures/never-executed"
        env_value = "synthetic-profile"
        seeds = {
            ("kp-mcp:fixture-stdio", "cursor"): json.dumps(
                {
                    "mcpServers": {
                        "fixture-stdio": {
                            "command": command,
                            "args": ["mcp"],
                            "env": {"INT014_PROFILE": env_value},
                            "enabled": False,
                            "tool_policy": {"allow": ["read-only"]},
                            "approval_policy": "always",
                            "timeout": 17,
                            "future": {"mode": "preserve"},
                        }
                    }
                },
                separators=(",", ":"),
            ).encode(),
            ("kp-mcp:fixture-stdio", "codex"): (
                '[mcp_servers."fixture-stdio"]\n'
                f'command = "{command}"\n'
                'args = ["mcp"]\n'
                'enabled = false\n'
                'approval_policy = "always"\n'
                'timeout = 17\n'
                'future = "preserve"\n'
                '\n[mcp_servers."fixture-stdio".env]\n'
                f'INT014_PROFILE = "{env_value}"\n'
                '\n[mcp_servers."fixture-stdio".tool_policy]\n'
                'allow = ["read-only"]\n'
            ).encode(),
            ("kp-mcp:fixture-stdio", "claude"): json.dumps(
                {
                    "mcpServers": {
                        "fixture-stdio": {
                            "type": "stdio",
                            "command": command,
                            "args": ["mcp"],
                            "env": {"INT014_PROFILE": env_value},
                            "enabled": False,
                            "tool_policy": {"allow": ["read-only"]},
                            "approval_policy": "always",
                            "timeout": 17,
                            "future": {"mode": "preserve"},
                        }
                    }
                },
                separators=(",", ":"),
            ).encode(),
        }
        first = migration.preview_migration(
            request,
            self.api,
            fixture_parent=self.fixture_parent,
            fixture_preimages=seeds,
        )
        second = migration.preview_migration(
            request,
            self.api,
            fixture_parent=self.fixture_parent,
            fixture_preimages=seeds,
        )
        self.assertEqual(first, second)
        encoded = json.dumps(first, sort_keys=True)
        self.assertNotIn(command, encoded)
        self.assertNotIn(env_value, encoded)
        for row in first["entries"]:
            self.assertIn("ownership_unknown", row["reason_codes"])
            self.assertIn("ownership_unknown", row["conflicts"])
            self.assertIn("preview_conflict", row["reason_codes"])
            self.assertIn("fixture_zero_writes", row["reason_codes"])
            self.assertTrue(
                {"/enabled", "/tool_policy/allow", "/approval_policy", "/timeout"}
                <= set(row["preserved_paths"]),
                row,
            )
            self.assertTrue(
                {"/future", "/future/mode"} & set(row["preserved_paths"]), row
            )

    def test_fixture_command_is_never_executed(self):
        with tempfile.TemporaryDirectory(prefix="int014-command-sentinel-", dir=self.fixture_parent) as directory:
            root = Path(directory)
            command = root / "must-not-run"
            sentinel = root / "executed"
            command.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n")
            command.chmod(0o700)
            value = json.loads(FIXTURE.read_text())
            value["catalog"] = [value["catalog"][0]]
            value["catalog"][0]["transport"]["command"] = str(command)
            value["catalog"][0]["targets"] = ["cursor"]
            value["selection"] = [{"connection_id": "kp-mcp:fixture-stdio", "targets": ["cursor"]}]
            request = migration.validate_request(value)
            result = migration.preview_migration(
                request, self.api, fixture_parent=self.fixture_parent
            )
            self.assertFalse(sentinel.exists())
            self.assertNotIn(str(command), json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
