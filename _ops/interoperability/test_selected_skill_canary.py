"""Selective two-link canary: scope, partial recovery and foreign-edit refusal."""
from argparse import Namespace
from contextlib import contextmanager, ExitStack
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).parent))
import selected_skill_canary as m


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix="selected-skills-owner-") as raw:
        root = Path(raw).resolve()
        home = root / "home"
        for shelf in (".codex/skills", ".agents/skills", ".cursor/skills", ".claude/skills"):
            (home / shelf).mkdir(parents=True)
        desired = {}
        for name in m.SKILLS:
            path = home / "dev/capabilities/skills/global/skills" / name
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text("synthetic fixture\n")
            desired[name] = str(path)
        for name in ("prompt-architect", "verification-before-completion", "operator-voice", "isokit"):
            path = home / "kept" / name
            path.mkdir(parents=True)
            (home / ".codex/skills" / name).symlink_to(path)
        config = home / ".codex/config.toml"
        config.write_text("[skills]\n")
        config.chmod(0o600)
        args = Namespace(home=home, operation_dir=root / "operation", portability_manifest=root / "manifest.json", approve=None)
        proof = {"desired": desired, "manifest": {"manifest_path": str(args.portability_manifest)}, "payload_sha256": m.PAYLOAD}
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, "home", return_value=home))
            stack.enter_context(patch.object(m, "LINK_MODE", 0o700 if hasattr(os, "lchmod") else 0o777))
            stack.enter_context(patch.object(m, "source_proof", side_effect=lambda *_: copy.deepcopy(proof)))
            stack.enter_context(patch.object(m, "host_observation", return_value={"build": "23880", "cli_sha256": m.CLI_SHA256}))
            stack.enter_context(patch.dict(os.environ, {"CODEX_HOME": str(home / ".codex")}))
            yield Namespace(root=root, home=home, args=args, proof=proof, config=config,
                            targets=[home / ".codex/skills" / name for name in m.SKILLS], desired=desired)


def prepare(f):
    result = m.preview(f.args)
    f.args.approve = result["action_sha256"]
    return m.load(f.args.operation_dir)


