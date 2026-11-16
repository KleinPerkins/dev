#!/usr/bin/env bash
# Hermetic M1 Host-Wiring tests. Never reads or writes the operator's real HOME.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

python3 - "$ROOT" <<'PY'
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(sys.argv[1]).resolve()
PIN = "cfe9437739d2928014c2156532d1986a8511fd30"
INTERVAL = 21600
MIN_INTERVAL = 3600
MAX_INTERVAL = 43200
LABEL = "com.kleinperkins.awa-integrity"
OWNER = "KleinPerkins/dev:awa-integrity-host/v1"

WRAPPER = ROOT / "_ops" / "bin" / "awa-integrity-host-sweep.sh"
JOB_INSTALLER = ROOT / "_ops" / "bin" / "install-awa-integrity-job.sh"
HANDLER = ROOT / "_ops" / "local-jobs" / "awa-integrity.sh"
SCHEDULE_FIXTURE = (
    ROOT
    / "_ops"
    / "tests"
    / "fixtures"
    / "awa-v1.8.1"
    / "awa-integrity-schedule.v1.json"
)
HOOK_OWNER_FIXTURE = SCHEDULE_FIXTURE.with_name("awa-hook-owner.v2.json")
BINDING_CHECKER = ROOT / "_ops" / "bin" / "check-awa-release-binding.py"
COMPOSITE_DELEGATOR = (
    ROOT / "_ops" / "cursor-hooks" / "worktree-guard-with-integrity.sh"
)
STOP_DELEGATOR = ROOT / "_ops" / "cursor-hooks" / "awa-integrity-observer.sh"
HANDOFF_DELEGATOR = ROOT / "_ops" / "cursor-hooks" / "awa-session-handoff.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "awa-integrity-host-wiring.md"
RULE_SOURCE = ROOT / "_ops" / "rules" / "agent-context.md"
RULE_PROJECTION = ROOT / "_ops" / "rules" / "dev-operating-model.mdc"
WORKTREE_RULE = ROOT / "_ops" / "rules" / "global" / "worktree-default.mdc"


FAKE_LOCAL_JOBS = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_LOCAL_JOBS_STATE"])
log_path = Path(os.environ["FAKE_LOCAL_JOBS_LOG"])
launchctl = os.environ["FAKE_LAUNCHCTL"]
state_path.parent.mkdir(parents=True, exist_ok=True)
state = json.loads(state_path.read_text()) if state_path.is_file() else {
    "types": [],
    "handlers": {},
    "instances": [],
}
overlay_dir = Path(os.environ.get(
    "LOCAL_JOBS_OVERLAY_DIR", os.environ["FAKE_LOCAL_JOBS_OVERLAY"]
))
overlay = overlay_dir / "awa-integrity.yml"
transient_type = overlay.is_file()
argv = sys.argv[1:]
verb = argv[0] if argv else ""
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv, separators=(",", ":")) + "\n")

def value(flag, default=None):
    if flag not in argv:
        return default
    index = argv.index(flag)
    return argv[index + 1]

def save():
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

if verb == "list-types":
    types = sorted(set(state["types"]) | ({"awa-integrity"} if transient_type else set()))
    catalog_mode = os.environ.get("FAKE_LOCAL_JOBS_CATALOG_MODE", "valid")
    if catalog_mode == "malformed":
        print("{")
    elif catalog_mode == "ambiguous":
        print(json.dumps([
            {"slug": "awa-integrity"},
            {"slug": "awa-integrity"},
        ]))
    elif "--json" in argv:
        print(json.dumps([
            {
                "slug": item,
                "description": f"Fixture {item} type",
                "cardinality": "singleton",
                "singleton_id": item,
                "label_template": f"com.kleinperkins.{item}",
                "add_schema": [],
            }
            for item in types
        ]))
    else:
        for item in types:
            print(f"{item} (singleton) — Fixture {item} type")
elif verb == "handler-path":
    if "awa-integrity" not in state["types"]:
        raise SystemExit(11)
    print(state["handlers"]["awa-integrity"])
elif verb == "view-jobs":
    print(json.dumps({"registry": "fake", "instances": state["instances"]}))
elif verb == "add-job":
    if "awa-integrity" not in state["types"] and not transient_type:
        raise SystemExit(12)
    if "--dry-run" in argv:
        print(json.dumps({"dry_run": True}))
        raise SystemExit(0)
    if any(item["id"] == "awa-integrity" for item in state["instances"]):
        raise SystemExit(13)
    seconds = int(value("--interval-seconds"))
    enabled = value("--enabled", "true") == "true"
    state["instances"].append({
        "id": "awa-integrity",
        "type": "awa-integrity",
        "owner": value("--owner"),
        "enabled": enabled,
        "schedule": {"kind": "interval", "seconds": seconds},
        "launchd_label": "com.kleinperkins.awa-integrity",
        "launchd_loaded": False,
    })
    save()
elif verb == "update-job":
    item = next(item for item in state["instances"] if item["id"] == "awa-integrity")
    if "--interval-seconds" in argv:
        item["schedule"] = {
            "kind": "interval",
            "seconds": int(value("--interval-seconds")),
        }
    if "--enabled" in argv:
        item["enabled"] = value("--enabled") == "true"
    if "--owner" in argv:
        item["owner"] = value("--owner")
    save()
elif verb in ("enable-job", "disable-job"):
    item = next(item for item in state["instances"] if item["id"] == "awa-integrity")
    item["enabled"] = verb == "enable-job"
    item["launchd_loaded"] = item["enabled"]
    save()
    subprocess.run([launchctl, verb, item["launchd_label"]], check=True)
