"""Fixture-only INT-008 imported-utility isolation tests."""

from argparse import Namespace
from contextlib import contextmanager, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import imported_skill_isolation as m


@contextmanager
def fixture(config: bytes | None = None):
    with tempfile.TemporaryDirectory(prefix="int008-imported-isolation-") as raw:
        root = Path(raw).resolve()
        host = root / "host"
        operation = root / "operation"
        for relative in (
            ".codex",
            ".agents/skills",
            ".cursor/skills",
            ".codex/skills/.system",
            ".codex/plugins/sample",
        ):
            (host / relative).mkdir(parents=True)

        content = {}
        expected = {}
        for name in m.SKILL_NAMES:
            skill = host / ".agents/skills" / name
            skill.mkdir()
            data = f"# fixture {name}\nCursor-only semantics for {name}.\n".encode()
            (skill / "SKILL.md").write_bytes(data)
            (skill / "SKILL.md").chmod(0o640)
            content[name] = data
            expected[name] = m.sha(data)

            # Same-name skills in other discovery roots are outside this executor.
            codex_copy = host / ".codex/skills" / name
            codex_copy.mkdir()
            (codex_copy / "SKILL.md").write_text(f"# unrelated Codex {name}\n")
            cursor_copy = host / ".cursor/skills" / name
            cursor_copy.mkdir()
            (cursor_copy / "SKILL.md").write_text(f"# unrelated Cursor {name}\n")

        (host / ".codex/skills/.system/marker").write_text("system-owned\n")
        (host / ".codex/plugins/sample/marker").write_text("plugin-owned\n")
        (host / ".cursor/config.json").parent.mkdir(exist_ok=True)
        (host / ".cursor/config.json").write_text('{"cursor":true}\n')
        config_path = host / ".codex/config.toml"
        config_bytes = config if config is not None else (
            b'# fixture config\napi_token = "fixture-secret-value"\n\n'
            b'[[skills.config]]\npath = "/other/sdk/SKILL.md"\nenabled = true\n'
            b'unknown_field = "preserve-me"\n'
        )
        config_path.write_bytes(config_bytes)
        config_path.chmod(0o640)
        args = Namespace(
            host_root=host,
            operation_dir=operation,
            host_build="21828",
            approve=None,
        )
        with patch.object(m, "EXPECTED_SHA256", expected):
            yield Namespace(
                root=root,
                host=host,
                operation=operation,
                config=config_path,
                args=args,
                source_content=content,
                expected=expected,
            )


def preview(f) -> dict:
    result = m.preview(f.args)
    f.args.approve = result["action_sha256"]
    return result


def preserved_tree(f) -> dict[str, tuple[int, bytes]]:
    paths = []
    for name in m.SKILL_NAMES:
        paths.extend(
            [
                f.host / ".agents/skills" / name / "SKILL.md",
                f.host / ".codex/skills" / name / "SKILL.md",
                f.host / ".cursor/skills" / name / "SKILL.md",
            ]
        )
    paths.extend(
        [
            f.host / ".codex/skills/.system/marker",
            f.host / ".codex/plugins/sample/marker",
            f.host / ".cursor/config.json",
        ]
    )
    return {
        str(path): (stat.S_IMODE(path.stat().st_mode), path.read_bytes()) for path in paths
    }


