import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from doc_warden.canonical import canonical_json
from doc_warden.triggers import (
    hook_capability_report,
    job_egress,
    maintenance_job_contract,
    read_projection_freshness,
)
from fixture_factory import FixtureFactory, ROOT


INSTALLER = ROOT / "_ops/bin/install-doc-warden-hooks.sh"
SESSION_HOOK = ROOT / "_ops/cursor-hooks/doc-warden-session.sh"
OBSERVE_HOOK = ROOT / "_ops/cursor-hooks/doc-warden-observe.sh"
POLICY = ROOT / "_ops/doc-warden/POLICY.md"


class HookContractTests(unittest.TestCase):
    def run_installer(self, home: Path, *arguments: str, check: bool = True, env=None):
        return subprocess.run(
            ["bash", str(INSTALLER), *arguments],
            text=True,
            capture_output=True,
            check=check,
            env={
                **os.environ,
                "DOC_WARDEN_HOOKS_FILE": str(home / ".cursor/hooks.json"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                **(env or {}),
            },
        )

    @staticmethod
    def hook_env(state: Path) -> dict[str, str]:
        return {
            **os.environ,
            "XDG_STATE_HOME": str(state),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "_ops/doc-warden/v2"),
        }

    def run_hook(self, event: str, payload: dict, state: Path):
        command = (
            ["bash", str(SESSION_HOOK)]
            if event == "session-start"
            else ["bash", str(OBSERVE_HOOK), event]
        )
        return subprocess.run(
            command,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
            env=self.hook_env(state),
        )

    def run_hook_through_shell_pipe(
        self,
        command: list[str],
        payload: dict,
        state: Path,
        *,
        home: Path,
    ):
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                'printf "%s" "$CURSOR_HOOK_PAYLOAD" | "$@"',
                "doc-warden-hook-pipe",
                *command,
            ],
            text=True,
            capture_output=True,
            check=True,
            env={
                **self.hook_env(state),
                "DOC_WARDEN_HOOKS_FILE": str(home / ".cursor/hooks.json"),
                "CURSOR_HOOK_PAYLOAD": json.dumps(payload),
            },
        )

    def run_maintenance(self, repo: Path, state: Path):
        return subprocess.run(
            [
                "python3",
                "-m",
                "doc_warden.cli",
                "doctor",
                "fleet",
                "--refresh-projections",
                "--repo",
                str(repo),
            ],
            text=True,
            capture_output=True,
            check=True,
            env=self.hook_env(state),
        )

    def mark_stale(self, fixture, state: Path) -> None:
        self.run_hook(
            "after-file-edit",
            {
                "cwd": str(fixture.repo),
                "file_path": str(fixture.repo / "README.md"),
            },
            state,
        )
        self.assertIsNotNone(
            read_projection_freshness(fixture.repo, state)
        )

    def hooks_fixture(self, home: Path) -> tuple[Path, bytes]:
        path = home / ".cursor/hooks.json"
        path.parent.mkdir(parents=True)
        original = (
            b'{\n  "version": 1,\n  "hooks": {\n'
            b'    "sessionStart": [{"command": "./hooks/unrelated.sh"}]\n'
            b"  }\n}\n"
        )
        path.write_bytes(original)
        return path, original

    def test_dry_run_is_deterministic_owned_only_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            before = sorted(
                (str(path.relative_to(home)), path.read_bytes())
                for path in home.rglob("*")
                if path.is_file()
            )
            first = self.run_installer(home, "--dry-run")
            second = self.run_installer(home, "--dry-run")
            self.assertEqual(first.stdout, second.stdout)
            preview = json.loads(first.stdout)
            self.assertEqual(preview["mode"], "dry-run")
            self.assertEqual(preview["writes"], [])
            self.assertEqual(len(preview["owned_additions"]), 3)
            self.assertNotIn("unrelated.sh", first.stdout)
            self.assertEqual(hooks.read_bytes(), original)
            self.assertEqual(
                sorted(
                    (str(path.relative_to(home)), path.read_bytes())
                    for path in home.rglob("*")
                    if path.is_file()
                ),
                before,
            )

    def test_installed_commands_follow_invoking_checkout_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "alternate checkout"
            installer = checkout / "_ops/bin/install-doc-warden-hooks.sh"
            installer.parent.mkdir(parents=True)
            shutil.copy2(INSTALLER, installer)
            home = root / "home"
            self.hooks_fixture(home)

            completed = subprocess.run(
                ["bash", str(installer), "--dry-run"],
                text=True,
                capture_output=True,
                check=True,
                env={
                    **os.environ,
                    "DOC_WARDEN_HOOKS_FILE": str(home / ".cursor/hooks.json"),
                    "XDG_STATE_HOME": str(root / "state"),
                },
            )
            preview = json.loads(completed.stdout)
            checkout_prefix = f"{checkout.resolve()}{os.sep}"
            for row in preview["owned_additions"]:
                command = shlex.split(row["entry"]["command"])
                self.assertEqual(command[0], "/bin/bash")
                self.assertTrue(
                    str(Path(command[1]).resolve()).startswith(checkout_prefix),
                    command,
                )
            self.assertNotIn("/Users/laurence.duggan/dev", completed.stdout)

    def test_installed_commands_bind_both_shims_to_their_own_source_root(self):
        fixture = FixtureFactory.create("hook-source-binding")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home = root / "home"
                self.hooks_fixture(home)
                malicious = root / "workspace-controlled"
                package = malicious / "doc_warden"
                package.mkdir(parents=True)
                (package / "__init__.py").write_text("", encoding="utf-8")
                marker = malicious / "redirected-python-loaded"
                (package / "cli.py").write_text(
                    "import os\n"
                    "from pathlib import Path\n"
                    "Path(os.environ['MALICIOUS_MARKER']).write_text('loaded')\n"
                    "print('{\"compromised\":true}')\n",
                    encoding="utf-8",
                )
                state = root / "state"
                env = {
                    **os.environ,
                    "DOC_WARDEN_HOOKS_FILE": str(home / ".cursor/hooks.json"),
                    "XDG_STATE_HOME": str(state),
                    "DOC_WARDEN_SOURCE_ROOT": str(malicious),
                    "PYTHONPATH": str(malicious),
                    "MALICIOUS_MARKER": str(marker),
                }
                preview = json.loads(
                    self.run_installer(
                        home,
                        "--dry-run",
                        env={
                            "DOC_WARDEN_SOURCE_ROOT": str(malicious),
                            "PYTHONPATH": str(malicious),
                        },
                    ).stdout
                )
                commands = {
                    row["entry"]["description"]: shlex.split(
                        row["entry"]["command"]
                    )
                    for row in preview["owned_additions"]
                }

                edited = subprocess.run(
                    commands["doc-warden-observe-file-edit"],
                    input=json.dumps(
                        {
                            "cwd": str(fixture.repo),
                            "file_path": str(fixture.repo / "README.md"),
                        }
                    ),
                    text=True,
                    capture_output=True,
                    check=True,
                    cwd=malicious,
                    env=env,
                )
                stopped = subprocess.run(
                    commands["doc-warden-observe-stop"],
                    input=json.dumps({"cwd": str(fixture.repo)}),
                    text=True,
                    capture_output=True,
                    check=True,
                    cwd=malicious,
                    env=env,
                )
                session = subprocess.run(
                    commands["doc-warden-session-context"],
                    input=json.dumps({"cwd": str(fixture.repo)}),
                    text=True,
                    capture_output=True,
                    check=True,
                    cwd=malicious,
                    env=env,
                )

                self.assertEqual(json.loads(edited.stdout), {})
                self.assertIn(
                    "followup_message",
                    json.loads(stopped.stdout),
                )
                self.assertIn(
                    "additional_context",
                    json.loads(session.stdout),
                )
                self.assertFalse(marker.exists())
        finally:
            fixture.cleanup()

    def test_source_and_installed_commands_preserve_piped_json_stdin(self):
        fixture = FixtureFactory.create("hook-piped-stdin")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home = root / "home"
                hooks, _ = self.hooks_fixture(home)
                self.run_installer(home, "--install")
                document = json.loads(hooks.read_text(encoding="utf-8"))
                installed = {
                    entry["description"]: shlex.split(entry["command"])
                    for entries in document["hooks"].values()
                    for entry in entries
                    if entry.get("description", "").startswith("doc-warden-")
                }
                source = {
                    "doc-warden-observe-file-edit": [
                        "/bin/bash",
                        str(OBSERVE_HOOK),
                        "after-file-edit",
                    ],
                    "doc-warden-observe-stop": [
                        "/bin/bash",
                        str(OBSERVE_HOOK),
                        "stop",
                    ],
                    "doc-warden-session-context": [
                        "/bin/bash",
                        str(SESSION_HOOK),
                    ],
                }
                revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                edit_payload = {
                    "cwd": str(fixture.repo),
                    "workspace_roots": [str(fixture.repo)],
                    "file_path": str(fixture.repo / "README.md"),
                }
                root_payload = {
                    "cwd": str(fixture.repo),
                    "workspace_roots": [str(fixture.repo)],
                }

                for label, commands in (
                    ("source", source),
                    ("installed", installed),
                ):
                    with self.subTest(label=label):
                        state = root / f"{label}-state"
                        edited = self.run_hook_through_shell_pipe(
                            commands["doc-warden-observe-file-edit"],
                            edit_payload,
                            state,
                            home=home,
                        )
                        stopped = self.run_hook_through_shell_pipe(
                            commands["doc-warden-observe-stop"],
                            root_payload,
                            state,
                            home=home,
                        )
                        session = self.run_hook_through_shell_pipe(
                            commands["doc-warden-session-context"],
                            root_payload,
                            state,
                            home=home,
                        )

                        self.assertEqual(json.loads(edited.stdout), {})
                        self.assertIsNotNone(
                            read_projection_freshness(fixture.repo, state)
                        )
                        self.assertIn(
                            "followup_message",
                            json.loads(stopped.stdout),
                        )
                        self.assertIn(
                            revision[:12],
                            json.loads(session.stdout)["additional_context"],
                        )
        finally:
            fixture.cleanup()

    def test_global_blocking_hook_registration_is_fail_open(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.hooks_fixture(home)
            preview = json.loads(self.run_installer(home, "--dry-run").stdout)
            blocking = {
                "beforeShellExecution",
                "beforeMCPExecution",
                "beforeReadFile",
            }
            for owned in preview["owned_additions"]:
                entry = owned["entry"]
                self.assertEqual(entry["type"], "command")
                if owned["event"] in blocking:
                    self.assertIs(entry.get("failClosed"), False)

    def test_after_file_edit_and_stop_are_never_claimed_as_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.hooks_fixture(home)
            preview = json.loads(self.run_installer(home, "--dry-run").stdout)
            observed = {
                row["event"]: row
                for row in preview["owned_additions"]
                if row["event"] in {"afterFileEdit", "stop"}
            }
            self.assertEqual(set(observed), {"afterFileEdit", "stop"})
            for row in observed.values():
                self.assertEqual(row["semantics"], "observation_only")
                self.assertFalse(row["can_block"])
                self.assertIs(row["entry"]["failClosed"], False)
                self.assertNotIn("permission", row["entry"])

    def test_cloud_report_uses_project_hook_capabilities_only(self):
        report = hook_capability_report()
        self.assertFalse(report["user_hooks_run_in_cloud"])
        self.assertTrue(report["project_command_hooks_only"])
        self.assertEqual(
            report["supported_cloud_events"],
            ("beforeShellExecution", "afterFileEdit"),
        )
        self.assertNotIn("sessionStart", report["supported_cloud_events"])
        self.assertNotIn("stop", report["supported_cloud_events"])

    def test_installer_preserves_unrelated_entries_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, _ = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            installed = hooks.read_bytes()
            document = json.loads(installed)
            self.assertEqual(
                document["hooks"]["sessionStart"][0]["command"],
                "./hooks/unrelated.sh",
            )
            owned = [
                entry
                for entries in document["hooks"].values()
                for entry in entries
                if entry.get("description", "").startswith("doc-warden-")
            ]
            self.assertEqual(len(owned), 3)
            self.run_installer(home, "--install")
            self.assertEqual(hooks.read_bytes(), installed)
            post_install_preview = json.loads(
                self.run_installer(home, "--dry-run").stdout
            )
            self.assertEqual(post_install_preview["owned_additions"], [])

            self.run_installer(home, "--uninstall")
            uninstalled = json.loads(hooks.read_text(encoding="utf-8"))
            self.assertEqual(
                uninstalled["hooks"]["sessionStart"],
                [{"command": "./hooks/unrelated.sh"}],
            )
            self.assertFalse(
                any(
                    entry.get("description", "").startswith("doc-warden-")
                    for entries in uninstalled["hooks"].values()
                    for entry in entries
                )
            )

    def test_first_install_recovers_preexisting_exact_owned_hooks_without_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, _ = self.hooks_fixture(home)
            preview = json.loads(
                self.run_installer(home, "--dry-run").stdout
            )
            self.assertEqual(len(preview["owned_additions"]), 3)
            document = json.loads(hooks.read_text(encoding="utf-8"))
            owned_descriptions = set()
            for row in preview["owned_additions"]:
                document["hooks"].setdefault(row["event"], []).append(
                    row["entry"]
                )
                owned_descriptions.add(row["entry"]["description"])
            hooks.write_text(
                json.dumps(document, indent=3, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            preexisting = hooks.read_bytes()
            state_root = home / ".local/state/doc-warden/hooks"
            backup = state_root / "preimage.json"
            manifest = state_root / "preimage-manifest.json"
            self.assertFalse(backup.exists())
            self.assertFalse(manifest.exists())

            installed = self.run_installer(
                home,
                "--install",
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(
                json.loads(installed.stdout)["status"],
                "installed",
            )
            self.assertEqual(hooks.read_bytes(), preexisting)
            self.assertTrue(backup.is_file())
            self.assertFalse(backup.is_symlink())
            self.assertTrue(manifest.is_file())
            self.assertFalse(manifest.is_symlink())

            manifest.unlink()
            repaired = self.run_installer(
                home,
                "--install",
                check=False,
            )
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(
                json.loads(repaired.stdout)["status"],
                "installed",
            )
            self.assertEqual(hooks.read_bytes(), preexisting)
            self.assertTrue(manifest.is_file())
            self.assertFalse(manifest.is_symlink())

            restored = self.run_installer(
                home,
                "--restore",
                check=False,
            )

            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(
                json.loads(restored.stdout)["status"],
                "restored",
            )
            self.assertEqual(hooks.read_bytes(), backup.read_bytes())
            restored_document = json.loads(
                hooks.read_text(encoding="utf-8")
            )
            self.assertEqual(
                restored_document["hooks"]["sessionStart"],
                [{"command": "./hooks/unrelated.sh"}],
            )
            self.assertFalse(
                any(
                    entry.get("description") in owned_descriptions
                    for entries in restored_document["hooks"].values()
                    for entry in entries
                )
            )

    def test_idempotent_install_repairs_missing_manifest_for_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            state_root = home / ".local/state/doc-warden/hooks"
            backup = state_root / "preimage.json"
            manifest = state_root / "preimage-manifest.json"

            self.run_installer(home, "--install")
            installed = hooks.read_bytes()
            installed_document = json.loads(installed)
            owned = [
                entry
                for entries in installed_document["hooks"].values()
                for entry in entries
                if entry.get("description", "").startswith("doc-warden-")
            ]
            self.assertEqual(len(owned), 3)
            self.assertEqual(backup.read_bytes(), original)

            manifest.unlink()
            self.run_installer(home, "--install")
            self.assertEqual(hooks.read_bytes(), installed)
            self.assertEqual(backup.read_bytes(), original)

            restored = self.run_installer(home, "--restore", check=False)

            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertTrue(manifest.is_file())
            self.assertEqual(hooks.read_bytes(), original)
            self.assertEqual(
                json.loads(hooks.read_text(encoding="utf-8"))["hooks"][
                    "sessionStart"
                ],
                [{"command": "./hooks/unrelated.sh"}],
            )

    def test_missing_manifest_accepts_owned_hook_reordering(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            manifest = (
                home
                / ".local/state/doc-warden/hooks/preimage-manifest.json"
            )
            self.run_installer(home, "--install")
            document = json.loads(hooks.read_text(encoding="utf-8"))
            document["hooks"]["sessionStart"].reverse()
            reordered = (
                json.dumps(document, indent=3, sort_keys=True) + "\n"
            ).encode("utf-8")
            hooks.write_bytes(reordered)
            manifest.unlink()

            repaired = self.run_installer(
                home,
                "--install",
                check=False,
            )

            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(hooks.read_bytes(), reordered)
            self.run_installer(home, "--restore")
            self.assertEqual(hooks.read_bytes(), original)

    def test_idempotent_install_repairs_missing_manifest_for_absent_preimage(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks = home / ".cursor/hooks.json"
            manifest = (
                home
                / ".local/state/doc-warden/hooks/preimage-manifest.json"
            )
            self.assertFalse(hooks.exists())

            self.run_installer(home, "--install")
            installed = hooks.read_bytes()
            original_manifest = json.loads(
                manifest.read_text(encoding="utf-8")
            )
            self.assertFalse(original_manifest["existed"])
            self.assertIsNone(original_manifest["preimage_sha256"])

            manifest.unlink()
            repaired = self.run_installer(
                home,
                "--install",
                check=False,
            )

            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(hooks.read_bytes(), installed)
            self.assertTrue(manifest.is_file())
            repaired_manifest = json.loads(
                manifest.read_text(encoding="utf-8")
            )
            self.assertFalse(repaired_manifest["existed"])
            self.assertIsNone(repaired_manifest["preimage_sha256"])
            self.assertEqual(
                repaired_manifest["installed_sha256"],
                original_manifest["installed_sha256"],
            )

            repaired_bytes = manifest.read_bytes()
            self.run_installer(home, "--install")
            self.assertEqual(hooks.read_bytes(), installed)
            self.assertEqual(manifest.read_bytes(), repaired_bytes)

            self.run_installer(home, "--restore")
            self.assertFalse(hooks.exists())
            self.run_installer(home, "--restore")
            self.assertFalse(hooks.exists())

    def test_missing_preimage_state_recovers_canonical_absent_install(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks = home / ".cursor/hooks.json"
            state_root = home / ".local/state/doc-warden/hooks"
            backup = state_root / "preimage.json"
            manifest = state_root / "preimage-manifest.json"
            self.assertFalse(hooks.exists())

            self.run_installer(home, "--install")
            installed = hooks.read_bytes()
            backup.unlink()
            manifest.unlink()

            repaired = self.run_installer(
                home,
                "--install",
                check=False,
            )

            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(hooks.read_bytes(), installed)
            repaired_manifest = json.loads(
                manifest.read_text(encoding="utf-8")
            )
            self.assertFalse(repaired_manifest["existed"])
            self.assertIsNone(repaired_manifest["preimage_sha256"])

            self.run_installer(home, "--restore")
            self.assertFalse(hooks.exists())

    def test_restore_reinstates_the_exact_preimage(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            self.assertNotEqual(hooks.read_bytes(), original)
            self.run_installer(home, "--restore")
            self.assertEqual(hooks.read_bytes(), original)

    def test_restore_recovers_missing_hook_file_from_valid_preimage(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            hooks.unlink()

            restored = self.run_installer(home, "--restore", check=False)

            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(hooks.read_bytes(), original)

    def test_restore_recovers_exact_preimage_after_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            self.run_installer(home, "--uninstall")
            self.assertNotEqual(hooks.read_bytes(), original)

            restored = self.run_installer(home, "--restore", check=False)

            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(hooks.read_bytes(), original)

    def test_restore_recovers_absent_preimage_after_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks = home / ".cursor/hooks.json"
            self.run_installer(home, "--install")
            self.run_installer(home, "--uninstall")
            self.assertTrue(hooks.is_file())

            restored = self.run_installer(home, "--restore", check=False)

            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertFalse(hooks.exists())

    def test_restore_recovers_when_only_owned_hook_content_diverged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            document = json.loads(hooks.read_text(encoding="utf-8"))
            document["hooks"]["stop"][0]["command"] = "./hooks/changed-owned.sh"
            hooks.write_text(
                json.dumps(document, indent=4, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            restored = self.run_installer(home, "--restore", check=False)

            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(hooks.read_bytes(), original)

    def test_restore_refuses_hook_file_symlink_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, _ = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            installed = hooks.read_bytes()
            target = home / "linked-hooks.json"
            target.write_bytes(installed)
            hooks.unlink()
            hooks.symlink_to(target)

            restored = self.run_installer(
                home,
                "--restore",
                check=False,
            )

            self.assertNotEqual(restored.returncode, 0)
            self.assertIn("hook_path_unsafe", restored.stderr)
            self.assertTrue(hooks.is_symlink())
            self.assertEqual(target.read_bytes(), installed)

    def test_install_and_uninstall_refuse_hook_file_symlink_without_touching_target(self):
        for mode in ("--install", "--uninstall"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                hooks, original = self.hooks_fixture(home)
                linked_content = original
                if mode == "--uninstall":
                    self.run_installer(home, "--install")
                    linked_content = hooks.read_bytes()
                target = home / "linked-hooks.json"
                target.write_bytes(linked_content)
                hooks.unlink()
                hooks.symlink_to(target)
                state_root = home / ".local/state/doc-warden/hooks"
                state_before = (
                    sorted(
                        (
                            str(path.relative_to(state_root)),
                            path.read_bytes(),
                        )
                        for path in state_root.rglob("*")
                        if path.is_file()
                    )
                    if state_root.exists()
                    else []
                )

                completed = self.run_installer(
                    home,
                    mode,
                    check=False,
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("hook_path_unsafe", completed.stderr)
                self.assertTrue(hooks.is_symlink())
                self.assertEqual(target.read_bytes(), linked_content)
                self.assertEqual(
                    (
                        sorted(
                            (
                                str(path.relative_to(state_root)),
                                path.read_bytes(),
                            )
                            for path in state_root.rglob("*")
                            if path.is_file()
                        )
                        if state_root.exists()
                        else []
                    ),
                    state_before,
                )

    def test_reinstall_preserves_first_preimage_after_intervening_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            state_root = home / ".local/state/doc-warden/hooks"
            backup = state_root / "preimage.json"
            manifest = state_root / "preimage-manifest.json"
            self.run_installer(home, "--install")
            first_backup = backup.read_bytes()
            first_manifest = json.loads(
                manifest.read_text(encoding="utf-8")
            )
            self.assertEqual(first_backup, original)
            self.run_installer(home, "--uninstall")

            document = json.loads(hooks.read_text(encoding="utf-8"))
            document["hooks"].setdefault("afterFileEdit", []).append(
                {
                    "command": "./hooks/intervening.sh",
                    "description": "unrelated-intervening-edit",
                }
            )
            intervening = (
                json.dumps(document, indent=3, sort_keys=True) + "\n"
            ).encode("utf-8")
            hooks.write_bytes(intervening)

            self.run_installer(home, "--install")
            reinstalled_manifest = json.loads(
                manifest.read_text(encoding="utf-8")
            )
            self.assertEqual(backup.read_bytes(), first_backup)
            self.assertEqual(
                reinstalled_manifest["existed"],
                first_manifest["existed"],
            )
            self.assertEqual(
                reinstalled_manifest["preimage_sha256"],
                first_manifest["preimage_sha256"],
            )
            self.assertNotEqual(
                reinstalled_manifest["installed_sha256"],
                first_manifest["installed_sha256"],
            )
            self.run_installer(home, "--restore")
            self.assertEqual(hooks.read_bytes(), original)

    def test_reinstall_after_manifest_loss_preserves_first_preimage(self):
        for originally_existed in (True, False):
            with self.subTest(originally_existed=originally_existed):
                with tempfile.TemporaryDirectory() as directory:
                    home = Path(directory)
                    hooks = home / ".cursor/hooks.json"
                    original = None
                    if originally_existed:
                        hooks, original = self.hooks_fixture(home)
                    state_root = (
                        home / ".local/state/doc-warden/hooks"
                    )
                    backup = state_root / "preimage.json"
                    manifest = state_root / "preimage-manifest.json"

                    self.run_installer(home, "--install")
                    first_backup = backup.read_bytes()
                    first_manifest = json.loads(
                        manifest.read_text(encoding="utf-8")
                    )
                    self.run_installer(home, "--uninstall")
                    manifest.unlink()

                    reinstalled = self.run_installer(
                        home,
                        "--install",
                        check=False,
                    )

                    self.assertEqual(
                        reinstalled.returncode,
                        0,
                        reinstalled.stderr,
                    )
                    self.assertEqual(backup.read_bytes(), first_backup)
                    repaired_manifest = json.loads(
                        manifest.read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        repaired_manifest["existed"],
                        first_manifest["existed"],
                    )
                    self.assertEqual(
                        repaired_manifest["preimage_sha256"],
                        first_manifest["preimage_sha256"],
                    )

                    self.run_installer(home, "--restore")
                    if originally_existed:
                        self.assertEqual(hooks.read_bytes(), original)
                    else:
                        self.assertFalse(hooks.exists())

    def test_reinstall_after_manifest_loss_refuses_unrelated_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, _ = self.hooks_fixture(home)
            state_root = home / ".local/state/doc-warden/hooks"
            backup = state_root / "preimage.json"
            manifest = state_root / "preimage-manifest.json"
            self.run_installer(home, "--install")
            self.run_installer(home, "--uninstall")
            manifest.unlink()
            unrelated = b'{"hooks":{"sessionStart":[]}}\n'
            backup.write_bytes(unrelated)
            current = hooks.read_bytes()

            reinstalled = self.run_installer(
                home,
                "--install",
                check=False,
            )

            self.assertNotEqual(reinstalled.returncode, 0)
            self.assertIn(
                "hook_preimage_bytes_invalid",
                reinstalled.stderr,
            )
            self.assertEqual(hooks.read_bytes(), current)
            self.assertEqual(backup.read_bytes(), unrelated)
            self.assertFalse(manifest.exists())

    def test_restore_refuses_to_discard_post_install_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, _ = self.hooks_fixture(home)
            self.run_installer(home, "--install")
            document = json.loads(hooks.read_text(encoding="utf-8"))
            document["hooks"]["sessionStart"].append(
                {"command": "./hooks/added-after-install.sh"}
            )
            changed = (
                json.dumps(document, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            hooks.write_bytes(changed)

            restored = self.run_installer(
                home,
                "--restore",
                check=False,
            )
            self.assertNotEqual(restored.returncode, 0)
            self.assertIn("hook_restore_conflict", restored.stderr)
            self.assertEqual(hooks.read_bytes(), changed)

    def test_forced_failure_leaves_hook_file_at_exact_preimage(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks, original = self.hooks_fixture(home)
            manifest = (
                home
                / ".local/state/doc-warden/hooks/preimage-manifest.json"
            )
            failed = self.run_installer(
                home,
                "--install",
                check=False,
                env={"DOC_WARDEN_HOOK_TEST_FAIL_STAGE": "before-replace"},
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("forced_failure_before_replace", failed.stderr)
            self.assertEqual(hooks.read_bytes(), original)
            self.assertFalse(manifest.exists())

            restored = self.run_installer(
                home,
                "--restore",
                check=False,
            )

            self.assertNotEqual(restored.returncode, 0)
            self.assertIn("hook_preimage_missing", restored.stderr)
            self.assertEqual(restored.stdout, "")
            self.assertEqual(hooks.read_bytes(), original)

    def test_hook_shims_are_command_only_fail_open_and_freshness_only(self):
        fixture = FixtureFactory.create()
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                before = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                    text=True,
                )
                env = {
                    **os.environ,
                    "XDG_STATE_HOME": str(state),
                }
                edited = subprocess.run(
                    ["bash", str(OBSERVE_HOOK), "after-file-edit"],
                    input=json.dumps(
                        {
                            "cwd": str(fixture.repo),
                            "file_path": str(fixture.repo / "README.md"),
                        }
                    ),
                    text=True,
                    capture_output=True,
                    check=True,
                    env=env,
                )
                self.assertEqual(json.loads(edited.stdout), {})
                markers = list(
                    (state / "doc-warden/freshness").glob("*.json")
                )
                self.assertEqual(len(markers), 1)
                marker = json.loads(markers[0].read_text(encoding="utf-8"))
                self.assertEqual(marker["status"], "potentially_stale")
                self.assertEqual(marker["repository_writes"], [])

                stopped = subprocess.run(
                    ["bash", str(OBSERVE_HOOK), "stop"],
                    input=json.dumps({"cwd": str(fixture.repo)}),
                    text=True,
                    capture_output=True,
                    check=True,
                    env=env,
                )
                self.assertIn("followup_message", json.loads(stopped.stdout))

                session = subprocess.run(
                    ["bash", str(SESSION_HOOK)],
                    input=json.dumps({"cwd": str(fixture.repo)}),
                    text=True,
                    capture_output=True,
                    check=True,
                    env=env,
                )
                self.assertIn("additional_context", json.loads(session.stdout))
                self.assertEqual(
                    subprocess.check_output(
                        ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                        text=True,
                    ),
                    before,
                )
        finally:
            fixture.cleanup()

    def test_after_file_edit_uses_edited_file_repository_in_multi_root_payload(self):
        cwd_fixture = FixtureFactory.create("hook-cwd")
        edited_fixture = FixtureFactory.create("hook-edited")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                completed = self.run_hook(
                    "after-file-edit",
                    {
                        "cwd": str(cwd_fixture.repo),
                        "workspace_root": str(cwd_fixture.repo),
                        "workspace_roots": [
                            str(cwd_fixture.repo),
                            str(edited_fixture.repo),
                        ],
                        "file_path": str(edited_fixture.repo / "README.md"),
                    },
                    state,
                )
                self.assertEqual(json.loads(completed.stdout), {})
                self.assertIsNone(
                    read_projection_freshness(cwd_fixture.repo, state)
                )
                edited_freshness = read_projection_freshness(
                    edited_fixture.repo,
                    state,
                )
                self.assertIsNotNone(edited_freshness)
                self.assertEqual(
                    edited_freshness["repository_key"],
                    edited_fixture.repository_key,
                )
        finally:
            cwd_fixture.cleanup()
            edited_fixture.cleanup()

    def test_stop_uses_edited_file_repository_in_multi_root_payload(self):
        cwd_fixture = FixtureFactory.create("stop-cwd")
        edited_fixture = FixtureFactory.create("stop-edited")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                payload = {
                    "cwd": str(cwd_fixture.repo),
                    "workspace_root": str(cwd_fixture.repo),
                    "workspace_roots": [
                        str(cwd_fixture.repo),
                        str(edited_fixture.repo),
                    ],
                    "file_path": str(edited_fixture.repo / "README.md"),
                }
                edited = self.run_hook("after-file-edit", payload, state)
                self.assertEqual(json.loads(edited.stdout), {})
                self.assertIsNone(
                    read_projection_freshness(cwd_fixture.repo, state)
                )
                self.assertIsNotNone(
                    read_projection_freshness(edited_fixture.repo, state)
                )

                stopped = self.run_hook("stop", payload, state)

                self.assertIn(
                    "followup_message",
                    json.loads(stopped.stdout),
                )
        finally:
            cwd_fixture.cleanup()
            edited_fixture.cleanup()

    def test_stop_checks_later_stale_root_in_multi_root_payload(self):
        first_fixture = FixtureFactory.create("stop-first-root")
        stale_fixture = FixtureFactory.create("stop-stale-root")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                self.mark_stale(stale_fixture, state)

                stopped = self.run_hook(
                    "stop",
                    {
                        "cwd": str(first_fixture.repo),
                        "workspace_root": str(first_fixture.repo),
                        "workspace_roots": [
                            str(first_fixture.repo),
                            str(stale_fixture.repo),
                        ],
                    },
                    state,
                )

                self.assertEqual(
                    json.loads(stopped.stdout),
                    {
                        "followup_message": (
                            "Doc-warden observed that the generated governance "
                            "view may be stale. Refresh the read-only roadmap "
                            "view; this is an observation, not a blocking gate."
                        )
                    },
                )
                self.assertNotIn(str(first_fixture.repo), stopped.stdout)
                self.assertNotIn(str(stale_fixture.repo), stopped.stdout)
        finally:
            first_fixture.cleanup()
            stale_fixture.cleanup()

    def test_after_file_edit_invalid_or_missing_path_is_ignored(self):
        fixture = FixtureFactory.create("hook-invalid-file")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                for payload in (
                    {
                        "cwd": str(fixture.repo),
                        "file_path": str(fixture.repo / "missing.md"),
                    },
                    {"cwd": str(fixture.repo)},
                ):
                    with self.subTest(payload=payload):
                        completed = self.run_hook(
                            "after-file-edit",
                            payload,
                            state,
                        )
                        self.assertEqual(json.loads(completed.stdout), {})
                        self.assertIsNone(
                            read_projection_freshness(fixture.repo, state)
                        )
        finally:
            fixture.cleanup()

    def test_after_file_edit_ignores_unconfigured_repository(self):
        fixture = FixtureFactory.create("unconfigured")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                completed = self.run_hook(
                    "after-file-edit",
                    {
                        "cwd": str(fixture.repo),
                        "file_path": str(fixture.repo / "README.md"),
                    },
                    state,
                )

                self.assertEqual(json.loads(completed.stdout), {})
                self.assertIsNone(
                    read_projection_freshness(fixture.repo, state)
                )
                self.assertFalse(
                    (state / "doc-warden/freshness").exists()
                )
        finally:
            fixture.cleanup()

    def test_session_start_keeps_cwd_priority_over_unrelated_file_path(self):
        cwd_fixture = FixtureFactory.create("session-cwd")
        other_fixture = FixtureFactory.create("session-file")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                completed = self.run_hook(
                    "session-start",
                    {
                        "cwd": str(cwd_fixture.repo),
                        "file_path": str(other_fixture.repo / "README.md"),
                    },
                    state,
                )
                context = json.loads(completed.stdout)["additional_context"]
                cwd_revision = subprocess.check_output(
                    ["git", "-C", str(cwd_fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                self.assertIn(cwd_revision[:12], context)
                self.assertIn("roadmap rows are visible", context)
                self.assertIn("read-only roadmap refresh", context)
                self.assertFalse(
                    (state / "doc-warden/freshness").exists()
                )
        finally:
            cwd_fixture.cleanup()
            other_fixture.cleanup()

    def test_session_start_truthfully_reports_unhealthy_governance_states(self):
        fixtures = []
        try:
            unmigrated = FixtureFactory.create("unconfigured")
            fixtures.append(unmigrated)

            write_disabled = FixtureFactory.create("session-write-disabled")
            fixtures.append(write_disabled)
            config_path = (
                write_disabled.repo / ".planning/doc-warden.json"
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["enabled"] = False
            config_path.write_bytes(canonical_json(config))

            invalid = FixtureFactory.create("session-invalid")
            fixtures.append(invalid)
            (invalid.repo / ".planning/doc-warden.json").write_text(
                "{invalid",
                encoding="utf-8",
            )

            snapshot_blocked = FixtureFactory.create(
                "session-snapshot-blocked"
            )
            fixtures.append(snapshot_blocked)
            (snapshot_blocked.repo / ".planning/ROADMAP.md").write_text(
                "raw-roadmap-body",
                encoding="utf-8",
            )

            cases = (
                (
                    unmigrated,
                    "requires governance migration",
                ),
                (
                    write_disabled,
                    "governance writes are disabled",
                ),
                (
                    invalid,
                    "governance view is blocked or invalid",
                ),
                (
                    snapshot_blocked,
                    "governance view is blocked or invalid",
                ),
            )
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                for fixture, expected in cases:
                    with self.subTest(expected=expected):
                        completed = self.run_hook(
                            "session-start",
                            {"cwd": str(fixture.repo)},
                            state,
                        )
                        output = json.loads(completed.stdout)
                        self.assertEqual(
                            set(output),
                            {"additional_context"},
                        )
                        context = output["additional_context"]
                        self.assertIn(expected, context)
                        self.assertIn(
                            "Roadmap rows were not summarized",
                            context,
                        )
                        self.assertIn("doctor repo", context)
                        self.assertNotIn(
                            "roadmap rows are visible",
                            context,
                        )
                        self.assertNotIn(
                            "read-only roadmap refresh",
                            context,
                        )
                        self.assertNotIn(
                            "raw-roadmap-body",
                            context,
                        )
                        self.assertNotIn(
                            "roadmap markers invalid",
                            context,
                        )
                        self.assertLessEqual(len(context), 512)
        finally:
            for fixture in fixtures:
                fixture.cleanup()

    def test_head_advancement_carries_stale_marker_to_current_revision(self):
        fixture = FixtureFactory.create("hook-head-advance")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                self.mark_stale(fixture, state)
                prior = read_projection_freshness(fixture.repo, state)
                self.assertIsNotNone(prior)

                (fixture.repo / "README.md").write_text(
                    "fixture advanced\n",
                    encoding="utf-8",
                )
                subprocess.run(
                    ["git", "-C", str(fixture.repo), "add", "README.md"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(fixture.repo), "commit", "-qm", "advance"],
                    check=True,
                )
                current_revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()

                stopped = self.run_hook(
                    "stop",
                    {"cwd": str(fixture.repo)},
                    state,
                )
                self.assertIn("followup_message", json.loads(stopped.stdout))
                carried = read_projection_freshness(fixture.repo, state)
                self.assertIsNotNone(carried)
                self.assertNotEqual(prior["source_revision"], current_revision)
                self.assertEqual(carried["source_revision"], current_revision)
        finally:
            fixture.cleanup()

    def test_successful_canvas_refresh_clears_matching_freshness_marker(self):
        fixture = FixtureFactory.create("hook-canvas-refresh")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "state"
                self.mark_stale(fixture, state)
                target = root / "roadmap.canvas.tsx"
                completed = subprocess.run(
                    [
                        "python3",
                        "-m",
                        "doc_warden.cli",
                        "view",
                        "repo",
                        "--repo",
                        str(fixture.repo),
                        "--canvas",
                        str(target),
                    ],
                    text=True,
                    capture_output=True,
                    check=True,
                    env=self.hook_env(state),
                )
                self.assertEqual(
                    json.loads(completed.stdout)["source_revision"],
                    subprocess.check_output(
                        ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                        text=True,
                    ).strip(),
                )
                self.assertTrue(target.is_file())
                self.assertIsNone(
                    read_projection_freshness(fixture.repo, state)
                )
        finally:
            fixture.cleanup()

    def test_canvas_refresh_refuses_symlinked_freshness_marker(self):
        fixture = FixtureFactory.create("hook-canvas-symlink")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "state"
                self.mark_stale(fixture, state)
                marker = next(
                    (state / "doc-warden/freshness").glob("*.json")
                )
                outside = root / "outside-marker.json"
                outside.write_bytes(marker.read_bytes())
                outside_before = outside.read_bytes()
                marker.unlink()
                marker.symlink_to(outside)
                target = root / "roadmap.canvas.tsx"

                completed = subprocess.run(
                    [
                        "python3",
                        "-m",
                        "doc_warden.cli",
                        "view",
                        "repo",
                        "--repo",
                        str(fixture.repo),
                        "--canvas",
                        str(target),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=self.hook_env(state),
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(
                    json.loads(completed.stdout)["code"],
                    "projection_freshness_marker_unavailable",
                )
                self.assertFalse(target.exists())
                self.assertTrue(marker.is_symlink())
                self.assertEqual(outside.read_bytes(), outside_before)
        finally:
            fixture.cleanup()

    def test_successful_canvas_refresh_clears_valid_diverged_history_marker(self):
        fixture = FixtureFactory.create("hook-canvas-diverged-history")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "state"
                original_revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                config = (
                    fixture.repo / ".planning/doc-warden.json"
                ).read_bytes()
                self.mark_stale(fixture, state)

                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(fixture.repo),
                        "switch",
                        "--orphan",
                        "rewritten",
                    ],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                (fixture.repo / "README.md").write_text(
                    "rewritten history\n",
                    encoding="utf-8",
                )
                config_path = fixture.repo / ".planning/doc-warden.json"
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_bytes(config)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(fixture.repo),
                        "add",
                        "README.md",
                        ".planning/doc-warden.json",
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(fixture.repo),
                        "commit",
                        "-qm",
                        "rewritten root",
                    ],
                    check=True,
                )
                current_revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                self.assertEqual(
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(fixture.repo),
                            "cat-file",
                            "-e",
                            f"{original_revision}^{{commit}}",
                        ],
                        check=False,
                    ).returncode,
                    0,
                )
                self.assertNotEqual(
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(fixture.repo),
                            "merge-base",
                            "--is-ancestor",
                            original_revision,
                            current_revision,
                        ],
                        check=False,
                    ).returncode,
                    0,
                )

                target = root / "roadmap.canvas.tsx"
                completed = subprocess.run(
                    [
                        "python3",
                        "-m",
                        "doc_warden.cli",
                        "view",
                        "repo",
                        "--repo",
                        str(fixture.repo),
                        "--canvas",
                        str(target),
                    ],
                    text=True,
                    capture_output=True,
                    check=True,
                    env=self.hook_env(state),
                )
                self.assertEqual(
                    json.loads(completed.stdout)["source_revision"],
                    current_revision,
                )
                self.assertTrue(target.is_file())
                self.assertIsNone(
                    read_projection_freshness(fixture.repo, state)
                )
                stopped = self.run_hook(
                    "stop",
                    {"cwd": str(fixture.repo)},
                    state,
                )
                self.assertEqual(json.loads(stopped.stdout), {})
        finally:
            fixture.cleanup()

    def test_generated_canvas_and_projection_edits_do_not_reopen_staleness(self):
        fixture = FixtureFactory.create("hook-generated-canvas")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "state"
                governed_source = fixture.repo / ".planning/doc-warden.json"
                self.run_hook(
                    "after-file-edit",
                    {
                        "cwd": str(fixture.repo),
                        "file_path": str(governed_source),
                    },
                    state,
                )
                self.assertIsNotNone(
                    read_projection_freshness(fixture.repo, state)
                )

                canvas = fixture.repo / "roadmap.canvas.tsx"
                subprocess.run(
                    [
                        "python3",
                        "-m",
                        "doc_warden.cli",
                        "view",
                        "repo",
                        "--repo",
                        str(fixture.repo),
                        "--canvas",
                        str(canvas),
                    ],
                    text=True,
                    capture_output=True,
                    check=True,
                    env=self.hook_env(state),
                )
                self.assertIsNone(
                    read_projection_freshness(fixture.repo, state)
                )

                for generated in (
                    canvas,
                    fixture.repo / ".planning/generated/index.json",
                ):
                    generated.parent.mkdir(parents=True, exist_ok=True)
                    generated.touch()
                    edited = self.run_hook(
                        "after-file-edit",
                        {
                            "cwd": str(fixture.repo),
                            "file_path": str(generated),
                        },
                        state,
                    )
                    self.assertEqual(json.loads(edited.stdout), {})
                    self.assertIsNone(
                        read_projection_freshness(fixture.repo, state)
                    )
        finally:
            fixture.cleanup()

    def test_read_only_maintenance_preserves_stale_evidence_until_real_refresh(self):
        fixture = FixtureFactory.create("hook-maintenance-refresh")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "state"
                self.mark_stale(fixture, state)
                marker = next(
                    (state / "doc-warden/freshness").glob("*.json")
                )
                marker_before = marker.read_bytes()
                seed = (
                    ROOT
                    / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
                )
                seed_before = seed.read_bytes()
                completed = subprocess.run(
                    [
                        "python3",
                        "-m",
                        "doc_warden.cli",
                        "doctor",
                        "fleet",
                        "--refresh-projections",
                        "--repo",
                        str(fixture.repo),
                    ],
                    text=True,
                    capture_output=True,
                    check=True,
                    env=self.hook_env(state),
                )
                result = json.loads(completed.stdout)
                self.assertEqual(result["sink"], "job")
                self.assertEqual(marker.read_bytes(), marker_before)
                self.assertIsNotNone(
                    read_projection_freshness(fixture.repo, state)
                )
                self.assertEqual(
                    result["payload"]["status"],
                    "attention_required",
                )
                self.assertIn(
                    "generated_projection_freshness",
                    result["payload"]["uncertain"],
                )
                self.assertEqual(
                    result["payload"]["next_action"],
                    "refresh_governance_view_in_chat",
                )
                self.assertEqual(seed.read_bytes(), seed_before)
        finally:
            fixture.cleanup()

    def test_fleet_maintenance_reports_other_checkout_marker_without_consuming_it(self):
        anchor = FixtureFactory.create("maintenance-anchor")
        edited = FixtureFactory.create("maintenance-edited")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "state"
                self.mark_stale(edited, state)
                marker = next(
                    (state / "doc-warden/freshness").glob("*.json")
                )
                marker_before = marker.read_bytes()

                completed = self.run_maintenance(anchor.repo, state)
                payload = json.loads(completed.stdout)["payload"]

                self.assertEqual(payload["status"], "attention_required")
                self.assertIn(
                    "generated_projection_freshness",
                    payload["uncertain"],
                )
                self.assertEqual(
                    payload["next_action"],
                    "refresh_governance_view_in_chat",
                )
                self.assertEqual(marker.read_bytes(), marker_before)
                self.assertIsNotNone(
                    read_projection_freshness(edited.repo, state)
                )
                self.assertIsNone(
                    read_projection_freshness(anchor.repo, state)
                )
        finally:
            anchor.cleanup()
            edited.cleanup()

    def test_fleet_maintenance_reports_invalid_markers_without_mutating_them(self):
        fixture = FixtureFactory.create("maintenance-invalid-markers")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / "state"
                freshness = state / "doc-warden/freshness"
                freshness.mkdir(parents=True)
                malformed = freshness / f"{'a' * 64}.json"
                malformed.write_bytes(b"{not-json")
                unavailable_target = root / "outside-marker.json"
                unavailable_target.write_bytes(b"outside")
                unavailable = freshness / f"{'b' * 64}.json"
                unavailable.symlink_to(unavailable_target)

                completed = self.run_maintenance(fixture.repo, state)
                replayed = self.run_maintenance(fixture.repo, state)
                payload = json.loads(completed.stdout)["payload"]

                self.assertEqual(replayed.stdout, completed.stdout)
                self.assertEqual(payload["status"], "attention_required")
                self.assertEqual(
                    [
                        value
                        for value in payload["uncertain"]
                        if value.startswith("generated_projection_freshness")
                    ],
                    [
                        "generated_projection_freshness_malformed",
                        "generated_projection_freshness_unavailable",
                    ],
                )
                self.assertEqual(
                    payload["next_action"],
                    "inspect_projection_freshness_state",
                )
                self.assertEqual(malformed.read_bytes(), b"{not-json")
                self.assertTrue(unavailable.is_symlink())
                self.assertEqual(unavailable.readlink(), unavailable_target)
                self.assertEqual(unavailable_target.read_bytes(), b"outside")
        finally:
            fixture.cleanup()

    def test_fleet_maintenance_bounds_marker_scan_without_mutating_entries(self):
        fixture = FixtureFactory.create("maintenance-marker-bound")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "state"
                freshness = state / "doc-warden/freshness"
                freshness.mkdir(parents=True)
                for index in range(257):
                    (freshness / f"{index:064x}.json").write_bytes(b"{}")

                completed = self.run_maintenance(fixture.repo, state)
                payload = json.loads(completed.stdout)["payload"]

                self.assertEqual(payload["status"], "attention_required")
                self.assertIn(
                    "generated_projection_freshness_scan_limited",
                    payload["uncertain"],
                )
                self.assertEqual(
                    payload["next_action"],
                    "inspect_projection_freshness_state",
                )
                self.assertEqual(
                    len(list(freshness.glob("*.json"))),
                    257,
                )
                self.assertEqual(
                    (freshness / f"{0:064x}.json").read_bytes(),
                    b"{}",
                )
        finally:
            fixture.cleanup()

    def test_local_job_command_cannot_apply_commit_push_or_merge(self):
        job = maintenance_job_contract()
        self.assertEqual(job["id"], "doc-warden-maintenance")
        self.assertEqual(job["type"], "command")
        self.assertEqual(job["serialization"], "per_job_dispatcher_lock")
        self.assertGreaterEqual(job["interval_seconds"], 60)
        self.assertEqual(
            job["args"],
            [
                str(ROOT / "_ops/bin/doc-warden.sh"),
                "doctor",
                "fleet",
                "--refresh-projections",
                "--repo",
                str(ROOT),
            ],
        )
        self.assertEqual(
            shlex.split(job["display_command"]),
            [job["program"], *job["args"]],
        )
        command = " ".join([job["program"], *job["args"]]).lower()
        for forbidden in (
            " reconcile ",
            " apply ",
            " commit ",
            " push ",
            " merge ",
            "gh ",
            "github",
            " draft ",
            " update ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, f" {command} ")
        self.assertTrue(job["read_only"])

        envelope = job_egress(
            {
                "schema": "doc-warden/job-report/v1",
                "job_id": job["id"],
                "status": "pass",
                "source_revision": "a" * 40,
                "read_only": True,
                "serialized": True,
                "repository_writes": [],
            }
        )
        self.assertEqual(envelope["sink"], "job")
        self.assertEqual(envelope["payload"]["repository_writes"], [])

    def test_policy_maintenance_command_matches_generated_contract(self):
        match = re.search(
            r"Portable command contract:\n\n```text\n([^\n]+)\n```",
            POLICY.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(match)
        job = maintenance_job_contract()
        root = str(ROOT.resolve())
        normalized = [
            argument.replace(root, "<resolved-source-root>")
            for argument in [job["program"], *job["args"]]
        ]
        self.assertEqual(
            shlex.split(match.group(1)),
            normalized,
        )

    def test_local_job_command_preserves_typed_source_root_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "governed checkout; literal"
            wrapper = source_root / "_ops/bin/doc-warden.sh"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("#!/bin/bash\n", encoding="utf-8")

            job = maintenance_job_contract(source_root=source_root)

            self.assertEqual(job["program"], "/bin/bash")
            resolved_root = source_root.resolve()
            self.assertEqual(
                job["args"],
                [
                    str(wrapper.resolve()),
                    "doctor",
                    "fleet",
                    "--refresh-projections",
                    "--repo",
                    str(resolved_root),
                ],
            )
            self.assertEqual(
                shlex.split(job["display_command"]),
                [job["program"], *job["args"]],
            )

    def test_maintenance_lock_is_shared_across_checkout_copies(self):
        worker = textwrap.dedent(
            """
            import sys
            import time
            from pathlib import Path

            import doc_warden.cli as cli

            tag, fake_source, log_path, release_path = sys.argv[1:]
            cli.__file__ = fake_source
            log = Path(log_path)
            release = Path(release_path)

            def inventory(_repo):
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(tag + "\\n")
                    handle.flush()
                if tag == "first":
                    deadline = time.monotonic() + 5
                    while not release.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                return []

            cli.inventory_fleet = inventory
            cli._repo_status = lambda _repo: {"source_revision": "a" * 40}
            cli._maintenance_egress(Path.cwd())
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for name in ("checkout-a", "checkout-b"):
                source = root / name / "_ops/doc-warden/v2/doc_warden/cli.py"
                source.parent.mkdir(parents=True)
                source.write_text("# checkout-local module\\n", encoding="utf-8")
                sources.append(source)
            log = root / "entered.log"
            release = root / "release"
            home = root / "home"
            state = root / "state"
            home.mkdir()
            env = {
                **os.environ,
                "DOC_WARDEN_HOOKS_FILE": str(home / ".cursor/hooks.json"),
                "XDG_STATE_HOME": str(state),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ROOT / "_ops/doc-warden/v2"),
            }

            first = subprocess.Popen(
                [
                    "python3",
                    "-c",
                    worker,
                    "first",
                    str(sources[0]),
                    str(log),
                    str(release),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=root,
                env=env,
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.exists() and "first" in log.read_text(encoding="utf-8"):
                    break
                if first.poll() is not None:
                    break
                time.sleep(0.01)
            if not log.exists() or "first" not in log.read_text(encoding="utf-8"):
                release.touch()
                stdout, stderr = first.communicate(timeout=5)
                self.fail(
                    "first maintenance worker did not enter: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )

            second = subprocess.Popen(
                [
                    "python3",
                    "-c",
                    worker,
                    "second",
                    str(sources[1]),
                    str(log),
                    str(release),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=root,
                env=env,
            )
            overlap_deadline = time.monotonic() + 1
            overlapped = False
            while time.monotonic() < overlap_deadline:
                entered = log.read_text(encoding="utf-8").splitlines()
                if "second" in entered:
                    overlapped = True
                    break
                if second.poll() is not None:
                    break
                time.sleep(0.01)

            release.touch()
            first_stdout, first_stderr = first.communicate(timeout=5)
            second_stdout, second_stderr = second.communicate(timeout=5)
            self.assertEqual(
                first.returncode,
                0,
                f"stdout={first_stdout!r} stderr={first_stderr!r}",
            )
            self.assertEqual(
                second.returncode,
                0,
                f"stdout={second_stdout!r} stderr={second_stderr!r}",
            )
            self.assertFalse(
                overlapped,
                "maintenance workers from distinct checkouts entered concurrently",
            )
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                ["first", "second"],
            )
            self.assertTrue(
                (state / "doc-warden/locks/maintenance.lock").is_file()
            )

    def test_maintenance_cli_emits_closed_read_only_job_egress(self):
        fixture = FixtureFactory.create()
        try:
            before = subprocess.check_output(
                ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                text=True,
            )
            with tempfile.TemporaryDirectory() as state:
                env = {
                    **os.environ,
                    "XDG_STATE_HOME": state,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(ROOT / "_ops/doc-warden/v2"),
                }
                completed = subprocess.run(
                    [
                        "python3",
                        "-m",
                        "doc_warden.cli",
                        "doctor",
                        "fleet",
                        "--refresh-projections",
                        "--repo",
                        str(fixture.repo),
                    ],
                    text=True,
                    capture_output=True,
                    check=True,
                    env=env,
                )
            result = json.loads(completed.stdout)
            self.assertEqual(result["schema"], "doc-warden/egress/v1")
            self.assertEqual(result["sink"], "job")
            self.assertTrue(result["payload"]["serialized"])
            self.assertTrue(result["payload"]["read_only"])
            self.assertEqual(result["payload"]["repository_writes"], [])
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                    text=True,
                ),
                before,
            )
        finally:
            fixture.cleanup()

    def test_doc_warden_skill_is_in_the_managed_install_allow_lists(self):
        source = (ROOT / "_ops/bin/install-skills.sh").read_text(encoding="utf-8")
        for assignment in (
            "DEV_SKILLS=",
            "CURSOR_SKILLS=",
            "CLAUDE_SKILLS=",
            "CODEX_SKILLS=",
        ):
            line = next(
                line for line in source.splitlines() if line.startswith(assignment)
            )
            self.assertIn("doc-warden", line)


if __name__ == "__main__":
    unittest.main()
