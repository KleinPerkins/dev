"""Isokit canary ownership, no-clobber publication, recovery and refusal tests."""
from argparse import Namespace
from contextlib import contextmanager, ExitStack
import copy
import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import isokit_migration as m


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix="isokit-owner-") as raw:
        root = Path(raw).resolve()
        home = root / "home"
        for name in (".codex/skills", ".agents/skills", ".cursor/skills", ".claude/skills"):
            (home / name).mkdir(parents=True)
        desired = home / "dev/capabilities/skills" / m.PREFIX
        desired.mkdir(parents=True)
        (desired / "SKILL.md").write_text("---\nname: isokit\ndescription: synthetic fixture\n---\n")
        for name in ("prompt-architect", "verification-before-completion"):
            source = home / "dev/capabilities/skills/global/skills" / name
            source.mkdir(parents=True)
            (home / ".codex/skills" / name).symlink_to(source)
        config = home / ".codex/config.toml"
        config.write_text("[skills]\n")
        config.chmod(0o600)
        args = Namespace(home=home, operation_dir=root / "operation",
                         portability_manifest=root / "manifest.json", approve=None)
        proof = {"desired": str(desired), "manifest": {"manifest_path": str(args.portability_manifest)},
                 "payload_sha256": m.PAYLOAD}
        with ExitStack() as stack:
            # Linux source-check fixtures cannot chmod symlinks. The production
            # host gate remains macOS-only with its fixed 0700 link mode.
            stack.enter_context(patch.object(m, "LINK_MODE", 0o700 if hasattr(os, "lchmod") else 0o777))
            stack.enter_context(patch.object(m, "source_proof", side_effect=lambda *_: copy.deepcopy(proof)))
            stack.enter_context(patch.object(m, "host_observation", return_value={"build": m.HOST_BUILD}))
            stack.enter_context(patch.dict(os.environ, {"CODEX_HOME": str(home / ".codex")}))
            yield Namespace(root=root, home=home, desired=desired, args=args, proof=proof,
                            target=home / ".codex/skills/isokit", config=config)


def prepare(f):
    result = m.preview(f.args)
    f.args.approve = result["action_sha256"]
    return m.load(f.args.operation_dir)