class IsolationTransaction(unittest.TestCase):
    def test_preview_apply_verify_idempotence_and_exact_rollback(self):
        with fixture() as f:
            config_before = f.config.read_bytes()
            mode_before = stat.S_IMODE(f.config.stat().st_mode)
            preserved = preserved_tree(f)
            result = preview(f)

            self.assertTrue(result["changed"])
            self.assertEqual(result["selectors_to_add"], list(m.SKILL_NAMES))
            self.assertEqual(result["native_effect"], "unqualified-until-separate-discovery-canary")
            self.assertFalse(result["production_rollout"])
            self.assertEqual(stat.S_IMODE(f.operation.stat().st_mode), 0o700)
            for name in (m.PREIMAGE_NAME, "operation.json", "preview-receipt.json"):
                self.assertEqual(stat.S_IMODE((f.operation / name).stat().st_mode), 0o600)
            self.assertEqual((f.operation / m.PREIMAGE_NAME).read_bytes(), config_before)

            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-applied")
            self.assertEqual(m.apply_operation(f.args)["status"], "already-applied")
            self.assertEqual(stat.S_IMODE(f.config.stat().st_mode), mode_before)
            after = f.config.read_bytes()
            self.assertTrue(after.startswith(config_before))
            parsed = tomllib.loads(after.decode())
            target_rows = {
                row["path"]: row
                for row in parsed["skills"]["config"]
                if row["path"].startswith(str(f.host / ".agents/skills"))
            }
            self.assertEqual(
                set(target_rows),
                {
                    str(f.host / ".agents/skills" / name / "SKILL.md")
                    for name in m.SKILL_NAMES
                },
            )
            self.assertTrue(all(row["enabled"] is False for row in target_rows.values()))
            self.assertEqual(preserved_tree(f), preserved)

            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-preimage")
            self.assertEqual(
                m.apply_operation(f.args, rollback=True)["status"], "already-rolled-back"
            )
            self.assertEqual(f.config.read_bytes(), config_before)
            self.assertEqual(stat.S_IMODE(f.config.stat().st_mode), mode_before)
            self.assertEqual(preserved_tree(f), preserved)

    def test_existing_exact_disabled_override_is_preserved_and_new_preview_noops(self):
        with fixture() as f:
            existing = str(f.host / ".agents/skills/sdk/SKILL.md")
            original = (
                f'# existing user override\n[[skills.config]]\npath = "{existing}"\n'
                "enabled = false\n"
            ).encode()
            f.config.write_bytes(original)
            f.config.chmod(0o600)
            result = preview(f)
            self.assertEqual(result["already_disabled"], ["sdk"])
            self.assertEqual(
                result["selectors_to_add"], ["update-cli-config", "create-subagent"]
            )
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            applied = f.config.read_bytes()
            self.assertTrue(applied.startswith(original))
            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(f.config.read_bytes(), original)

        with fixture() as f:
            rows = "".join(
                f'[[skills.config]]\npath = "{f.host / ".agents/skills" / name / "SKILL.md"}"\n'
                "enabled = false\n"
                for name in m.SKILL_NAMES
            ).encode()
            f.config.write_bytes(rows)
            f.config.chmod(0o600)
            result = preview(f)
            self.assertFalse(result["changed"])
            self.assertEqual(result["selectors_to_add"], [])
            self.assertEqual(m.apply_operation(f.args)["status"], "already-satisfied")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-satisfied")
            self.assertEqual(f.config.read_bytes(), rows)

    def test_raw_config_is_private_and_never_copied_into_json_records(self):
        with fixture() as f:
            preview(f)
            secret = b"fixture-secret-value"
            self.assertIn(secret, (f.operation / m.PREIMAGE_NAME).read_bytes())
            self.assertNotIn(secret, (f.operation / "operation.json").read_bytes())
            self.assertNotIn(secret, (f.operation / "preview-receipt.json").read_bytes())

    def test_changed_config_preimage_and_postimage_refuse_without_clobber(self):
        with fixture() as f:
            preview(f)
            changed = f.config.read_bytes() + b"\n[unrelated]\nchanged = true\n"
            f.config.write_bytes(changed)
            f.config.chmod(0o640)
            with self.assertRaisesRegex(ValueError, "preimage changed"):
                m.apply_operation(f.args)
            self.assertEqual(f.config.read_bytes(), changed)

        with fixture() as f:
            preview(f)
            m.apply_operation(f.args)
            later = f.config.read_bytes() + b"\n[unrelated]\nlater = true\n"
            f.config.write_bytes(later)
            f.config.chmod(0o640)
            with self.assertRaisesRegex(ValueError, "rollback refused"):
                m.apply_operation(f.args, rollback=True)
            self.assertEqual(f.config.read_bytes(), later)

    def test_source_hash_path_kind_and_metadata_drift_refuse(self):
        with fixture() as f:
            source = f.host / ".agents/skills/sdk/SKILL.md"
            source.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "inventory hash changed"):
                m.preview(f.args)
            self.assertFalse(f.operation.exists())

        with fixture() as f:
            source = f.host / ".agents/skills/sdk/SKILL.md"
            source.unlink()
            source.symlink_to(f.host / ".agents/skills/update-cli-config/SKILL.md")
            with self.assertRaises((ValueError, OSError)):
                m.preview(f.args)
            self.assertFalse(f.operation.exists())

        with fixture() as f:
            preview(f)
            source = f.host / ".agents/skills/sdk/SKILL.md"
            source.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "preimages changed"):
                m.apply_operation(f.args)
            self.assertNotIn(m.BEGIN_MARKER.encode(), f.config.read_bytes())

    def test_action_receipt_private_preimage_and_root_tampering_refuse(self):
        cases = ("action", "receipt", "preimage", "root-mode")
        for case in cases:
            with self.subTest(case=case), fixture() as f:
                preview(f)
                if case == "action":
                    path = f.operation / "operation.json"
                    row = json.loads(path.read_text())
                    row["affected_sessions"] = "tampered"
                    path.write_text(json.dumps(row))
                    path.chmod(0o600)
                    pattern = "action changed"
                elif case == "receipt":
                    path = f.operation / "preview-receipt.json"
                    row = json.loads(path.read_text())
                    row["extra"] = True
                    path.write_text(json.dumps(row))
                    path.chmod(0o600)
                    pattern = "receipt changed"
                elif case == "preimage":
                    path = f.operation / m.PREIMAGE_NAME
                    path.write_bytes(path.read_bytes() + b"tampered")
                    path.chmod(0o600)
                    pattern = "preimage changed"
                else:
                    f.operation.chmod(0o755)
                    pattern = "mode 0700"
                with self.assertRaisesRegex(ValueError, pattern):
                    m.load_operation(f.operation, f.host)

    def test_atomic_stage_failure_preserves_live_config_and_clears_private_copy(self):
        with fixture() as f:
            before = f.config.read_bytes()
            preview(f)
            stage = None
            plan, _receipt, _preimage, _postimage = m.load_operation(f.operation, f.host)
            stage = Path(plan["config"]["stage_path"])
            with patch.object(m.os, "replace", side_effect=OSError("injected replace failure")):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    m.apply_operation(f.args)
            self.assertEqual(f.config.read_bytes(), before)
            self.assertFalse(stage.exists())
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")

    def test_bound_interrupted_stages_resume_or_cancel_through_existing_verbs(self):
        with fixture() as f:
            preview(f)
            plan, _receipt, _preimage, postimage = m.load_operation(f.operation, f.host)
            stage = Path(plan["config"]["stage_path"])
            stage.write_bytes(postimage)
            stage.chmod(plan["config"]["after"]["mode"])
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertFalse(stage.exists())

        with fixture() as f:
            preview(f)
            plan, _receipt, _preimage, postimage = m.load_operation(f.operation, f.host)
            stage = Path(plan["config"]["stage_path"])
            stage.write_bytes(postimage)
            stage.chmod(plan["config"]["after"]["mode"])
            self.assertEqual(
                m.apply_operation(f.args, rollback=True)["status"], "already-rolled-back"
            )
            self.assertFalse(stage.exists())

        with fixture() as f:
            preview(f)
            m.apply_operation(f.args)
            plan, _receipt, preimage, _postimage = m.load_operation(f.operation, f.host)
            stage = Path(plan["config"]["stage_path"])
            stage.write_bytes(preimage)
            stage.chmod(plan["config"]["before"]["mode"])
            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")
            self.assertFalse(stage.exists())

        with fixture() as f:
            preview(f)
            m.apply_operation(f.args)
            plan, _receipt, preimage, _postimage = m.load_operation(f.operation, f.host)
            stage = Path(plan["config"]["stage_path"])
            stage.write_bytes(preimage)
            stage.chmod(plan["config"]["before"]["mode"])
            self.assertEqual(m.apply_operation(f.args)["status"], "already-applied")
            self.assertFalse(stage.exists())

    def test_unknown_interrupted_stage_refuses_and_is_retained(self):
        with fixture() as f:
            before = f.config.read_bytes()
            preview(f)
            plan, _receipt, _preimage, _postimage = m.load_operation(f.operation, f.host)
            stage = Path(plan["config"]["stage_path"])
            stage.write_bytes(b"unknown staged bytes")
            stage.chmod(plan["config"]["after"]["mode"])
            with self.assertRaisesRegex(ValueError, "not the bound target image"):
                m.apply_operation(f.args)
            self.assertEqual(f.config.read_bytes(), before)
            self.assertEqual(stage.read_bytes(), b"unknown staged bytes")


