#!/usr/bin/env bash
# Hermetic E-06 host-overlay lifecycle tests. Never reads or writes the operator's real HOME.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

python3 - "$ROOT" <<'PY'
import copy
import hashlib
import json
import os
import shutil
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
PREDECESSOR_PIN = "60ae49b4b118211d4702d9297e3f479222f45cc0"
ROLE_IDS = [
    "worktree.session-context",
    "worktree.file-observer",
    "recovery.maintenance",
    "finish.prompt-recall",
    "worktree.shell-guard-composite",
    "worktree.stop-observer",
    "worktree.session-handoff",
]


def contract_document():
    # Synthetic interface fixture, deliberately not the released AWA contract bytes.
    return {
        "fixture": "dev-e06-host-overlay",
        "hook_ownership": {
            "schema": "awa-hook-owner/v1",
            "modes": ["direct", "external"],
            "default_mode": "direct",
            "selection_env": "AWA_HOOK_OWNER",
            "selection_schema": "awa-hook-owner-selection/v1",
            "external_real_hook_file_writes": False,
            "roles": [
                {
                    "id": "worktree.session-context",
                    "event": "sessionStart",
                    "direct_command_role": "kernel/hooks/worktree-session.sh",
                    "external_command_path_class": "host-policy-delegator",
                    "entry": {"type": "command", "timeout": 5, "failClosed": False},
                },
                {
                    "id": "worktree.shell-guard",
                    "event": "beforeShellExecution",
                    "direct_command_role": "kernel/hooks/worktree-guard.sh",
                    "external_command_path_class": "host-policy-delegator",
                    "entry": {"type": "command", "timeout": 20, "failClosed": False},
                },
                {
                    "id": "worktree.file-observer",
                    "event": "afterFileEdit",
                    "direct_command_role": "kernel/hooks/worktree-guard.sh",
                    "external_command_path_class": "host-policy-delegator",
                    "entry": {"type": "command", "timeout": 20},
                },
                {
                    "id": "recovery.maintenance",
                    "event": "sessionStart",
                    "direct_command_role": "kernel/hooks/awa-recovery-maintenance.sh",
                    "external_command_path_class": "installed-awa",
                    "entry": {"type": "command", "timeout": 5, "failClosed": False},
                },
                {
                    "id": "finish.prompt-recall",
                    "event": "beforeSubmitPrompt",
                    "direct_command_role": "kernel/hooks/before-submit-prompt.sh",
                    "external_command_path_class": "installed-awa",
                    "entry": {
                        "type": "command",
                        "matcher": "UserPromptSubmit",
                        "timeout": 20,
                        "failClosed": False,
                    },
                },
            ],
        },
    }


BUILDER = r'''
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

mode = os.environ.get("FAKE_GCB_MODE", "ok")
if mode == "missing-runtime":
    raise SystemExit(0)

data_home = Path(os.environ["XDG_DATA_HOME"])
config_home = Path(os.environ["XDG_CONFIG_HOME"])
runtime = data_home / "awa" / "current"
pointer_path = data_home / "awa" / "release-pointer.json"
gcb_path = data_home / "awa" / "gcb-pointer.json"
selection_path = config_home / "awa" / "hook-owner.json"
shelf = Path(os.environ["FAKE_SHELF_DIR"])
contract_source = shelf / "fixture-contract.json"
contract_bytes = contract_source.read_bytes()
contract_digest = hashlib.sha256(contract_bytes).hexdigest()
v2_bytes = (shelf / "fixture-hook-owner-v2.json").read_bytes()
schedule_bytes = (shelf / "fixture-integrity-schedule.json").read_bytes()

for rel in (
    "kernel/hooks/worktree-session.sh",
    "kernel/hooks/worktree-guard.sh",
    "kernel/hooks/awa-recovery-maintenance.sh",
    "kernel/hooks/before-submit-prompt.sh",
    "kernel/hooks/worktree-guard-with-integrity.sh",
    "kernel/hooks/awa-integrity-observer.sh",
    "kernel/hooks/awa-session-handoff.sh",
    "kernel/bin/awa-integrity-sweep.sh",
    "kernel/bin/dev-worktree.sh",
    "bin/awa-engine.sh",
):
    path = runtime / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)

policy = runtime / "kernel" / "policy" / "default-worktree-policy.yml"
policy.parent.mkdir(parents=True, exist_ok=True)
policy.write_text("version: 1\ngoverned_roots: []\n", encoding="utf-8")
resolver = runtime / "kernel" / "lib" / "awa_policy.py"
resolver.parent.mkdir(parents=True, exist_ok=True)
resolver.write_text(
    "#!/usr/bin/env python3\nimport sys\n"
    "print('exclude fixture') if 'classify' in sys.argv else print('{}')\n",
    encoding="utf-8",
)
resolver.chmod(0o755)
contract_path = runtime / "contracts" / "awa-contract.v1.json"
contract_path.parent.mkdir(parents=True, exist_ok=True)
contract_path.write_bytes(contract_bytes)
(runtime / "contracts" / "awa-hook-owner.v2.json").write_bytes(v2_bytes)
(runtime / "contracts" / "awa-integrity-schedule.v1.json").write_bytes(schedule_bytes)
if mode == "v2-contract-mismatch":
    (runtime / "contracts" / "awa-hook-owner.v2.json").write_bytes(v2_bytes + b" ")
if mode == "schedule-mismatch":
    (runtime / "contracts" / "awa-integrity-schedule.v1.json").write_bytes(
        schedule_bytes + b" "
    )

slack = runtime / "engine" / "integrity_slack.py"
slack.parent.mkdir(parents=True, exist_ok=True)
(slack.parent / "__init__.py").write_text("", encoding="utf-8")
(slack.parent / "paths.py").write_text("", encoding="utf-8")
slack.write_text(
    "import json, os\n"
    "from pathlib import Path\n"
    "from . import paths\n"
    "KEYCHAIN_SERVICE = __name__\n"
    "KEYCHAIN_ACCOUNT = str(Path(__file__).stat().st_ino)\n"
    "KEYCHAIN_NOT_FOUND_EXIT = 44\n"
    "def config_path():\n"
    "    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))"
    " / 'awa' / 'integrity-slack.json'\n"
    "def load_configured_user_id():\n"
    "    try:\n"
    "        value=json.loads(config_path().read_text())\n"
    "    except Exception:\n"
    "        return None\n"
    "    return 'configured' if value == {'fixture': 'configured'} else None\n",
    encoding="utf-8",
)

selected = "direct" if mode == "nonexternal" else "external"
selection_path.parent.mkdir(parents=True, exist_ok=True)
selection_path.write_text(
    json.dumps(
        {
            "schema": "awa-hook-owner-selection/v1",
            "contract": "awa-hook-owner/v1",
            "mode": selected,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
pointer = {
    "schema": "awa-release-pointer/v1",
    "version": "0.0.0" if mode == "wrong-version" else "1.8.2",
    "source": str(data_home / "awa" / "checkout"),
    "commit": os.environ["FAKE_PIN"],
    "runtime": str(runtime / "wrong") if mode == "wrong-runtime" else str(runtime),
    "policy": str(policy),
    "hook_owner_contract": "awa-hook-owner/v1",
    "hook_owner_mode": selected,
    "hook_owner_contract_sha256": (
        "0" * 64 if mode == "contract-mismatch" else contract_digest
    ),
    "installed_at": "2026-08-18T00:00:00Z",
}
pointer_path.parent.mkdir(parents=True, exist_ok=True)
if mode == "malformed-pointer":
    pointer_path.write_text("{", encoding="utf-8")
else:
    pointer_path.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")

checkout = data_home / "awa" / "checkout"
checkout.mkdir(parents=True, exist_ok=True)
gcb = {
    "schema": "awa-gcb-pointer/v1",
    "id": "awa",
    "kind": "global-capability-binding",
    "source": "github.com/KleinPerkins/awa",
    "ref": "0" * 40 if mode == "wrong-ref" else os.environ["FAKE_PIN"],
    "clone_url": "fixture://awa",
    "checkout": str(checkout),
    "shelf": str(shelf),
    "release_pointer": str(pointer_path),
}
gcb_path.write_text(json.dumps(gcb, indent=2, sort_keys=True) + "\n", encoding="utf-8")
'''


