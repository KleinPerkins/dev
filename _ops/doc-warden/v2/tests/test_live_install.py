import json
import os
import tempfile
import subprocess
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import doc_warden.live_install as live_install_module
from doc_warden.artifacts import apply_preview, consent_for, repository_profile
from doc_warden.canonical import canonical_json, digest_ref, parse_json_object
from doc_warden.codex_authoring import host_projection, host_transaction
from doc_warden.codex_authoring.native_authoring_transport import NativeAuthoringChannel
from doc_warden.codex_authoring.native_authoring_runner import RoleRequest, _role_dispatch
from doc_warden.gsd_adapter import CENTRAL_REPOSITORY_ID, CENTRAL_REPOSITORY_KEY as CURRENT_REPOSITORY_KEY
from doc_warden.live_install import (
    CENTRAL_REPOSITORY_KEY,
    GSD_COMMIT,
    GSD_NPM_INTEGRITY,
    GSD_PACKAGE,
    GSD_UPSTREAM_REPOSITORY,
    GSD_UPSTREAM_TARBALL,
    GSD_VERSION,
    M1_QUALIFICATION,
    QUALIFICATION_DIGEST_PATHS,
    apply_prepared_install,
    apply_install,
    doctor,
    doctor_observation_status,
    load_install_operation,
    prepare_install,
    prepare_uninstall,
    preview_doctor_receipt,
    preview_install,
    uninstall,
    validate_doctor_observation,
    validate_global_hooks,
    _runtime_writer,
)
from doc_warden.runtime_host import _toolchain, qualify_destination, read_destination_qualification, run_runtime_script
from doc_warden.scm import RepositoryIdentity
from fixture_factory import ROOT


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def cursor_sentinels(home: Path) -> dict[str, bytes]:
    values = {}
    for relative in (".cursor", ".gsd"):
        path = home / relative
        if path.exists():
            values.update(
                {f"{relative}/{key}": value for key, value in snapshot(path).items()}
            )
    return values


def runtime_digests(repo: Path) -> dict[str, str]:
    runtime = repo / "_ops/doc-warden/runtime/gsd-core"
    return {
        name: digest_ref((runtime / relative).read_bytes())
        for name, relative in QUALIFICATION_DIGEST_PATHS.items()
    }


def live_install_repository(root: Path):
    repo = root / "repo"
    runtime = repo / "_ops/doc-warden/runtime/gsd-core"
    qualification = (
        repo
        / "_ops/doc-warden/state/v2/runtime/gsd-core-v1.11.0-qualification.json"
    )
    runtime.mkdir(parents=True)
    qualification.parent.mkdir(parents=True)
    (repo / "README.md").write_text("fixture\n")
    source_runtime = ROOT / "_ops/doc-warden/runtime/gsd-core"
    for name in (
        "gsd-core-pin.json",
        "package-lock.json",
        "package.json",
        "runtime-interface.v1.json",
    ):
        (runtime / name).write_bytes((source_runtime / name).read_bytes())
    installer = runtime / "install.sh"
    installer.write_text("#!/bin/sh\nexit 0\n")
    installer.chmod(0o755)
    verifier = runtime / "tests/verify-binding.sh"
    verifier.parent.mkdir()
    verifier.write_text("#!/bin/sh\nexit 0\n")
    digests = {
        name: digest_ref((runtime / relative).read_bytes()).removeprefix(
            "sha256:"
        )
        for name, relative in QUALIFICATION_DIGEST_PATHS.items()
    }
    digests["verifier_sha256"] = digest_ref(
        verifier.read_bytes()
    ).removeprefix("sha256:")
    qualification.write_bytes(
        canonical_json(
            {
                "dependency_licenses": [
                    {
                        "integrity": GSD_NPM_INTEGRITY,
                        "license": "MIT",
                        "name": GSD_PACKAGE,
                        "optional": False,
                        "version": GSD_VERSION,
                    }
                ],
                "digests": digests,
                "git_commit": GSD_COMMIT,
                "license_review": {
                    "claude_agent_sdk": {
                        "classification": "Anthropic legal agreements apply",
                        "disposition": "reviewed",
                        "license_file": "Anthropic legal agreements",
                    },
                    "gsd_core": {
                        "classification": "MIT",
                        "disposition": "permitted_with_attribution",
                    },
                },
                "lifecycle_scripts": {
                    "executed": False,
                    "install_policy": "npm ci --ignore-scripts --omit=dev",
                    "package_scripts_present": True,
                },
                "npm_integrity": GSD_NPM_INTEGRITY,
                "package": GSD_PACKAGE,
                "qualification": M1_QUALIFICATION,
                "qualified_at": "2026-08-28T11:49:24Z",
                "schema": "doc-warden/gsd-runtime-qualification/v2",
                "toolchain": {
                    "node": "v26.4.0",
                    "npm": "11.17.0",
                    "platform": "darwin",
                },
                "upstream": {
                    "commit": f"{GSD_UPSTREAM_REPOSITORY}/commit/{GSD_COMMIT}",
                    "license": (
                        f"{GSD_UPSTREAM_REPOSITORY}/blob/{GSD_COMMIT}/LICENSE"
                    ),
                    "repository": GSD_UPSTREAM_REPOSITORY,
                    "tarball": GSD_UPSTREAM_TARBALL,
                },
                "version": GSD_VERSION,
            }
        )
    )
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Fixture"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "user.email",
            "fixture@example.invalid",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md", "_ops"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True
    )
    return repo, qualification


def live_install_fixture(root: Path):
    repo, qualification = live_install_repository(root)
    home = root / "home"
    data_home = root / "data"
    state_home = root / "state"
    with mock.patch.dict(
        "os.environ", {"XDG_STATE_HOME": str(state_home)}, clear=False
    ):
        preview = prepare_install(
            repo,
            home=home,
            data_home=data_home,
            operation_id=str(uuid.uuid4()),
        )
        operation = load_install_operation(
            preview["operation_id"], preview["action_digest"]
        )
    return repo, home, data_home, qualification, operation


def installed_runtime_fixture(root: Path):
    root = root.resolve(strict=True)
    repo, qualification = live_install_repository(root)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "git@github.com:KleinPerkins/dev-fixture.git",
        ],
        check=True,
    )
    home = root / "home"
    data_home = root / "data"
    runtime = repo / "_ops/doc-warden/runtime/gsd-core"
    release = data_home / "gsd-core/releases" / GSD_COMMIT
    release.mkdir(parents=True)
    interface = parse_json_object((runtime / "runtime-interface.v1.json").read_bytes())
    for skill in interface["host_skills"]:
        descriptor = home / ".cursor/skills" / skill["id"] / "SKILL.md"
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(f"# {skill['id']}\n", encoding="utf-8")
    package = release / "node_modules/@opengsd/gsd-core/package.json"
    package.parent.mkdir(parents=True)
    package.write_bytes(canonical_json({"name": GSD_PACKAGE, "version": GSD_VERSION}))
    shims = {}
    stable_bin = home / ".local/bin"
    stable_bin.mkdir(parents=True)
    for name in ("gsd-core", "gsd-tools", "gsd_run"):
        shim = release / "doc-warden-bin" / name
        shim.parent.mkdir(parents=True, exist_ok=True)
        shim.write_text(f"#!/bin/sh\n# {name}\n", encoding="utf-8")
        shim.chmod(0o755)
        (stable_bin / name).symlink_to(shim)
        shims[name] = {
            "path": str(shim),
            "sha256": digest_ref(shim.read_bytes()).removeprefix("sha256:"),
        }
    manifest = data_home / "gsd-core/doc-warden-manifest.json"
    manifest.write_bytes(
        canonical_json(
            {
                "schema": "doc-warden/gsd-install-manifest/v1",
                "owner": "doc-warden",
                "release_root": str(release),
                "cursor_root": str(home / ".cursor"),
                "pin_digest": digest_ref((runtime / "gsd-core-pin.json").read_bytes()).removeprefix(
                    "sha256:"
                ),
                "lock_digest": digest_ref((runtime / "package-lock.json").read_bytes()).removeprefix(
                    "sha256:"
                ),
                "interface_digest": digest_ref(
                    (runtime / "runtime-interface.v1.json").read_bytes()
                ).removeprefix("sha256:"),
                "defaults_preimage": {"state": "absent"},
                "shims": shims,
            }
        )
    )
    return repo, home, data_home, qualification, manifest