elif verb == "repair-job":
    item = next(item for item in state["instances"] if item["id"] == "awa-integrity")
    subprocess.run([launchctl, verb, item["launchd_label"]], check=True)
elif verb == "delete-job":
    state["instances"] = [
        item for item in state["instances"] if item["id"] != "awa-integrity"
    ]
    save()
    subprocess.run([launchctl, verb, "com.kleinperkins.awa-integrity"], check=True)
elif verb == "doctor":
    print("doctor: PASS")
else:
    raise SystemExit(14)
'''


FAKE_AUTHORING = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_LOCAL_JOBS_STATE"])
overlay_dir = Path(os.environ["FAKE_LOCAL_JOBS_OVERLAY"])
overlay = overlay_dir / "awa-integrity.yml"
state = json.loads(state_path.read_text()) if state_path.is_file() else {
    "types": [],
    "handlers": {},
    "instances": [],
}
argv = sys.argv[1:]
verb = argv[0] if argv else ""

def value(flag):
    index = argv.index(flag)
    return argv[index + 1]

def save():
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

backup = overlay_dir / ".awa-integrity.rollback"
overlay_dir.mkdir(parents=True, exist_ok=True)
if verb == "register":
    handler = value("--handler")
    if "awa-integrity" in state["types"]:
        raise SystemExit(20)
    backup.write_text("absent\n", encoding="utf-8")
    overlay.write_text(
        "awa-integrity:\n"
        f"  handler: {handler}\n"
        "  description: AWA integrity surveillance host schedule\n",
        encoding="utf-8",
    )
    overlay.chmod(0o600)
    state["types"].append("awa-integrity")
    state["handlers"]["awa-integrity"] = handler
    save()
    print(json.dumps({"backup": str(backup)}))
elif verb == "unregister":
    overlay.unlink(missing_ok=True)
    state["types"] = [item for item in state["types"] if item != "awa-integrity"]
    state["handlers"].pop("awa-integrity", None)
    save()
    print(json.dumps({"unregistered": "awa-integrity"}))
elif verb == "restore-registry":
    overlay.unlink(missing_ok=True)
    state["types"] = [item for item in state["types"] if item != "awa-integrity"]
    state["handlers"].pop("awa-integrity", None)
    save()
    backup.unlink(missing_ok=True)
elif verb == "verify":
    print(json.dumps({"type": "awa-integrity", "ok": True, "errors": []}))
elif verb == "regression":
    print(json.dumps({"ok": True, "results": []}))
else:
    raise SystemExit(21)
'''


FAKE_LAUNCHCTL = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_LAUNCHCTL_LOG"
mkdir -p "$FAKE_LAUNCHCTL_STATE"
case "${1:-}" in
  bootstrap)
    label="$(basename "${3:?}")"
    : > "$FAKE_LAUNCHCTL_STATE/${label%.plist}"
    ;;
  bootout)
    label="${2##*/}"
    rm -f "$FAKE_LAUNCHCTL_STATE/$label"
    ;;
  print)
    label="${2##*/}"
    [ -f "$FAKE_LAUNCHCTL_STATE/$label" ]
    ;;