class Canary(unittest.TestCase):
    def test_two_link_lifecycle_never_claims_native_or_retained_authority(self):
        with fixture() as f:
            kept, config = m.preserved(f.home), f.config.read_bytes()
            plan = prepare(f)
            self.assertEqual(m.verify(f.args)["status"], "verified-preimage")
            self.assertEqual(m.apply(f.args)["status"], "applied-canary")
            self.assertEqual(m.apply(f.args)["status"], "already-applied")
            result = m.verify(f.args)
            self.assertEqual(result["status"], "verified-canary")
            self.assertFalse(result["native_qualified"])
            self.assertFalse(result["retention_authorized"])
            for row in plan["targets"]:
                self.assertEqual(m.observation(Path(row["target"])), m.ownership(plan, row))
            self.assertEqual(m.apply(f.args, undo=True)["status"], "rolled-back")
            self.assertEqual(m.apply(f.args, undo=True)["status"], "rolled-back")
            self.assertEqual(m.verify(f.args)["status"], "verified-preimage")
            self.assertEqual(m.preserved(f.home), kept)
            self.assertEqual(f.config.read_bytes(), config)
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                m.apply(f.args)

    def test_existing_targets_all_types_are_not_adopted(self):
        for index in (0, 1):
            for kind in ("file", "directory", "same-link", "dangling-link"):
                with self.subTest(index=index, kind=kind), fixture() as f:
                    target = f.targets[index]
                    if kind == "file": target.write_text("owner bytes")
                    elif kind == "directory": target.mkdir()
                    else: target.symlink_to(f.desired[m.SKILLS[index]] if kind == "same-link" else f.root / "missing")
                    before = m.observation(target)
                    with self.assertRaisesRegex(ValueError, "absent targets"):
                        m.preview(f.args)
                    self.assertEqual(m.observation(target), before)
                    self.assertFalse(f.args.operation_dir.exists())

    def test_each_native_opt_out_alias_source_and_tilde_is_preserved(self):
        for name in m.SKILLS:
            for kind in ("codex", "agents", "source", "tilde"):
                with self.subTest(name=name, kind=kind), fixture() as f:
                    if kind == "source": location = f.desired[name]
                    elif kind == "tilde": location = f"~/.codex/skills/{name}/SKILL.md"
                    else: location = str(f.home / ("." + kind) / "skills" / name / "SKILL.md")
                    f.config.write_text(f'[[skills.config]]\npath = "{location}"\nenabled = false\n')
                    before = f.config.read_bytes()
                    with self.assertRaisesRegex(ValueError, "explicitly disabled"):
                        m.preview(f.args)
                    self.assertEqual(f.config.read_bytes(), before)
                    self.assertFalse(f.args.operation_dir.exists())

    def test_native_alias_is_preserved_and_refuses(self):
        with fixture() as f:
            path = f.home / ".agents/skills/capability"
            path.symlink_to(f.desired["capability"])
            before = m.observation(path)
            with self.assertRaisesRegex(ValueError, "native alias"):
                m.preview(f.args)
            self.assertEqual(m.observation(path), before)

    def test_wrong_approval_and_non_default_home_or_codex_home_refuse(self):
        with fixture() as f:
            f.args.home = f.root
            with self.assertRaisesRegex(ValueError, "operator home"):
                m.preview(f.args)
            f.args.home = f.home
            with patch.dict(os.environ, {"CODEX_HOME": str(f.root / "other")}):
                with self.assertRaisesRegex(ValueError, "CODEX_HOME"):
                    m.preview(f.args)
            prepare(f)
            f.args.approve = "0" * 64
            with self.assertRaisesRegex(ValueError, "exact action"):
                m.apply(f.args)
            self.assertTrue(all(m.observation(p)["kind"] == "absent" for p in f.targets))

    def test_source_host_config_and_preserved_path_drift_refuse_before_publication(self):
        for kind in ("source", "host", "config", "retained-link", "other-client"):
            with self.subTest(kind=kind), fixture() as f:
                prepare(f)
                with ExitStack() as stack:
                    if kind == "source": f.proof["payload_sha256"] = "changed"
                    elif kind == "host": stack.enter_context(patch.object(m, "host_observation", return_value={"build": "other"}))
                    elif kind == "config": f.config.write_text("# owner edit\n")
                    elif kind == "retained-link": (f.home / ".codex/skills/isokit").unlink()
                    else: (f.home / ".cursor/skills/frontend-design").mkdir()
                    with self.assertRaises(ValueError): m.apply(f.args)
                    self.assertTrue(all(m.observation(p)["kind"] == "absent" for p in f.targets))

    def test_second_publication_interruption_resumes_without_replacing_first_inode(self):
        with fixture() as f:
            plan = prepare(f)
            real, calls = os.link, []
            def interrupt(src, dst, **kw):
                calls.append(str(dst))
                if len(calls) == 2: raise OSError("interrupted second publication")
                return real(src, dst, **kw)
            with patch.object(m.os, "link", side_effect=interrupt):
                with self.assertRaises(OSError): m.apply(f.args)
            first = m.observation(f.targets[0])
            self.assertEqual(first, m.ownership(plan, plan["targets"][0]))
            with self.assertRaisesRegex(ValueError, "staging"):
                m.verify(f.args)
            self.assertEqual(m.apply(f.args)["status"], "applied-canary")
            self.assertEqual(m.observation(f.targets[0]), first)
            m.apply(f.args, undo=True)
            self.assertEqual(m.verify(f.args)["status"], "verified-preimage")

    def test_second_no_clobber_race_preserves_winner_and_cleans_other_owned_links(self):
        with fixture() as f:
            plan = prepare(f)
            real = os.link
            def race(src, dst, **kw):
                if Path(dst) == f.targets[1]: Path(dst).write_text("foreign winner")
                return real(src, dst, **kw)
            with patch.object(m.os, "link", side_effect=race):
                with self.assertRaises(FileExistsError): m.apply(f.args)
            with self.assertRaisesRegex(ValueError, "foreign edits preserved"):
                m.apply(f.args, undo=True)
            self.assertEqual(f.targets[1].read_text(), "foreign winner")
            self.assertEqual(m.observation(f.targets[0])["kind"], "absent")
            self.assertTrue(all(m.observation(Path(row["staging"]))["kind"] == "absent" for row in plan["targets"]))
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                m.apply(f.args)

    def test_lost_publication_response_resumes_without_second_inode(self):
        with fixture() as f:
            plan = prepare(f)
            real = os.link
            def lost(src, dst, **kw):
                real(src, dst, **kw)
                if Path(dst) == f.targets[1]: raise OSError("response lost")
            with patch.object(m.os, "link", side_effect=lost):
                with self.assertRaises(OSError): m.apply(f.args)
            before = [m.observation(p) for p in f.targets]
            self.assertEqual(m.apply(f.args)["status"], "already-applied")
            self.assertEqual([m.observation(p) for p in f.targets], before)
            m.apply(f.args, undo=True)

    def test_same_source_foreign_inode_is_not_adopted_during_rollback(self):
        with fixture() as f:
            prepare(f); m.apply(f.args)
            f.targets[0].rename(f.root / "keep-original-inode")
            f.targets[0].symlink_to(f.desired[m.SKILLS[0]])
            m.atom.shared.set_symlink_mode(f.targets[0], m.LINK_MODE)
            foreign = m.observation(f.targets[0])
            with self.assertRaisesRegex(ValueError, "foreign edits preserved"):
                m.apply(f.args, undo=True)
            self.assertEqual(m.observation(f.targets[0]), foreign)
            self.assertEqual(m.observation(f.targets[1])["kind"], "absent")

    def test_unowned_staging_refuses_before_either_target_is_published(self):
        with fixture() as f:
            plan = prepare(f)
            stage = Path(plan["targets"][1]["staging"])
            stage.symlink_to(f.desired[m.SKILLS[1]])
            foreign = m.observation(stage)
            with self.assertRaisesRegex(ValueError, "unowned target or staging"):
                m.apply(f.args)
            self.assertTrue(all(m.observation(p)["kind"] == "absent" for p in f.targets))
            with self.assertRaises(ValueError): m.apply(f.args, undo=True)
            self.assertEqual(m.observation(stage), foreign)

    def test_missing_owned_link_is_never_recreated(self):
        with fixture() as f:
            prepare(f); m.apply(f.args); f.targets[0].unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                m.apply(f.args)
            self.assertEqual(m.observation(f.targets[0])["kind"], "absent")
            m.apply(f.args, undo=True)

    def test_rollback_survives_source_and_config_drift_without_claiming_preservation(self):
        with fixture() as f:
            prepare(f); m.apply(f.args)
            f.proof["payload_sha256"] = "foreign change"
            f.config.write_text("# preserve owner config\n")
            self.assertEqual(m.apply(f.args, undo=True)["status"], "rolled-back")
            self.assertEqual(f.config.read_text(), "# preserve owner config\n")
            with self.assertRaisesRegex(ValueError, "source, host, policy"):
                m.verify(f.args)

    def test_managed_parent_replacement_refuses_publication_and_rollback(self):
        with fixture() as f:
            prepare(f)
            parent = f.home / ".codex/skills"
            parent.rename(f.home / ".codex/old-skills"); parent.mkdir()
            with self.assertRaisesRegex(ValueError, "parent identity"): m.apply(f.args)
            with self.assertRaisesRegex(ValueError, "parent identity"): m.apply(f.args, undo=True)

    def test_private_records_and_lock_are_regular_unshared_and_exact(self):
        for change in ("mode", "symlink", "hardlink", "digest", "duplicate"):
            with self.subTest(change=change), fixture() as f:
                prepare(f); record=f.args.operation_dir / "operation.json"
                if change == "mode": record.chmod(0o644)
                elif change == "symlink": record.rename(f.root / "record");record.symlink_to(f.root / "record")
                elif change == "hardlink": os.link(record, f.root / "record")
                elif change == "digest": record.write_text(record.read_text().replace('"mode":"canary"', '"mode":"retained"'))
                else: record.write_text('{"schema":"one",' + record.read_text()[1:])
                with self.assertRaises((ValueError, OSError)): m.apply(f.args)
        with fixture() as f:
            prepare(f)
            with m.operation_lock(f.args.operation_dir):
                with self.assertRaises(BlockingIOError):
                    with m.operation_lock(f.args.operation_dir): pass
            os.link(f.args.operation_dir / "operation.lock", f.root / "hardlinked-lock")
            with self.assertRaises(ValueError):
                with m.operation_lock(f.args.operation_dir): pass

    def test_recomputed_digest_cannot_expand_paths_worker_or_retained_scope(self):
        for change in ("target", "staging", "desired", "count", "count-bool", "model", "retained", "workload", "unknown"):
            with self.subTest(change=change), fixture() as f:
                prepare(f); path=f.args.operation_dir / "operation.json";plan=json.loads(path.read_text());plan.pop("action_sha256")
                if change in {"target", "staging", "desired"}: plan["targets"][0][change]=str(f.root / "foreign")
                elif change == "count": plan["native_worker"]["count"]=2
                elif change == "count-bool": plan["native_worker"]["count"]=True
                elif change == "model": plan["native_worker"]["requested_model"]="other"
                elif change == "retained": plan["retention_authorized"]=True
                elif change == "workload": plan["workload"]["outputs"].append("foreign")
                else: plan["extra"]=True
                plan["action_sha256"]=m.sha(m.canonical(plan));path.write_text(json.dumps(plan));f.args.approve=plan["action_sha256"]
                with self.assertRaisesRegex(ValueError, "fixed identity"):
                    m.apply(f.args)

    def test_source_implementation_drift_refuses(self):
        with fixture() as f:
            prepare(f)
            with patch.object(m, "implementation", return_value="changed"):
                with self.assertRaisesRegex(ValueError, "implementation"): m.apply(f.args)

    def test_owner_receipt_failure_removes_only_newly_created_exact_staging(self):
        with fixture() as f:
            plan=prepare(f);real=m.atom.write_once
            def failure(path, value):
                if path.name.startswith("link-owner-"): raise OSError("receipt write failed")
                return real(path,value)
            with patch.object(m.atom,"write_once",side_effect=failure):
                with self.assertRaises(OSError):m.apply(f.args)
            self.assertTrue(all(m.observation(Path(row[key]))["kind"]=="absent" for row in plan["targets"] for key in ("target","staging")))

    def test_operation_relocation_source_root_and_git_storage_refuse(self):
        with fixture() as f:
            prepare(f); moved=f.root/"moved";f.args.operation_dir.rename(moved);f.args.operation_dir=moved
            with self.assertRaisesRegex(ValueError,"fixed identity"):m.apply(f.args)
        with fixture() as f:
            f.args.operation_dir=f.home/"dev/private-operation"
            with self.assertRaisesRegex(ValueError,"outside source roots"):m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())
        with fixture() as f:
            prepare(f)
            subprocess.run(["git","-C",str(f.args.operation_dir),"init","-q"],check=True)
            with self.assertRaisesRegex(ValueError,"outside Git"):m.apply(f.args)

    def test_linked_managed_parent_is_not_followed_by_preview(self):
        with fixture() as f:
            parent=f.home/".codex/skills";parent.rename(f.home/"real-skills");parent.symlink_to(f.home/"real-skills")
            with self.assertRaisesRegex(ValueError,"symlink"):m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

    def test_operation_storage_cannot_modify_the_verified_runtime_export(self):
        with fixture() as f:
            f.args.operation_dir=m.HERE.parents[1]/"unapproved-operation"
            with self.assertRaisesRegex(ValueError,"outside source roots"):m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

    def test_malformed_policy_and_numeric_enablement_are_not_interpreted_as_consent(self):
        for content in ('skills=[]\n','[skills]\nconfig={}\n','[[skills.config]]\npath=4\n','[[skills.config]]\npath="unused"\nenabled=0\n'):
            with self.subTest(content=content),fixture() as f:
                f.config.write_text(content)
                with self.assertRaises(ValueError):m.preview(f.args)
                self.assertFalse(f.args.operation_dir.exists())

    def test_changed_fixture_bytes_are_bound_to_the_exact_operation(self):
        with fixture() as f:
            prepare(f);replacement=f.root/"fixture-source";replacement.mkdir()
            for name in ("fixture.py","workload.json"):(replacement/name).write_bytes((m.FIXTURE/name).read_bytes()+b"\n")
            with patch.object(m,"FIXTURE",replacement):
                with self.assertRaisesRegex(ValueError,"fixed identity"):m.apply(f.args)

    def test_corrupt_owner_receipt_is_held_while_other_owned_target_is_removed(self):
        with fixture() as f:
            plan=prepare(f);m.apply(f.args)
            record=f.args.operation_dir/("link-owner-"+m.SKILLS[0]+".json")
            row=json.loads(record.read_text());row["link"]["inode"]=True;record.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError,"foreign edits preserved"):m.apply(f.args,undo=True)
            self.assertTrue(f.targets[0].is_symlink())
            self.assertEqual(m.observation(f.targets[1])["kind"],"absent")
            with self.assertRaisesRegex(ValueError,"cannot be replayed"):m.apply(f.args)

    def test_frozen_workload_cannot_silently_request_additional_workers(self):
        with fixture() as f:
            replacement=f.root/"fixture-source";replacement.mkdir()
            (replacement/"fixture.py").write_bytes((m.FIXTURE/"fixture.py").read_bytes())
            brief=json.loads((m.FIXTURE/"workload.json").read_text());brief["parent_protocol"]["worker_count"]=2
            (replacement/"workload.json").write_text(json.dumps(brief))
            with patch.object(m,"FIXTURE",replacement):
                with self.assertRaisesRegex(ValueError,"one-worker"):m.preview(f.args)
            self.assertTrue(all(m.observation(p)["kind"]=="absent" for p in f.targets))


