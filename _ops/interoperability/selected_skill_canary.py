#!/usr/bin/env python3
"""Temporary Codex-only canary for two exact personal migration payloads.

Source acceptance and fresh exact human publication/worker consent are external.
This process starts no worker, installer, service or retained installation.
Cooperating invocation locks are mistake hygiene, not a hostile-user boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib
import uuid

HERE = Path(__file__).absolute().parent
HELPERS = {
    "isokit_migration.py": "3969049ba709ff45a0e869dade580d604a67fc7bca98451988d38ca3f4687b95",
    "skill_migration.py": "79460a05441a2403c89ab96e8d38ef4f65a8b30b416817d7b2cae76b4f091a08",
    "inventory.py": "5414d384788924f66f7ed324aa2c0092c5367a58ac914c36532c85a5fcd9f64e",
}
for name, digest in HELPERS.items():
    path = HERE / name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("accepted transaction helper changed")
sys.path.insert(0, str(HERE))
import isokit_migration as atom

if Path(atom.__file__).absolute() != HERE / "isokit_migration.py":
    raise ValueError("transaction helper imported from a different root")

SKILLS = ("capability", "frontend-design")
PIN = "f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a"
PAYLOAD = "41f71eacf1f1c5452b238ffb6fc761ca81078f4f0a125f57de571bf35280b1c2"
FILE_COUNT = 7
SCHEMA = "interoperability/selected-skill-canary/v1"
LINK_MODE = 0o700
CLI = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
CLI_SHA256 = "58a91f6ea19bea477ae3a2ec48d619f0039afe75d3476260747e11d201fa7cea"
INFO_SHA256 = "7a3920d56d052cdf4bf803a92e2098be015eaf9263589d51e04ac4121f16eed7"
WORKER = {"requested_model": "gpt-6.1-sol", "reasoning_effort": "high", "count": 1,
          "native_tool": "collaboration.spawn_agent",
          "fork_turns": "none", "first_parent_wait_ms": 60000, "hard_deadline_ms": 120000,
          "nested_workers": 0, "extra_roots": False, "serving_identity_proven": False}
FIXTURE = HERE / "fixtures/selected-skill-canary"
canonical, sha = atom.canonical, atom.sha
regular, observation, directory = atom.regular, atom.observation, atom.directory
operation_lock = atom.operation_lock


def implementation() -> str:
    rows = {"selected_skill_canary.py": sha(regular(Path(__file__).absolute()))}
    for name, digest in HELPERS.items():
        if sha(regular(HERE / name)) != digest:
            raise ValueError("accepted transaction helper changed")
        rows[name] = digest
    for name in ("fixture.py", "workload.json"):
        rows["fixtures/selected-skill-canary/" + name] = sha(regular(FIXTURE / name))
    return sha(canonical(rows))


def workload(operation: Path) -> dict:
    brief = json.loads(regular(FIXTURE / "workload.json"))
    protocol = {"native_tool": WORKER["native_tool"], "worker_count": WORKER["count"],
                "requested_model": WORKER["requested_model"], "reasoning_effort": WORKER["reasoning_effort"],
                "fork_turns": WORKER["fork_turns"], "immediate_first_wait_ms": WORKER["first_parent_wait_ms"],
                "interrupt_if_unfinished_after_first_wait": True,
                "strict_actual_worker_deadline_ms": WORKER["hard_deadline_ms"],
                "rollback_after_every_outcome": True, "retained_installation_authorized": False}
    if (brief.get("schema") != "interoperability/selected-skill-workload/v1"
            or brief.get("required_skills") != list(SKILLS)
            or canonical(brief.get("parent_protocol")) != canonical(protocol)):
        raise ValueError("frozen native workload escaped the two-skill/one-worker canary contract")
    return {"fixture_source_sha256": sha(regular(FIXTURE / "fixture.py")),
            "brief_sha256": sha(regular(FIXTURE / "workload.json")),
            "private_root": str(operation / "fixture"),
            "outputs": ["capability-state.json", "component.html", "worker-notes.md"],
            "parent_created_marker": "fixture-owner.json"}


def host_observation() -> dict:
    host = atom.host_observation()
    if host["app_metadata_sha256"] != INFO_SHA256 or sha(regular(CLI)) != CLI_SHA256:
        raise ValueError("qualified build-23880 app or CLI bytes changed")
    interpreter = Path(sys.executable).resolve(strict=True)
    return {**host, "cli_sha256": CLI_SHA256,
            "interpreter": {"path": str(interpreter), "sha256": sha(regular(interpreter)),
                            "version": list(sys.version_info[:3])}}


def source_proof(home: Path, manifest: Path) -> dict:
    binding = atom.shared.portability_manifest_proof(manifest)
    primary = atom.shared.pinned_primary_observation(home, binding)
    root = home / "dev/capabilities/skills"
    prefixes = ["global/skills/" + name for name in SKILLS]
    rows = []
    for raw in atom.shared.git_bytes(root, "ls-tree", "-rz", PIN, "--", *prefixes).split(b"\0"):
        if not raw:
            continue
        meta, raw_path = raw.split(b"\t", 1)
        mode, kind, blob = meta.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755"} or not any(path.startswith(p + "/") for p in prefixes):
            raise ValueError("selected payload escaped its fixed regular-file allowlist")
        data = regular(root / path)
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != blob:
            raise ValueError("selected tracked source changed")
        rows.append({"path": path, "mode": mode, "git_blob": blob, "sha256": sha(data)})
    if len(rows) != FILE_COUNT or sha(canonical(rows)) != PAYLOAD:
        raise ValueError("selected seven-file payload does not match its approved pin")
    for prefix in prefixes:
        base = root / prefix
        expected = {r["path"] for r in rows if r["path"].startswith(prefix + "/")}
        found, dirs_seen = set(), set()
        for parent, dirs, files in os.walk(base, followlinks=False):
            parent = Path(parent)
            directory(parent)
            dirs_seen.add(str(parent.relative_to(base)))
            for name in dirs:
                directory(parent / name)
            for name in files:
                regular(parent / name)
                found.add(str((parent / name).relative_to(root)))
        if found != expected or dirs_seen != {"."}:
            raise ValueError("unreviewed selected payload file or directory")
    return {"manifest": binding, "primary": primary, "payload_sha256": PAYLOAD,
            "file_count": FILE_COUNT, "desired": {name: str(root / "global/skills" / name) for name in SKILLS}}


def policy(home: Path, desired: dict) -> dict:
    config = home / ".codex/config.toml"
    state = observation(config)
    if state["kind"] == "absent":
        return {"config": state, "rows": [], "enablement": "unknown-no-override"}
    if state["kind"] != "file":
        raise ValueError("unsupported Codex configuration path")
    parsed = tomllib.loads(regular(config).decode("utf-8"))
    skills = parsed.get("skills", {})
    if not isinstance(skills, dict) or not isinstance(skills.get("config", []), list):
        raise ValueError("unsupported native skill-policy shape")
    targets = [home / shelf / name for shelf in (".codex/skills", ".agents/skills") for name in SKILLS]
    targets.extend(Path(desired[name]) for name in SKILLS)
    exact = {p for base in targets for p in (base, base / "SKILL.md")}
    resolved = {p.resolve(strict=False) for p in exact}
    matched = []
    for row in skills.get("config", []):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("unsupported native skill-policy row")
        enabled = row.get("enabled")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("unsupported native skill enablement value")
        path = atom.shared.normalize_config_path(row["path"], home).absolute()
        if path in exact or path.resolve(strict=False) in resolved:
            if enabled is False:
                raise ValueError("selected skill is explicitly disabled; preserve the owner opt-out")
            matched.append({"path_sha256": sha(str(path).encode()), "enabled": enabled})
    return {"config": state, "rows": matched, "enablement": "explicit-overrides-preserved" if matched else "unknown-no-override"}


def preserved(home: Path) -> list[dict]:
    paths = [home / ".codex", home / ".codex/skills"]
    paths.extend(home / ".codex/skills" / name for name in ("prompt-architect", "verification-before-completion", "operator-voice", "isokit"))
    for shelf in (".agents", ".cursor", ".claude"):
        paths.extend([home / shelf, home / shelf / "skills"])
        paths.extend(home / shelf / "skills" / name for name in SKILLS)
    result = []
    for path in paths:
        atom.shared.no_symlink_components(path.parent)
        result.append({"path": str(path), "state": observation(path)})
    if any(observation(home / ".agents/skills" / name)["kind"] != "absent" for name in SKILLS):
        raise ValueError("existing native alias needs separate owner reconciliation")
    return result


def target_rows(home: Path, identifier: str) -> list[dict]:
    parent = home / ".codex/skills"
    return [{"name": name, "target": str(parent / name),
             "staging": str(parent / (".selected-canary-" + identifier + "-" + name)),
             "desired": str(home / "dev/capabilities/skills/global/skills" / name)} for name in SKILLS]


def private_operation(path: Path, home: Path, *, existing: bool = False) -> Path:
    roots = tuple(home / p for p in ("dev", ".codex", ".agents", ".cursor", ".claude")) + (HERE.parents[1],)
    if not existing:
        return atom.shared.private_operation_path(path, roots)
    operation = path.expanduser().absolute()
    atom.shared.no_symlink_components(operation)
    operation = operation.resolve(strict=True)
    if any(operation == root.resolve(strict=False) or operation.is_relative_to(root.resolve(strict=False)) for root in roots):
        raise ValueError("private operation storage must be outside source roots")
    inside = subprocess.run(["git", "-C", str(operation), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if inside.returncode == 0 and inside.stdout.strip() == "true":
        raise ValueError("private operation storage must be outside Git worktrees")
    return operation


def preview(args) -> dict:
    home = args.home.expanduser().absolute()
    if home != Path.home().absolute():
        raise ValueError("non-default operator home needs a separate owner contract")
    directory(home)
    if os.environ.get("CODEX_HOME", str(home / ".codex")) != str(home / ".codex"):
        raise ValueError("non-default CODEX_HOME needs a separate owner contract")
    source = source_proof(home, args.portability_manifest)
    kept, config, host = preserved(home), policy(home, source["desired"]), host_observation()
    parent = directory(home / ".codex/skills")
    identifier = str(uuid.uuid4())
    targets = target_rows(home, identifier)
    if any(observation(Path(row[key]))["kind"] != "absent" for row in targets for key in ("target", "staging")):
        raise ValueError("canary requires absent targets and named staging; no path is adopted or replaced")
    operation = private_operation(args.operation_dir, home)
    directory(operation.parent)
    operation.mkdir(mode=0o700)
    created = {}
    try:
        plan = {"schema": SCHEMA, "mode": "canary", "operation_id": identifier,
                "operation_dir": str(operation), "operation_root": directory(operation),
                "home": str(home), "source": source, "host": host, "policy": config,
                "targets": targets, "parent": parent, "preserved": kept,
                "implementation_sha256": implementation(), "native_worker": WORKER,
                "workload": workload(operation),
                "native_qualified": False, "retention_authorized": False,
                "affected_sessions": "All Codex sessions scanning the shared skill root; existing contexts may retain prior discovery."}
        digest = sha(canonical(plan))
        for name, data in (("operation.lock", {}), ("operation.json", {**plan, "action_sha256": digest})):
            atom.write_once(operation / name, data)
            created[name] = observation(operation / name)
        return {"status": "previewed", "operation_dir": str(operation), "action_sha256": digest,
                "targets": targets, "native_worker_started": False, "native_qualified": False, "retention_authorized": False}
    except BaseException:
        for name, state in created.items():
            if observation(operation / name) == state:
                (operation / name).unlink()
        try:
            operation.rmdir()
        except OSError:
            pass
        raise


def read_record(path: Path) -> dict:
    info = path.lstat()
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        raise ValueError("private operator-owned record required")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate record key")
            result[key] = value
        return result
    value = json.loads(regular(path), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("private record must be an object")
    return value


def load(operation: Path) -> dict:
    home = Path.home().absolute()
    operation = private_operation(operation, home, existing=True)
    if directory(operation)["mode"] != 0o700:
        raise ValueError("operation root is not private")
    plan = read_record(operation / "operation.json")
    digest = plan.pop("action_sha256")
    if sha(canonical(plan)) != digest:
        raise ValueError("operation digest changed")
    fields = {"schema", "mode", "operation_id", "operation_dir", "operation_root", "home", "source", "host", "policy", "targets", "parent", "preserved", "implementation_sha256", "native_worker", "workload", "native_qualified", "retention_authorized", "affected_sessions"}
    identifier = str(uuid.UUID(plan["operation_id"]))
    if (set(plan) != fields or plan["schema"] != SCHEMA or plan["mode"] != "canary"
            or plan["home"] != str(home) or plan["operation_dir"] != str(operation)
            or directory(operation) != plan["operation_root"]
            or plan["targets"] != target_rows(home, identifier)
            or plan["source"]["desired"] != {r["name"]: r["desired"] for r in plan["targets"]}
            or canonical(plan["native_worker"]) != canonical(WORKER)
            or plan["workload"] != workload(operation) or plan["native_qualified"] is not False
            or plan["retention_authorized"] is not False or implementation() != plan["implementation_sha256"]):
        raise ValueError("operation escaped its fixed identity, paths, worker scope or implementation")
    plan["action_sha256"] = digest
    return plan


def unchanged(plan: dict, *, source: bool = True) -> None:
    home = Path(plan["home"])
    if directory(home / ".codex/skills") != plan["parent"]:
        raise ValueError("managed parent identity changed")
    if source and (source_proof(home, Path(plan["source"]["manifest"]["manifest_path"])) != plan["source"]
                   or host_observation() != plan["host"] or policy(home, plan["source"]["desired"]) != plan["policy"]
                   or preserved(home) != plan["preserved"]):
        raise ValueError("source, host, policy or preserved path changed")


def ownership(plan: dict, row: dict) -> dict | None:
    path = Path(plan["operation_dir"]) / ("link-owner-" + row["name"] + ".json")
    if observation(path)["kind"] == "absent":
        return None
    value = read_record(path)
    link = value.get("link", {})
    if (set(value) != {"action_sha256", "name", "link"} or value["action_sha256"] != plan["action_sha256"]
            or value["name"] != row["name"] or not isinstance(link, dict)
            or set(link) != {"kind", "target", "device", "inode", "mode", "uid"}
            or link.get("kind") != "symlink" or link.get("target") != row["desired"]
            or type(link.get("device")) is not int or type(link.get("inode")) is not int
            or type(link.get("uid")) is not int or link.get("uid") != os.getuid() or link.get("mode") != LINK_MODE):
        raise ValueError("link-owner receipt changed")
    return link


def rollback(plan: dict) -> dict:
    unchanged(plan, source=False)
    operation = Path(plan["operation_dir"])
    marker = operation / "rollback-started.json"
    held = []
    if observation(marker)["kind"] == "absent":
        atom.write_once(marker, {"action_sha256": plan["action_sha256"]})
    elif read_record(marker) != {"action_sha256": plan["action_sha256"]}:
        held.append("rollback marker changed")
    for row in plan["targets"]:
        try:
            owned = ownership(plan, row)
        except (ValueError, OSError, KeyError, TypeError):
            held.append(row["name"] + " ownership changed")
            continue
        for key in ("target", "staging"):
            path = Path(row[key])
            state = observation(path)
            if state["kind"] == "absent":
                continue
            if owned is None or state != owned:
                held.append(row["name"] + " " + key)
                continue
            if observation(path) != owned:
                held.append(row["name"] + " concurrent " + key)
                continue
            path.unlink()
    if held:
        raise ValueError("foreign edits preserved; exact rollback held: " + ", ".join(held))
    marker = operation / "rolled-back.json"
    if observation(marker)["kind"] == "absent":
        atom.write_once(marker, {"action_sha256": plan["action_sha256"]})
    elif read_record(marker) != {"action_sha256": plan["action_sha256"]}:
        raise ValueError("rollback receipt changed")
    return {"status": "rolled-back", "native_qualified": False, "retention_authorized": False}


def apply(args, *, undo: bool = False) -> dict:
    plan = load(args.operation_dir)
    if args.approve != plan["action_sha256"]:
        raise ValueError("exact action digest and external operator approval required")
    if undo:
        return rollback(plan)
    operation = Path(plan["operation_dir"])
    if any(observation(operation / marker)["kind"] != "absent" for marker in ("rollback-started.json", "rolled-back.json")):
        raise ValueError("rolled-back or held canary cannot be replayed; prepare a fresh operation")
    unchanged(plan)
    # Check all slots before the first publication; never adopt an existing inode.
    for row in plan["targets"]:
        owned = ownership(plan, row)
        states = [observation(Path(row[key])) for key in ("target", "staging")]
        if any(s["kind"] != "absent" and (owned is None or s != owned) for s in states):
            raise ValueError("unowned target or staging is preserved")
        if owned is not None and all(s["kind"] == "absent" for s in states):
            raise ValueError("previously owned link is missing; no recreation permitted")
    all_applied = True
    for row in plan["targets"]:
        unchanged(plan)
        target, stage = Path(row["target"]), Path(row["staging"])
        owned = ownership(plan, row)
        if owned is not None and observation(target) == owned:
            if observation(stage)["kind"] != "absent":
                if observation(stage) != owned:
                    raise ValueError("later staging edit preserved")
                stage.unlink()
            continue
        all_applied = False
        if observation(target)["kind"] != "absent":
            raise ValueError("target changed; no replacement permitted")
        if owned is None:
            if observation(stage)["kind"] != "absent":
                raise ValueError("unowned staging is preserved")
            os.symlink(row["desired"], stage)
            created = observation(stage)
            try:
                atom.shared.set_symlink_mode(stage, LINK_MODE)
                created = observation(stage)
                atom.write_once(operation / ("link-owner-" + row["name"] + ".json"),
                                {"action_sha256": plan["action_sha256"], "name": row["name"], "link": created})
            except BaseException:
                if observation(stage) == created:
                    stage.unlink()
                raise
            owned = ownership(plan, row)
        if observation(stage) != owned:
            raise ValueError("owned staging identity changed")
        unchanged(plan)
        os.link(stage, target, follow_symlinks=False)
        stage.unlink()
        if observation(target) != owned:
            raise ValueError("published link identity changed")
    unchanged(plan)
    return {"status": "already-applied" if all_applied else "applied-canary",
            "native_worker_started": False, "native_qualified": False, "retention_authorized": False}


def verify(args) -> dict:
    plan = load(args.operation_dir)
    unchanged(plan)
    if any(observation(Path(row["staging"]))["kind"] != "absent" for row in plan["targets"]):
        raise ValueError("interrupted staging needs exact apply or rollback")
    states = [observation(Path(row["target"])) for row in plan["targets"]]
    if all(s["kind"] == "absent" for s in states):
        return {"status": "verified-preimage", "preserved_unchanged": True,
                "native_qualified": False, "retention_authorized": False}
    if not all(state == ownership(plan, row) for state, row in zip(states, plan["targets"])):
        raise ValueError("targets are partial or not the exact owned inodes")
    return {"status": "verified-canary", "native_qualified": False, "retention_authorized": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply", "verify", "rollback"))
    parser.add_argument("--operation-dir", type=Path, required=True)
    parser.add_argument("--portability-manifest", type=Path)
    parser.add_argument("--approve")
    args = parser.parse_args(argv)
    args.home = Path.home()
    os.umask(0o077)
    try:
        if args.operation == "preview":
            if args.portability_manifest is None or args.approve is not None:
                raise ValueError("preview requires the exact manifest and is not approval")
            result = preview(args)
        else:
            with operation_lock(args.operation_dir):
                result = verify(args) if args.operation == "verify" else apply(args, undo=args.operation == "rollback")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