esac
'''


FAKE_CLOCK = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' '2026-08-26T22:00:00Z'
'''


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dev-awa-integrity-host-")
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.data = self.base / "xdg-data"
        self.config = self.base / "xdg-config"
        self.state = self.base / "xdg-state"
        self.runtime = self.data / "awa" / "current"
        self.local_jobs_state = self.base / "local-jobs"
        self.local_jobs_overlay = self.local_jobs_state / "registry.d"
        self.fake_state = self.base / "fake-local-jobs.json"
        self.local_jobs_log = self.base / "local-jobs.log"
        self.launchctl_log = self.base / "launchctl.log"
        self.launchctl_state = self.base / "launchctl-state"
        self.env_log = self.base / "sweep-env.json"
        self.fake_bin = self.base / "bin"
        self.fake_bin.mkdir(parents=True)
        self.local_jobs = self.fake_bin / "local-jobs"
        self.authoring = self.fake_bin / "authoring.py"
        self.launchctl = self.fake_bin / "launchctl"
        self.clock = self.fake_bin / "clock"
        self._write(self.local_jobs, FAKE_LOCAL_JOBS)
        self._write(self.authoring, FAKE_AUTHORING)
        self._write(self.launchctl, FAKE_LAUNCHCTL)
        self._write(self.clock, FAKE_CLOCK)
        self._seed_runtime()
        self.env = {
            **{key: value for key, value in os.environ.items()
               if not key.startswith(("AWA_", "DEV_AWA_", "GIT_", "LOCAL_JOBS_"))
               and key != "DEV_SESSION_ID"},
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.state),
            "AWA_HOME": str(self.runtime),
            "DEV_AWA_GCB_DIR": str(self.gcb_dir),
            "AWA_ENGINE_TEST_ACTIVE": "1",
            "DEV_AWA_LOCAL_JOBS_CLI": str(self.local_jobs),
            "DEV_AWA_LOCAL_JOBS_HOME": str(self.base / "fake-local-jobs-home"),
            "DEV_AWA_LOCAL_JOBS_AUTHORING": str(self.authoring),
            "DEV_AWA_LOCAL_JOBS_PYTHON": sys.executable,
            "LOCAL_JOBS_STATE": str(self.local_jobs_state),
            "LOCAL_JOBS_OVERLAY_DIR": str(self.local_jobs_overlay),
            "FAKE_LOCAL_JOBS_STATE": str(self.fake_state),
            "FAKE_LOCAL_JOBS_OVERLAY": str(self.local_jobs_overlay),
            "FAKE_LOCAL_JOBS_LOG": str(self.local_jobs_log),
            "FAKE_LAUNCHCTL": str(self.launchctl),
            "FAKE_LAUNCHCTL_LOG": str(self.launchctl_log),
            "FAKE_LAUNCHCTL_STATE": str(self.launchctl_state),
            "DEV_AWA_CLOCK": str(self.clock),
            "FAKE_SWEEP_ENV_LOG": str(self.env_log),
            "PATH": f"{self.fake_bin}:{os.environ.get('PATH', '')}",
        }

    @staticmethod
    def _write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _seed_runtime(self):
        self.gcb_dir = self.base / "gcb" / "global" / "tools" / "awa"
        self.gcb_dir.mkdir(parents=True)
        (self.gcb_dir / "meta.yml").write_text(
            "schema: kp-capability/v1\n"
            "id: awa\nkind: tool\nflavor: 2\nscope: global\n"
            'provenance_source: "github.com/KleinPerkins/awa"\n'
            f'provenance_ref: "{PIN}"\n',
            encoding="utf-8",
        )
        self._write(self.gcb_dir / "install.sh", "#!/usr/bin/env bash\nexit 0\n")

        schedule = self.runtime / "contracts" / "awa-integrity-schedule.v1.json"
        schedule.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCHEDULE_FIXTURE, schedule)
        shutil.copy2(
            HOOK_OWNER_FIXTURE,
            self.runtime / "contracts" / "awa-hook-owner.v2.json",
        )
        v1_contract = {
            "hook_ownership": {
                "schema": "awa-hook-owner/v1",
                "modes": ["direct", "external"],
                "default_mode": "direct",
                "selection_env": "AWA_HOOK_OWNER",
                "selection_schema": "awa-hook-owner-selection/v1",
                "external_real_hook_file_writes": False,
                "roles": [
                    {"id": "worktree.session-context"},
                    {"id": "worktree.shell-guard"},
                    {"id": "worktree.file-observer"},
                    {"id": "recovery.maintenance"},
                    {"id": "finish.prompt-recall"},
                ],
            }
        }
        v1_path = self.runtime / "contracts" / "awa-contract.v1.json"
        v1_path.write_text(
            json.dumps(v1_contract, indent=2) + "\n", encoding="utf-8"
        )
        for relative in (
            "kernel/bin/dev-worktree.sh",
            "kernel/hooks/worktree-session.sh",
            "kernel/hooks/worktree-guard.sh",
            "kernel/hooks/worktree-guard-with-integrity.sh",
            "kernel/hooks/awa-integrity-observer.sh",
            "kernel/hooks/awa-session-handoff.sh",
            "kernel/hooks/awa-recovery-maintenance.sh",
            "kernel/hooks/before-submit-prompt.sh",
        ):
            self._write(
                self.runtime / relative,
                "#!/usr/bin/env bash\ncat >/dev/null 2>&1 || true\nexit 0\n",
            )
        sweep = self.runtime / "kernel" / "bin" / "awa-integrity-sweep.sh"
        self._write(
            sweep,
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -u
                python3 - "$FAKE_SWEEP_ENV_LOG" <<'PYENV'
                import json, os, sys
                names = (
                    "DEV_SESSION_ID", "CURSOR_SESSION_ID", "AWA_SESSION_ID",
                    "AWA_LEASE_ID", "AWA_LOCK_ID",
                    "AWA_POLICY", "AWA_GOVERNED_ROOT",
                    "AWA_INTEGRITY_PROBE_REPO",
                )
                open(sys.argv[1], "w", encoding="utf-8").write(
                    json.dumps({name: os.environ.get(name) for name in names})
                )
                PYENV
                mode="${FAKE_EVALUATOR_EXIT:-0}"
                if [ "$mode" = "signal" ]; then kill -TERM "$$"; fi
                exit "$mode"
                """
            ),
        )
        policy = self.runtime / "kernel" / "policy" / "default-worktree-policy.yml"
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text("version: 1\n", encoding="utf-8")
        checkout = self.data / "awa" / "checkout"
        checkout.mkdir(parents=True)
        owner = self.config / "awa" / "hook-owner.json"
        owner.parent.mkdir(parents=True, exist_ok=True)
        owner.write_text(
            json.dumps(
                {
                    "schema": "awa-hook-owner-selection/v1",
                    "contract": "awa-hook-owner/v1",
                    "mode": "external",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        pointer = self.data / "awa" / "release-pointer.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(
            json.dumps(
                {
                    "schema": "awa-release-pointer/v1",
                    "version": "1.8.2",
                    "source": str(checkout),
                    "commit": PIN,
                    "runtime": str(self.runtime),
                    "policy": str(policy),
                    "hook_owner_contract": "awa-hook-owner/v1",
                    "hook_owner_mode": "external",
                    "hook_owner_contract_sha256": hashlib.sha256(
                        v1_path.read_bytes()
                    ).hexdigest(),
                    "installed_at": "2026-08-26T22:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.data / "awa" / "gcb-pointer.json").write_text(
            json.dumps(
                {
                    "schema": "awa-gcb-pointer/v1",
                    "id": "awa",
                    "kind": "global-capability-binding",
                    "source": "github.com/KleinPerkins/awa",
                    "ref": PIN,
                    "clone_url": "fixture://awa",
                    "checkout": str(checkout),
                    "shelf": str(self.gcb_dir),
                    "release_pointer": str(pointer),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def run(self, argv, updates=None):
        env = dict(self.env)
        if updates:
            env.update({key: str(value) for key, value in updates.items()})
        return subprocess.run(
            [str(item) for item in argv],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_wrapper(self, evaluator_exit):
        return self.run(
            [WRAPPER],
            updates={
                "FAKE_EVALUATOR_EXIT": evaluator_exit,
                "DEV_SESSION_ID": "must-be-removed",
                "CURSOR_SESSION_ID": "must-be-removed",
                "AWA_SESSION_ID": "must-be-removed",
                "AWA_LEASE_ID": "must-be-removed",
                "AWA_LOCK_ID": "must-be-removed",
            },
        )

    def run_job(self, verb):
        return self.run([JOB_INSTALLER, verb])

    def fake_jobs(self):
        if not self.fake_state.is_file():
            return {"types": [], "instances": []}
        return json.loads(self.fake_state.read_text(encoding="utf-8"))

    def close(self):
        self.tmp.cleanup()


class IntegrityHostTest(unittest.TestCase):
    def test_parent_runtime_overrides_cannot_escape_disposable_fixture(self):
        names = ["AWA_GOVERNED_ROOT", "AWA_ENGINE_HOME", "DEV_AWA_SKILLS_ROOT",
                 "DEV_AWA_RELEASE_POINTER", "DEV_AWA_GCB_POINTER",
                 "DEV_AWA_OWNER_SELECTION", "GIT_INDEX_FILE", "DEV_SESSION_ID"]
        poison = {name: str(self.fx.base / "outside-fixture") for name in names}
        with patch.dict(os.environ, poison):
            fixture = Fixture()
        self.addCleanup(fixture.close)
        for name in names:
            self.assertNotIn(name, fixture.env)
        self.assertEqual(fixture.env["AWA_HOME"], str(fixture.runtime))
        self.assertEqual(fixture.env["DEV_AWA_GCB_DIR"], str(fixture.gcb_dir))
        self.assertEqual(fixture.env["LOCAL_JOBS_STATE"], str(fixture.local_jobs_state))

    def setUp(self):
        self.fx = Fixture()

    def tearDown(self):
        self.fx.close()

    def test_required_source_surfaces_exist_and_are_executable(self):
        for path in (
            WRAPPER,
            JOB_INSTALLER,
            HANDLER,
            BINDING_CHECKER,
            COMPOSITE_DELEGATOR,
            STOP_DELEGATOR,
            HANDOFF_DELEGATOR,
        ):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), path)
                self.assertTrue(os.access(path, os.X_OK), path)
        self.assertTrue(SCHEDULE_FIXTURE.is_file(), SCHEDULE_FIXTURE)
        self.assertTrue(HOOK_OWNER_FIXTURE.is_file(), HOOK_OWNER_FIXTURE)

    def test_integrity_entrypoints_supply_explicit_host_probe_repo(self):
        expected = (
            'export AWA_INTEGRITY_PROBE_REPO="${AWA_INTEGRITY_PROBE_REPO:-'
            '$ROOT/capabilities/awa}"'
        )
        for path in (WRAPPER, COMPOSITE_DELEGATOR, STOP_DELEGATOR):
            with self.subTest(path=path):
                self.assertIn(expected, path.read_text(encoding="utf-8"))

    def test_exact_v1_8_contract_fixture_digests(self):
        expected = {
            HOOK_OWNER_FIXTURE:
                "0c2753a3ced8be7d47b3a6613db0ba59dd55830cb6efa2fa801a0aeb0c0cd22b",
            SCHEDULE_FIXTURE:
                "d6cdfef9b1e240290cbea678d49795fcdced80d9f0099627f579bdf5a98804a6",
        }
        for path, digest in expected.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_source_only_preview_is_nonmutating_and_owner_marked(self):
        before_state = self.fx.fake_jobs()
        before_overlay = (
            self.local_jobs_overlay().read_bytes()
            if self.local_jobs_overlay().is_file()
            else None
        )
        result = self.fx.run_job("--preview")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.fx.fake_jobs(), before_state)
        after_overlay = (
            self.local_jobs_overlay().read_bytes()
            if self.local_jobs_overlay().is_file()
            else None
        )
        self.assertEqual(after_overlay, before_overlay)
        self.assertFalse(self.fx.launchctl_log.exists())
        source = JOB_INSTALLER.read_text(encoding="utf-8")
        self.assertIn(OWNER, source)
        self.assertNotIn("write_overlay", source)

    def test_mover_rule_source_and_projection_are_truthful(self):
        cursor = WORKTREE_RULE.read_text(encoding="utf-8")
        self.assertIn("Agents Window", cursor)
        self.assertIn("Worktree", cursor)
        source = RULE_SOURCE.read_text(encoding="utf-8")
        for phrase in ("For Codex", "inspect native attachments", "create/attach",
                       "verify the returned root, branch, Git directories and writer",
                       "not native attachment or AWA protection", "separate indexes"):
            self.assertIn(phrase, source)
        for text in (cursor, source):
            self.assertNotIn("move_agent_to_root", text)
        projection = RULE_PROJECTION.read_text(encoding="utf-8")
        self.assertIn(source.strip(), projection)

    def test_uat_runbook_is_gated_and_secret_free(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        for phrase in (
            "operator GO",
            "source-only",
            "host triggers",
            "local-jobs",
            "status.json",
            "console",
            "rollback",
            "generation-bound",
            "specifically captured",
            "Never select an arbitrary",
            "intentional removal/uninstall",
            "Slack alerts: opted out",
        ):
            self.assertIn(phrase, text)
        for private_identifier in (
            "KEYCHAIN_SERVICE",
            "KEYCHAIN_ACCOUNT",
            "xox",
        ):
            self.assertNotIn(private_identifier, text)

    def test_wrapper_truth_table_and_no_awa_session_lease_lock(self):
        expected = {
            "0": (0, "green", 0),
            "1": (0, "degraded", 1),
            "2": (0, "red", 2),
            "3": (3, "red", 3),
            "70": (70, "red", 70),
        }
        for evaluator, (scheduler_rc, severity, evaluator_rc) in expected.items():
            with self.subTest(evaluator=evaluator):
                result = self.fx.run_wrapper(evaluator)
                self.assertEqual(
                    result.returncode,
                    scheduler_rc,
                    result.stdout + result.stderr,
                )
                marker = [
                    line
                    for line in result.stdout.splitlines()
                    if line.startswith("@@AWA_INTEGRITY_HOST_SWEEP@@ ")
                ]
                self.assertEqual(len(marker), 1, result.stdout + result.stderr)
                payload = json.loads(marker[0].split(" ", 1)[1])
                self.assertEqual(payload["severity"], severity)
                self.assertEqual(payload["evaluator_exit"], evaluator_rc)
                self.assertEqual(payload["scheduler_exit"], scheduler_rc)
                self.assertEqual(payload["checked_at"], "2026-08-26T22:00:00Z")
                inherited = json.loads(self.fx.env_log.read_text(encoding="utf-8"))
                for name in (
                    "DEV_SESSION_ID",
                    "CURSOR_SESSION_ID",
                    "AWA_SESSION_ID",
                    "AWA_LEASE_ID",
                    "AWA_LOCK_ID",
                ):
                    self.assertIsNone(inherited[name])
                self.assertEqual(
                    inherited["AWA_POLICY"],
                    str(ROOT / "_ops" / "policy" / "worktree-policy.yml"),
                )
                self.assertEqual(inherited["AWA_GOVERNED_ROOT"], str(ROOT))
                self.assertEqual(
                    inherited["AWA_INTEGRITY_PROBE_REPO"],
                    str(ROOT / "capabilities" / "awa"),
                )

    def test_wrapper_propagates_signal_exit(self):
        result = self.fx.run_wrapper("signal")
        self.assertEqual(result.returncode, 143, result.stdout + result.stderr)
        marker = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("@@AWA_INTEGRITY_HOST_SWEEP@@ ")
        ]
        self.assertEqual(len(marker), 1)
        payload = json.loads(marker[0].split(" ", 1)[1])
        self.assertEqual(payload["evaluator_exit"], 143)
        self.assertEqual(payload["scheduler_exit"], 143)
        self.assertEqual(payload["severity"], "red")

    def test_stage_is_idempotent_disabled_and_exact(self):
        first = self.fx.run_job("--stage")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.fx.run_job("--stage")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        jobs = self.fx.fake_jobs()
        self.assertEqual(jobs["types"], ["awa-integrity"])
        self.assertEqual(len(jobs["instances"]), 1)
        instance = jobs["instances"][0]
        self.assertEqual(instance["launchd_label"], LABEL)
        self.assertEqual(instance["schedule"]["seconds"], INTERVAL)
        self.assertFalse(instance["enabled"])
        overlay = self.local_jobs_overlay()
        self.assertTrue(overlay.is_file())
        self.assertFalse(overlay.is_symlink())
        self.assertEqual(stat.S_IMODE(overlay.stat().st_mode), 0o600)
        calls = [
            json.loads(line)
            for line in self.fx.local_jobs_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(sum(call[0] == "add-job" for call in calls), 1)
        self.assertFalse(any(path.suffix == ".plist" for path in self.fx.base.rglob("*")))

    def test_stage_refuses_malformed_or_ambiguous_type_catalog(self):
        for catalog_mode in ("malformed", "ambiguous"):
            with self.subTest(catalog_mode=catalog_mode):
                fx = Fixture()
                try:
                    result = fx.run(
                        [JOB_INSTALLER, "--stage"],
                        updates={"FAKE_LOCAL_JOBS_CATALOG_MODE": catalog_mode},
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "type catalog is malformed or ambiguous",
                        result.stderr,
                    )
                    self.assertEqual(fx.fake_jobs()["types"], [])
                    self.assertEqual(fx.fake_jobs()["instances"], [])
                finally:
                    fx.close()

    def test_stage_updates_schedule_without_disabling_owned_active_job(self):
        self.assertEqual(self.fx.run_job("--stage").returncode, 0)
        state = self.fx.fake_jobs()
        state["instances"][0]["schedule"]["seconds"] = MIN_INTERVAL
        state["instances"][0]["enabled"] = True
        self.fx.fake_state.write_text(
            json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
        )
        repaired = self.fx.run_job("--stage")
        self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
        instance = self.fx.fake_jobs()["instances"][0]
        self.assertEqual(instance["schedule"]["seconds"], INTERVAL)
        self.assertTrue(instance["enabled"])
        self.assertEqual(instance["owner"], OWNER)

    def test_real_local_jobs_framework_in_isolated_home_when_available(self):
        local_jobs_home = Path(
            os.environ.get(
                "DEV_AWA_REAL_LOCAL_JOBS_HOME",
                ROOT / "capabilities" / "skills" / "global" / "skills" / "local-jobs",
            )
        )
        cli = local_jobs_home / "scripts" / "local-jobs.sh"
        authoring = local_jobs_home / "lib" / "authoring.py"
        if not cli.is_file() or not authoring.is_file():
            self.skipTest("local-jobs sibling checkout is unavailable")
        yaml_probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import pathlib,yaml; print(pathlib.Path(yaml.__file__).parent.parent)",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if yaml_probe.returncode != 0:
            self.skipTest("local-jobs PyYAML dependency is unavailable")
        updates = {
            "DEV_AWA_LOCAL_JOBS_CLI": cli,
            "DEV_AWA_LOCAL_JOBS_HOME": local_jobs_home,
            "DEV_AWA_LOCAL_JOBS_AUTHORING": authoring,
            "DEV_AWA_LOCAL_JOBS_PYTHON": sys.executable,
            "LOCAL_JOBS_PRESERVE_HARNESS_ENV": "1",
            "LOCAL_JOBS_REGISTRY": local_jobs_home / "config" / "registry.yml",
            "PYTHONPATH": yaml_probe.stdout.strip(),
        }
        staged = self.fx.run([JOB_INSTALLER, "--stage"], updates=updates)
        self.assertEqual(staged.returncode, 0, staged.stdout + staged.stderr)
        restaged = self.fx.run([JOB_INSTALLER, "--stage"], updates=updates)
        self.assertEqual(restaged.returncode, 0, restaged.stdout + restaged.stderr)
        self.assertFalse(any(self.fx.home.rglob("*.plist")))
        private_overlay = self.fx.local_jobs_overlay / "awa-integrity.yml"
        self.assertTrue(private_overlay.is_file(), private_overlay)
        self.assertEqual(stat.S_IMODE(private_overlay.stat().st_mode), 0o600)
        activated = self.fx.run([JOB_INSTALLER, "--activate"], updates=updates)
        self.assertEqual(activated.returncode, 0, activated.stdout + activated.stderr)
        doctor = self.fx.run([JOB_INSTALLER, "--doctor"], updates=updates)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        deactivated = self.fx.run([JOB_INSTALLER, "--deactivate"], updates=updates)
        self.assertEqual(
            deactivated.returncode,
            0,
            deactivated.stdout + deactivated.stderr,
        )
        removed = self.fx.run([JOB_INSTALLER, "--remove"], updates=updates)
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertFalse(
            (self.fx.local_jobs_overlay / "awa-integrity.yml").exists()
        )

    def test_stage_refuses_foreign_type_and_instance_ownership(self):
        foreign_type = {
            "types": ["awa-integrity"],
            "handlers": {"awa-integrity": "/opt/foreign/handler.sh"},
            "instances": [],
        }
        self.fx.fake_state.write_text(
            json.dumps(foreign_type) + "\n", encoding="utf-8"
        )
        before = self.fx.fake_state.read_bytes()
        refused_type = self.fx.run_job("--stage")
        self.assertNotEqual(refused_type.returncode, 0)
        self.assertIn("another handler", refused_type.stderr)
        self.assertEqual(self.fx.fake_state.read_bytes(), before)

        self.fx.fake_state.unlink()
        self.assertEqual(self.fx.run_job("--stage").returncode, 0)
        state = self.fx.fake_jobs()
        state["instances"][0]["owner"] = "foreign"
        self.fx.fake_state.write_text(
            json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
        )
        before = self.fx.fake_state.read_bytes()
        refused_instance = self.fx.run_job("--stage")
        self.assertNotEqual(refused_instance.returncode, 0)
        self.assertIn("owned by another source", refused_instance.stderr)
        self.assertEqual(self.fx.fake_state.read_bytes(), before)

    def test_stage_transaction_rolls_back_each_injected_cutpoint(self):
        for cutpoint in ("after-register", "after-add"):
            with self.subTest(cutpoint=cutpoint):
                fx = Fixture()
                try:
                    result = fx.run(
                        [JOB_INSTALLER, "--stage"],
                        updates={"DEV_AWA_JOB_TEST_FAIL_STAGE": cutpoint},
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(fx.fake_jobs()["types"], [])
                    self.assertEqual(fx.fake_jobs()["instances"], [])
                    self.assertFalse(
                        (fx.local_jobs_overlay / "awa-integrity.yml").exists()
                    )
                    self.assertFalse(
                        any(path.suffix == ".plist" for path in fx.base.rglob("*"))
                    )
                finally:
                    fx.close()

    def test_host_sources_ship_no_plist_or_network_client(self):
        self.assertFalse(
            any(
                path.name.endswith(".plist") and "awa-integrity" in path.name
                for path in (ROOT / "_ops").rglob("*")
            )
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (WRAPPER, JOB_INSTALLER, HANDLER)
        )
        for primitive in ("curl ", "wget ", "urllib", "requests.", "socket."):
            self.assertNotIn(primitive, combined)

    def test_composite_delegator_preserves_guard_payload_and_degrades_open(self):
        target = (
            self.fx.runtime
            / "kernel"
            / "hooks"
            / "worktree-guard-with-integrity.sh"
        )
        self.fx._write(target, "#!/usr/bin/env bash\ncat\n")
        payload = '{"permission":"deny","user_message":"fixture"}\n'
        delegated = subprocess.run(
            [str(COMPOSITE_DELEGATOR)],
            cwd=ROOT,
            env=self.fx.env,
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(delegated.returncode, 0)
        self.assertEqual(delegated.stdout, payload)
        target.unlink()
        degraded = subprocess.run(
            [str(COMPOSITE_DELEGATOR)],
            cwd=ROOT,
            env=self.fx.env,
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(degraded.returncode, 0)
        self.assertEqual(json.loads(degraded.stdout)["permission"], "allow")

    def local_jobs_overlay(self):
        return self.fx.local_jobs_state / "registry.d" / "awa-integrity.yml"

    def test_activate_repair_disable_remove_delegate_to_local_jobs(self):
        self.assertEqual(self.fx.run_job("--stage").returncode, 0)
        self.assertEqual(self.fx.run_job("--activate").returncode, 0)
        self.assertTrue(self.fx.fake_jobs()["instances"][0]["enabled"])
        self.assertEqual(self.fx.run_job("--repair").returncode, 0)
        self.assertEqual(self.fx.run_job("--deactivate").returncode, 0)
        self.assertFalse(self.fx.fake_jobs()["instances"][0]["enabled"])
        self.assertEqual(self.fx.run_job("--remove").returncode, 0)
        self.assertEqual(self.fx.fake_jobs()["instances"], [])
        self.assertFalse(self.local_jobs_overlay().exists())
        launchctl_calls = self.fx.launchctl_log.read_text(encoding="utf-8")
        self.assertIn(f"enable-job {LABEL}", launchctl_calls)
        self.assertIn(f"repair-job {LABEL}", launchctl_calls)
        self.assertIn(f"disable-job {LABEL}", launchctl_calls)
        self.assertIn(f"delete-job {LABEL}", launchctl_calls)

    def test_schedule_contract_bounds_are_enforced_before_registration(self):
        schedule_path = (
            self.fx.runtime / "contracts" / "awa-integrity-schedule.v1.json"
        )
        original = json.loads(schedule_path.read_text(encoding="utf-8"))
        for seconds in (MIN_INTERVAL - 1, MAX_INTERVAL + 1):
            with self.subTest(seconds=seconds):
                mutated = dict(original)
                mutated["interval_seconds"] = seconds
                schedule_path.write_text(json.dumps(mutated) + "\n", encoding="utf-8")
                result = self.fx.run_job("--stage")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("binding", (result.stdout + result.stderr).lower())
                self.assertFalse(self.fx.fake_state.exists())

    def test_handler_retains_actual_severity_in_runlog(self):
        fake_home = self.fx.base / "fake-local-jobs-home"
        lib = fake_home / "lib"
        lib.mkdir(parents=True)
        (lib / "handler_lib.sh").write_text(
            textwrap.dedent(
                """\
                set -euo pipefail
                hl_die() { printf '%s\n' "$*" >&2; exit 2; }
                handler_main() {
                  [ "${1:-}" = run ] || exit 2
                  shift
                  handler_do_run "$@"
                }
                """
            ),
            encoding="utf-8",
        )
        for evaluator, expected_status, expected_severity, expected_rc in (
            ("0", "success", "green", 0),
            ("1", "success", "degraded", 0),
            ("2", "completed_with_failures", "red", 0),
            ("70", "failure", "red", 70),
        ):
            with self.subTest(evaluator=evaluator):
                result = self.fx.run(
                    [HANDLER, "run", "--id", "awa-integrity"],
                    updates={
                        "LOCAL_JOBS_HOME": fake_home,
                        "DEV_AWA_INTEGRITY_WRAPPER": WRAPPER,
                        "FAKE_EVALUATOR_EXIT": evaluator,
                    },
                )
                self.assertEqual(
                    result.returncode,
                    expected_rc,
                    result.stdout + result.stderr,
                )
                runlog = [
                    line
                    for line in result.stdout.splitlines()
                    if line.startswith("@@RUNLOG@@ ")
                ]
                self.assertEqual(len(runlog), 1, result.stdout + result.stderr)
                payload = json.loads(runlog[0].split(" ", 1)[1])
                self.assertEqual(payload["status"], expected_status)
                self.assertEqual(payload["fields"]["severity"], expected_severity)
                self.assertEqual(
                    payload["fields"]["evaluator_exit"],
                    int(evaluator),
                )
                if expected_severity == "degraded":
                    # The fake sweep prints no status JSON, so no reasons exist.
                    self.assertEqual(
                        payload["fields"]["warning"],
                        "degraded (reasons unavailable; see run log)",
                    )
                    self.assertIn("awa-integrity: WARNING", result.stdout)
                else:
                    self.assertNotIn("warning", payload["fields"])

    def test_handler_unknown_severity_fails_closed(self):
        fake_home = self.fx.base / "fake-local-jobs-home"
        lib = fake_home / "lib"
        lib.mkdir(parents=True)
        (lib / "handler_lib.sh").write_text(
            textwrap.dedent(
                """\
                set -euo pipefail
                hl_die() { printf '%s\\n' "$*" >&2; exit 2; }
                handler_main() { shift; handler_do_run "$@"; }
                """
            ),
            encoding="utf-8",
        )
        for marker in (
            '@@AWA_INTEGRITY_HOST_SWEEP@@ {"severity":"purple","scheduler_exit":0}',
            '@@AWA_INTEGRITY_HOST_SWEEP@@ {"scheduler_exit":0}',
            "no marker at all",
        ):
            with self.subTest(marker=marker):
                stub = self.fx.base / "stub-wrapper.sh"
                stub.write_text(
                    "#!/usr/bin/env bash\nprintf '%s\\n' '" + marker + "'\nexit 0\n",
                    encoding="utf-8",
                )
                stub.chmod(0o755)
                result = self.fx.run(
                    [HANDLER, "run", "--id", "awa-integrity"],
                    updates={
                        "LOCAL_JOBS_HOME": fake_home,
                        "DEV_AWA_INTEGRITY_WRAPPER": stub,
                    },
                )
                runlog = [
                    line
                    for line in result.stdout.splitlines()
                    if line.startswith("@@RUNLOG@@ ")
                ]
                self.assertEqual(len(runlog), 1, result.stdout + result.stderr)
                payload = json.loads(runlog[0].split(" ", 1)[1])
                self.assertEqual(payload["status"], "completed_with_failures")
                self.assertEqual(payload["fields"]["severity"], "red")


    # Field structure captured from a real `awa-integrity-status/v1` sweep
    # (2026-10-21 launchd run); hashes shortened, nothing machine-specific kept.
    REAL_SWEEP = {
        "alert": {
            "attempted": [],
            "delivered": {"native": "accepted", "slack": "opted_out"},
            "last_transition": "red->degraded@2026-10-20T08:59:46Z#85998",
        },
        "artifacts": {
            "console": {"gen": 88228, "path": "console/88228.html", "sha256": "77b6"},
            "history": {"gen": 88228, "path": "history/88228.json", "sha256": "0772"},
        },
        "fresh_until": "2026-10-22T00:34:05Z",
        "generated_at": "2026-10-21T00:34:05Z",
        "generation": 88228,
        "invariants": [
            {"checked_at": "2026-10-21T00:34:05Z", "id": "guard_safety",
             "evidence": "primary denies and linked workspace allows",
             "profile": "deep", "severity": "green"},
            {"checked_at": "2026-10-21T00:34:05Z", "id": "entry_handshake",
             "evidence": "native entry evidence stale",
             "profile": "deep", "severity": "degraded"},
            {"checked_at": "2026-10-21T00:34:05Z", "id": "recovery",
             "evidence": "recovery scan is clean",
             "profile": "deep", "severity": "green"},
            {"checked_at": "2026-10-21T00:34:05Z", "id": "lifecycle",
             "evidence": "worktree lifecycle needs attention (unleased=85, conflicts=1, problems=89)",
             "profile": "deep", "severity": "degraded"},
            {"checked_at": "2026-10-21T00:34:05Z", "id": "parity",
             "evidence": "kernel and engine classifications agree",
             "profile": "deep", "severity": "green"},
        ],
        "orphans": {"husks": 0, "leases_unreconciled": 3,
                    "sessions_dangling": 0, "worktrees": 85},
        "overall": "degraded",
        "profile": "deep",
        "recovery": {"last_status": "ok", "needs_repair": 0, "quarantine_count": 1},
        "release": {"commit": "unknown", "version": "1.8.2"},
        "schema": "awa-integrity-status/v1",
        "worktrees": {"active": 12, "checked": True, "conflicts": 1,
                      "discovered_linked": 89, "managed": 3,
                      "problems": 89, "unleased": 85},
    }
    MARKER = (
        '@@AWA_INTEGRITY_HOST_SWEEP@@ {"checked_at":"2026-10-21T00:40:40Z",'
        '"evaluator_exit":1,"expected_evaluator_exit":true,"scheduler_exit":0,'
        '"schema":"dev-awa-integrity-host-sweep/v1","severity":"degraded"}'
    )

    def _run_handler_with_sweep_text(self, sweep_text):
        fake_home = self.fx.base / "fake-local-jobs-home"
        lib = fake_home / "lib"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "handler_lib.sh").write_text(
            textwrap.dedent(
                """\
                set -euo pipefail
                hl_die() { printf '%s\\n' "$*" >&2; exit 2; }
                handler_main() { shift; handler_do_run "$@"; }
                """
            ),
            encoding="utf-8",
        )
        body = self.fx.base / "sweep-body.txt"
        body.write_text(sweep_text, encoding="utf-8")
        stub = self.fx.base / "stub-wrapper.sh"
        stub.write_text(
            "#!/usr/bin/env bash\ncat '" + str(body) + "'\nexit 0\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        result = self.fx.run(
            [HANDLER, "run", "--id", "awa-integrity"],
            updates={"LOCAL_JOBS_HOME": fake_home, "DEV_AWA_INTEGRITY_WRAPPER": stub},
        )
        runlog = [l for l in result.stdout.splitlines() if l.startswith("@@RUNLOG@@ ")]
        self.assertEqual(len(runlog), 1, result.stdout + result.stderr)
        return json.loads(runlog[0].split(" ", 1)[1]), result

    def test_degraded_warning_lists_real_reasons_not_raw_json(self):
        pretty = json.dumps(self.REAL_SWEEP, indent=2, sort_keys=True)
        payload, result = self._run_handler_with_sweep_text(pretty + "\n" + self.MARKER + "\n")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["fields"]["severity"], "degraded")
        warning = payload["fields"]["warning"]
        self.assertEqual(
            warning,
            "degraded: 85 of 89 linked worktrees unleased; 1 conflict; "
            "native entry evidence stale",
        )
        for fragment in ("{", "}", "[", '"', "alert", "attempted"):
            self.assertNotIn(fragment, warning)
        self.assertIn("awa-integrity: WARNING " + warning, result.stdout)

    def test_degraded_warning_survives_leading_noise_and_hostile_evidence(self):
        doc = json.loads(json.dumps(self.REAL_SWEEP))
        doc["invariants"][1]["evidence"] = 'stale {"x": [1]} entry'
        pretty = json.dumps(doc, indent=2, sort_keys=True)
        payload, _ = self._run_handler_with_sweep_text(
            "note: starting sweep\n" + pretty + "\n" + self.MARKER + "\n"
        )
        warning = payload["fields"]["warning"]
        self.assertTrue(warning.startswith("degraded: 85 of 89"), warning)
        for fragment in ("{", "}", "[", "]", '"'):
            self.assertNotIn(fragment, warning)

    def test_degraded_warning_falls_back_when_json_unusable(self):
        pretty = json.dumps(self.REAL_SWEEP, indent=2, sort_keys=True)
        no_reasons = dict(self.REAL_SWEEP, worktrees={}, invariants=[])
        fallback = "degraded (reasons unavailable; see run log)"
        cases = {
            "truncated": pretty[: len(pretty) // 2] + "\n" + self.MARKER + "\n",
            "garbage": "{ not json at all\n" + self.MARKER + "\n",
            "no-json": self.MARKER + "\n",
            "no-reasons": json.dumps(no_reasons, indent=2) + "\n" + self.MARKER + "\n",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                payload, _ = self._run_handler_with_sweep_text(text)
                self.assertEqual(payload["status"], "success")
                self.assertEqual(payload["fields"]["severity"], "degraded")
                self.assertEqual(payload["fields"]["warning"], fallback)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrityHostTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("awa-integrity-host: OK")
PY