class Host(unittest.TestCase):
    def test_app_and_cli_bytes_must_match_even_when_build_is_unchanged(self):
        data=b"synthetic CLI";expected=m.sha(data)
        with patch.object(m.atom,"host_observation",return_value={"build":"23880","app_metadata_sha256":m.INFO_SHA256}),patch.object(m,"regular",return_value=data),patch.object(m,"CLI_SHA256",expected):
            self.assertEqual(m.host_observation()["cli_sha256"],expected)
            self.assertEqual(m.host_observation()["interpreter"]["version"],list(sys.version_info[:3]))
            with patch.object(m,"CLI_SHA256","0"*64):
                with self.assertRaisesRegex(ValueError,"bytes changed"):m.host_observation()
            with patch.object(m.atom,"host_observation",return_value={"build":"23880","app_metadata_sha256":"other"}):
                with self.assertRaisesRegex(ValueError,"bytes changed"):m.host_observation()


class ExactSource(unittest.TestCase):
    def test_seven_real_git_blobs_and_untracked_or_linked_payload_drift(self):
        with tempfile.TemporaryDirectory(prefix="selected-skills-source-") as raw:
            home=Path(raw).resolve()/"home";root=home/"dev/capabilities/skills"
            for name in m.SKILLS:
                base=root/"global/skills"/name;base.mkdir(parents=True)
                for leaf in ("SKILL.md","meta.yml","install.sh"):(base/leaf).write_text("fixture "+name+leaf)
            (root/"global/skills/frontend-design/LICENSE.txt").write_text("fixture license")
            def git(*args):return subprocess.run(["git","-C",str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
            git("init","-q");git("add",".");git("-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","fixture")
            pin=git("rev-parse","HEAD");rows=[]
            for entry in m.atom.shared.git_bytes(root,"ls-tree","-rz",pin,"--",*["global/skills/"+n for n in m.SKILLS]).split(b"\0"):
                if not entry:continue
                meta,name=entry.split(b"\t");mode,kind,blob=meta.decode().split();name=name.decode();rows.append({"path":name,"mode":mode,"git_blob":blob,"sha256":m.sha((root/name).read_bytes())})
            with patch.object(m,"PIN",pin),patch.object(m,"PAYLOAD",m.sha(m.canonical(rows))),patch.object(m.atom.shared,"portability_manifest_proof",return_value={"manifest_path":str(home/"manifest")}),patch.object(m.atom.shared,"pinned_primary_observation",return_value={"head":pin}):
                self.assertEqual(m.source_proof(home,home/"manifest")["file_count"],7)
                target=root/"global/skills/capability/SKILL.md";before=target.read_bytes();target.write_text("changed")
                with self.assertRaisesRegex(ValueError,"tracked source changed"):m.source_proof(home,home/"manifest")
                target.write_bytes(before);extra=target.parent/"extra";extra.write_text("foreign")
                with self.assertRaisesRegex(ValueError,"unreviewed"):m.source_proof(home,home/"manifest")
                extra.unlink();extra.mkdir()
                with self.assertRaisesRegex(ValueError,"unreviewed"):m.source_proof(home,home/"manifest")
                extra.rmdir();target.unlink();target.symlink_to(root/"global/skills/frontend-design/SKILL.md")
                with self.assertRaises(ValueError):m.source_proof(home,home/"manifest")


class SyntheticFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location("selected_skill_fixture",m.FIXTURE/"fixture.py");cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    @contextmanager
    def marked(self):
        with tempfile.TemporaryDirectory(prefix="selected-lifecycle-") as raw:
            root=Path(raw).resolve();marker=root/"fixture-owner.json";marker.write_bytes(m.canonical({"schema":"interoperability/selected-skill-fixture/v1","operation_id":str(uuid.uuid4()),"action_sha256":"a"*64}));marker.chmod(0o600);yield root

    def test_actual_fixture_install_repair_and_ready_are_separate_and_idempotent(self):
        with self.marked() as root:
            self.assertEqual(self.api.run(root,"status")["verdict"],"Not installed")
            self.assertFalse((root/"capability-state.json").exists())
            self.assertEqual(self.api.run(root,"install")["verdict"],"Needs repair")
            self.assertEqual(self.api.run(root,"doctor")["verdict"],"Needs repair")
            self.assertEqual(self.api.run(root,"repair")["verdict"],"Ready")
            self.assertEqual(self.api.run(root,"repair")["repair_count"],1)
            self.assertEqual(self.api.run(root,"install")["install_count"],1)

    def test_unmarked_or_foreign_state_never_overwritten(self):
        with self.marked() as root:
            path=root/"capability-state.json";path.write_text("foreign bytes");path.chmod(0o600)
            with self.assertRaises(ValueError):self.api.run(root,"install")
            self.assertEqual(path.read_text(),"foreign bytes")
            path.unlink();(root/"fixture-owner.json").unlink()
            with self.assertRaises(FileNotFoundError):self.api.run(root,"install")
            self.assertFalse(path.exists())

    def test_linked_state_or_root_and_insecure_modes_refuse(self):
        for change in ("state-link","state-hardlink","marker-mode","root-mode"):
            with self.subTest(change=change),self.marked() as root:
                if change.startswith("state"):
                    foreign=root/"foreign";foreign.write_text("keep");foreign.chmod(0o600)
                    if change=="state-link":(root/"capability-state.json").symlink_to(foreign)
                    else:os.link(foreign,root/"capability-state.json")
                elif change=="marker-mode":(root/"fixture-owner.json").chmod(0o644)
                else:root.chmod(0o755)
                with self.assertRaises(ValueError):self.api.run(root,"install")


if __name__ == "__main__":
    unittest.main()