class Canary(unittest.TestCase):
    def test_complete_canary_is_idempotent_and_exactly_rolled_back(self):
        with fixture() as f:
            kept = m.preserved(f.home)
            config = f.config.read_bytes()
            plan = prepare(f)
            self.assertEqual(m.verify(f.args)["status"], "verified-preimage")
            self.assertEqual(m.apply(f.args)["status"], "applied-canary")
            owned = m.ownership(plan)
            self.assertEqual(m.observation(f.target), owned)
            self.assertEqual(m.apply(f.args)["status"], "already-applied")
            self.assertFalse(m.verify(f.args)["native_qualified"])
            self.assertFalse(m.verify(f.args)["retention_authorized"])
            self.assertEqual(m.apply(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(m.verify(f.args)["status"], "verified-preimage")
            self.assertEqual(m.apply(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(m.preserved(f.home), kept)
            self.assertEqual(f.config.read_bytes(), config)
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                m.apply(f.args)

    def test_preview_refuses_all_existing_target_types_without_replacement(self):
        for kind in ("file", "directory", "same-link", "dangling-link"):
            with self.subTest(kind=kind), fixture() as f:
                if kind == "file": f.target.write_text("owner bytes")
                elif kind == "directory": f.target.mkdir()
                else: f.target.symlink_to(f.desired if kind == "same-link" else f.root / "missing")
                before = m.observation(f.target)
                with self.assertRaisesRegex(ValueError, "absent target"):
                    m.preview(f.args)
                self.assertEqual(m.observation(f.target), before)
                self.assertFalse(f.args.operation_dir.exists())

    def test_explicit_opt_out_at_alias_or_source_refuses_before_publication(self):
        for path_kind in ("codex", "agents", "source"):
            with self.subTest(path_kind=path_kind), fixture() as f:
                location = f.desired if path_kind == "source" else f.home / ("." + path_kind) / "skills/isokit/SKILL.md"
                f.config.write_text(f'[[skills.config]]\npath = "{location}"\nenabled = false\n')
                before = f.config.read_bytes()
                with self.assertRaisesRegex(ValueError, "explicitly disabled"):
                    m.preview(f.args)
                self.assertEqual(f.config.read_bytes(), before)
                self.assertFalse(f.target.exists())

    def test_foreign_native_alias_is_not_removed_or_adopted(self):
        with fixture() as f:
            alias = f.home / ".agents/skills/isokit"
            alias.symlink_to(f.desired)
            before = m.observation(alias)
            with self.assertRaisesRegex(ValueError, "alias"):
                m.preview(f.args)
            self.assertEqual(m.observation(alias), before)

    def test_exact_approval_required(self):
        with fixture() as f:
            prepare(f)
            f.args.approve = "0" * 64
            with self.assertRaisesRegex(ValueError, "exact action"):
                m.apply(f.args)
            self.assertFalse(f.target.exists())

    def test_source_host_config_and_preserved_path_drift_each_refuse(self):
        for change in ("source", "host", "config", "preserved"):
            with self.subTest(change=change), fixture() as f:
                prepare(f)
                with ExitStack() as stack:
                    if change == "source": f.proof["payload_sha256"] = "changed"
                    elif change == "host": stack.enter_context(patch.object(m, "host_observation", return_value={"build": "other"}))
                    elif change == "config": f.config.write_text("# owner edit\n")
                    else: (f.home / ".cursor/skills/isokit").mkdir()
                    with self.assertRaises(ValueError): m.apply(f.args)
                    self.assertFalse(f.target.exists())

    def test_changed_same_target_inode_is_not_owned(self):
        with fixture() as f:
            prepare(f)
            m.apply(f.args)
            # Keep the original inode alive, so replacing it cannot reuse that inode.
            f.target.rename(f.root / "retained-original-link")
            f.target.symlink_to(f.desired)
            m.shared.set_symlink_mode(f.target, m.LINK_MODE)
            replacement = m.observation(f.target)
            with self.assertRaisesRegex(ValueError, "exact rollback refused"):
                m.apply(f.args, rollback=True)
            self.assertEqual(m.observation(f.target), replacement)
            with self.assertRaisesRegex(ValueError, "not the exact"):
                m.verify(f.args)

    def test_no_clobber_race_preserves_foreign_winner_and_owned_staging(self):
        with fixture() as f:
            plan = prepare(f)
            original = os.link
            def race(src, dst, **kw):
                Path(dst).write_text("concurrent owner")
                return original(src, dst, **kw)
            with patch.object(m.os, "link", side_effect=race):
                with self.assertRaises(FileExistsError): m.apply(f.args)
            self.assertEqual(f.target.read_text(), "concurrent owner")
            self.assertEqual(m.observation(Path(plan["staging"])), m.ownership(plan))
            with self.assertRaisesRegex(ValueError, "exact rollback refused"):
                m.apply(f.args, rollback=True)
            self.assertEqual(f.target.read_text(), "concurrent owner")

    def test_interrupted_owned_staging_resumes_or_rolls_back(self):
        for recovery in ("apply", "rollback"):
            with self.subTest(recovery=recovery), fixture() as f:
                plan = prepare(f)
                with patch.object(m.os, "link", side_effect=OSError("simulated interruption")):
                    with self.assertRaises(OSError): m.apply(f.args)
                self.assertEqual(m.observation(Path(plan["staging"])), m.ownership(plan))
                if recovery == "apply":
                    self.assertEqual(m.apply(f.args)["status"], "applied-canary")
                else: m.apply(f.args, rollback=True)
                self.assertFalse(Path(plan["staging"]).is_symlink())

    def test_publication_with_lost_response_resumes_without_second_link(self):
        with fixture() as f:
            plan=prepare(f);original=os.link
            def lost_response(src,dst,**kw):
                original(src,dst,**kw)
                raise OSError("publication response lost")
            with patch.object(m.os,"link",side_effect=lost_response):
                with self.assertRaises(OSError):m.apply(f.args)
            self.assertEqual(m.observation(f.target),m.ownership(plan))
            self.assertEqual(m.apply(f.args)["status"],"already-applied")
            self.assertFalse(Path(plan["staging"]).is_symlink())

    def test_cli_lock_rejects_cooperating_overlap_and_unshared_record(self):
        with fixture() as f:
            prepare(f)
            with m.operation_lock(f.args.operation_dir):
                with self.assertRaises(BlockingIOError):
                    with m.operation_lock(f.args.operation_dir):pass
            path=f.args.operation_dir/"operation.lock";os.link(path,f.root/"linked-lock")
            with self.assertRaisesRegex(ValueError,"lock changed"):
                with m.operation_lock(f.args.operation_dir):pass

    def test_unowned_staging_is_preserved(self):
        with fixture() as f:
            plan = prepare(f)
            stage = Path(plan["staging"])
            stage.symlink_to(f.desired)
            before = m.observation(stage)
            with self.assertRaisesRegex(ValueError, "unowned staging"):
                m.apply(f.args)
            with self.assertRaisesRegex(ValueError, "exact rollback refused"):
                m.apply(f.args, rollback=True)
            self.assertEqual(m.observation(stage), before)

    def test_rollback_survives_source_and_policy_drift_but_reports_remaining_drift(self):
        with fixture() as f:
            prepare(f)
            m.apply(f.args)
            f.proof["payload_sha256"] = "owner change"
            f.config.write_text("# preserve new config\n")
            self.assertEqual(m.apply(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(f.config.read_text(), "# preserve new config\n")
            with self.assertRaisesRegex(ValueError, "config drift"):
                m.verify(f.args)

    def test_private_record_mode_link_and_action_tampering_refuse(self):
        for change in ("mode", "symlink", "hardlink", "action"):
            with self.subTest(change=change), fixture() as f:
                prepare(f)
                path = f.args.operation_dir / "operation.json"
                if change == "mode": path.chmod(0o644)
                elif change == "symlink": path.rename(f.root / "record");path.symlink_to(f.root / "record")
                elif change == "hardlink": os.link(path, f.root / "record")
                else:
                    data=json.loads(path.read_text());data["target"]=str(f.root / "foreign");path.write_text(json.dumps(data))
                with self.assertRaises((ValueError, OSError)): m.apply(f.args)
                self.assertFalse(f.target.exists())

    def test_recomputed_record_cannot_expand_managed_path(self):
        with fixture() as f:
            prepare(f)
            path=f.args.operation_dir / "operation.json"
            row=json.loads(path.read_text());row.pop("action_sha256");row["target"]=str(f.root / "foreign")
            row["action_sha256"]=m.sha(m.canonical(row));path.write_text(json.dumps(row))
            f.args.approve=row["action_sha256"]
            with self.assertRaisesRegex(ValueError, "fixed identity"):
                m.apply(f.args)

    def test_managed_parent_replacement_refuses_even_exact_path(self):
        with fixture() as f:
            prepare(f)
            parent=f.target.parent;parent.rename(f.home / ".codex/old-skills");parent.mkdir()
            with self.assertRaisesRegex(ValueError, "parent identity"):
                m.apply(f.args)

    def test_record_root_relocation_refuses(self):
        with fixture() as f:
            prepare(f)
            moved=f.root / "moved-operation";f.args.operation_dir.rename(moved);f.args.operation_dir=moved
            with self.assertRaisesRegex(ValueError, "fixed identity"):
                m.apply(f.args)

    def test_symlinked_parent_and_non_default_codex_home_refuse(self):
        with fixture() as f:
            with patch.dict(os.environ, {"CODEX_HOME":str(f.root / "other")}):
                with self.assertRaisesRegex(ValueError, "non-default"):
                    m.preview(f.args)
            parent=f.target.parent;parent.rename(f.home / "real-skills");parent.symlink_to(f.home / "real-skills")
            with self.assertRaisesRegex(ValueError, "symlink"):
                m.preview(f.args)

    def test_host_requires_exact_codex_identity_build_and_architecture(self):
        for changed in ("identity", "build", "architecture", "platform"):
            data={"CFBundleIdentifier":"com.openai.codex","CFBundleVersion":m.HOST_BUILD}
            if changed == "identity": data["CFBundleIdentifier"]="com.openai.chatgpt"
            if changed == "build": data["CFBundleVersion"]="other"
            with self.subTest(changed=changed), patch.object(m.sys,"platform","linux" if changed=="platform" else "darwin"), patch.object(m.platform,"machine",return_value="x86_64" if changed=="architecture" else "arm64"), patch.object(m,"regular",return_value=plistlib.dumps(data)):
                with self.assertRaises(ValueError): m.host_observation()


class ExactSource(unittest.TestCase):
    def test_real_git_payload_runtime_and_browser_bindings_refuse_drift(self):
        with tempfile.TemporaryDirectory(prefix="isokit-source-") as raw:
            home=Path(raw).resolve()/"home";root=home/"dev/capabilities/skills";skill=root/m.PREFIX;skill.mkdir(parents=True)
            for i in range(123): (skill/("SKILL.md" if i==0 else f"source-{i:03}.txt")).write_text(f"fixture {i}\n")
            def git(*args):
                return subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,check=True).stdout.strip()
            git("init","-q");git("add",".");git("-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","fixture")
            pin=git("rev-parse","HEAD");rows=[]
            for line in m.shared.git_bytes(root,"ls-tree","-rz",pin,"--",m.PREFIX).split(b"\0"):
                if not line:continue
                meta,path=line.split(b"\t");mode,kind,blob=meta.decode().split();path=path.decode()
                rows.append({"path":path,"mode":mode,"blob":blob,"sha256":m.sha((root/path).read_bytes())})
            runtime=skill/"node_modules/playwright-core";runtime.mkdir(parents=True)
            for i in range(115):(runtime/f"runtime-{i:03}.js").write_text(f"fixture runtime {i}\n")
            runtime_digest,_=m.tree_digest(runtime)
            browsers=home/".local/share/personal-portability/playwright-browsers";browsers.mkdir(parents=True)
            browser=browsers/"fixture-browser";browser.write_text("fixture binary");browser_hash=m.sha(browser.read_bytes())
            with patch.object(m,"PIN",pin),patch.object(m,"PAYLOAD",m.sha(m.canonical(rows))),patch.object(m,"RUNTIME",runtime_digest),patch.object(m,"BROWSER_FILES",{"fixture-browser":browser_hash}),patch.object(m.shared,"portability_manifest_proof",return_value={"manifest_path":str(home/"manifest")}),patch.object(m.shared,"pinned_primary_observation",return_value={"head":pin}):
                self.assertEqual(m.source_proof(home,home/"manifest")["isokit_file_count"],123)
                source=skill/"SKILL.md";before=source.read_bytes();source.write_text("changed")
                with self.assertRaisesRegex(ValueError,"tracked source changed"):m.source_proof(home,home/"manifest")
                source.write_bytes(before)
                extra=skill/"unreviewed.txt";extra.write_text("extra")
                with self.assertRaisesRegex(ValueError,"unreviewed file"):m.source_proof(home,home/"manifest")
                extra.unlink();extra=skill/"unreviewed-dir";extra.mkdir()
                with self.assertRaisesRegex(ValueError,"unreviewed file or directory"):m.source_proof(home,home/"manifest")
                extra.rmdir();runtime_file=runtime/"runtime-000.js";before=runtime_file.read_bytes();runtime_file.write_text("changed")
                with self.assertRaisesRegex(ValueError,"runtime changed"):m.source_proof(home,home/"manifest")
                runtime_file.write_bytes(before);browser.write_text("changed")
                with self.assertRaisesRegex(ValueError,"browser bundle changed"):m.source_proof(home,home/"manifest")


if __name__ == "__main__":
    unittest.main()