def live_install_consent(operation):
    now = datetime.now(timezone.utc)
    return {
        "schema": "doc-warden/consent-envelope/v1",
        "operation_id": operation.operation_id,
        "repository_key": operation.repository_key,
        "canonical_root": operation.canonical_root,
        "source_revision": operation.source_revision,
        "action_digest": operation.action_digest,
        "consequence_class": "external",
        "nonce": str(uuid.uuid4()),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "choice": "apply",
    }


def fake_gh_bin(root: Path) -> Path:
    directory = root / "fake-bin"
    directory.mkdir()
    gh = directory / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        "'{\"id\":1278387789,\"full_name\":\"KleinPerkins/dev-fixture\"}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return directory


def run_doc_warden_cli(*arguments, extra_env=None, check=True):
    wrapper = ROOT / "_ops/bin/doc-warden.sh"
    return subprocess.run(
        ["bash", str(wrapper), *arguments],
        text=True,
        capture_output=True,
        check=check,
        env={**os.environ, **(extra_env or {})},
    )


class LiveInstallTests(unittest.TestCase):
    def test_only_the_gated_wrapper_passes_the_live_home_flag(self):
        with mock.patch.dict(os.environ, {"DOC_WARDEN_ALLOW_LIVE_HOME": "1"}):
            self.assertNotIn("DOC_WARDEN_ALLOW_LIVE_HOME", live_install_module._environment(ROOT, ROOT))
            authorized = live_install_module._environment(ROOT, ROOT, allow_live_home=True)
        self.assertEqual(authorized["DOC_WARDEN_ALLOW_LIVE_HOME"], "1")

    def test_uninstall_accepts_exact_legacy_destination_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo, home, data, _, manifest = installed_runtime_fixture(root)
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            recorded_home, recorded_data = alias / home.name, alias / data.name
            record = parse_json_object(manifest.read_bytes())
            record.update(cursor_root=str(recorded_home / ".cursor"),
                          release_root=str(recorded_data / "gsd-core/releases" / GSD_COMMIT))
            manifest.write_bytes(canonical_json(record))
            with mock.patch("doc_warden.live_install.subprocess.run") as owner:
                uninstall(repo, home=home, data_home=data)
            self.assertEqual(owner.call_args.kwargs["env"]["HOME"], str(recorded_home))
            self.assertEqual(owner.call_args.kwargs["env"]["XDG_DATA_HOME"], str(recorded_data))

    def test_uninstall_refuses_data_owned_by_another_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo, _, data, _, manifest = installed_runtime_fixture(root)
            original = manifest.read_bytes()
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(root / "state")}):
                with self.assertRaisesRegex(ValueError, "live_uninstall_destination_mismatch"):
                    prepare_uninstall(repo, home=root / "another-home", data_home=data)
            self.assertEqual(manifest.read_bytes(), original)

    def test_uninstall_cli_requires_exact_apply_and_binds_destination_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo, _ = live_install_repository(root)
            home, data = root / "home", root / "data"
            sentinel = home / ".gsd/defaults.json"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_bytes(b"before")
            environment = {"XDG_STATE_HOME": str(root / "state")}
            uninstall_args = ("runtime", "uninstall-gsd", "--repo", str(repo), "--home", str(home),
                              "--data-home", str(data))
            result = run_doc_warden_cli(*uninstall_args, extra_env=environment, check=False)
            self.assertEqual(parse_json_object(result.stdout)["code"], "runtime_apply_requires_generic_apply")
            preview = parse_json_object(run_doc_warden_cli(
                *uninstall_args, "--preview", extra_env=environment,
            ).stdout)
            self.assertEqual(preview["consequence"], "live_runtime_uninstall")
            self.assertEqual(preview["data_home"], str(data))
            apply_args = ("apply", "--operation-id", preview["operation_id"],
                          "--action-digest", preview["action_digest"])
            result = run_doc_warden_cli(*apply_args, extra_env=environment, check=False)
            self.assertEqual(parse_json_object(result.stdout)["code"], "fresh_exact_consent_required")
            with mock.patch.dict(os.environ, environment):
                operation = load_install_operation(preview["operation_id"], preview["action_digest"])
                envelope = root / "consent.json"
                envelope.write_bytes(canonical_json(live_install_consent(operation)))
            apply_args += ("--consent-envelope", str(envelope))
            sentinel.write_bytes(b"operator changed after preview")
            result = run_doc_warden_cli(*apply_args, extra_env=environment, check=False)
            self.assertEqual(parse_json_object(result.stdout)["code"], "operation_specification_mismatch")
            self.assertEqual(sentinel.read_bytes(), b"operator changed after preview")
            sentinel.write_bytes(b"before")
            applied = run_doc_warden_cli(*apply_args, extra_env=environment)
            replayed = run_doc_warden_cli(*apply_args, extra_env=environment)
            self.assertEqual(applied.stdout, replayed.stdout)
            self.assertEqual(parse_json_object(applied.stdout)["schema"], "doc-warden/live-uninstall-result/v1")

    def test_install_and_uninstall_refuse_when_either_destination_has_a_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = live_install_repository(root)
            home, data = root / "home", root / "data"
            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                targets = ((home, data), (home, root / "other-data"), (root / "other-home", data))
                operations = []
                for target_home, target_data in targets:
                    preview = prepare_install(repo, home=target_home, data_home=target_data)
                    operations.append(load_install_operation(preview["operation_id"], preview["action_digest"]))
                with live_install_module._runtime_writer(home, data), mock.patch(
                    "doc_warden.live_install.apply_install",
                ) as installer, mock.patch("doc_warden.live_install._uninstall_locked") as uninstaller:
                    for operation in operations:
                        with self.subTest(home=operation.home, data=operation.data_home):
                            with self.assertRaisesRegex(ValueError, "^live_install_operation_busy$"):
                                apply_prepared_install(operation, live_install_consent(operation),
                                                       real_home=root / "actual-home")
                            with self.assertRaisesRegex(ValueError, "^live_install_operation_busy$"):
                                uninstall(operation.repo, home=operation.home, data_home=operation.data_home)
                    installer.assert_not_called()
                    uninstaller.assert_not_called()

    def test_same_version_toolchain_replacement_changes_host_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("node", "npm", "python3", "bash"):
                binary = root / name
                binary.write_text("#!/bin/sh\nprintf 'fixture version\n'\n")
                binary.chmod(0o755)
            with mock.patch.dict("os.environ", {"PATH": str(root)}):
                initial = _toolchain()
                (root / "python3").write_text("#!/bin/sh\n# replacement\nprintf 'fixture version\n'\n")
                changed = _toolchain()
            self.assertEqual(initial["executables"]["python3"]["version"],
                             changed["executables"]["python3"]["version"])
            self.assertNotEqual(initial, changed)

    def test_runtime_script_dispatch_binds_shell_and_child_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            shell = root / "measured-bash"
            shell.write_text('#!/bin/sh\nprintf "qualified bash\\n"\nexec /bin/bash "$@"\n')
            paths = {"bash": shell}
            for tool, filename in (("node", "node-binary"), ("npm", "npm-cli.js"), ("python3", "python3.13")):
                path = root / filename
                path.write_text(f"#!/bin/sh\nprintf 'qualified {tool}\\n'\n")
                paths[tool] = path
            for path in paths.values():
                path.chmod(0o700)
            toolchain = {"executables": {tool: {"path": str(path), "digest": digest_ref(path.read_bytes())}
                                        for tool, path in paths.items()}}
            other = root / "other"
            other.mkdir()
            for tool in paths:
                replacement = other / tool
                replacement.write_text("#!/bin/sh\nprintf 'wrong executable\\n'\nexit 1\n")
                replacement.chmod(0o700)
            startup = root / "startup.sh"
            startup.write_text("exit 42\n")
            script = root / "verifier.sh"
            script.write_text("set -e\nnode\nnpm\npython3\nbash -c 'printf nested'\n")
            result = run_runtime_script(script, toolchain=toolchain,
                                        env={"PATH": str(other), "BASH_ENV": str(startup)},
                                        check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.splitlines(),
                             ["qualified bash", "qualified node", "qualified npm", "qualified python3",
                              "qualified bash", "nested"])

            def replace_measured_shell(argv, **_options):
                self.assertEqual(argv[0], str(shell))
                shell.write_text("#!/bin/sh\nexit 0\n")
                return subprocess.CompletedProcess(argv, 0)

            with mock.patch("doc_warden.runtime_host.subprocess.run", side_effect=replace_measured_shell):
                with self.assertRaisesRegex(ValueError, "^runtime_toolchain_changed$"):
                    run_runtime_script(script, toolchain=toolchain)

    def test_exact_install_replay_reads_the_record_and_recovers_before_completion_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = live_install_repository(root)
            home, data = root / "home", root / "data"
            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                preview = prepare_install(repo, home=home, data_home=data)
                operation = load_install_operation(preview["operation_id"], preview["action_digest"])
                consent = live_install_consent(operation)
                actual_write = live_install_module.atomic_write

                def lose_result(destination, relative, content):
                    if relative.startswith("runtime/install-"):
                        raise OSError("fixture crash before recording the outcome")
                    return actual_write(destination, relative, content)

                with mock.patch("doc_warden.live_install.atomic_write", side_effect=lose_result):
                    with self.assertRaisesRegex(OSError, "fixture crash"):
                        apply_prepared_install(operation, consent, real_home=root / "actual-home")
                wrapper = data / "gsd-core/doc-warden-wrapper-preimage.json"
                self.assertTrue(wrapper.is_file())
                with mock.patch("doc_warden.live_install.apply_install") as fresh_install:
                    recovered = apply_prepared_install(operation, consent, real_home=root / "actual-home")
                    replay = apply_prepared_install(operation, consent, real_home=root / "actual-home")
                    fresh_install.assert_not_called()
                self.assertEqual(recovered, replay)
                self.assertEqual(replay["status"], "applied")

    def test_uninstall_preserves_later_edits_and_keeps_preimages_after_owner_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = live_install_repository(root)
            home, data = root / "home", root / "data"
            path = home / ".cursor/gsd-install-state.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"original")

            def simulate_install(*args, **kwargs):
                path.write_bytes(b"installed")

            with mock.patch("doc_warden.live_install.subprocess.run", side_effect=simulate_install):
                apply_install(repo, home=home, data_home=data, isolated_home_qualified=True,
                              host_signer_qualified=False, real_home=root / "actual-home",
                              expected_runtime_digests=runtime_digests(repo))
            receipt = data / "gsd-core/doc-warden-wrapper-preimage.json"
            before = receipt.read_bytes()
            path.unlink()
            with mock.patch("doc_warden.live_install.subprocess.run") as owner:
                with self.assertRaisesRegex(ValueError, "live_install_postimage_changed"):
                    uninstall(repo, home=home, data_home=data)
                owner.assert_not_called()
            self.assertFalse(path.exists())
            self.assertEqual(receipt.read_bytes(), before)
            path.write_bytes(b"later edit")
            with mock.patch("doc_warden.live_install.subprocess.run") as owner:
                with self.assertRaisesRegex(ValueError, "live_install_postimage_changed"):
                    uninstall(repo, home=home, data_home=data)
                owner.assert_not_called()
            self.assertEqual(path.read_bytes(), b"later edit")
            self.assertEqual(receipt.read_bytes(), before)
            path.write_bytes(b"installed")
            with mock.patch("doc_warden.live_install.subprocess.run",
                            side_effect=subprocess.CalledProcessError(1, "fixture uninstaller")):
                with self.assertRaisesRegex(ValueError, "live_install_uninstall_incomplete"):
                    uninstall(repo, home=home, data_home=data)
            self.assertEqual(path.read_bytes(), b"installed")
            self.assertEqual(receipt.read_bytes(), before)
            restore = live_install_module._restore_wrapper_preimages

            def delete_after_owner_snapshot(home, record, expected):
                path.unlink()
                restore(home, record, expected)

            with mock.patch("doc_warden.live_install._restore_wrapper_preimages",
                            side_effect=delete_after_owner_snapshot), mock.patch(
                "doc_warden.live_install.subprocess.run",
            ):
                with self.assertRaisesRegex(ValueError, "live_install_postimage_changed"):
                    uninstall(repo, home=home, data_home=data)
            self.assertFalse(path.exists())
            self.assertEqual(receipt.read_bytes(), before)

    def test_uninstall_recovers_its_durable_outcome_or_retains_recovery_evidence(self):
        for failed_step in ("record_completion", "remove_wrapper"):
            with self.subTest(failed_step=failed_step), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                repo, _ = live_install_repository(root)
                home, data = root / "home", root / "data"
                residue = home / ".cursor/gsd-install-state.json"
                residue.parent.mkdir(parents=True)
                residue.write_bytes(b"original")

                def simulate_install(*args, **kwargs):
                    residue.write_bytes(b"installed")

                with mock.patch("doc_warden.live_install.subprocess.run", side_effect=simulate_install):
                    apply_install(repo, home=home, data_home=data, isolated_home_qualified=True,
                                  host_signer_qualified=False, real_home=root / "actual-home",
                                  expected_runtime_digests=runtime_digests(repo))
                wrapper = data / "gsd-core/doc-warden-wrapper-preimage.json"
                original_write = live_install_module.atomic_write
                original_unlink = Path.unlink
                with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(root / "state")}):
                    preview = prepare_uninstall(repo, home=home, data_home=data)
                    operation = load_install_operation(preview["operation_id"], preview["action_digest"])
                    consent = live_install_consent(operation)
                    basename = f"uninstall-{operation.operation_id}.json"
                    state = root / "state/doc-warden/runtime"

                    def lose_receipt(destination, name, content):
                        if Path(name).name == basename and failed_step == "record_completion":
                            raise OSError("fixture completion storage failure")
                        return original_write(destination, name, content)

                    def fail_unlink(path, *args, **kwargs):
                        if path == wrapper and failed_step == "remove_wrapper":
                            raise OSError("fixture wrapper release failure")
                        return original_unlink(path, *args, **kwargs)

                    with mock.patch("doc_warden.live_install.atomic_write", side_effect=lose_receipt), mock.patch.object(
                        Path, "unlink", fail_unlink,
                    ):
                        with self.assertRaisesRegex(ValueError, "live_uninstall_recovery_required"):
                            apply_prepared_install(operation, consent, real_home=root / "actual-home")
                    self.assertEqual(residue.read_bytes(), b"original")
                    self.assertTrue(wrapper.is_file())
                    pending = state / f"uninstall-pending-{operation.operation_id}.json"
                    self.assertTrue(pending.is_file())
                    with mock.patch("doc_warden.live_install._uninstall_locked") as owner:
                        if failed_step == "record_completion":
                            with self.assertRaisesRegex(ValueError, "live_uninstall_recovery_required"):
                                apply_prepared_install(operation, consent, real_home=root / "actual-home")
                            self.assertTrue(wrapper.is_file())
                            self.assertTrue(pending.is_file())
                            self.assertFalse((state / basename).exists())
                        else:
                            result = apply_prepared_install(operation, consent, real_home=root / "actual-home")
                            self.assertEqual(result["status"], "applied")
                            self.assertFalse(wrapper.exists())
                            self.assertFalse(pending.exists())
                        owner.assert_not_called()

    def test_current_owner_requires_qualification_for_this_exact_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = live_install_repository(root)
            home, data = root / "qualified-home", root / "data"
            profile = repo / ".planning/doc-warden.json"
            profile.parent.mkdir()
            profile.write_bytes(canonical_json(repository_profile(
                repo, CURRENT_REPOSITORY_KEY, github_repository_id=CENTRAL_REPOSITORY_ID,
            )))
            shell = Path("/bin/bash").resolve(strict=True)
            executable = {"path": str(shell), "digest": digest_ref(shell.read_bytes()), "version": "fixture"}
            toolchain = {"executables": {name: executable for name in ("node", "npm", "python3", "bash")}}
            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}), mock.patch(
                "doc_warden.runtime_host.observe_repository_identity",
                return_value=RepositoryIdentity("KleinPerkins/dev", CENTRAL_REPOSITORY_ID),
            ) as identity, mock.patch(
                "doc_warden.runtime_host._toolchain", return_value=toolchain,
            ):
                with self.assertRaisesRegex(ValueError, "runtime_destination_qualification_required"):
                    prepare_install(repo, home=home, data_home=data)
                evidence = qualify_destination(repo, home=home, data_home=data)
                self.assertEqual(evidence["status"], "qualified")
                preview = prepare_install(repo, home=home, data_home=data)
                _, _, _, _, valid_until = read_destination_qualification(repo, home=home, data_home=data)
                with mock.patch("doc_warden.runtime_host.datetime", wraps=datetime) as host_clock, mock.patch(
                    "doc_warden.live_install.datetime", wraps=datetime,
                ) as operation_clock:
                    near_expiry = valid_until - timedelta(minutes=1)
                    host_clock.now.return_value = near_expiry
                    operation_clock.now.return_value = near_expiry
                    closing_preview = prepare_install(repo, home=home, data_home=data)
                    self.assertEqual(closing_preview["expires_at"], valid_until.isoformat())
                    closing_operation = load_install_operation(closing_preview["operation_id"],
                                                               closing_preview["action_digest"])
                    host_clock.now.return_value = valid_until
                    for prepare in (prepare_install, prepare_uninstall):
                        with self.assertRaisesRegex(ValueError, "^runtime_destination_qualification_expired$"):
                            prepare(repo, home=home, data_home=data)
                    with mock.patch("doc_warden.live_install.apply_install") as blocked_installer:
                        with self.assertRaisesRegex(ValueError, "^runtime_destination_qualification_expired$"):
                            apply_prepared_install(closing_operation, live_install_consent(closing_operation), real_home=home)
                        blocked_installer.assert_not_called()
                    read_destination_qualification(repo, home=home, data_home=data, require_fresh=False)
                    host_clock.now.return_value = valid_until - timedelta(days=2)
                    with self.assertRaisesRegex(ValueError, "^runtime_destination_qualification_changed$"):
                        read_destination_qualification(repo, home=home, data_home=data, require_fresh=False)
                self.assertEqual(preview["repository_key"], CURRENT_REPOSITORY_KEY)
                self.assertEqual(preview["github_repository_id"], CENTRAL_REPOSITORY_ID)
                with self.assertRaisesRegex(ValueError, "runtime_destination_qualification_required"):
                    prepare_install(repo, home=root / "other-home", data_home=data)
                with mock.patch("doc_warden.live_install.apply_install") as installer, mock.patch(
                    "doc_warden.live_install._live_doctor_state",
                ) as readback:
                    operation = load_install_operation(preview["operation_id"], preview["action_digest"])
                    result = apply_prepared_install(operation, live_install_consent(operation), real_home=home)
                    self.assertEqual(result["status"], "applied")
                    installer.assert_called_once()
                    self.assertEqual(installer.call_args.kwargs["toolchain"], toolchain)
                    readback.assert_called_once()
                identity.return_value = RepositoryIdentity("KleinPerkins/dev", 111)
                with self.assertRaisesRegex(ValueError, "runtime_install_repository_identity_mismatch"):
                    prepare_install(repo, home=home, data_home=data)

    def test_uninstall_preview_and_apply_do_not_run_installation_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo, _ = live_install_repository(root)
            home, data = root / "home", root / "data"

            def fail_install_check(script, *arguments, **options):
                if arguments == ("--check",):
                    raise subprocess.CalledProcessError(1, [str(script), *arguments])
                return run_runtime_script(script, *arguments, **options)

            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}), mock.patch(
                "doc_warden.live_install.run_runtime_script", side_effect=fail_install_check,
            ) as owner:
                with self.assertRaises(subprocess.CalledProcessError):
                    prepare_install(repo, home=home, data_home=data)
                owner.reset_mock()
                preview = prepare_uninstall(repo, home=home, data_home=data)
                self.assertEqual(preview["status"], "ready")
                owner.assert_not_called()
                operation = load_install_operation(preview["operation_id"], preview["action_digest"])
                applied = apply_prepared_install(operation, live_install_consent(operation), real_home=root / "real-home")
                self.assertEqual(applied["status"], "applied")
                self.assertEqual([call.args[1:] for call in owner.call_args_list], [("--uninstall",)])

    def assert_install_revalidation_refuses(self, operation, consent=None):
        with mock.patch("doc_warden.live_install.apply_install") as installer:
            with self.assertRaisesRegex(
                ValueError, "operation_specification_mismatch"
            ):
                apply_prepared_install(
                    operation,
                    (
                        consent
                        if consent is not None
                        else live_install_consent(operation)
                    ),
                    real_home=operation.home.with_name("real-home"),
                )
        installer.assert_not_called()

    def persisted_doctor_observation(self, root: Path):
        repo, home, data, _, _ = installed_runtime_fixture(root)
        with mock.patch(
            "doc_warden.scm._github_metadata",
            return_value={
                "full_name": "KleinPerkins/dev-fixture",
                "id": 1278387789,
            },
        ):
            observation, preview = preview_doctor_receipt(
                repo, home=home, data_home=data
            )
            apply_preview(
                preview,
                consent_for(preview, consequence_class="structural"),
            )
        return repo, home, data, observation, preview

    def test_live_install_uses_digest_bound_generic_apply_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _qualification = live_install_repository(root)
            home = root / "unused/../home"
            data = root / "unused/../data"
            state = root / "state"
            with mock.patch.dict(
                "os.environ", {"XDG_STATE_HOME": str(state)}, clear=False
            ):
                preview = prepare_install(
                    repo,
                    home=home,
                    data_home=data,
                    operation_id=str(uuid.uuid4()),
                )
                specification = (
                    state
                    / "doc-warden/operations"
                    / f"{preview['operation_id']}.json"
                )
                self.assertEqual(specification.stat().st_mode & 0o077, 0)
                operation = load_install_operation(
                    preview["operation_id"], preview["action_digest"]
                )
                now = datetime.now(timezone.utc)
                consent = {
                    "schema": "doc-warden/consent-envelope/v1",
                    "operation_id": operation.operation_id,
                    "repository_key": CENTRAL_REPOSITORY_KEY,
                    "canonical_root": operation.canonical_root,
                    "source_revision": operation.source_revision,
                    "action_digest": operation.action_digest,
                    "consequence_class": "external",
                    "nonce": str(uuid.uuid4()),
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=5)).isoformat(),
                    "choice": "apply",
                }
                with mock.patch(
                    "doc_warden.live_install.apply_install"
                ) as installer:
                    with self.assertRaisesRegex(ValueError, "runtime_destination_qualification_required"):
                        apply_prepared_install(operation, consent, real_home=home.resolve())
                    installer.assert_not_called()
                    result = apply_prepared_install(operation, consent, real_home=root / "real-home")
                installer.assert_called_once()
                self.assertEqual(
                    installer.call_args.kwargs["expected_runtime_digests"],
                    operation.runtime_digests,
                )
                self.assertEqual(result["status"], "applied")

    def test_live_install_prepare_rejects_invalid_qualification(self):
        drifts = {
            "minimal": lambda value: {
                "qualification": {"isolated_home_apply": "passed"}
            },
            "schema": lambda value: {
                **value,
                "schema": "doc-warden/gsd-runtime-qualification/v1",
            },
            "vendor_clone": lambda value: {
                **value,
                "qualification": {
                    **value["qualification"],
                    "vendor_clone_touched": True,
                },
            },
            "frozen_pin_identity": lambda value: {
                **value,
                "git_commit": "0" * 40,
            },
        }
        for name, mutate in drifts.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                repo, qualification = live_install_repository(root)
                value = parse_json_object(qualification.read_bytes())
                qualification.write_bytes(canonical_json(mutate(value)))
                with self.assertRaisesRegex(
                    ValueError, "runtime_qualification_invalid"
                ):
                    prepare_install(
                        repo,
                        home=root / "home",
                        data_home=root / "data",
                        operation_id=str(uuid.uuid4()),
                    )

    def test_live_install_prepare_rejects_declared_runtime_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = live_install_repository(root)
            (repo / "_ops/doc-warden/runtime/gsd-core/package-lock.json").write_text(
                "{}\n"
            )
            with self.assertRaisesRegex(
                ValueError, "runtime_qualification_digest_mismatch"
            ):
                prepare_install(
                    repo,
                    home=root / "home",
                    data_home=root / "data",
                    operation_id=str(uuid.uuid4()),
                )

    def test_live_install_rejects_source_revision_drift_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _, _, _, operation = live_install_fixture(root)
            (repo / "README.md").write_text("changed after load\n")
            subprocess.run(
                ["git", "-C", str(repo), "add", "README.md"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "drift"], check=True
            )
            self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_runtime_pin_drift_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _, _, _, operation = live_install_fixture(root)
            pin = repo / "_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json"
            pin.write_bytes(canonical_json({"package": "changed"}))
            self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_runtime_dependency_drift_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _, _, _, operation = live_install_fixture(root)
            lock = repo / "_ops/doc-warden/runtime/gsd-core/package-lock.json"
            lock.write_text("{}\n")
            self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_installer_drift_after_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _, _, _, operation = live_install_fixture(root)
            installer = repo / "_ops/doc-warden/runtime/gsd-core/install.sh"
            installer.write_text("#!/bin/sh\nexit 1\n")
            self.assert_install_revalidation_refuses(operation)

    def test_live_install_rechecks_installer_immediately_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _, data_home, _, operation = live_install_fixture(root)
            installer = repo / "_ops/doc-warden/runtime/gsd-core/install.sh"
            executed = root / "mutated-installer-executed"
            original_validate = live_install_module._validated_runtime_files
            validation_count = 0

            def mutate_after_first_validation(target_repo, expected_digests):
                nonlocal validation_count
                validation_count += 1
                validated = original_validate(target_repo, expected_digests)
                if validation_count == 1:
                    installer.write_text(
                        f"#!/bin/sh\ntouch {executed}\nexit 0\n"
                    )
                return validated

            with mock.patch(
                "doc_warden.live_install._validated_runtime_files",
                side_effect=mutate_after_first_validation,
            ), self.assertRaisesRegex(
                ValueError, "operation_specification_mismatch"
            ):
                apply_prepared_install(
                    operation,
                    live_install_consent(operation),
                    real_home=root / "real-home",
                )
            self.assertEqual(validation_count, 2)
            self.assertFalse(executed.exists())
            self.assertFalse(
                (
                    data_home
                    / "gsd-core/doc-warden-wrapper-preimage.json"
                ).exists()
            )

    def test_live_install_rejects_qualification_drift_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, qualification, operation = live_install_fixture(root)
            value = parse_json_object(qualification.read_bytes())
            value["qualification"]["isolated_home_apply"] = "failed"
            qualification.write_bytes(canonical_json(value))
            self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_target_drift_after_load(self):
        for target in ("repository", "home", "data_home"):
            with (
                self.subTest(target=target),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                repo, home, data_home, _, operation = live_install_fixture(root)
                if target == "repository":
                    moved = root / "moved-repo"
                    repo.rename(moved)
                    repo.symlink_to(moved, target_is_directory=True)
                else:
                    path = home if target == "home" else data_home
                    replacement = root / f"{target}-replacement"
                    replacement.mkdir()
                    path.symlink_to(replacement, target_is_directory=True)
                self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_expiry_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, _, operation = live_install_fixture(root)
            expired_now = datetime.fromisoformat(operation.expires_at) + timedelta(
                seconds=1
            )

            class ExpiredDateTime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return expired_now if tz is None else expired_now.astimezone(tz)

            with mock.patch("doc_warden.live_install.datetime", ExpiredDateTime):
                self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_managed_sentinel_drift_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, home, _, _, operation = live_install_fixture(root)
            managed = home / ".cursor/skills/rebound"
            managed.parent.mkdir(parents=True)
            managed.write_text("changed after load\n")
            self.assert_install_revalidation_refuses(operation)

    def test_live_install_rejects_operation_binding_drift_after_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, _, operation = live_install_fixture(root)
            drifts = {
                "operation_id": str(uuid.uuid4()),
                "repository_key": str(uuid.uuid4()),
                "canonical_root": str(root / "different-repo"),
                "action_digest": "sha256:" + "0" * 64,
            }
            for field, value in drifts.items():
                with self.subTest(field=field):
                    changed = replace(operation, **{field: value})
                    self.assert_install_revalidation_refuses(
                        changed, live_install_consent(changed)
                    )

    def test_live_install_preview_writes_nothing_and_refuses_fail_closed_global_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _qualification = live_install_repository(root)
            home = root / "home"
            data = root / "data"
            (home / ".cursor").mkdir(parents=True)
            (home / ".cursor/sentinel").write_bytes(b"keep\n")
            before = cursor_sentinels(home)
            preview = preview_install(repo, home=home, data_home=data)
            self.assertEqual(preview["status"], "ready")
            self.assertEqual(cursor_sentinels(home), before)
            with self.assertRaisesRegex(
                ValueError, "global_blocking_hook_must_fail_open"
            ):
                preview_install(
                    repo,
                    home=home,
                    data_home=data,
                    proposed_hooks=[
                        {
                            "owner": "doc-warden",
                            "event": "beforeShellExecution",
                            "failClosed": True,
                        }
                    ],
                )

    def test_preview_ignores_unmanaged_volatile_cursor_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            volatile = home / ".cursor/projects/session.jsonl"
            volatile.parent.mkdir(parents=True)

            def check_writes_only_unmanaged_state(*_args, **_kwargs):
                volatile.write_text("cursor activity\n")
                return subprocess.CompletedProcess([], 0)

            with mock.patch(
                "doc_warden.live_install.subprocess.run",
                side_effect=check_writes_only_unmanaged_state,
            ):
                preview = preview_install(ROOT, home=home, data_home=data)
            self.assertEqual(preview["status"], "ready")

    def test_live_install_then_uninstall_is_idempotent_back_to_real_home_sentinels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            (home / ".cursor").mkdir(parents=True)
            (home / ".cursor/sentinel").write_bytes(b"keep\n")
            before = cursor_sentinels(home)
            # Product API receives explicit fixture paths. The caller never
            # reassigns HOME/CODEX_HOME; only the existing product child env does.
            actual_home = Path.home().resolve()
            host_paths = [actual_home / relative for relative in (
                ".cursor/hooks.json", ".gsd/defaults.json", ".local/bin/gsd-core",
                ".local/bin/gsd-tools", ".local/bin/gsd_run",
                ".local/share/gsd-core/doc-warden-manifest.json",
                ".local/share/gsd-core/doc-warden-wrapper-preimage.json")]
            def fingerprints():
                return {str(p): ("symlink", os.readlink(p)) if p.is_symlink()
                        else ("file", digest_ref(p.read_bytes())) if p.is_file()
                        else ("absent", None) for p in host_paths}
            host_before = fingerprints()
            original_environment = {k: os.environ.get(k) for k in ("HOME", "CODEX_HOME")}
            real_run = subprocess.run
            npm_user = root / 'npm-user.npmrc'; npm_user.write_text('')
            npm_global = root / 'npm-global.npmrc'; npm_global.write_text('')
            def confined_installer(*args, **kwargs):
                command = args[0] if args else kwargs['args']
                if command and str(command[0]).endswith('/install.sh'):
                    child = dict(kwargs['env'])
                    self.assertEqual(Path(child['HOME']).resolve(), home.resolve())
                    self.assertEqual(Path(child['XDG_DATA_HOME']).resolve(), data.resolve())
                    self.assertNotIn('DOC_WARDEN_ALLOW_LIVE_HOME', child)
                    self.assertNotEqual(home.resolve(), actual_home)
                    self.assertTrue(home.resolve().is_relative_to(root.resolve()))
                    self.assertTrue(data.resolve().is_relative_to(root.resolve()))
                    # npm cache and configuration stay inside the same fixture.
                    child.update(npm_config_cache=str(root/'npm-cache'),
                                 npm_config_userconfig=str(npm_user),
                                 npm_config_globalconfig=str(npm_global))
                    kwargs['env'] = child
                return real_run(*args, **kwargs)
            with mock.patch('doc_warden.live_install.subprocess.run', side_effect=confined_installer):
                self._isolated_install_cycles(home, data, root, before)
            self.assertEqual(fingerprints(), host_before)
            self.assertEqual({k: os.environ.get(k) for k in original_environment}, original_environment)

    def _isolated_install_cycles(self, home, data, root, before):
        for _ in range(2):
            apply_install(
                ROOT,
                home=home,
                data_home=data,
                isolated_home_qualified=True,
                host_signer_qualified=False,
                real_home=root / "real-home",
                expected_runtime_digests=runtime_digests(ROOT),
            )
            uninstall(ROOT, home=home, data_home=data)
            self.assertEqual(cursor_sentinels(home), before)

    def test_live_install_blocked_until_isolated_home_and_host_signer_qualified(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            data = home / "data"
            with self.assertRaisesRegex(ValueError, "isolated_home_not_qualified"):
                apply_install(
                    ROOT,
                    home=home,
                    data_home=data,
                    isolated_home_qualified=False,
                    host_signer_qualified=False,
                    real_home=home,
                    expected_runtime_digests=runtime_digests(ROOT),
                )
            with self.assertRaisesRegex(ValueError, "host_signer_not_qualified"):
                apply_install(
                    ROOT,
                    home=home,
                    data_home=data,
                    isolated_home_qualified=True,
                    host_signer_qualified=False,
                    real_home=home,
                    expected_runtime_digests=runtime_digests(ROOT),
                )

    def test_reinstall_requires_an_intervening_owned_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            (data / "gsd-core").mkdir(parents=True)
            (data / "gsd-core/doc-warden-wrapper-preimage.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "live_install_already_applied"):
                apply_install(
                    ROOT,
                    home=home,
                    data_home=data,
                    isolated_home_qualified=True,
                    host_signer_qualified=False,
                    real_home=root / "real-home",
                    expected_runtime_digests=runtime_digests(ROOT),
                )

    def test_failed_install_rolls_back_wrapper_receipt_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            home.mkdir()
            failure = subprocess.CalledProcessError(1, ["install.sh", "--apply"])
            with mock.patch(
                "doc_warden.live_install.subprocess.run",
                side_effect=[failure, subprocess.CompletedProcess([], 0)],
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    apply_install(
                        ROOT,
                        home=home,
                        data_home=data,
                        isolated_home_qualified=True,
                        host_signer_qualified=False,
                        real_home=root / "real-home",
                        expected_runtime_digests=runtime_digests(ROOT),
                    )
            self.assertFalse(
                (data / "gsd-core/doc-warden-wrapper-preimage.json").exists()
            )

    def test_failed_install_retains_recovery_preimage_if_upstream_uninstall_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            marker = home / ".cursor/gsd-install-state.json"
            marker.parent.mkdir(parents=True)
            marker.write_text("before\n")
            failure = subprocess.CalledProcessError(1, ["install.sh"])
            with mock.patch(
                "doc_warden.live_install.subprocess.run",
                side_effect=[failure, failure],
            ):
                with self.assertRaisesRegex(
                    ValueError, "live_install_rollback_incomplete"
                ):
                    apply_install(
                        ROOT,
                        home=home,
                        data_home=data,
                        isolated_home_qualified=True,
                        host_signer_qualified=False,
                        real_home=root / "real-home",
                        expected_runtime_digests=runtime_digests(ROOT),
                    )
            self.assertEqual(marker.read_text(), "before\n")
            self.assertTrue(
                (data / "gsd-core/doc-warden-wrapper-preimage.json").exists()
            )

    def test_live_doctor_emits_and_validates_bounded_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, _, manifest = installed_runtime_fixture(root)
            observation_id = "8716de90-97ce-4fa9-9760-897889d34466"
            observed_at = "2026-08-29T12:00:00+00:00"
            observation = doctor(
                repo,
                home=home,
                data_home=data,
                observation_id=observation_id,
                observed_at=observed_at,
            )
            self.assertEqual(
                observation["schema"],
                "doc-warden/gsd-live-doctor-observation/v1",
            )
            self.assertEqual(observation["status"], "passed")
            self.assertEqual(observation["observation_id"], observation_id)
            self.assertEqual(observation["observed_at"], observed_at)
            self.assertEqual(
                observation["receipt_path"],
                (
                    "_ops/doc-warden/state/v2/runtime/live-doctor/"
                    f"{observation_id}.json"
                ),
            )
            self.assertEqual(
                observation["machine_install_receipt"]["digest"],
                digest_ref(manifest.read_bytes()),
            )
            self.assertEqual(
                {row["id"] for row in observation["authoring_interfaces"]},
                {
                    "gsd-new-project",
                    "gsd-discuss-phase",
                    "gsd-plan-phase",
                    "gsd-validate-phase",
                },
            )
            self.assertTrue(
                all(
                    row["digest_basis"] == "live_descriptor_bytes"
                    for row in observation["authoring_interfaces"]
                )
            )
            self.assertEqual(
                observation["runtime"]["interface_digest_basis"],
                "m1_t01_qualification",
            )
            self.assertEqual(
                {row["command"] for row in observation["deterministic_utilities"]},
                {"gsd-core", "gsd-tools"},
            )
            self.assertNotIn(str(home), canonical_json(observation).decode("utf-8"))
            self.assertEqual(
                validate_doctor_observation(repo, observation, home=home, data_home=data)[
                    "evidence_status"
                ],
                "not_persisted",
            )
            status = doctor_observation_status(
                repo, observation, home=home, data_home=data
            )
            self.assertEqual(status["live_freshness"], "current")
            self.assertFalse(status["historical_valid"])
            self.assertFalse(status["evidence_verified"])
            self.assertEqual(status["historical_status"], "not_historical")

    def test_live_doctor_current_ephemeral_observation_is_not_historical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, _, _ = installed_runtime_fixture(root)
            observation = doctor(repo, home=home, data_home=data)

            status = validate_doctor_observation(
                repo, observation, home=home, data_home=data
            )

            self.assertEqual(status["status"], "valid")
            self.assertEqual(status["live_freshness"], "current")
            self.assertEqual(status["historical_status"], "not_historical")
            self.assertEqual(status["evidence_status"], "not_persisted")
            self.assertFalse(status["historical_valid"])
            self.assertFalse(status["evidence_verified"])

    def test_live_doctor_historical_observation_survives_head_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, observation, _ = self.persisted_doctor_observation(root)
            (repo / "DELIVERED.md").write_text("delivered\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "delivery"],
                check=True,
            )

            with mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/dev-fixture",
                    "id": 1278387789,
                },
            ):
                status = doctor_observation_status(
                    repo, observation, home=home, data_home=data
                )
                validated = validate_doctor_observation(
                    repo, observation, home=home, data_home=data
                )

            self.assertTrue(status["historical_valid"])
            self.assertTrue(status["evidence_verified"])
            self.assertEqual(status["historical_status"], "verified")
            self.assertEqual(status["evidence_status"], "verified")
            self.assertEqual(status["live_freshness"], "stale_source_revision")
            self.assertEqual(validated, status)
            self.assertEqual(status["source_revision"], observation["source_revision"])
            self.assertNotEqual(
                status["current_source_revision"], observation["source_revision"]
            )
            with self.assertRaisesRegex(
                ValueError, "live_doctor_observation_stale"
            ):
                doctor_observation_status(
                    repo,
                    observation,
                    home=home,
                    data_home=data,
                    require_current=True,
                )

    def test_live_doctor_cli_surfaces_stale_status_and_require_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, observation, _ = self.persisted_doctor_observation(root)
            (repo / "DELIVERED.md").write_text("delivered\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "delivery"],
                check=True,
            )
            fake_bin = fake_gh_bin(root)
            env = {
                "BASH_ENV": "/dev/null",
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            observation_path = (repo / observation["receipt_path"]).resolve()

            result = run_doc_warden_cli(
                "runtime",
                "doctor-gsd",
                "--repo",
                str(repo),
                "--home",
                str(home),
                "--data-home",
                str(data),
                "--observation",
                str(observation_path),
                extra_env=env,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["live_freshness"], "stale_source_revision")
            self.assertEqual(payload["evidence_status"], "verified")

            refused = run_doc_warden_cli(
                "runtime",
                "doctor-gsd",
                "--repo",
                str(repo),
                "--home",
                str(home),
                "--data-home",
                str(data),
                "--observation",
                str(observation_path),
                "--require-current",
                extra_env=env,
                check=False,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(
                json.loads(refused.stdout)["code"],
                "live_doctor_observation_stale",
            )

    def test_live_doctor_deleted_persisted_observation_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, observation, _ = self.persisted_doctor_observation(root)
            (repo / observation["receipt_path"]).unlink()

            with mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/dev-fixture",
                    "id": 1278387789,
                },
            ):
                with self.assertRaisesRegex(
                    ValueError, "live_doctor_evidence_missing"
                ):
                    validate_doctor_observation(
                        repo, observation, home=home, data_home=data
                    )

    def test_live_doctor_observation_id_must_match_receipt_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, _, _ = installed_runtime_fixture(root)
            observation = doctor(repo, home=home, data_home=data)
            tampered = {
                **observation,
                "receipt_path": (
                    "_ops/doc-warden/state/v2/runtime/live-doctor/"
                    f"{uuid.uuid4()}.json"
                ),
            }

            with self.assertRaisesRegex(
                ValueError, "live_doctor_observation_path_mismatch"
            ):
                validate_doctor_observation(
                    repo, tampered, home=home, data_home=data
                )

    def test_live_doctor_evidence_validation_reads_each_record_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, observation, preview = self.persisted_doctor_observation(root)
            observation_path = (repo / observation["receipt_path"]).resolve()
            receipt_path = (
                repo
                / "_ops/doc-warden/state/v2/receipts"
                / f"{preview.operation_id}.json"
            ).resolve()
            event_path = (
                repo
                / "_ops/doc-warden/state/v2/events"
                / f"{preview.event_id}.json"
            ).resolve()
            targets = {observation_path, receipt_path, event_path}
            counts = {path: 0 for path in targets}
            original_read_bytes = Path.read_bytes

            def counted_read_bytes(path):
                if path in targets:
                    counts[path] += 1
                return original_read_bytes(path)

            with mock.patch("pathlib.Path.read_bytes", counted_read_bytes), mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/dev-fixture",
                    "id": 1278387789,
                },
            ):
                status = validate_doctor_observation(
                    repo, observation, home=home, data_home=data
                )

            self.assertEqual(status["evidence_status"], "verified")
            self.assertEqual(counts[observation_path], 1)
            self.assertEqual(counts[receipt_path], 1)
            self.assertEqual(counts[event_path], 1)

    def test_live_doctor_historical_observation_refuses_tampering(self):
        cases = {
            "source_revision": lambda value: {
                **value,
                "source_revision": "f" * 40,
            },
            "runtime_digest": lambda value: {
                **value,
                "runtime": {
                    **value["runtime"],
                    "pin_digest": "sha256:" + "f" * 64,
                },
            },
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    repo, home, data, observation, _ = (
                        self.persisted_doctor_observation(root)
                    )
                    tampered = mutate(observation)
                    with mock.patch(
                        "doc_warden.scm._github_metadata",
                        return_value={
                            "full_name": "KleinPerkins/dev-fixture",
                            "id": 1278387789,
                        },
                    ):
                        with self.assertRaises(ValueError):
                            validate_doctor_observation(
                                repo, tampered, home=home, data_home=data
                            )

    def test_live_doctor_historical_observation_requires_paired_evidence(self):
        cases = {
            "receipt": lambda repo, preview: (
                repo
                / "_ops/doc-warden/state/v2/receipts"
                / f"{preview.operation_id}.json"
            ),
            "event": lambda repo, preview: (
                repo
                / "_ops/doc-warden/state/v2/events"
                / f"{preview.event_id}.json"
            ),
        }
        for name, target_for in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    repo, home, data, observation, preview = (
                        self.persisted_doctor_observation(root)
                    )
                    target_for(repo, preview).unlink()
                    with mock.patch(
                        "doc_warden.scm._github_metadata",
                        return_value={
                            "full_name": "KleinPerkins/dev-fixture",
                            "id": 1278387789,
                        },
                    ):
                        with self.assertRaises(ValueError):
                            validate_doctor_observation(
                                repo, observation, home=home, data_home=data
                            )

    def test_live_doctor_historical_observation_refuses_tampered_evidence(self):
        cases = {
            "receipt_source": (
                "receipts",
                lambda value: {**value, "source_revision": "f" * 40},
            ),
            "receipt_postimage": (
                "receipts",
                lambda value: {
                    **value,
                    "postimages": {
                        next(iter(value["postimages"])): "sha256:" + "f" * 64
                    },
                },
            ),
            "event_source": (
                "events",
                lambda value: {**value, "source_revision": "f" * 40},
            ),
            "repository_identity": (
                "receipts",
                lambda value: {
                    **value,
                    "bindings": {
                        **value["bindings"],
                        "repository_identity": {
                            **value["bindings"]["repository_identity"],
                            "github_repository": "KleinPerkins/other",
                        },
                    },
                },
            ),
        }
        for name, (kind, mutate) in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    repo, home, data, observation, preview = (
                        self.persisted_doctor_observation(root)
                    )
                    identifier = (
                        preview.operation_id
                        if kind == "receipts"
                        else preview.event_id
                    )
                    target = (
                        repo
                        / "_ops/doc-warden/state/v2"
                        / kind
                        / f"{identifier}.json"
                    )
                    target.write_bytes(
                        canonical_json(
                            mutate(parse_json_object(target.read_bytes()))
                        )
                    )
                    with mock.patch(
                        "doc_warden.scm._github_metadata",
                        return_value={
                            "full_name": "KleinPerkins/dev-fixture",
                            "id": 1278387789,
                        },
                    ):
                        with self.assertRaises(ValueError):
                            validate_doctor_observation(
                                repo, observation, home=home, data_home=data
                            )

    def test_live_doctor_observation_validation_refuses_interface_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, _, _ = installed_runtime_fixture(root)
            observation = doctor(repo, home=home, data_home=data)
            descriptor = home / ".cursor/skills/gsd-plan-phase/SKILL.md"
            descriptor.write_text("# changed\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "live_doctor_observation_mismatch"
            ):
                validate_doctor_observation(
                    repo, observation, home=home, data_home=data
                )

    def test_live_doctor_receipt_preview_uses_generic_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, home, data, _, _ = installed_runtime_fixture(root)
            repository_key = "8716de90-97ce-4fa9-9760-897889d34466"
            config = repo / ".planning/doc-warden.json"
            config.parent.mkdir()
            config.write_bytes(
                canonical_json(repository_profile(repo, repository_key))
            )
            subprocess.run(
                ["git", "-C", str(repo), "add", ".planning"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "profile"],
                check=True,
            )
            secret = "credential-that-must-not-persist"
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "set-url",
                    "origin",
                    (
                        f"https://oauth2:{secret}@github.com/"
                        "KleinPerkins/dev-fixture.git"
                    ),
                ],
                check=True,
            )
            with mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/dev-fixture",
                    "id": 1278387789,
                },
            ):
                observation, preview = preview_doctor_receipt(
                    repo, home=home, data_home=data
                )
            self.assertEqual(preview.repository_key, repository_key)
            self.assertEqual(preview.transition, "creation_snapshot")
            self.assertTrue(preview.consequential)
            self.assertNotIn(
                secret, canonical_json(preview.bindings).decode("utf-8")
            )
            self.assertEqual(
                [action.path for action in preview.actions],
                [observation["receipt_path"]],
            )
            self.assertEqual(
                preview.preimages[observation["receipt_path"]], None
            )
            self.assertEqual(
                preview.actions[0].content,
                canonical_json(observation),
            )
            self.assertIn("observed_at", observation)
            self.assertEqual(observation["status"], "passed")
            self.assertEqual(
                preview.postimages[observation["receipt_path"]],
                digest_ref(canonical_json(observation)),
            )
            self.assertFalse((repo / observation["receipt_path"]).exists())
            with mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/dev-fixture",
                    "id": 1278387789,
                },
            ):
                receipt = apply_preview(
                    preview,
                    consent_for(preview, consequence_class="structural"),
                )
            self.assertEqual(receipt["operation_id"], preview.operation_id)
            self.assertEqual(receipt["repository_key"], repository_key)
            with mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/dev-fixture",
                    "id": 1278387789,
                },
            ):
                self.assertEqual(
                    apply_preview(
                        preview,
                        consent_for(preview, consequence_class="structural"),
                    ),
                    receipt,
                )
            self.assertNotIn(
                secret, canonical_json(receipt).decode("utf-8")
            )
            self.assertNotIn(
                str(repo.resolve()), canonical_json(receipt).decode("utf-8")
            )
            self.assertEqual(
                (repo / observation["receipt_path"]).read_bytes(),
                canonical_json(observation),
            )

    def test_doc_warden_global_blocking_hooks_are_fail_open(self):
        validate_global_hooks(
            [
                {
                    "owner": "doc-warden",
                    "event": "beforeReadFile",
                    "failClosed": False,
                }
            ]
        )