FAKE_SHELF = r'''#!/usr/bin/env bash
set -euo pipefail
verb="${1:-install}"
printf '%s\t%s\t%s\t%s\n' "$verb" "${AWA_HOOK_OWNER-unset}" \
  "${AWA_POLICY-unset}" "${AWA_GOVERNED_ROOT-unset}" >> "$FAKE_GCB_LOG"
if [ "$verb" = "install" ] || [ "$verb" = "--repair" ] || [ -z "$verb" ]; then
  if [ "${AWA_HOOK_OWNER-unset}" != "external" ]; then
    printf '%s\n' "direct-owner-hook-access" >> "$FAKE_HOOK_TOUCH_LOG"
    if [ -f "$AWA_HOOKS_JSON" ]; then
      printf '\n' >> "$AWA_HOOKS_JSON"
    fi
  fi
fi
case "$verb" in
  --check)
    [ "${FAKE_GCB_MODE:-ok}" != "check-fail" ] || exit 31
    exit 0
    ;;
  --doctor)
    [ "${FAKE_GCB_MODE:-ok}" = "ok" ] || exit 32
    [ -f "$XDG_CONFIG_HOME/awa/hook-owner.json" ]
    [ -f "$XDG_DATA_HOME/awa/release-pointer.json" ]
    python3 - "$XDG_CONFIG_HOME/awa/hook-owner.json" \
      "$XDG_DATA_HOME/awa/release-pointer.json" "${AWA_HOOK_OWNER-unset}" <<'OWNERPY'
import json, sys
owner = json.load(open(sys.argv[1], encoding="utf-8"))
pointer = json.load(open(sys.argv[2], encoding="utf-8"))
expected = sys.argv[3]
if owner.get("mode") != expected or pointer.get("hook_owner_mode") != expected:
    raise SystemExit(1)
OWNERPY
    exit 0
    ;;
  install|--repair|"")
    [ "${FAKE_GCB_MODE:-ok}" != "fail" ] || exit 33
    export FAKE_SHELF_DIR
    FAKE_SHELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
    python3 "$FAKE_GCB_BUILDER"
    ;;
  *)
    exit 34
    ;;
esac
'''

FAKE_JOB_INSTALLER = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${1:-}" >> "$FAKE_JOB_LOG"
[ "${FAKE_JOB_FAIL_ON:-}" != "${1:-}" ] || exit 51
exit 0
'''

FAKE_SECURITY = r'''#!/usr/bin/env bash
set -euo pipefail
case "${FAKE_SECURITY_MODE:-absent}" in
  present) exit 0 ;;
  absent) exit 44 ;;
  *) exit 52 ;;
esac
'''

FAKE_PS = r'''#!/usr/bin/env bash
set -euo pipefail
pid="${FAKE_WORKER_PID:-}"
[ -n "$pid" ] || exit 0
counter="$FAKE_PS_COUNTER"
count=0
[ ! -f "$counter" ] || count="$(<"$counter")"
printf '%s\n' "$((count + 1))" > "$counter"
if [ "$count" -eq 0 ] && kill -0 "$pid" 2>/dev/null; then
  printf '%s %s %s\n' "$pid" "1" "$FAKE_WORKER_COMMAND"