class ConservativeConfigHandling(unittest.TestCase):
    def test_conflicting_ambiguous_and_folder_overrides_refuse_without_operation(self):
        cases = {
            "enabled-true": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents/skills/sdk/SKILL.md"}"\n'
                "enabled = true\n"
            ),
            "enabled-implicit": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents/skills/sdk/SKILL.md"}"\n'
            ),
            "extra-fields": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents/skills/sdk/SKILL.md"}"\n'
                'enabled = false\nproject = "fixture"\n'
            ),
            "folder-selector": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents/skills/sdk"}"\n'
                "enabled = false\n"
            ),
            "import-root-selector": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents"}"\n'
                "enabled = true\n"
            ),
            "import-skills-root-selector": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents/skills"}"\n'
                "enabled = true\n"
            ),
            "duplicate": lambda host: (
                f'[[skills.config]]\npath = "{host / ".agents/skills/sdk/SKILL.md"}"\n'
                "enabled = false\n"
                f'[[skills.config]]\npath = "{host / ".agents/skills/sdk/SKILL.md"}"\n'
                "enabled = false\n"
            ),
        }
        for case, config_for in cases.items():
            with self.subTest(case=case), fixture() as f:
                content = config_for(f.host).encode()
                f.config.write_bytes(content)
                f.config.chmod(0o600)
                with self.assertRaises(ValueError):
                    m.preview(f.args)
                self.assertEqual(f.config.read_bytes(), content)
                self.assertFalse(f.operation.exists())

    def test_case_and_same_file_aliases_refuse_without_operation(self):
        with fixture() as f:
            source = f.host / ".agents/skills/sdk/SKILL.md"
            alias = f.host / "sdk-alias.md"
            alias.symlink_to(source)
            content = (
                f'[[skills.config]]\npath = "{alias}"\nenabled = false\n'
            ).encode()
            f.config.write_bytes(content)
            f.config.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "same-file alias"):
                m.preview(f.args)
            self.assertEqual(f.config.read_bytes(), content)
            self.assertFalse(f.operation.exists())

        with fixture() as f:
            canonical = f.host / ".agents/skills/sdk/SKILL.md"
            case_alias = f.host / ".agents/skills/SDK/SKILL.md"
            content = (
                f'[[skills.config]]\npath = "{case_alias}"\nenabled = false\n'
            ).encode()
            f.config.write_bytes(content)
            f.config.chmod(0o600)
            real_samefile = m.same_existing_path

            def case_insensitive_samefile(left: Path, right: Path) -> bool:
                if str(left).casefold() == str(right).casefold():
                    return True
                return real_samefile(left, right)

            with patch.object(m, "same_existing_path", side_effect=case_insensitive_samefile):
                with self.assertRaisesRegex(ValueError, "same-file alias"):
                    m.preview(f.args)
            self.assertEqual(f.config.read_bytes(), content)
            self.assertFalse(f.operation.exists())

    def test_malformed_and_unsupported_toml_shapes_refuse(self):
        cases = (
            b"[[skills.config]\n",
            b'skills = "not-a-table"\n',
            b'[skills]\nconfig = "not-an-array"\n',
            b"[[skills.config]]\npath = 42\n",
            b'[[skills.config]]\npath = "/other"\nenabled = "false"\n',
        )
        for content in cases:
            with self.subTest(content=content), fixture(content) as f:
                with self.assertRaises(ValueError):
                    m.preview(f.args)
                self.assertFalse(f.operation.exists())

    def test_partial_or_inconsistent_managed_marker_refuses(self):
        cases = (
            (m.BEGIN_MARKER + "\n").encode(),
            (m.END_MARKER + "\n").encode(),
            (m.BEGIN_MARKER + "\n" + m.END_MARKER + "\n").encode(),
        )
        for content in cases:
            with self.subTest(content=content), fixture(content) as f:
                with self.assertRaisesRegex(ValueError, "marker"):
                    m.preview(f.args)
                self.assertFalse(f.operation.exists())

    def test_same_name_other_roots_and_unknown_fields_are_byte_preserved(self):
        with fixture() as f:
            content = (
                f'[[skills.config]]\npath = "{f.host / ".codex/skills/sdk/SKILL.md"}"\n'
                'enabled = true\nunknown = "preserved"\n\n'
                '[[skills.config]]\npath = "/plugin/cache/sdk/SKILL.md"\n'
                "enabled = false\n"
            ).encode()
            f.config.write_bytes(content)
            f.config.chmod(0o600)
            preview(f)
            m.apply_operation(f.args)
            self.assertTrue(f.config.read_bytes().startswith(content))
            m.apply_operation(f.args, rollback=True)
            self.assertEqual(f.config.read_bytes(), content)

    def test_crlf_and_missing_final_newline_are_preserved_as_prefix(self):
        with fixture(b'[features]\r\nexample = true') as f:
            before = f.config.read_bytes()
            preview(f)
            m.apply_operation(f.args)
            after = f.config.read_bytes()
            self.assertTrue(after.startswith(before + b"\r\n"))
            self.assertNotIn(b"\n", after.replace(b"\r\n", b""))
            m.apply_operation(f.args, rollback=True)
            self.assertEqual(f.config.read_bytes(), before)