class NativeAuthoringEventTest(unittest.TestCase):
    def test_dispatch_uses_the_measured_named_selector_fields(self):
        request = RoleRequest(Path("/fixture"), Path("/bundle"), Path("/client"), "gsd-planner", "Private brief")
        owner = SimpleNamespace(MODEL="fixture-model", EFFORT="high", verify_spawn_offer=mock.Mock())
        fields = ("agent_type", "task_name", "fork_turns", "model", "reasoning_effort", "message")
        offer = {"parameters": {"properties": dict.fromkeys(fields)}}
        launched = _role_dispatch(offer, request, owner)
        owner.verify_spawn_offer.assert_called_once_with(offer, "gsd-planner")
        self.assertEqual(launched["agent_type"], "gsd-planner")
        self.assertEqual(launched["message"], "Private brief")
        del offer["parameters"]["properties"]["agent_type"]
        with self.assertRaisesRegex(ValueError, "selector_unavailable"):
            _role_dispatch(offer, request, owner)

    def test_repeated_deltas_retain_only_thread_identity(self):
        channel = NativeAuthoringChannel.__new__(NativeAuthoringChannel)
        channel.observed = []
        channel.thread_notifications = set()
        channel.notification_count = 0
        parent = str(uuid.uuid4())
        delta = {"method": "item/agentMessage/delta", "params": {"threadId": parent, "delta": "private text"}}
        for _ in range(5000):
            channel._notification(delta)
        self.assertEqual(channel.observed, [{"method": delta["method"], "params": {"threadId": parent}}])
        foreign = str(uuid.uuid4())
        channel._notification({"method": delta["method"], "params": {"threadId": foreign, "delta": "private text"}})
        self.assertEqual(channel.observed[-1]["params"], {"threadId": foreign})


class HostProjectionTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(
            ["git", "-C", str(self.project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "--quiet", "--allow-empty", "-m", "Fixture"],
            check=True,
        )
        self.enterContext(mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root / "state")}))
        self.home, self.data = self.root / "home", self.root / "data"
        self.authority = {
            "repository_key": "47f7e608-ce5f-50ae-be86-10d7e95265f9",
            "source_revision": "a" * 40,
            "canonical_root": str(self.root / "authority"),
        }
        self.binding = {"source_root": str(self.root / "release")}
        self.qualification_count = 0

    def verify(self, binding):
        self.assertEqual(binding, self.binding)
        self.qualification_count += 1

    def preview(self, binding):
        return host_transaction.prepare_host_change(
            self.project, home=self.home, data_home=self.data, authority=self.authority,
            binding=binding, verify=self.verify,
        )

    def apply(self, operation, consent=None):
        if consent is None:
            consent = consent_for(SimpleNamespace(**operation), consequence_class="external")
        return host_transaction.apply_host_change(
            operation["operation_id"], operation["action_digest"], consent, verify=self.verify,
        )

    def installed(self):
        return host_transaction.read_installed_projection(
            self.project, state_root=self.root / "state/doc-warden", home=self.home, data_home=self.data,
        )

    def test_install_readback_removal_and_expired_exact_replay(self):
        operation = self.preview(self.binding)
        self.assertFalse((self.project / ".agents").exists())
        with self.assertRaisesRegex(ValueError, "projection_not_installed"):
            self.installed()
        self.assertEqual(operation["global_hooks"], [])
        installed = self.apply(operation)
        self.assertEqual(installed["status"], "installed")
        self.assertEqual(self.installed(), self.binding)
        self.assertEqual(host_projection.observe_descriptors(self.project), installed["postimages"])
        with mock.patch.object(host_transaction, "_is_expired", return_value=True):
            self.assertEqual(self.apply(operation), installed)
        self.assertEqual(self.qualification_count, 2)
        removal = self.preview(None)
        self.assertEqual(self.apply(removal)["status"], "removed")
        self.assertFalse(any(host_projection.observe_descriptors(self.project).values()))
        with self.assertRaisesRegex(ValueError, "projection_not_installed"):
            self.installed()

    def test_recover_after_a_descriptor_is_written_and_preserve_later_edits(self):
        operation = self.preview(self.binding)
        original = host_projection.atomic_write
        written = []

        def interrupted(root, path, data):
            if written:
                raise OSError("fixture interruption")
            written.append(original(root, path, data))

        with mock.patch.object(host_projection, "atomic_write", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "fixture interruption"):
                self.apply(operation)
        with self.assertRaisesRegex(ValueError, "projection_recovery_required"):
            self.installed()
        exact = written[0].read_bytes()
        written[0].write_bytes(b"Later edit")
        with self.assertRaisesRegex(ValueError, "projection_foreign"):
            self.apply(operation)
        self.assertEqual(written[0].read_bytes(), b"Later edit")
        written[0].write_bytes(exact)
        self.assertEqual(self.apply(operation)["status"], "installed")

    def test_first_use_and_competing_writer_refuse(self):
        operation = self.preview(self.binding)
        old = datetime.now(timezone.utc) - timedelta(minutes=12)
        consent = consent_for(SimpleNamespace(**operation), consequence_class="external")
        consent.update(issued_at=old.isoformat(), expires_at=(old + timedelta(minutes=10)).isoformat())
        with self.assertRaisesRegex(ValueError, "operation_specification_expired"):
            self.apply(operation, consent)
        self.assertFalse(self.home.exists())
        with _runtime_writer(self.root / "other-home", self.root / "other-data", project=self.project):
            with self.assertRaisesRegex(ValueError, "live_install_operation_busy"):
                self.apply(operation)
        self.assertFalse((self.project / ".agents").exists())

    def test_existing_descriptor_never_becomes_owned_by_byte_equality(self):
        descriptor = self.project / host_projection.PROJECTION_PATHS[0]
        descriptor.parent.mkdir(parents=True)
        contents = host_projection.render_descriptors(Path(self.binding["source_root"]) / host_transaction.SOURCE_ENTRY)
        descriptor.write_bytes(contents[host_projection.PROJECTION_PATHS[0]])
        descriptor.chmod(host_projection.FILE_MODE)
        with self.assertRaisesRegex(ValueError, "projection_foreign"):
            self.preview(self.binding)
        self.assertTrue(descriptor.is_file())


if __name__ == "__main__":
    unittest.main()