fi
'''


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dev-e06-overlay-")
        self.base = Path(self.tmp.name).resolve()
        self.dev = self.base / "dev"
        self.home = self.base / "home"
        self.data = self.base / "xdg-data"
        self.config = self.base / "xdg-config"
        self.state = self.base / "xdg-state"
        self.hooks = self.home / ".cursor" / "hooks.json"
        self.log = self.base / "gcb.log"
        self.job_log = self.base / "job.log"
        self.builder = self.base / "fixture-builder.py"
        self._copy_dev_surface()
        self._write_fake_gcb()
        self.env = {
            # Caller overrides describe its installed runtime, not this fixture.
            # Inheriting DEV_AWA_GCB_DIR can invoke the real Skills installer.
            **{key: value for key, value in os.environ.items()
               if not key.startswith(("AWA_", "DEV_AWA_", "GIT_", "LOCAL_JOBS_"))
               and key != "DEV_SESSION_ID"},
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.state),
            "AWA_HOME": str(self.runtime),
            "AWA_HOOKS_JSON": str(self.hooks),
            "FAKE_GCB_LOG": str(self.log),
            "FAKE_HOOK_TOUCH_LOG": str(self.base / "hook-touch.log"),
            "FAKE_NON_AWA_ENV_LOG": str(self.base / "non-awa-env.log"),
            "FAKE_GCB_BUILDER": str(self.builder),
            "FAKE_PIN": PIN,
            "FAKE_GCB_MODE": "ok",
            "DEV_AWA_JOB_INSTALLER": str(self.dev / "_ops" / "bin" / "fake-job.sh"),
            "FAKE_JOB_LOG": str(self.job_log),
            "DEV_AWA_SECURITY_BIN": str(self.base / "security"),
            "FAKE_SECURITY_MODE": "absent",
        }

    @property
    def runtime(self):
        return self.data / "awa" / "current"

    @property
    def overlay(self):
        return self.dev / "_ops" / "bin" / "install-dev-awa-overlay.sh"

    @property
    def bootstrap(self):
        return self.dev / "bootstrap.sh"

    @property
    def hook_installer(self):
        return self.dev / "_ops" / "bin" / "install-worktree-hooks.sh"

    @property
    def rollback_record(self):
        return self.state / "awa" / "dev-host-overlay" / "hook-preimage.json"

    def rollback_backup(self):
        record = json.loads(self.rollback_record.read_text(encoding="utf-8"))
        return self.hooks.parent / record["preimage"]["backup_name"]

    def close(self):
        self.tmp.cleanup()

    def _copy(self, rel):
        source = ROOT / rel
        target = self.dev / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    def _copy_dev_surface(self):
        for rel in (
            "bootstrap.sh",
            "capabilities/bootstrap.sh",
            "_ops/interoperability/original_sources.py",
            "_ops/interoperability/inventory.py",
            "_ops/bin/install-dev-awa-overlay.sh",
            "_ops/bin/install-worktree-hooks.sh",
            "_ops/bin/check-awa-release-binding.py",
            "_ops/bin/install-awa-integrity-job.sh",
            "_ops/bin/dev-worktree.sh",
            "_ops/local-jobs/awa-integrity.sh",
            "_ops/cursor-hooks/worktree-guard.sh",
            "_ops/cursor-hooks/worktree-session.sh",
            "_ops/cursor-hooks/worktree-guard-with-integrity.sh",
            "_ops/cursor-hooks/awa-integrity-observer.sh",
            "_ops/cursor-hooks/awa-session-handoff.sh",
            "_ops/policy/worktree-policy.yml",
            "_ops/policy/worktree-modes.yml",
            "_ops/checks/awa-contract-freeze.sh",
            "_ops/tests/fixtures/awa-v1.8.1/awa-hook-owner.v2.json",
            "_ops/tests/fixtures/awa-v1.8.1/awa-integrity-schedule.v1.json",
        ):
            self._copy(rel)
        dashboard = self.dev / "_ops" / "bin" / "install-awa-dashboard.sh"
        dashboard.parent.mkdir(parents=True, exist_ok=True)
        dashboard.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        dashboard.chmod(0o755)
        fake_job = self.dev / "_ops" / "bin" / "fake-job.sh"
        fake_job.write_text(FAKE_JOB_INSTALLER, encoding="utf-8")
        fake_job.chmod(0o755)
        security = self.base / "security"
        security.write_text(FAKE_SECURITY, encoding="utf-8")
        security.chmod(0o755)
        fake_ps = self.base / "ps"
        fake_ps.write_text(FAKE_PS, encoding="utf-8")
        fake_ps.chmod(0o755)

    def _write_fake_gcb(self):
        shelf = self.dev / "capabilities" / "skills" / "global" / "tools" / "awa"
        shelf.mkdir(parents=True, exist_ok=True)
        (shelf / "meta.yml").write_text(
            "schema: kp-capability/v1\n"
            "id: awa\nkind: tool\nflavor: 2\nscope: global\n"
            'provenance_source: "github.com/KleinPerkins/awa"\n'
            f'provenance_ref: "{PIN}"\n',
            encoding="utf-8",
        )
        (shelf / "fixture-contract.json").write_text(
            json.dumps(contract_document(), indent=2) + "\n", encoding="utf-8"
        )
        shutil.copy2(
            ROOT / "_ops/tests/fixtures/awa-v1.8.1/awa-hook-owner.v2.json",
            shelf / "fixture-hook-owner-v2.json",
        )
        shutil.copy2(
            ROOT / "_ops/tests/fixtures/awa-v1.8.1/awa-integrity-schedule.v1.json",
            shelf / "fixture-integrity-schedule.json",
        )
        install = shelf / "install.sh"
        install.write_text(FAKE_SHELF, encoding="utf-8")
        install.chmod(0o755)
        skills_bootstrap = self.dev / "capabilities" / "skills" / "bootstrap.sh"
        skills_bootstrap.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            '[ "${1:-}" = "--reconcile" ]\n'
            'bash "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)'
            '/global/tools/awa/install.sh"\n'
            'if [ "${FAKE_SOURCE_CHANGE_AFTER_AWA:-0}" = "1" ]; then\n'
            '  printf "\\n# changed after first use\\n" >> "$(dirname "${BASH_SOURCE[0]:-$0}")/global/tools/awa/install.sh"\n'
            'fi\n'
            'rc="${FAKE_CAPABILITIES_RC_AFTER_AWA:-0}"\n'
            '[ "$rc" -eq 0 ] || exit "$rc"\n',
            encoding="utf-8",
        )
        skills_bootstrap.chmod(0o755)
        # This lane tests overlay ordering, not production source provenance.
        # Use a real disposable owner repo and replace only its copied helper's
        # original object anchor with the synthetic fixture commit. The separate
        # bootstrap continuity tests retain production anchors and rejection cases.
        skills = skills_bootstrap.parent
        git_env = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
        git_env["HOME"] = str(self.home)
        for args in (("init", "-q", "-b", "main"),
                     ("remote", "add", "origin", "git@github.com:KleinPerkins/skills.git"),
                     ("add", "."),
                     ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                      "commit", "-qm", "synthetic overlay source")):
            subprocess.run(["git", "-C", str(skills), *args], env=git_env,
                           check=True, capture_output=True)
        anchor = subprocess.check_output(["git", "-C", str(skills), "rev-parse", "HEAD"],
                                         env=git_env, text=True).strip()
        resolver = self.dev / "_ops/interoperability/original_sources.py"
        resolver.write_text(resolver.read_text().replace(
            "bc58eb77f442307ab4f124ab5aeec3f99571cb21", anchor))
        for rel in (
            "_ops/bin/install-agent-rules.sh",
            "_ops/bin/install-mcp.sh",
            "_ops/bin/install-skills.sh",
            "_ops/checks/verify-operating-model.sh",
            "capabilities/mcp-bootstrap.sh",
        ):
            stub = self.dev / rel
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s\\n' \"${AWA_HOOK_OWNER-unset}\""
                " >> \"$FAKE_NON_AWA_ENV_LOG\"\n"
                f'[ "${{FAKE_FAIL_NON_AWA_MATCH:-}}" != "{rel}" ] || exit 41\n',
                encoding="utf-8",
            )
            stub.chmod(0o755)
        (self.dev / "personal" / "ecosystem-orchestrator" / ".git").mkdir(
            parents=True
        )
        self.builder.write_text(BUILDER, encoding="utf-8")
        self.builder.chmod(0o755)

    def write_hooks(self, document=None, raw=None, mode=0o640):
        self.hooks.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            self.hooks.write_bytes(raw)
        else:
            self.hooks.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        self.hooks.chmod(mode)

    def read_hooks(self):
        return json.loads(self.hooks.read_text(encoding="utf-8"))

    def backups(self):
        return sorted(self.hooks.parent.glob("hooks.json.bak-*"))

    def snapshot(self):
        if not self.hooks.exists():
            return (False, None, None, None, tuple(self.backups()))
        info = self.hooks.stat()
        return (
            True,
            self.hooks.read_bytes(),
            stat.S_IMODE(info.st_mode),
            (info.st_ino, info.st_mtime_ns),
            tuple(path.name for path in self.backups()),
        )

    def run(self, argv, updates=None):
        env = dict(self.env)
        if updates:
            env.update({key: str(value) for key, value in updates.items()})
        return subprocess.run(
            [str(item) for item in argv],
            cwd=self.dev,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def popen(self, argv, updates=None):
        env = dict(self.env)
        if updates:
            env.update({key: str(value) for key, value in updates.items()})
        return subprocess.Popen(
            [str(item) for item in argv],
            cwd=self.dev,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_overlay(self, *args, updates=None):
        return self.run([self.overlay, *args], updates=updates)

    def run_bootstrap(self, updates=None):
        return self.run([self.bootstrap], updates=updates)

    def run_hooks(self, *args, updates=None):
        return self.run([self.hook_installer, *args], updates=updates)

    def seed_runtime(self, mode="ok"):
        result = self.run(
            [
                self.dev
                / "capabilities"
                / "skills"
                / "global"
                / "tools"
                / "awa"
                / "install.sh"
            ],
            updates={"AWA_HOOK_OWNER": "external", "FAKE_GCB_MODE": mode},
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)

    def intended(self):
        dev = self.dev.resolve()
        return {
            "sessionStart": [
                {
                    "command": str(
                        dev / "_ops" / "cursor-hooks" / "worktree-session.sh"
                    ),
                    "type": "command",
                    "timeout": 5,
                    "failClosed": False,
                },
                {
                    "command": str(
                        self.runtime
                        / "kernel"
                        / "hooks"
                        / "awa-recovery-maintenance.sh"
                    ),
                    "type": "command",
                    "timeout": 5,
                    "failClosed": False,
                },
                {
                    "command": str(
                        dev / "_ops" / "cursor-hooks" / "awa-session-handoff.sh"
                    ),
                    "type": "command",
                    "timeout": 5,
                    "failClosed": False,
                },
            ],
            "beforeShellExecution": [
                {
                    "command": str(
                        dev
                        / "_ops"
                        / "cursor-hooks"
                        / "worktree-guard-with-integrity.sh"
                    ),
                    "type": "command",
                    "timeout": 20,
                    "failClosed": False,
                }
            ],
            "afterFileEdit": [
                {
                    "command": str(
                        dev / "_ops" / "cursor-hooks" / "worktree-guard.sh"
                    ),
                    "type": "command",
                    "timeout": 20,
                }
            ],
            "beforeSubmitPrompt": [
                {
                    "command": str(
                        self.runtime / "kernel" / "hooks" / "before-submit-prompt.sh"
                    ),
                    "type": "command",
                    "matcher": "UserPromptSubmit",
                    "timeout": 20,
                    "failClosed": False,
                }
            ],
            "stop": [
                {
                    "command": str(
                        dev / "_ops" / "cursor-hooks" / "awa-integrity-observer.sh"
                    ),
                    "type": "command",
                    "timeout": 5,
                    "failClosed": False,
                }
            ],
        }

    def assert_matrix(self, testcase):
        result = self.run_hooks("--check")
        testcase.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        hooks = self.read_hooks()["hooks"]
        intended = self.intended()
        for event, entries in intended.items():
            for entry in entries:
                testcase.assertEqual(
                    [candidate for candidate in hooks[event] if candidate == entry],
                    [entry],
                )


class HostOverlayTest(unittest.TestCase):
    def test_parent_runtime_overrides_cannot_escape_disposable_fixture(self):
        names = ["AWA_GOVERNED_ROOT", "AWA_ENGINE_HOME", "DEV_AWA_GCB_DIR",
                 "DEV_AWA_SKILLS_ROOT", "DEV_AWA_RELEASE_POINTER", "DEV_AWA_GCB_POINTER",
                 "DEV_AWA_OWNER_SELECTION", "GIT_INDEX_FILE", "DEV_SESSION_ID",
                 "LOCAL_JOBS_STATE"]
        poison = {name: str(self.fx.base / "outside-fixture") for name in names}
        with patch.dict(os.environ, poison):
            fixture = Fixture()
        self.addCleanup(fixture.close)
        for name in names:
            self.assertNotIn(name, fixture.env)
        self.assertEqual(fixture.env["AWA_HOME"], str(fixture.runtime))
        result = fixture.run_overlay()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(fixture.log.is_file())

    def setUp(self):
        self.fx = Fixture()

    def tearDown(self):
        self.fx.close()

    def assert_unchanged(self, before):
        self.assertEqual(self.fx.snapshot(), before)

    def legacy_five_preimage(self, unrelated=None):
        direct = self.fx.runtime / "kernel" / "hooks"
        session_rows = []
        if unrelated is not None:
            session_rows.append(unrelated)
        session_rows.extend(
            [
                {"command": str(direct / "worktree-session.sh")},
                {"command": str(direct / "awa-recovery-maintenance.sh")},
            ]
        )
        return {
            "version": 1,
            "hooks": {
                "sessionStart": session_rows,
                "beforeShellExecution": [
                    {"command": str(direct / "worktree-guard.sh")}
                ],
                "afterFileEdit": [
                    {"command": str(direct / "worktree-guard.sh")}
                ],
                "beforeSubmitPrompt": [
                    {"command": str(direct / "before-submit-prompt.sh")}
                ],
            },
        }

    def test_missing_source_entrypoint_never_executes_overlay(self):
        (self.fx.dev / "capabilities/bootstrap.sh").unlink()
        result = self.fx.run_bootstrap()
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertFalse(self.fx.log.exists())
        self.assertFalse(self.fx.hooks.exists())

    def test_changed_source_after_first_use_is_not_executed_as_repair(self):
        result = self.fx.run_bootstrap(updates={"FAKE_SOURCE_CHANGE_AFTER_AWA": "1"})
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertEqual(len(self.fx.log.read_text().splitlines()), 1)
        self.assertFalse(self.fx.hooks.exists())
        script = self.fx.dev / "capabilities/skills/global/tools/awa/install.sh"
        before = script.read_bytes()
        self.assertIn(b"changed after first use", before)
        result = self.fx.run_bootstrap()
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertEqual(script.read_bytes(), before)
        self.assertEqual(len(self.fx.log.read_text().splitlines()), 1)

    def test_source_override_is_checked_before_any_capability_executes(self):
        wrong = self.fx.base / "untrusted-skills/global/tools/awa"
        wrong.mkdir(parents=True)
        marker = self.fx.base / "unverified-source-executed"
        script = wrong / "install.sh"
        script.write_text("touch " + str(marker) + "\n")
        before = script.read_bytes()
        result = self.fx.run_bootstrap(updates={"DEV_AWA_SKILLS_ROOT": str(wrong.parents[2])})
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertEqual(script.read_bytes(), before)
        self.assertFalse(marker.exists())
        self.assertFalse(self.fx.log.exists())
        self.assertFalse(self.fx.hooks.exists())

    def test_source_refusal_stops_before_rejected_gcb_or_later_writers(self):
        script = self.fx.dev / "capabilities/skills/global/tools/awa/install.sh"
        script.write_text(script.read_text() + "\n# unreviewed source change\n")
        before = script.read_bytes()
        for attempt in range(2):
            result = self.fx.run_bootstrap()
            self.assertEqual(result.returncode, 78, (attempt, result.stdout, result.stderr))
            self.assertIn("source checkout refused before use", result.stderr)
            self.assertEqual(script.read_bytes(), before)
            self.assertFalse(self.fx.log.exists())
            self.assertFalse(self.fx.hooks.exists())
            self.assertFalse((self.fx.base / "non-awa-env.log").exists())

    def test_root_bootstrap_selects_external_before_skills_reconcile(self):
        unrelated = {"command": "/opt/unrelated/session-hook", "timeout": 9}
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [unrelated]}}, mode=0o640
        )
        first = self.fx.run_bootstrap()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        rows = self.fx.log.read_text(encoding="utf-8").splitlines()
        installs = [row.split("\t") for row in rows if row.split("\t")[0] == "install"]
        self.assertGreaterEqual(len(installs), 2)
        self.assertEqual(installs[0][1], "external")
        self.assertEqual(
            installs[0][2],
            str(self.fx.dev / "_ops" / "policy" / "worktree-policy.yml"),
        )
        self.assertEqual(installs[0][3], str(self.fx.dev))
        self.assertFalse((self.fx.base / "hook-touch.log").exists())
        self.assertEqual(
            set(
                (self.fx.base / "non-awa-env.log")
                .read_text(encoding="utf-8")
                .splitlines()
            ),
            {"unset"},
        )
        self.fx.assert_matrix(self)
        self.assertEqual(self.fx.read_hooks()["hooks"]["sessionStart"][0], unrelated)
        first_bytes = self.fx.hooks.read_bytes()
        first_backups = [path.name for path in self.fx.backups()]
        self.assertEqual(len(first_backups), 1)

        second = self.fx.run_bootstrap()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.fx.hooks.read_bytes(), first_bytes)
        self.assertEqual([path.name for path in self.fx.backups()], first_backups)
        self.assertFalse((self.fx.base / "hook-touch.log").exists())

    def test_offline_bootstrap_converges_validated_external_runtime(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        result = self.fx.run_bootstrap(updates={"ECO_BOOTSTRAP_OFFLINE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.fx.base / "hook-touch.log").exists())
        self.fx.assert_matrix(self)

    def test_capabilities_failure_still_resolves_overlay_before_exit(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        result = self.fx.run_bootstrap(
            updates={"FAKE_CAPABILITIES_RC_AFTER_AWA": "37"}
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.fx.assert_matrix(self)
        self.assertFalse((self.fx.base / "non-awa-env.log").exists())
        self.assertFalse((self.fx.base / "hook-touch.log").exists())

    def test_child_status_78_still_repairs_after_source_execution(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        result = self.fx.run_bootstrap(updates={"FAKE_CAPABILITIES_RC_AFTER_AWA": "78"})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.fx.assert_matrix(self)
        self.assertFalse((self.fx.base / "non-awa-env.log").exists())
        self.assertFalse((self.fx.base / "hook-touch.log").exists())

    def test_overlay_failure_aborts_before_non_awa_and_preserves_preimage(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        before = self.fx.snapshot()
        result = self.fx.run_bootstrap(updates={"FAKE_GCB_MODE": "check-fail"})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_unchanged(before)
        self.assertTrue((self.fx.runtime / "kernel" / "bin" / "dev-worktree.sh").is_file())
        owner = json.loads(
            (self.fx.config / "awa" / "hook-owner.json").read_text(encoding="utf-8")
        )
        self.assertEqual(owner["mode"], "external")
        self.assertFalse((self.fx.base / "non-awa-env.log").exists())
        self.assertFalse((self.fx.base / "hook-touch.log").exists())

    def test_later_failure_observes_complete_matrix_and_original_environment(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        result = self.fx.run_bootstrap(
            updates={
                "AWA_HOOK_OWNER": "caller-owner",
                "AWA_POLICY": "caller-policy",
                "AWA_GOVERNED_ROOT": "caller-root",
                "FAKE_FAIL_NON_AWA_MATCH": "_ops/bin/install-agent-rules.sh",
            }
        )
        self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
        self.fx.assert_matrix(self)
        rows = self.fx.log.read_text(encoding="utf-8").splitlines()
        installs = [row.split("\t") for row in rows if row.split("\t")[0] == "install"]
        self.assertEqual(installs[0][1], "external")
        self.assertEqual(
            installs[0][2],
            str(self.fx.dev / "_ops" / "policy" / "worktree-policy.yml"),
        )
        self.assertEqual(installs[0][3], str(self.fx.dev))
        self.assertEqual(
            (self.fx.base / "non-awa-env.log").read_text(encoding="utf-8"),
            "caller-owner\n",
        )
        self.assertFalse((self.fx.base / "hook-touch.log").exists())

    def test_overlay_external_lifecycle_and_idempotence(self):
        unrelated = {"command": "/opt/unrelated/session-hook", "timeout": 9}
        unrelated_stop = {"command": "/opt/unrelated/stop-hook", "timeout": 7}
        self.fx.write_hooks(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [unrelated],
                    "stop": [unrelated_stop],
                },
            },
            mode=0o640,
        )
        first = self.fx.run_overlay()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        rows = self.fx.log.read_text(encoding="utf-8").splitlines()
        installs = [row for row in rows if row.split("\t", 1)[0] in ("install", "")]
        self.assertTrue(installs)
        self.assertEqual(installs[-1].split("\t")[1], "external")
        self.assertIn(str(self.fx.dev / "_ops" / "policy" / "worktree-policy.yml"), installs[-1])
        self.assertIn(str(self.fx.dev), installs[-1])
        self.fx.assert_matrix(self)
        self.assertEqual(self.fx.read_hooks()["hooks"]["sessionStart"][0], unrelated)
        self.assertEqual(self.fx.read_hooks()["hooks"]["stop"][0], unrelated_stop)
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), 0o640)
        first_bytes = self.fx.hooks.read_bytes()
        first_backups = [path.name for path in self.fx.backups()]
        self.assertEqual(len(first_backups), 1)

        for args in (("--doctor",), (), ("--repair",), ("--doctor",)):
            result = self.fx.run_overlay(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.fx.hooks.read_bytes(), first_bytes)
        self.assertEqual([path.name for path in self.fx.backups()], first_backups)

    def test_slack_doctor_distinguishes_opt_out_configured_and_misconfigured(self):
        self.fx.write_hooks({"version": 1, "hooks": {}})
        installed = self.fx.run_overlay()
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)

        opted_out = self.fx.run_overlay("--doctor")
        self.assertEqual(opted_out.returncode, 0, opted_out.stdout + opted_out.stderr)
        self.assertIn("Slack alerts: opted out (default)", opted_out.stdout)
        self.assertFalse(any(
            path.name == "__pycache__" or path.suffix == ".pyc"
            for path in self.fx.runtime.rglob("*")
        ))

        config = self.fx.config / "awa" / "integrity-slack.json"
        config.write_text('{"fixture":"configured"}\n', encoding="utf-8")
        config.chmod(0o600)
        configured = self.fx.run_overlay(
            "--doctor", updates={"FAKE_SECURITY_MODE": "present"}
        )
        self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
        self.assertIn("Slack alerts: configured", configured.stdout)

        config.unlink()
        mismatched = self.fx.run_overlay(
            "--doctor", updates={"FAKE_SECURITY_MODE": "present"}
        )
        self.assertNotEqual(mismatched.returncode, 0)
        self.assertIn("Slack alerts: misconfigured", mismatched.stdout)

    def test_slack_doctor_reports_unsafe_config_and_probe_failure(self):
        self.fx.write_hooks({"version": 1, "hooks": {}})
        self.assertEqual(self.fx.run_overlay().returncode, 0)
        config = self.fx.config / "awa" / "integrity-slack.json"
        config.write_text("{", encoding="utf-8")
        config.chmod(0o644)
        unsafe = self.fx.run_overlay("--doctor")
        self.assertNotEqual(unsafe.returncode, 0)
        self.assertIn("Slack alerts: misconfigured", unsafe.stdout)
        config.unlink()
        failed = self.fx.run_overlay(
            "--doctor", updates={"FAKE_SECURITY_MODE": "failed"}
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Slack alerts: failed", failed.stdout)

    def test_binding_failures_never_touch_hook_transaction(self):
        for mode in (
            "fail",
            "missing-runtime",
            "malformed-pointer",
            "contract-mismatch",
            "nonexternal",
            "wrong-version",
            "wrong-ref",
            "wrong-runtime",
            "v2-contract-mismatch",
            "schedule-mismatch",
        ):
            with self.subTest(mode=mode):
                fx = Fixture()
                try:
                    fx.write_hooks(
                        {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
                    )
                    before = fx.snapshot()
                    result = fx.run_overlay(updates={"FAKE_GCB_MODE": mode})
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(fx.snapshot(), before)
                finally:
                    fx.close()

    def test_job_stage_failure_occurs_before_hook_transaction(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        before = self.fx.snapshot()
        result = self.fx.run_overlay(updates={"FAKE_JOB_FAIL_ON": "--stage"})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_unchanged(before)
        self.assertEqual(self.fx.job_log.read_text(encoding="utf-8"), "--stage\n")

    def test_binding_rejects_stale_shelf_pointer_until_gcb_repairs_it(self):
        self.fx.seed_runtime()
        pointer_path = self.fx.data / "awa" / "gcb-pointer.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["shelf"] = "/old/dev-worktree/capabilities/skills/global/tools/awa"
        pointer_path.write_text(
            json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.fx.write_hooks({"version": 1, "hooks": {}})
        result = self.fx.run_hooks()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        repaired = self.fx.run_overlay()
        self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
        self.fx.assert_matrix(self)

    def test_malformed_hook_json_is_refused_without_write_or_backup(self):
        self.fx.write_hooks(raw=b"{not-json", mode=0o600)
        before = self.fx.snapshot()
        result = self.fx.run_overlay()
        self.assertNotEqual(result.returncode, 0)
        self.assert_unchanged(before)

    def test_converges_empty_direct_mixed_stale_and_current_states(self):
        self.fx.seed_runtime()
        direct = self.fx.runtime / "kernel" / "hooks"
        cases = {
            "empty": {"version": 1, "hooks": {}},
            "three-role": {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {
                            "command": "/old/dev/_ops/cursor-hooks/worktree-session.sh",
                            "timeout": 5,
                            "failClosed": False,
                        }
                    ],
                    "beforeShellExecution": [
                        {
                            "command": "/old/dev/_ops/cursor-hooks/worktree-guard.sh",
                            "timeout": 20,
                            "failClosed": False,
                        }
                    ],
                    "afterFileEdit": [
                        {
                            "command": "/old/dev/_ops/cursor-hooks/worktree-guard.sh",
                            "timeout": 20,
                        }
                    ],
                },
            },
            "direct-five": {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {"command": str(direct / "worktree-session.sh")},
                        {"command": str(direct / "awa-recovery-maintenance.sh")},
                    ],
                    "beforeShellExecution": [
                        {"command": str(direct / "worktree-guard.sh")}
                    ],
                    "afterFileEdit": [{"command": str(direct / "worktree-guard.sh")}],
                    "beforeSubmitPrompt": [
                        {"command": str(direct / "before-submit-prompt.sh")}
                    ],
                },
            },
            "bash-prefixed": {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {
                            "command": f"bash {direct / 'worktree-session.sh'}",
                        },
                        {
                            "command": f"/bin/bash {direct / 'awa-recovery-maintenance.sh'}",
                        },
                    ],
                    "beforeShellExecution": [
                        {
                            "command": f"bash {direct / 'worktree-guard.sh'}",
                        },
                        {
                            "command": "bash /opt/unrelated/worktree-guard.sh",
                            "keep": True,
                        },
                    ],
                    "afterFileEdit": [
                        {
                            "command": f"/bin/bash {direct / 'worktree-guard.sh'}",
                        }
                    ],
                    "beforeSubmitPrompt": [
                        {
                            "command": (
                                f"bash {direct / 'before-submit-prompt.sh'} "
                                "--legacy-argument"
                            ),
                        }
                    ],
                },
            },
            "mixed": {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {"command": "/old/dev/_ops/cursor-hooks/worktree-session.sh"},
                        {"command": str(direct / "worktree-session.sh")},
                        {"command": str(direct / "awa-recovery-maintenance.sh")},
                        {"command": "/opt/unrelated/worktree-session.sh", "keep": True},
                    ],
                    "beforeShellExecution": [
                        {"command": "/old/dev/_ops/cursor-hooks/worktree-guard.sh"},
                        {"command": str(direct / "worktree-guard.sh")},
                        {"command": "/opt/unrelated/worktree-guard.sh", "keep": True},
                    ],
                    "afterFileEdit": [
                        {"command": str(direct / "worktree-guard.sh")}
                    ],
                    "beforeSubmitPrompt": [
                        {"command": str(direct / "before-submit-prompt.sh")}
                    ],
                },
            },
        }
        for name, document in cases.items():
            with self.subTest(name=name):
                fx = Fixture()
                try:
                    fx.seed_runtime()
                    fx.write_hooks(document)
                    result = fx.run_hooks()
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    fx.assert_matrix(self)
                    flat = [
                        entry
                        for entries in fx.read_hooks()["hooks"].values()
                        for entry in entries
                    ]
                    self.assertEqual(
                        len(
                            [
                                entry
                                for entry in flat
                                if entry.get("command", "").endswith(
                                    (
                                        "worktree-session.sh",
                                        "worktree-guard.sh",
                                        "worktree-guard-with-integrity.sh",
                                        "awa-integrity-observer.sh",
                                        "awa-session-handoff.sh",
                                        "awa-recovery-maintenance.sh",
                                        "before-submit-prompt.sh",
                                    )
                                )
                                and (
                                    "/awa/current/kernel/hooks/" in entry["command"]
                                    or "/_ops/cursor-hooks/" in entry["command"]
                                )
                            ]
                        ),
                        7,
                    )
                    if name in ("bash-prefixed", "mixed"):
                        self.assertTrue(any(entry.get("keep") for entry in flat))
                    if name == "bash-prefixed":
                        self.assertFalse(
                            any(
                                "--legacy-argument"
                                in str(entry.get("command", ""))
                                for entry in flat
                            )
                        )
                finally:
                    fx.close()

        self.fx.write_hooks({"version": 1, "hooks": {}})
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        current = self.fx.hooks.read_bytes()
        backups = [path.name for path in self.fx.backups()]
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        self.assertEqual(self.fx.hooks.read_bytes(), current)
        self.assertEqual([path.name for path in self.fx.backups()], backups)

    def test_check_rejects_each_projection_drift(self):
        mutations = {}
        for name in (
            "missing",
            "duplicate",
            "stale",
            "wrong-field",
            "wrong-event",
            "wrong-path",
        ):
            fx = Fixture()
            try:
                fx.seed_runtime()
                fx.write_hooks({"version": 1, "hooks": {}})
                self.assertEqual(fx.run_hooks().returncode, 0)
                data = fx.read_hooks()
                hooks = data["hooks"]
                if name == "missing":
                    hooks["beforeSubmitPrompt"] = []
                elif name == "duplicate":
                    hooks["beforeShellExecution"].append(
                        dict(hooks["beforeShellExecution"][0])
                    )
                elif name == "stale":
                    hooks["sessionStart"].append(
                        {
                            "command": "/old/dev/_ops/cursor-hooks/worktree-session.sh",
                            "type": "command",
                            "timeout": 5,
                            "failClosed": False,
                        }
                    )
                elif name == "wrong-field":
                    hooks["afterFileEdit"][0]["failClosed"] = False
                elif name == "wrong-event":
                    hooks.setdefault("sessionStart", []).append(
                        hooks["beforeShellExecution"].pop(0)
                    )
                elif name == "wrong-path":
                    hooks["beforeSubmitPrompt"][0]["command"] = "/not/awa/custom.sh"
                fx.write_hooks(data)
                result = fx.run_hooks("--check")
                self.assertNotEqual(
                    result.returncode, 0, f"{name} unexpectedly passed\n{result.stdout}"
                )
            finally:
                fx.close()

    def test_atomic_candidate_and_replace_failures_preserve_original(self):
        self.fx.seed_runtime()
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        before = self.fx.snapshot()
        candidate = self.fx.run_hooks(
            updates={"DEV_AWA_HOOK_TEST_FAIL_STAGE": "candidate"}
        )
        self.assertNotEqual(candidate.returncode, 0)
        self.assert_unchanged(before)

        replace = self.fx.run_hooks(
            updates={"DEV_AWA_HOOK_TEST_FAIL_STAGE": "replace"}
        )
        self.assertNotEqual(replace.returncode, 0)
        self.assertEqual(self.fx.hooks.read_bytes(), before[1])
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), before[2])

    def test_remove_drops_only_proven_awa_rows(self):
        self.fx.seed_runtime()
        unrelated = {"command": "/opt/unrelated/stop-hook", "timeout": 7}
        self.fx.write_hooks(
            {"version": 1, "hooks": {"stop": [unrelated]}}, mode=0o640
        )
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        removed = self.fx.run_hooks("--remove")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertEqual(self.fx.read_hooks()["hooks"]["stop"], [unrelated])
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), 0o640)
        flat = [
            entry
            for entries in self.fx.read_hooks()["hooks"].values()
            for entry in entries
        ]
        self.assertFalse(
            any(
                "/_ops/cursor-hooks/" in str(entry.get("command", ""))
                or "/awa/current/kernel/hooks/" in str(entry.get("command", ""))
                for entry in flat
            )
        )

    def test_deactivate_restores_exact_legacy_five_role_preimage(self):
        self.fx.seed_runtime()
        unrelated = {"command": "/opt/unrelated/session-hook", "timeout": 9}
        preimage = self.legacy_five_preimage(unrelated)
        raw = (json.dumps(preimage, separators=(",", ":")) + "\n").encode("utf-8")
        self.fx.write_hooks(raw=raw, mode=0o640)
        slack = self.fx.config / "awa" / "integrity-slack.json"
        slack.parent.mkdir(parents=True, exist_ok=True)
        slack.write_bytes(b'{"fixture":"untouched"}\n')
        slack.chmod(0o600)
        preimage_digest = hashlib.sha256(raw).hexdigest()

        installed = self.fx.run_overlay()
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.fx.assert_matrix(self)
        self.assertNotEqual(hashlib.sha256(self.fx.hooks.read_bytes()).hexdigest(), preimage_digest)

        rolled_back = self.fx.run_overlay("--deactivate")
        self.assertEqual(
            rolled_back.returncode,
            0,
            rolled_back.stdout + rolled_back.stderr,
        )
        self.assertEqual(self.fx.hooks.read_bytes(), raw)
        self.assertEqual(
            hashlib.sha256(self.fx.hooks.read_bytes()).hexdigest(),
            preimage_digest,
        )
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), 0o640)
        self.assertEqual(slack.read_bytes(), b'{"fixture":"untouched"}\n')

    def test_zero_row_preimage_is_legitimate_and_restored_byte_exactly(self):
        self.fx.seed_runtime()
        raw = b'{"hooks":{},"version":1}\n'
        self.fx.write_hooks(raw=raw, mode=0o600)
        installed = self.fx.run_hooks()
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.fx.assert_matrix(self)
        restored = self.fx.run_hooks("--restore-preimage")
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertEqual(self.fx.hooks.read_bytes(), raw)
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), 0o600)

    def test_explicit_remove_keeps_intentional_uninstall_semantics(self):
        self.fx.seed_runtime()
        raw = (
            json.dumps(self.legacy_five_preimage(), separators=(",", ":")) + "\n"
        ).encode("utf-8")
        self.fx.write_hooks(raw=raw, mode=0o640)
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        removed = self.fx.run_hooks("--remove")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertNotEqual(self.fx.hooks.read_bytes(), raw)
        flat = [
            entry
            for entries in self.fx.read_hooks()["hooks"].values()
            for entry in entries
        ]
        self.assertFalse(any(
            "/_ops/cursor-hooks/" in str(entry.get("command", ""))
            or "/awa/current/kernel/hooks/" in str(entry.get("command", ""))
            for entry in flat
        ))
        refused = self.fx.run_hooks("--restore-preimage")
        self.assertNotEqual(refused.returncode, 0)

    def _mark_rollback_as_compatible_predecessor(self, fx=None):
        fixture = fx or self.fx
        record = json.loads(
            fixture.rollback_record.read_text(encoding="utf-8")
        )
        record["provenance"]["release_commit"] = PREDECESSOR_PIN
        fixture.rollback_record.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        fixture.rollback_record.chmod(0o600)
        return record

    def test_v181_rollback_evidence_advances_without_rewriting_preimage(self):
        self.fx.seed_runtime()
        self.fx.write_hooks({"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}})
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        record = self._mark_rollback_as_compatible_predecessor()
        record["provenance"]["release_commit"] = "ff978ade5ff9c7604f58f4b3810b1cd75ea3287f"
        self.fx.rollback_record.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        backup = self.fx.rollback_backup()
        before = (backup.stat().st_ino, backup.read_bytes(), self.fx.hooks.read_bytes())
        result = self.fx.run_hooks()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, (backup.stat().st_ino, backup.read_bytes(), self.fx.hooks.read_bytes()))
        record["provenance"]["release_commit"] = PIN
        self.assertEqual(json.loads(self.fx.rollback_record.read_text()), record)

    def test_install_migrates_exact_compatible_rollback_provenance(self):
        self.fx.seed_runtime()
        unrelated = {"command": "/opt/unrelated/session-hook", "timeout": 9}
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [unrelated]}},
            mode=0o640,
        )
        installed = self.fx.run_hooks()
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)

        predecessor = self._mark_rollback_as_compatible_predecessor()
        hook_bytes = self.fx.hooks.read_bytes()
        hook_mode = stat.S_IMODE(self.fx.hooks.stat().st_mode)
        backup = self.fx.rollback_backup()
        backup_bytes = backup.read_bytes()
        backup_mode = stat.S_IMODE(backup.stat().st_mode)
        backup_inode = backup.stat().st_ino
        generation = predecessor["generation"]
        record_inode = self.fx.rollback_record.stat().st_ino
        preimage = copy.deepcopy(predecessor["preimage"])
        postimage = copy.deepcopy(predecessor["postimage"])
        backups = [path.name for path in self.fx.backups()]

        migrated = self.fx.run_hooks()
        self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
        self.assertIn("migrated compatible rollback provenance", migrated.stdout)
        current = json.loads(
            self.fx.rollback_record.read_text(encoding="utf-8")
        )
        expected = copy.deepcopy(predecessor)
        expected["provenance"]["release_commit"] = PIN
        self.assertEqual(current, expected)
        self.assertEqual(current["generation"], generation)
        self.assertNotEqual(self.fx.rollback_record.stat().st_ino, record_inode)
        self.assertEqual(
            stat.S_IMODE(self.fx.rollback_record.stat().st_mode), 0o600
        )
        self.assertEqual(current["preimage"], preimage)
        self.assertEqual(current["postimage"], postimage)
        self.assertEqual(self.fx.hooks.read_bytes(), hook_bytes)
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), hook_mode)
        self.assertEqual(backup.read_bytes(), backup_bytes)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), backup_mode)
        self.assertEqual(backup.stat().st_ino, backup_inode)
        self.assertEqual([path.name for path in self.fx.backups()], backups)
        self.assertEqual(
            self.fx.read_hooks()["hooks"]["sessionStart"][0], unrelated
        )

    def test_install_refuses_unknown_rollback_predecessor(self):
        self.fx.seed_runtime()
        self.fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        record = self._mark_rollback_as_compatible_predecessor()
        record["provenance"]["release_commit"] = "0" * 40
        self.fx.rollback_record.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        before_record = self.fx.rollback_record.read_bytes()
        before_hooks = self.fx.hooks.read_bytes()
        before_backup = self.fx.rollback_backup().read_bytes()
        refused = self.fx.run_hooks()
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.fx.rollback_record.read_bytes(), before_record)
        self.assertEqual(self.fx.hooks.read_bytes(), before_hooks)
        self.assertEqual(self.fx.rollback_backup().read_bytes(), before_backup)

    def test_install_refuses_compatible_predecessor_non_release_drift(self):
        mutations = {
            "source": lambda record: record["provenance"].__setitem__(
                "source", "github.com/other/awa"
            ),
            "v1-contract": lambda record: record["provenance"].__setitem__(
                "v1_contract_sha256", "0" * 64
            ),
            "v2-contract": lambda record: record["provenance"].__setitem__(
                "v2_contract_sha256", "0" * 64
            ),
            "v2-fixture": lambda record: record["provenance"].__setitem__(
                "v2_fixture_sha256", "0" * 64
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                fx = Fixture()
                try:
                    fx.seed_runtime()
                    fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
                    self.assertEqual(fx.run_hooks().returncode, 0)
                    record = self._mark_rollback_as_compatible_predecessor(fx)
                    mutate(record)
                    fx.rollback_record.write_text(
                        json.dumps(record, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    before_record = fx.rollback_record.read_bytes()
                    before_hooks = fx.hooks.read_bytes()
                    refused = fx.run_hooks()
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertEqual(fx.rollback_record.read_bytes(), before_record)
                    self.assertEqual(fx.hooks.read_bytes(), before_hooks)
                finally:
                    fx.close()

    def test_install_refuses_compatible_predecessor_when_projection_changes(self):
        self.fx.seed_runtime()
        self.fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        self._mark_rollback_as_compatible_predecessor()
        replacement = self.fx.dev / "_ops" / "cursor-hooks" / "worktree-session-v2.sh"
        shutil.copy2(
            self.fx.dev / "_ops" / "cursor-hooks" / "worktree-session.sh",
            replacement,
        )
        replacement.chmod(0o755)
        source = self.fx.hook_installer.read_text(encoding="utf-8")
        old = 'SESSION_HOOK="$ROOT/_ops/cursor-hooks/worktree-session.sh"'
        new = 'SESSION_HOOK="$ROOT/_ops/cursor-hooks/worktree-session-v2.sh"'
        self.assertEqual(source.count(old), 1)
        self.fx.hook_installer.write_text(
            source.replace(old, new), encoding="utf-8"
        )
        before_record = self.fx.rollback_record.read_bytes()
        before_hooks = self.fx.hooks.read_bytes()
        refused = self.fx.run_hooks()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("requires an unchanged hook projection", refused.stderr)
        self.assertEqual(self.fx.rollback_record.read_bytes(), before_record)
        self.assertEqual(self.fx.hooks.read_bytes(), before_hooks)

    def test_install_refuses_compatible_predecessor_with_hook_or_backup_drift(self):
        for drift in ("hook", "backup"):
            with self.subTest(drift=drift):
                fx = Fixture()
                try:
                    fx.seed_runtime()
                    fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
                    self.assertEqual(fx.run_hooks().returncode, 0)
                    self._mark_rollback_as_compatible_predecessor(fx)
                    if drift == "hook":
                        document = fx.read_hooks()
                        document["hooks"].setdefault("stop", []).insert(
                            0, {"command": "/opt/unrelated/new-stop", "timeout": 4}
                        )
                        fx.write_hooks(document, mode=0o640)
                    else:
                        fx.rollback_backup().write_bytes(b"{}\n")
                        fx.rollback_backup().chmod(0o600)
                    before_record = fx.rollback_record.read_bytes()
                    before_hooks = fx.hooks.read_bytes()
                    refused = fx.run_hooks()
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertEqual(fx.rollback_record.read_bytes(), before_record)
                    self.assertEqual(fx.hooks.read_bytes(), before_hooks)
                finally:
                    fx.close()

    def test_install_refuses_hardlinked_rollback_surfaces(self):
        for surface in ("record", "backup", "hook"):
            with self.subTest(surface=surface):
                fx = Fixture()
                alias = None
                try:
                    fx.seed_runtime()
                    fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
                    self.assertEqual(fx.run_hooks().returncode, 0)
                    self._mark_rollback_as_compatible_predecessor(fx)
                    target = {
                        "record": fx.rollback_record,
                        "backup": fx.rollback_backup(),
                        "hook": fx.hooks,
                    }[surface]
                    alias = target.with_name(target.name + ".hardlink")
                    os.link(target, alias)
                    refused = fx.run_hooks()
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertIn("exactly one hard link", refused.stderr)
                finally:
                    if alias is not None:
                        alias.unlink(missing_ok=True)
                    fx.close()

    def test_restore_refuses_invalid_untrusted_or_wrong_generation_backup(self):
        cases = (
            "missing-record",
            "malformed-record",
            "wrong-schema",
            "wrong-generation",
            "wrong-hook-path",
            "wrong-provenance",
            "mismatched-digest",
            "missing-backup",
            "symlink-backup",
            "untrusted-backup-mode",
        )
        for case in cases:
            with self.subTest(case=case):
                fx = Fixture()
                try:
                    fx.seed_runtime()
                    fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
                    installed = fx.run_hooks()
                    self.assertEqual(
                        installed.returncode,
                        0,
                        installed.stdout + installed.stderr,
                    )
                    postimage = fx.hooks.read_bytes()
                    post_mode = stat.S_IMODE(fx.hooks.stat().st_mode)
                    record_path = fx.rollback_record
                    backup = fx.rollback_backup()
                    if case == "missing-record":
                        record_path.unlink()
                    elif case == "malformed-record":
                        record_path.write_bytes(b"{")
                        record_path.chmod(0o600)
                    elif case == "missing-backup":
                        backup.unlink()
                    elif case == "symlink-backup":
                        target = backup.with_name("untrusted-preimage")
                        target.write_bytes(backup.read_bytes())
                        target.chmod(0o600)
                        backup.unlink()
                        backup.symlink_to(target)
                    elif case == "untrusted-backup-mode":
                        backup.chmod(0o644)
                    else:
                        record = json.loads(record_path.read_text(encoding="utf-8"))
                        if case == "wrong-schema":
                            record["schema"] = "dev-awa-hook-preimage/v0"
                        elif case == "wrong-generation":
                            record["generation"] = "0" * 32
                        elif case == "wrong-hook-path":
                            record["hook_path"] = "/tmp/not-the-selected-hook-file"
                        elif case == "wrong-provenance":
                            record["provenance"]["release_commit"] = "0" * 40
                        elif case == "mismatched-digest":
                            record["preimage"]["sha256"] = "0" * 64
                        record_path.write_text(
                            json.dumps(record, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        record_path.chmod(0o600)
                    refused = fx.run_hooks("--restore-preimage")
                    self.assertNotEqual(
                        refused.returncode,
                        0,
                        f"{case} unexpectedly restored\n"
                        + refused.stdout
                        + refused.stderr,
                    )
                    self.assertEqual(fx.hooks.read_bytes(), postimage)
                    self.assertEqual(
                        stat.S_IMODE(fx.hooks.stat().st_mode),
                        post_mode,
                    )
                finally:
                    fx.close()

    def test_restore_refuses_stale_postimage_without_losing_new_rows(self):
        self.fx.seed_runtime()
        self.fx.write_hooks({"version": 1, "hooks": {}}, mode=0o640)
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        document = self.fx.read_hooks()
        document["hooks"].setdefault("stop", []).insert(
            0, {"command": "/opt/new-unrelated-stop-hook", "timeout": 11}
        )
        self.fx.write_hooks(document, mode=0o640)
        changed = self.fx.hooks.read_bytes()
        refused = self.fx.run_hooks("--restore-preimage")
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.fx.hooks.read_bytes(), changed)
        self.assertEqual(
            self.fx.read_hooks()["hooks"]["stop"][0]["command"],
            "/opt/new-unrelated-stop-hook",
        )

    def test_restore_failures_preserve_or_recover_the_transaction_boundary(self):
        for cutpoint in ("restore-candidate", "restore-replace"):
            with self.subTest(cutpoint=cutpoint):
                fx = Fixture()
                try:
                    fx.seed_runtime()
                    raw = b'{"hooks":{},"version":1}\n'
                    fx.write_hooks(raw=raw, mode=0o640)
                    self.assertEqual(fx.run_hooks().returncode, 0)
                    postimage = fx.hooks.read_bytes()
                    failed = fx.run_hooks(
                        "--restore-preimage",
                        updates={"DEV_AWA_HOOK_TEST_FAIL_STAGE": cutpoint},
                    )
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertEqual(fx.hooks.read_bytes(), postimage)
                    recovered = fx.run_hooks("--restore-preimage")
                    self.assertEqual(
                        recovered.returncode,
                        0,
                        recovered.stdout + recovered.stderr,
                    )
                    self.assertEqual(fx.hooks.read_bytes(), raw)
                    self.assertEqual(
                        stat.S_IMODE(fx.hooks.stat().st_mode),
                        0o640,
                    )
                finally:
                    fx.close()

        raw = b'{"hooks":{},"version":1}\n'
        self.fx.seed_runtime()
        self.fx.write_hooks(raw=raw, mode=0o640)
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        interrupted = self.fx.run_hooks(
            "--restore-preimage",
            updates={"DEV_AWA_HOOK_TEST_FAIL_STAGE": "restore-post-replace"},
        )
        self.assertNotEqual(interrupted.returncode, 0)
        self.assertEqual(self.fx.hooks.read_bytes(), raw)
        retried = self.fx.run_hooks("--restore-preimage")
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("already restored", retried.stdout)

    def test_interrupted_install_keeps_a_safe_restorable_record(self):
        for cutpoint in ("replace", "post-replace"):
            with self.subTest(cutpoint=cutpoint):
                fx = Fixture()
                try:
                    fx.seed_runtime()
                    raw = b'{"hooks":{},"version":1}\n'
                    fx.write_hooks(raw=raw, mode=0o640)
                    failed = fx.run_hooks(
                        updates={"DEV_AWA_HOOK_TEST_FAIL_STAGE": cutpoint}
                    )
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertTrue(fx.rollback_record.is_file())
                    restored = fx.run_hooks("--restore-preimage")
                    self.assertEqual(
                        restored.returncode,
                        0,
                        restored.stdout + restored.stderr,
                    )
                    self.assertEqual(fx.hooks.read_bytes(), raw)
                    self.assertEqual(
                        stat.S_IMODE(fx.hooks.stat().st_mode),
                        0o640,
                    )
                finally:
                    fx.close()

    def test_concurrent_restore_attempts_serialize_and_converge(self):
        self.fx.seed_runtime()
        raw = b'{"hooks":{},"version":1}\n'
        self.fx.write_hooks(raw=raw, mode=0o640)
        self.assertEqual(self.fx.run_hooks().returncode, 0)
        processes = [
            self.fx.popen([self.fx.hook_installer, "--restore-preimage"])
            for _ in range(2)
        ]
        results = [process.communicate(timeout=10) for process in processes]
        for process, (stdout, stderr) in zip(processes, results):
            self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(self.fx.hooks.read_bytes(), raw)
        self.assertEqual(stat.S_IMODE(self.fx.hooks.stat().st_mode), 0o640)
        self.assertEqual(
            stat.S_IMODE(self.fx.rollback_record.parent.stat().st_mode),
            0o700,
        )
        self.assertEqual(stat.S_IMODE(self.fx.rollback_record.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.fx.rollback_backup().stat().st_mode), 0o600)

    def test_hook_restore_does_not_touch_job_or_slack_state(self):
        self.fx.seed_runtime()
        raw = b'{"hooks":{},"version":1}\n'
        self.fx.write_hooks(raw=raw, mode=0o640)
        sentinel_job = {
            "types": ["sentinel"],
            "handlers": {"sentinel": "/opt/sentinel"},
            "instances": [{"id": "sentinel", "type": "sentinel"}],
        }
        job_state = self.fx.state / "local-jobs" / "jobs.json"
        job_state.parent.mkdir(parents=True, exist_ok=True)
        job_state.write_text(
            json.dumps(sentinel_job, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.fx.job_log.write_text("sentinel\n", encoding="utf-8")
        slack = self.fx.config / "awa" / "integrity-slack.json"
        slack.parent.mkdir(parents=True, exist_ok=True)
        slack.write_bytes(b'{"fixture":"untouched"}\n')
        slack.chmod(0o600)
        before_job = job_state.read_bytes()
        before_log = self.fx.job_log.read_bytes()
        before_slack = slack.read_bytes()

        self.assertEqual(self.fx.run_hooks().returncode, 0)
        restored = self.fx.run_hooks("--restore-preimage")
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertEqual(self.fx.hooks.read_bytes(), raw)
        self.assertEqual(job_state.read_bytes(), before_job)
        self.assertEqual(self.fx.job_log.read_bytes(), before_log)
        self.assertEqual(slack.read_bytes(), before_slack)

    def test_deactivate_bounds_and_terminates_exact_integrity_worker(self):
        self.fx.write_hooks({"version": 1, "hooks": {}})
        self.assertEqual(self.fx.run_overlay().returncode, 0)
        worker = self.fx.runtime / "engine" / "integrity_detach.py"
        worker.write_text(
            "#!/usr/bin/env python3\n"
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "while True: time.sleep(1)\n",
            encoding="utf-8",
        )
        worker.chmod(0o755)
        process = subprocess.Popen(
            [str(worker)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            import time
            time.sleep(0.1)
            result = self.fx.run_overlay(
                "--deactivate",
                updates={
                    "AWA_ENGINE_TEST_ACTIVE": "1",
                    "DEV_AWA_TEST_PS_BIN": str(self.fx.base / "ps"),
                    "FAKE_WORKER_PID": str(process.pid),
                    "FAKE_WORKER_COMMAND": str(worker),
                    "FAKE_PS_COUNTER": str(self.fx.base / "ps-counter"),
                    "DEV_AWA_WORKER_WAIT_SECONDS": "0",
                    "DEV_AWA_WORKER_TERM_SECONDS": "0",
                },
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            process.wait(timeout=3)
            self.assertIn("--deactivate", self.fx.job_log.read_text(encoding="utf-8"))
            self.assertIn("--remove", self.fx.job_log.read_text(encoding="utf-8"))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)

    def test_offline_no_runtime_is_honest_nonmutating_deferral(self):
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        before = self.fx.snapshot()
        result = self.fx.run_overlay(
            updates={"ECO_BOOTSTRAP_OFFLINE": "1", "FAKE_GCB_MODE": "ok"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("defer", (result.stdout + result.stderr).lower())
        self.assert_unchanged(before)

    def test_missing_canonical_policy_refuses_before_runtime_or_trigger_mutation(self):
        for offline in ("0", "1"):
            fx = Fixture()
            try:
                fx.seed_runtime()
                (fx.dev / "_ops/policy/worktree-policy.yml").unlink()
                fx.write_hooks({"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}})
                before = fx.snapshot()
                result = fx.run_overlay(updates={"ECO_BOOTSTRAP_OFFLINE": offline})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("canonical host policy missing", result.stderr)
                self.assertEqual(fx.snapshot(), before)
                self.assertFalse((fx.dev / "_ops/policy/worktree-policy.yml").exists())
            finally:
                fx.close()

    def test_offline_runtime_seeds_missing_modes_before_hook_write(self):
        self.fx.seed_runtime()
        (self.fx.dev / "_ops/policy/worktree-modes.yml").unlink()
        self.fx.write_hooks({"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}})
        result = self.fx.run_overlay(updates={"ECO_BOOTSTRAP_OFFLINE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.fx.dev / "_ops/policy/worktree-modes.yml").is_file())
        self.fx.assert_matrix(self)

    def test_offline_repair_invokes_local_gcb_repair(self):
        self.fx.seed_runtime()
        self.fx.log.write_text("", encoding="utf-8")
        self.fx.write_hooks({"version": 1, "hooks": {}})
        result = self.fx.run_overlay(
            "--repair", updates={"ECO_BOOTSTRAP_OFFLINE": "1"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verbs = [
            row.split("\t", 1)[0]
            for row in self.fx.log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("--repair", verbs)
        self.fx.assert_matrix(self)

    def test_offline_install_refuses_direct_owner_without_repair(self):
        self.fx.seed_runtime(mode="nonexternal")
        self.fx.write_hooks(
            {"version": 1, "hooks": {"sessionStart": [{"command": "/keep"}]}}
        )
        before = self.fx.snapshot()
        result = self.fx.run_overlay(updates={"ECO_BOOTSTRAP_OFFLINE": "1"})
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.fx.snapshot(), before)

    def test_static_check_without_runtime_is_nonmutating(self):
        before = self.fx.snapshot()
        result = self.fx.run_overlay("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_unchanged(before)

    def test_source_preview_is_nonmutating_and_activation_gated(self):
        before = self.fx.snapshot()
        result = self.fx.run_overlay("--preview")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("source-only preview", result.stdout)
        self.assertIn("explicit operator GO", result.stdout)
        self.assert_unchanged(before)

    def test_source_check_does_not_treat_live_hook_state_as_source_input(self):
        self.fx.write_hooks(
            {
                "version": 1,
                "hooks": {
                    "beforeShellExecution": [
                        {
                            "command": (
                                "bash /old/.local/share/awa/current/kernel/"
                                "hooks/worktree-guard.sh"
                            )
                        }
                    ]
                },
            }
        )
        before = self.fx.snapshot()
        result = self.fx.run_overlay("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("source contract", result.stdout)
        self.assert_unchanged(before)


if __name__ == "__main__":
    selected = [
        name.strip()
        for name in os.environ.get("AWA_HOST_OVERLAY_TESTS", "").split(",")
        if name.strip()
    ]
    if selected:
        suite = unittest.TestSuite(HostOverlayTest(name) for name in selected)
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(HostOverlayTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("awa-host-overlay: OK")
PY