class ClosedInterface(unittest.TestCase):
    def test_relative_paths_and_operation_overlap_are_refused(self):
        with fixture() as f:
            f.args.host_root = Path("relative-host")
            with self.assertRaisesRegex(ValueError, "explicit absolute"):
                m.preview(f.args)

        with fixture() as f:
            f.args.operation_dir = f.host / "private-operation"
            with self.assertRaisesRegex(ValueError, "outside source and host roots"):
                m.preview(f.args)

    def test_missing_config_refuses_without_operation_or_source_changes(self):
        with fixture() as f:
            preserved = preserved_tree(f)
            f.config.unlink()
            with self.assertRaises(FileNotFoundError):
                m.preview(f.args)
            self.assertFalse(f.operation.exists())
            self.assertEqual(preserved_tree(f), preserved)

    def test_git_metadata_bare_roots_and_unknown_probe_fail_closed(self):
        with fixture() as f:
            metadata = f.root / "repo/.git"
            metadata.mkdir(parents=True)
            f.args.operation_dir = metadata / "private-operation"
            with self.assertRaisesRegex(ValueError, "outside Git metadata"):
                m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

        with fixture() as f:
            corrupt = f.root / "corrupt-repo"
            corrupt.mkdir()
            (corrupt / ".git").symlink_to(corrupt / "missing-git-dir")
            f.args.operation_dir = corrupt / "private-operation"
            with self.assertRaisesRegex(ValueError, "outside Git metadata"):
                m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

        with fixture() as f:
            bare = f.root / "bare.git"
            (bare / "objects").mkdir(parents=True)
            (bare / "refs").mkdir()
            (bare / "HEAD").write_text("ref: refs/heads/main\n")
            f.args.operation_dir = bare / "private-operation"
            with self.assertRaisesRegex(ValueError, "outside Git metadata"):
                m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

        with fixture() as f:
            failure = subprocess.CompletedProcess(
                args=["git"],
                returncode=128,
                stdout="",
                stderr="fatal: fixture-private-diagnostic\n",
            )
            with patch.object(m.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(ValueError, "could not be proven outside Git") as caught:
                    m.preview(f.args)
            self.assertNotIn("fixture-private-diagnostic", str(caught.exception))
            self.assertFalse(f.operation.exists())

    def test_cli_requires_explicit_host_root_operation_and_preview_build(self):
        parser = m.build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["preview", "--operation-dir", "/private/tmp/op"])
        with fixture() as f:
            f.args.host_build = None
            with self.assertRaisesRegex(ValueError, "host build"):
                m.preview(f.args)

    def test_bootstrap_route_exits_before_clone_or_broad_reconcile(self):
        with tempfile.TemporaryDirectory(prefix="int008-import-bootstrap-") as raw:
            root = Path(raw).resolve()
            dev = root / "dev"
            script = dev / "capabilities/bootstrap.sh"
            script.parent.mkdir(parents=True)
            shutil.copyfile(m.ROOT / "capabilities/bootstrap.sh", script)
            isolation = dev / "_ops/interoperability/imported_skill_isolation.py"
            isolation.parent.mkdir(parents=True)
            isolation.write_text(
                "import json,sys\nprint(json.dumps({'route': sys.argv[1], 'args': sys.argv[2:]}))\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            git_marker = root / "git-invoked"
            fake_git = fake_bin / "git"
            fake_git.write_text(f'#!/bin/sh\ntouch "{git_marker}"\nexit 99\n')
            fake_git.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(root / "home"),
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
            }
            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--codex-imported-skill-isolation",
                    "verify",
                    "--host-root",
                    str(root / "host"),
                    "--operation-dir",
                    str(root / "operation"),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["route"], "verify")
            self.assertFalse(git_marker.exists())
            self.assertFalse((dev / "capabilities/skills").exists())


if __name__ == "__main__":
    unittest.main()
