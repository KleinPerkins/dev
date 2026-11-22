#!/usr/bin/env bash
# _ops/bin/dev-new-repo.sh — scaffold a new personal repo that is BORN COMPLIANT (N1).
#
# Creates a PRIVATE (by default) KleinPerkins/<name> repo with an SSH origin, sets the LOCAL
# canonical noreply identity, installs the M2 identity-guard pre-commit, renders the uniform
# repo-baseline floor (SECURITY.md, CODEOWNERS, .gitignore block, dependabot.yml — see
# _ops/baseline/README.md), places it under ~/dev/personal/<name>, and makes the initial commit
# through the guard (proving compliance). This makes "the right way" the easy way — the moment
# most drift is otherwise introduced.
#
# Usage:
#   _ops/bin/dev-new-repo.sh <name> [--public|--private] [--desc "text"] [--resume] [--dry-run]
#   _ops/bin/dev-new-repo.sh --personal-codex <name> [--dry-run | --resume] [--public|--private]
#   _ops/bin/dev-new-repo.sh --capability <name> [--kind skill|rule|sub-agent|tool] [--shape snapshot|release-descriptor|descriptor-only] --dry-run
#
# Safe by design: --dry-run prints the exact plan and changes nothing. A real run refuses an
# existing target unless --resume names its operation state. Resume restores omitted persisted
# visibility/description and rejects explicit conflicts; remote steps require authenticated gh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/baseline-lib.sh"
DEV_ROOT="$OM_REPO_ROOT"
INSTALL_GUARD="$SCRIPT_DIR/install-identity-guard.sh"
REPO_BASELINE="$SCRIPT_DIR/repo-baseline.sh"
TEST_SHARDING="$SCRIPT_DIR/test-sharding.py"
TEST_SHARDING_REQUIRED=1

NAME=""; VIS="private"; VIS_EXPLICIT=0; PUSH=1; DRYRUN=0; DESC=""; DESC_EXPLICIT=0; CAPABILITY=0; KIND="skill"; SHAPE="descriptor-only"; FIXTURE_ROOT=""; FIXTURE_REPOSITORY_ID=""; FIXTURE_INTERRUPT_AFTER=""; RESUME=0; LEGACY_V1=0; PERSONAL_CODEX=0; PERSONAL_BINDING=""
while [ $# -gt 0 ]; do
  case "$1" in
    --personal-codex) PERSONAL_CODEX=1 ;;
    --capability) CAPABILITY=1 ;;
    --kind)    shift; KIND="${1:-}" ;;
    --shape)   shift; SHAPE="${1:-}" ;;
    --public)  VIS="public"; VIS_EXPLICIT=1 ;;
    --private) VIS="private"; VIS_EXPLICIT=1 ;;
    --no-push) PUSH=0 ;;
    --pr-automation) printf 'dev-new-repo: REFUSED retired controller enrollment\n' >&2; exit 2 ;;
    --no-pr-automation) : ;; # retained compatibility; enrollment is always disabled
    --dry-run) DRYRUN=1 ;;
    --resume) RESUME=1 ;;
    --legacy-v1) LEGACY_V1=1 ;;
    --fixture-repository-id)
      [ $# -ge 2 ] && case "$2" in -*) false ;; *) true ;; esac ||
        { printf 'dev-new-repo: --fixture-repository-id requires a positive integer\n' >&2; exit 2; }
      shift
      FIXTURE_REPOSITORY_ID="$1"
      ;;
    --fixture-interrupt-after)
      [ $# -ge 2 ] && case "$2" in -*) false ;; *) true ;; esac ||
        { printf 'dev-new-repo: --fixture-interrupt-after requires a phase\n' >&2; exit 2; }
      shift
      FIXTURE_INTERRUPT_AFTER="$1"
      ;;
    --fixture-root)
      [ $# -ge 2 ] && case "$2" in -*) false ;; *) true ;; esac ||
        { printf 'dev-new-repo: --fixture-root requires an absolute path\n' >&2; exit 2; }
      shift
      FIXTURE_ROOT="$1"
      ;;
    --desc)    shift; DESC="${1:-}"; DESC_EXPLICIT=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    -*) printf 'dev-new-repo: unknown flag: %s\n' "$1" >&2; exit 2 ;;
    *)  [ -z "$NAME" ] || { printf 'dev-new-repo: expected one repository name\n' >&2; exit 2; }
        NAME="$1" ;;
  esac
  shift
done

[ -n "$NAME" ] || { printf 'usage: dev-new-repo.sh <name> [--public|--private] [--desc "text"] [--resume (restores omitted intent; rejects conflicts)] [--dry-run]\n' >&2; exit 2; }
case "$NAME" in
  *[!A-Za-z0-9._-]*|"") printf 'dev-new-repo: invalid name %q (use letters, digits, . _ -)\n' "$NAME" >&2; exit 2 ;;
esac

case "$KIND" in skill|rule|sub-agent|tool) : ;; *) printf 'dev-new-repo: invalid capability kind %q\n' "$KIND" >&2; exit 2 ;; esac
case "$SHAPE" in snapshot|release-descriptor|descriptor-only) : ;; *) printf 'dev-new-repo: invalid tool shape %q\n' "$SHAPE" >&2; exit 2 ;; esac
if [ -n "$FIXTURE_ROOT" ] && [ "$PERSONAL_CODEX" -eq 0 ]; then
  case "$FIXTURE_ROOT" in
    /*) : ;;
    *) printf 'dev-new-repo: --fixture-root requires an absolute path\n' >&2; exit 2 ;;
  esac
  python3 - "$FIXTURE_ROOT" <<'PY' ||
import sys
import tempfile
from pathlib import Path

fixture_root = Path(sys.argv[1]).resolve()
temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
try:
    fixture_root.relative_to(temporary_root)
except ValueError:
    raise SystemExit(1)
PY
    {
      printf 'dev-new-repo: --fixture-root is test-only and must resolve under the system temporary directory\n' >&2
      exit 2
    }
fi
case "$FIXTURE_REPOSITORY_ID" in
  "") : ;;
  *[!0-9]*|0) printf 'dev-new-repo: --fixture-repository-id requires a positive integer\n' >&2; exit 2 ;;
esac
case "$FIXTURE_INTERRUPT_AFTER" in
  ""|scaffold-verified|initial-commit-landed|initial-committed|remote-create-attempted|remote-create-landed|remote-marker-cleared|remote-created) : ;;
  *) printf 'dev-new-repo: unsupported fixture interruption phase %q\n' "$FIXTURE_INTERRUPT_AFTER" >&2; exit 2 ;;
esac
[ -z "$FIXTURE_REPOSITORY_ID$FIXTURE_INTERRUPT_AFTER" ] || [ -n "$FIXTURE_ROOT" ] ||
  { printf 'dev-new-repo: fixture controls require --fixture-root\n' >&2; exit 2; }
[ "$RESUME" -eq 0 ] || [ "$CAPABILITY" -eq 0 ] ||
  { printf 'dev-new-repo: --resume is not supported for capability scaffolds\n' >&2; exit 2; }

DELIVERY_CLASS="$(bl_delivery_class "$OM_GH_USER/$NAME")"
case "$DELIVERY_CLASS" in
  retired|excluded) printf 'dev-new-repo: REFUSED retired/excluded repository\n' >&2; exit 2 ;;
esac
[ "$DELIVERY_CLASS" != identity-unverified ] ||
  { printf 'dev-new-repo: noncanonical native product identity\n' >&2; exit 2; }
if [ "$DELIVERY_CLASS" = native-github ]; then
  [ "${GH_HOST:-github.com}" = github.com ] ||
    { printf 'dev-new-repo: native delivery requires GitHub.com\n' >&2; exit 2; }
  export GH_HOST=github.com
  [ -z "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}" ] ||
    { printf 'dev-new-repo: native fixtures do not support push-remote rewrites\n' >&2; exit 2; }
  [ "$CAPABILITY" -eq 0 ] && [ "$LEGACY_V1" -eq 0 ] ||
    { printf 'dev-new-repo: native products require the born-v2 product scaffold\n' >&2; exit 2; }
  if [ "$RESUME" -eq 0 ] || [ "$VIS_EXPLICIT" -eq 1 ]; then
    [ "$VIS" = public ] ||
      { printf 'dev-new-repo: native delivery requires explicit --public visibility\n' >&2; exit 2; }
  fi
fi



if [ "$PERSONAL_CODEX" -eq 1 ]; then
  [ "$CAPABILITY" -eq 0 ] && [ "$LEGACY_V1" -eq 0 ] && [ "$DELIVERY_CLASS" = unenrolled ] ||
    { printf 'dev-new-repo: personal creation requires a new product name and born-v2 scaffold\n' >&2; exit 2; }
  [ "${GH_HOST:-github.com}" = github.com ] && [ -z "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}" ] ||
    { printf 'dev-new-repo: personal creation requires the canonical GitHub destination\n' >&2; exit 2; }
  export GH_HOST=github.com
  PERSONAL_TARGET="$SCRIPT_DIR/../portability/personal_scaffold.py"
  TARGET="$(python3 -I -B "$PERSONAL_TARGET" target "$NAME" "$FIXTURE_ROOT" "$RESUME")"
elif [ "$CAPABILITY" -eq 1 ]; then
  TARGET="$DEV_ROOT/capabilities/$NAME"
elif [ -n "$FIXTURE_ROOT" ]; then
  TARGET="$FIXTURE_ROOT/$NAME"
else
  TARGET="$DEV_ROOT/personal/$NAME"
fi
SSH_URL="git@github.com:$OM_GH_USER/$NAME.git"
INITIAL_COMMIT_MESSAGE="init: scaffold $OM_GH_USER/$NAME (born v2)"

run_doc_warden_v2() {
  env PATH="$PATH" bash "$DEV_ROOT/_ops/bin/doc-warden.sh" v2-preview "$@"
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$field"
}

new_id() {
  python3 -c 'import uuid; print(uuid.uuid4())'
}

state_file_for_target() {
  local git_path
  git_path="$(git -C "$TARGET" rev-parse --git-path doc-warden-new-repo.json)"
  case "$git_path" in
    /*) printf '%s\n' "$git_path" ;;
    *) printf '%s/%s\n' "$TARGET" "$git_path" ;;
  esac
}

create_operation_state() {
  local state_file="$1" repository_key="$2" greenfield_id="$3" remote_id="$4"
  python3 - "$state_file" "$OM_GH_USER/$NAME" "$repository_key" "$greenfield_id" \
    "$remote_id" "$NAME" "$VIS" "$DESC" "$SSH_URL" "$INITIAL_COMMIT_MESSAGE" "$PERSONAL_BINDING" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema": "dev-new-repo-operation/v2",
    "repository": sys.argv[2],
    "repository_key": sys.argv[3],
    "greenfield_operation_id": sys.argv[4],
    "remote_operation_id": sys.argv[5],
    "phase": "initialized",
    "github_repository_id": None,
    "test_sharding_required": True,
    "replay_intent": {
        "repository": sys.argv[2],
        "name": sys.argv[6],
        "visibility": sys.argv[7],
        "description": sys.argv[8],
        "origin": sys.argv[9],
        "marker": f"https://doc-warden.invalid/operations/{sys.argv[5]}",
        "initial_commit_message": sys.argv[10],
    },
}
if sys.argv[11]:
    payload["personal_checkout"] = sys.argv[11]
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_name(f".{path.name}.tmp")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
}

update_operation_state() {
  local state_file="$1" phase="$2" repository_id="${3:-}"
  python3 - "$state_file" "$phase" "$repository_id" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("schema") != "dev-new-repo-operation/v2":
    raise SystemExit("dev-new-repo: unsupported operation state")
payload["phase"] = sys.argv[2]
if sys.argv[3]:
    payload["github_repository_id"] = int(sys.argv[3])
temporary = path.with_name(f".{path.name}.tmp")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
}

read_operation_state() {
  local state_file="$1" field="$2"
  python3 - "$state_file" "$field" "$PERSONAL_BINDING" <<'PY'
import json
import re
import sys
import uuid
from pathlib import Path

path = Path(sys.argv[1])
if path.is_symlink() or not path.is_file():
    raise SystemExit("dev-new-repo: operation state is unavailable")
payload = json.loads(path.read_text(encoding="utf-8"))
required = {
    "schema",
    "repository",
    "repository_key",
    "greenfield_operation_id",
    "remote_operation_id",
    "phase",
    "github_repository_id",
    "replay_intent",
}
if sys.argv[3]:
    required.update({"personal_checkout", "test_sharding_required"})
if payload.get("personal_checkout", "") != sys.argv[3]:
    raise SystemExit("dev-new-repo: operation belongs to a different checkout or scaffold profile")
phases = {
    "initialized",
    "baseline-ready",
    "initial-committed",
    "remote-create-attempted",
    "remote-created-marked",
    "remote-created",
    "second-committed",
    "settings-applied",
    "waiting-external",
}
try:
    identifiers = (
        uuid.UUID(payload["repository_key"]),
        uuid.UUID(payload["greenfield_operation_id"]),
        uuid.UUID(payload["remote_operation_id"]),
    )
except (KeyError, TypeError, ValueError, AttributeError) as exc:
    raise SystemExit("dev-new-repo: operation state is invalid") from exc
repository_id = payload.get("github_repository_id")
intent = payload.get("replay_intent")
if (
    set(payload) not in (required, required | {"test_sharding_required"})
    or payload.get("schema") != "dev-new-repo-operation/v2"
    or ("test_sharding_required" in payload and payload["test_sharding_required"] is not True)
    or re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        str(payload.get("repository", "")),
    )
    is None
    or any(str(item) != source for item, source in zip(
        identifiers,
        (
            payload["repository_key"],
            payload["greenfield_operation_id"],
            payload["remote_operation_id"],
        ),
    ))
    or payload.get("phase") not in phases
    or (
        repository_id is not None
        and (type(repository_id) is not int or repository_id <= 0)
    )
    or (
        payload.get("phase") in {
            "remote-created-marked",
        }
        and repository_id is None
    )
    or not isinstance(intent, dict)
    or set(intent) != {
        "repository",
        "name",
        "visibility",
        "description",
        "origin",
        "marker",
        "initial_commit_message",
    }
    or intent.get("repository") != payload.get("repository")
    or intent.get("name") != payload.get("repository", "").split("/", 1)[-1]
    or intent.get("visibility") not in {"private", "public"}
    or not isinstance(intent.get("description"), str)
    or intent.get("origin") != f"git@github.com:{payload.get('repository')}.git"
    or intent.get("marker") != (
        "https://doc-warden.invalid/operations/"
        f"{payload.get('remote_operation_id')}"
    )
    or intent.get("initial_commit_message") != (
        f"init: scaffold {payload.get('repository')} (born v2)"
    )
):
    raise SystemExit("dev-new-repo: operation state is invalid")
value = (
    intent.get(sys.argv[2].removeprefix("intent."))
    if sys.argv[2].startswith("intent.")
    else payload.get(sys.argv[2])
)
print("" if value is None else value)
PY
}

github_repository_metadata() {
  local output rc=0
  output="$("$GITHUB_CLI" api "repos/$OM_GH_USER/$NAME" 2>&1)" || rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '%s\n' "$output"
    return 0
  fi
  if printf '%s' "$output" | grep -q '(HTTP 404)'; then
    return 4
  fi
  printf 'dev-new-repo: remote creation observation failed: %s\n' "$output" >&2
  return 75
}

install_fixture_github_cli() {
  local fake_bin source="${DOC_WARDEN_FIXTURE_GH_SOURCE:-}"
  fake_bin="$(dirname "$state_file")/doc-warden-fixture-bin"
  mkdir -p "$fake_bin"
  if [ ! -x "$fake_bin/gh" ]; then
    [ -f "$source" ] && [ ! -L "$source" ] ||
      { printf 'dev-new-repo: fixture GitHub harness is unavailable\n' >&2; return 2; }
    python3 - "$source" "$FIXTURE_ROOT" <<'PY' ||
from pathlib import Path
import sys
Path(sys.argv[1]).resolve(strict=True).relative_to(Path(sys.argv[2]).resolve(strict=True))
PY
      { printf 'dev-new-repo: fixture GitHub harness escaped fixture root\n' >&2; return 2; }
    mv "$source" "$fake_bin/gh"
  fi
  [ ! -L "$fake_bin/gh" ] ||
    { printf 'dev-new-repo: contained fixture GitHub harness is invalid\n' >&2; return 2; }
  DOC_WARDEN_GH_BIN="$fake_bin/gh"
  DOC_WARDEN_FIXTURE_REMOTE="$FIXTURE_ROOT/.doc-warden-fixture-remotes/$NAME.json"
  DOC_WARDEN_FIXTURE_GH_CALLS="$FIXTURE_ROOT/.doc-warden-fixture-remotes/$NAME.calls"
  DOC_WARDEN_FIXTURE_REPOSITORY_ID="$FIXTURE_REPOSITORY_ID"
  mkdir -p "$(dirname "$DOC_WARDEN_FIXTURE_REMOTE")"
  export DOC_WARDEN_GH_BIN DOC_WARDEN_FIXTURE_REMOTE
  export DOC_WARDEN_FIXTURE_GH_CALLS DOC_WARDEN_FIXTURE_REPOSITORY_ID
  GITHUB_CLI="$DOC_WARDEN_GH_BIN"
}

validate_remote_creation_metadata() {
  local metadata="$1" expected_homepage="$2" expected_id="${3:-}"
  python3 - "$state_file" \
    "$REMOTE_OPERATION_ID" "$OM_GH_USER/$NAME" "$VIS" \
    "$(git -C "$TARGET" remote get-url origin)" "$DESC" "$REMOTE_MARKER" \
    "$expected_homepage" "$expected_id" "$metadata" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
intent = state["replay_intent"]
metadata = json.loads(sys.argv[10]) if sys.argv[10] else None
expected_intent = {
    "repository": sys.argv[3],
    "name": sys.argv[3].split("/", 1)[1],
    "visibility": sys.argv[4],
    "origin": sys.argv[5],
    "description": sys.argv[6],
    "marker": sys.argv[7],
    "initial_commit_message": f"init: scaffold {sys.argv[3]} (born v2)",
}
if (
    state.get("remote_operation_id") != sys.argv[2]
    or intent != expected_intent
):
    raise SystemExit("dev-new-repo: persisted_replay_intent_mismatch")
if metadata is None:
    raise SystemExit(0)
if (
    metadata.get("full_name", "").casefold() != sys.argv[3].casefold()
    or metadata.get("visibility") != sys.argv[4]
    or (metadata.get("description") or "") != sys.argv[6]
    or (metadata.get("homepage") or "") != sys.argv[8]
    or type(metadata.get("id")) is not int
    or metadata["id"] <= 0
    or (sys.argv[9] and metadata["id"] != int(sys.argv[9]))
):
    raise SystemExit("dev-new-repo: remote creation identity is inconsistent")
print(metadata["id"])
PY
}

clear_remote_creation_marker() {
  "$GITHUB_CLI" api --method PATCH "repos/$OM_GH_USER/$NAME" \
    -f homepage= >/dev/null
}

verify_initial_commit_recovery() {
  [ -z "$(git -C "$TARGET" status --porcelain)" ] &&
    [ "$(git -C "$TARGET" rev-list --count HEAD)" = 1 ] &&
    [ "$(git -C "$TARGET" show -s --format=%s HEAD)" = "$INITIAL_COMMIT_MESSAGE" ] &&
    [ "$(git -C "$TARGET" rev-list --parents -n 1 HEAD | wc -w | tr -d ' ')" = 1 ] &&
    [ "$(git -C "$TARGET" remote get-url origin)" = "$SSH_URL" ] &&
    run_doc_warden_v2 greenfield verify \
      --repo "$TARGET" \
      --authority-root "$DEV_ROOT" \
      --repository-key "$REPOSITORY_KEY" >/dev/null &&
    python3 - "$TARGET" "$GREENFIELD_OPERATION_ID" "$REPOSITORY_KEY" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(
    (
        Path(sys.argv[1])
        / "_ops/doc-warden/state/v2/receipts"
        / f"{sys.argv[2]}.json"
    ).read_text(encoding="utf-8")
)
if (
    receipt.get("operation_id") != sys.argv[2]
    or receipt.get("repository_key") != sys.argv[3]
    or receipt.get("github_repository_id") is not None
):
    raise SystemExit(1)
PY
}

apply_stored_preview() {
  local operation_id="$1" action_digest="$2" consequence="$3"
  local consent_path operation_path apply_output apply_rc=0
  consent_path="$(dirname "$state_file")/consent-$operation_id.json"
  operation_path="$XDG_STATE_HOME/doc-warden/operations/$operation_id.json"
  PYTHONPATH="$DEV_ROOT/_ops/doc-warden/v2${PYTHONPATH:+:$PYTHONPATH}" \
    python3 - "$operation_id" "$action_digest" "$consequence" "$consent_path" <<'PY'
import sys
from pathlib import Path

from doc_warden.artifacts import consent_for
from doc_warden.canonical import canonical_json
from doc_warden.operation_store import load_preview

preview = load_preview(sys.argv[1], sys.argv[2])
destination = Path(sys.argv[4])
destination.write_bytes(canonical_json(consent_for(preview, sys.argv[3])))
destination.chmod(0o600)
PY
  apply_output="$(
    run_doc_warden_v2 apply \
      --operation-id "$operation_id" \
      --action-digest "$action_digest" \
      --consent-envelope "$consent_path"
  )" || apply_rc=$?
  rm -f "$consent_path" "$operation_path"
  rmdir \
    "$XDG_STATE_HOME/doc-warden/operations" \
    "$XDG_STATE_HOME/doc-warden" \
    "$XDG_STATE_HOME" 2>/dev/null || true
  if [ "$apply_rc" -ne 0 ]; then
    printf 'dev-new-repo: guarded transaction failed: %s\n' "$apply_output" >&2
    return "$apply_rc"
  fi
}

exact_greenfield_apply() {
  local preview action_digest
  preview="$(
    run_doc_warden_v2 greenfield scaffold \
      --repo "$TARGET" \
      --authority-root "$DEV_ROOT" \
      --name "$NAME" \
      --repository-key "$REPOSITORY_KEY" \
      --operation-id "$GREENFIELD_OPERATION_ID" \
      --preview
  )"
  action_digest="$(printf '%s' "$preview" | json_field action_digest)"
  apply_stored_preview \
    "$GREENFIELD_OPERATION_ID" \
    "$action_digest" \
    structural
}

exact_remote_observation_apply() {
  local preview action_digest
  preview="$(
    run_doc_warden_v2 greenfield observe-remote \
      --repo "$TARGET" \
      --authority-root "$DEV_ROOT" \
      --repository "$OM_GH_USER/$NAME" \
      --repository-id "$GITHUB_REPOSITORY_ID" \
      --operation-id "$REMOTE_OPERATION_ID" \
      --preview
  )"
  action_digest="$(printf '%s' "$preview" | json_field action_digest)"
  apply_stored_preview \
    "$REMOTE_OPERATION_ID" \
    "$action_digest" \
    external
}

delivery_preview() {
  python3 - "$DELIVERY_CLASS" "$OM_GH_USER/$NAME" "${GITHUB_REPOSITORY_ID:-}" <<'PREVIEW'
import json, sys
print(json.dumps({"schema": "dev-successor-delivery-preview/v1",
    "delivery_class": sys.argv[1], "repository": sys.argv[2],
    "github_repository_id": int(sys.argv[3]) if sys.argv[3] else None,
    "status": "pending_repository_owned_admission", "controller_enrollment": False,
    "target_staging": {"allowed": False}, "actions_taken": [],
    "external_gate": {"reason": "repository_owned_delivery_admission_required"}}, sort_keys=True))
PREVIEW
}

emit_born_v2_result() {
  local delivery_json="$1" resumed="$2" doctor_json="$3" commit_count sharding_json
  commit_count="$(git -C "$TARGET" rev-list --count HEAD)"
  sharding_json="$(python3 "$TEST_SHARDING" view --repo "$TARGET")" || return 1
  python3 - "$TARGET" "$OM_GH_USER/$NAME" "$VIS" "$REPOSITORY_KEY" \
    "${GITHUB_REPOSITORY_ID:-}" "$commit_count" "$resumed" "$delivery_json" \
    "$doctor_json" "$state_file" "$sharding_json" <<'PY'
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
delivery = json.loads(sys.argv[8])
native = delivery.get("delivery_class") == "native-github"
doctor = json.loads(sys.argv[9])
operation = json.loads(Path(sys.argv[10]).read_text(encoding="utf-8"))
profile = json.loads(
    (repo / ".planning" / "doc-warden.json").read_text(encoding="utf-8")
)
print(
    json.dumps(
        {
            "schema": "dev-new-repo-result/v2",
            "status": "waiting_external",
            "enabled": True,
            "repository": sys.argv[2],
            "visibility": sys.argv[3],
            "target": str(repo),
            "repository_key": sys.argv[4],
            "github_repository_id": int(sys.argv[5]) if sys.argv[5] else None,
            "commit_count": int(sys.argv[6]),
            "resumed": sys.argv[7] == "1",
            "test_sharding": json.loads(sys.argv[11]),
            "bindings": {
                "repository_key": profile["repository_key"],
                "github_repository_id": profile["github_repository_id"],
            },
            "delivery": delivery,
            "remote_creation_evidence": {
                "operation_id": operation["remote_operation_id"],
                "marker": operation["replay_intent"]["marker"],
                "repository_id": operation["github_repository_id"],
                "marker_cleared": bool(
                    operation["github_repository_id"]
                    and operation["phase"] not in {
                        "remote-create-attempted",
                        "remote-created-marked",
                    }
                ),
            },
            "inventory_observation": {
                "status": ("pending_repository_owned_observation" if native
                           else "pending_repository_owned_admission"),
                "repository": sys.argv[2],
                "github_repository_id": (
                    int(sys.argv[5]) if sys.argv[5] else None
                ),
                "default_branch": "main",
            },
            "maintenance_enrollment": {
                "status": ("pending_repository_owned_observation" if native
                           else "pending_repository_owned_admission"),
                "read_only": True,
            },
            "doctor": doctor,
            "next_action": delivery["external_gate"]["reason"],
            "workflows_present": sorted(
                str(path.relative_to(repo))
                for path in (repo / ".github" / "workflows").glob("*")
                if path.is_file()
            ),
            "rollback": {
                "before_remote": "remove_local_only_after_operator_choice",
                "after_remote": "preserve_receipts_and_require_external_delete_gate",
                "marker_cleanup": "resume_validates_identity_and_clears_homepage_marker",
                "remote_deleted": False,
                "remote_delete_requires_gate": True,
            },
        },
        sort_keys=True,
    )
)
PY
}

bind_personal_checkout() {
  # Both the session-lock and simultaneous retries with the same writer ID matter.
  # The shell owns fd 9 for this invocation. The OS releases it on process exit.
  exec 9<"$TARGET"
  PERSONAL_BINDING="$(python3 -I -B "$PERSONAL_TARGET" binding "$TARGET" "$FIXTURE_ROOT" "$FIXTURE_REPOSITORY_ID")"
}

stage_scaffold() {
  if [ "$PERSONAL_CODEX" -eq 1 ]; then
    python3 -I -B "$PERSONAL_TARGET" stage "$TARGET" "$1" "$2"
  else
    git -C "$TARGET" add .
  fi
}

acquire_personal_writer() {
  local observation
  observation="$(cd "$TARGET" && bash "$DEV_ROOT/_ops/hooks/session-lock" acquire)" || return 1
  case "$observation" in
    "session-lock: acquired/refreshed for env:$DEV_SESSION_ID.") return 0 ;;
    *) printf 'dev-new-repo: unable to verify the personal checkout writer\n' >&2; return 1 ;;
  esac
}

run_born_v2() {
  local resumed=0 state_file phase delivery_json doctor_json baseline_output
  local GITHUB_CLI=gh REMOTE_MARKER=""
  GITHUB_REPOSITORY_ID=""
  # Fixture-mode baseline override: lets the test harness inject a stub that exits 1.
  # Only active when FIXTURE_ROOT is set (test/fixture runs only; no production effect).
  [ -z "${DOC_WARDEN_FIXTURE_REPO_BASELINE:-}" ] || [ -z "${FIXTURE_ROOT:-}" ] || \
    REPO_BASELINE="${DOC_WARDEN_FIXTURE_REPO_BASELINE}"

  if [ "$DRYRUN" -eq 1 ]; then
    delivery_json="$(delivery_preview)"
    local workflow_note="none during bootstrap"
    local qualification_note="repository-owned delivery admission remains pending"
    local forbidden_note="no Actions workflow, no hosted/self-hosted runner, no auto-merge arm, no controller assignment/qualification mutation"
    local staging_note="keep delivery unenrolled; retired controller staging is refused"
    local maintenance_note="retain pending repository-owned observation"
    local authority_note="successor delivery disposition"
    local footer_note="no .github/workflows files are created during bootstrap; private/no-CI and unenrolled targets remain without CI."
    if [ "$DELIVERY_CLASS" = native-github ]; then
      workflow_note="none during bootstrap; native GitHub CI follows verified bootstrap"
      qualification_note="repository-owned native delivery; no controller enrollment"
      forbidden_note="no paid/larger/self-hosted runner, no auto-merge arm, no fleet/controller mutation"
      staging_note="keep native delivery pending repository-owned qualification"
      maintenance_note="retain repository-owned read-only governance observation; no runnerless enrollment"
      authority_note="native delivery classification"
      footer_note="no .github/workflows files are created during bootstrap; only free standard hosted CI is authorized afterward."
    fi
    cat <<EOF
dev-new-repo born-v2 preview:
  target      : $OM_GH_USER/$NAME ($VIS)
  local path  : $TARGET
  profile     : proportional doc-warden v2
  workflows   : $workflow_note
  qualification: $qualification_note
  local files : baseline README/SECURITY/CODEOWNERS/dependabot/gitignore; AGENTS; minimal .planning project/roadmap/state/skill/guards; v2 events/receipts
  verification: sharding required; foundation pending until at least two runnable shards cover all tests
  GitHub gate : create $VIS repository and push source only; repository-owned settings admission remains separate
  forbidden   : $forbidden_note

[dry-run] exact ordered sequence:
  1. validate request and preview the exact target
  2. create local main repository
  3. apply local noreply identity
  4. install identity/session/data guards
  5. apply workflow-free baseline
  6. mint stable repository key and scaffold v2
  7. verify and create first guarded commit
  8. create $VIS GitHub remote only after the named external gate
     creation carries a one-operation UUID homepage marker
  9. observe remote ID and create second guarded commit
     first validate the exact marker, persist remote ID, and clear the marker
 10. $staging_note
 11. push only after source verification and operator authorization
 12. retain pending settings admission; do not mutate delivery controls
 13. write the inventory observation after remote/default-branch observation
 14. $maintenance_note
 15. run doctor and print the exact external next action

[dry-run] rollback and compensation:
  before remote creation: preserve the preview, then remove the local directory only after operator choice
  after remote creation: preserve both commit/receipt IDs; remote deletion requires an explicit external gate
  marker cleanup: validate the operation UUID and clear its temporary homepage idempotently
  interrupted after remote creation: resume from .git operation state; never auto-delete the remote
  remote marker: operation-specific UUID evidence is cleared after identity is persisted

[dry-run] $authority_note:
$delivery_json
[dry-run] $footer_note
[dry-run] no changes made.
EOF
    return
  fi

  if [ "$PERSONAL_CODEX" -eq 1 ] && [ -z "${DEV_SESSION_ID:-}" ]; then
    printf 'dev-new-repo: set DEV_SESSION_ID to the current writer before creation or resume\n' >&2
    return 2
  fi
  if [ -e "$TARGET" ]; then
    [ "$RESUME" -eq 1 ] ||
      { printf 'dev-new-repo: target exists (refusing): %s\n' "$TARGET" >&2; return 1; }
    git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1 ||
      { printf 'dev-new-repo: resume target is not a git repository\n' >&2; return 1; }
    if [ "$PERSONAL_CODEX" -eq 1 ]; then
      bind_personal_checkout
    fi
    state_file="$(state_file_for_target)"
    [ -f "$state_file" ] ||
      { printf 'dev-new-repo: no resumable born-v2 operation state\n' >&2; return 1; }
    [ "$(read_operation_state "$state_file" repository)" = "$OM_GH_USER/$NAME" ] ||
      { printf 'dev-new-repo: operation state target mismatch\n' >&2; return 1; }
    REPOSITORY_KEY="$(read_operation_state "$state_file" repository_key)"
    GREENFIELD_OPERATION_ID="$(read_operation_state "$state_file" greenfield_operation_id)"
    REMOTE_OPERATION_ID="$(read_operation_state "$state_file" remote_operation_id)"
    GITHUB_REPOSITORY_ID="$(read_operation_state "$state_file" github_repository_id)"
    phase="$(read_operation_state "$state_file" phase)"
    if [ "$(read_operation_state "$state_file" test_sharding_required)" != True ]; then
      TEST_SHARDING_REQUIRED=0
    fi
    if [ "$DELIVERY_CLASS" = native-github ] || [ "$PERSONAL_CODEX" -eq 1 ]; then
      local stored_origin fetch_origin push_origin
      stored_origin="$(read_operation_state "$state_file" intent.origin)"
      fetch_origin="$(git -C "$TARGET" remote get-url --all origin)"
      push_origin="$(git -C "$TARGET" remote get-url --push --all origin)"
      if [ "$stored_origin" != "$SSH_URL" ] || [ "$fetch_origin" != "$stored_origin" ] || [ "$push_origin" != "$stored_origin" ]; then
        printf 'dev-new-repo: persisted native origin or push URL changed; refusing resume\n' >&2
        return 1
      fi
    fi
    local stored_visibility stored_description
    stored_visibility="$(read_operation_state "$state_file" intent.visibility)"
    stored_description="$(read_operation_state "$state_file" intent.description)"
    [ "$VIS_EXPLICIT" -eq 0 ] || [ "$VIS" = "$stored_visibility" ] ||
      { printf 'dev-new-repo: persisted_replay_intent_mismatch: visibility\n' >&2; return 1; }
    [ "$DESC_EXPLICIT" -eq 0 ] || [ "$DESC" = "$stored_description" ] ||
      { printf 'dev-new-repo: persisted_replay_intent_mismatch: description\n' >&2; return 1; }
    VIS="$stored_visibility"
    DESC="$stored_description"
    if [ "$DELIVERY_CLASS" = native-github ] && [ "$VIS" != public ]; then
      printf 'dev-new-repo: persisted native visibility is not public; refusing resume\n' >&2
      return 1
    fi

    if [ "$PERSONAL_CODEX" -eq 1 ]; then acquire_personal_writer; fi
    resumed=1
  else
    [ "$RESUME" -eq 0 ] ||
      { printf 'dev-new-repo: persisted_replay_intent_mismatch: target/name %s\n' "$TARGET" >&2; return 1; }
    if [ "$PERSONAL_CODEX" -eq 1 ]; then
      mkdir -m 700 -- "$TARGET"
      git -C "$TARGET" init --template= -b main >/dev/null
      bind_personal_checkout
    else
      mkdir -p "$TARGET"
      git -C "$TARGET" init -b main >/dev/null
    fi
    if [ "$PERSONAL_CODEX" -eq 1 ]; then acquire_personal_writer; fi
    git -C "$TARGET" config --local user.name "$OM_GH_USER"
    git -C "$TARGET" config --local user.email "$OM_NOREPLY"
    git -C "$TARGET" remote add origin "$SSH_URL"
    REPOSITORY_KEY="$(new_id)"
    GREENFIELD_OPERATION_ID="$(new_id)"
    REMOTE_OPERATION_ID="$(new_id)"
    state_file="$(state_file_for_target)"
    create_operation_state "$state_file" "$REPOSITORY_KEY" "$GREENFIELD_OPERATION_ID" "$REMOTE_OPERATION_ID"
    phase="initialized"
  fi
  if [ "$TEST_SHARDING_REQUIRED" -eq 1 ] && git -C "$TARGET" rev-parse --verify HEAD >/dev/null 2>&1; then
    local sharding_observation
    sharding_observation="$(python3 "$TEST_SHARDING" verify --repo "$TARGET")" || return 1
    printf '%s' "$sharding_observation" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("required") is True else 1)' || {
      printf 'dev-new-repo: persisted test-sharding requirement is missing; refusing resume\n' >&2
      return 1
    }
  fi
  REMOTE_MARKER="https://doc-warden.invalid/operations/$REMOTE_OPERATION_ID"
  if [ -n "$FIXTURE_ROOT" ] && [ -n "$FIXTURE_REPOSITORY_ID" ]; then
    install_fixture_github_cli
  fi
  XDG_STATE_HOME="$(dirname "$state_file")/doc-warden-operation-state"
  BORN_V2_TEMP_STATE="$XDG_STATE_HOME"
  export XDG_STATE_HOME
  cleanup_born_v2_temp_state() {
    [ "${XDG_STATE_HOME:-}" = "${BORN_V2_TEMP_STATE:-}" ] || return
    [ ! -L "$BORN_V2_TEMP_STATE" ] || return
    rm -rf -- "$BORN_V2_TEMP_STATE"
  }
  trap cleanup_born_v2_temp_state EXIT

  if [ "$phase" = "initialized" ]; then
    bash "$INSTALL_GUARD" "$TARGET" >/dev/null
    if [ -n "$(git -C "$TARGET" status --porcelain)" ]; then
      if [ -n "$FIXTURE_ROOT" ]; then
        baseline_output="$(
          env -u GH_TOKEN -u GITHUB_TOKEN \
            GH_CONFIG_DIR="$(dirname "$state_file")/doc-warden-gh-config" \
            bash "$REPO_BASELINE" verify "$TARGET"
        )"
      else
        baseline_output="$(bash "$REPO_BASELINE" verify "$TARGET")"
      fi
      printf '%s\n' "$baseline_output" | grep -q 'Overall: COMPLIANT' ||
        {
          printf 'dev-new-repo: interrupted baseline is partial; preserve operation state and remove the local target only after operator choice\n' >&2
          return 75
        }
    else
      if [ -n "$FIXTURE_ROOT" ]; then
        env -u GH_TOKEN -u GITHUB_TOKEN \
          GH_CONFIG_DIR="$(dirname "$state_file")/doc-warden-gh-config" \
          bash "$REPO_BASELINE" apply "$TARGET" >/dev/null
      else
        bash "$REPO_BASELINE" apply "$TARGET" >/dev/null
      fi
    fi
    update_operation_state "$state_file" baseline-ready
    phase="baseline-ready"
  fi

  if [ "$phase" = "baseline-ready" ]; then
    if git -C "$TARGET" rev-parse --verify HEAD >/dev/null 2>&1; then
      verify_initial_commit_recovery ||
        {
          printf 'dev-new-repo: initial_commit_recovery_inconsistent\n' >&2
          return 1
        }
      update_operation_state "$state_file" initial-committed
      phase="initial-committed"
    else
      exact_greenfield_apply
      if [ "$TEST_SHARDING_REQUIRED" -eq 1 ]; then
        local aggregate_gate="ci-required"
        python3 "$TEST_SHARDING" bootstrap --repo "$TARGET" --aggregate "$aggregate_gate" >/dev/null
      fi
      run_doc_warden_v2 greenfield verify \
        --repo "$TARGET" \
        --authority-root "$DEV_ROOT" \
        --repository-key "$REPOSITORY_KEY" >/dev/null
      if [ "$FIXTURE_INTERRUPT_AFTER" = "scaffold-verified" ]; then
        printf 'dev-new-repo: interrupted after verified scaffold transaction; exact --resume replay is available and no remote was created\n' >&2
        return 75
      fi
      stage_scaffold "$GREENFIELD_OPERATION_ID" initial
      git -C "$TARGET" commit -m "$INITIAL_COMMIT_MESSAGE" >/dev/null
      if [ "$FIXTURE_INTERRUPT_AFTER" = "initial-commit-landed" ]; then
        printf 'dev-new-repo: interrupted after the initial commit landed; --resume will verify it before advancing operation state\n' >&2
        return 75
      fi
      update_operation_state "$state_file" initial-committed
      phase="initial-committed"
    fi
  fi

  if [ "$FIXTURE_INTERRUPT_AFTER" = "initial-committed" ] && [ "$phase" = "initial-committed" ]; then
    printf 'dev-new-repo: interrupted before remote creation; the verified local commit is retained for --resume and no remote was created\n' >&2
    return 75
  fi

  if [ -n "$FIXTURE_ROOT" ] && [ -z "$FIXTURE_REPOSITORY_ID" ]; then
    delivery_json="$(delivery_preview)"
    doctor_json="$(
      run_doc_warden_v2 doctor repo --repo "$TARGET"
    )"
    update_operation_state "$state_file" waiting-external
    emit_born_v2_result "$delivery_json" "$resumed" "$doctor_json"
    return
  fi

  if [ "$PERSONAL_CODEX" -eq 1 ] && [ -z "$FIXTURE_ROOT" ]; then
    [ "$(gh api --hostname github.com user --jq .login)" = "$OM_GH_USER" ] ||
      { printf 'dev-new-repo: personal GitHub account unavailable; local operation retained\n' >&2; return 75; }
  fi
  if [ "$phase" = "initial-committed" ] ||
    [ "$phase" = "remote-create-attempted" ] ||
    [ "$phase" = "remote-created-marked" ]; then
    verify_initial_commit_recovery ||
      {
        printf 'dev-new-repo: initial_commit_recovery_inconsistent\n' >&2
        return 1
      }
  fi

  if [ "$phase" = "initial-committed" ]; then
    "$GITHUB_CLI" auth status -h github.com >/dev/null 2>&1 ||
      { printf 'dev-new-repo: gh is not authenticated; local born-v2 source is retained for --resume\n' >&2; return 75; }
    local existing_rc=0
    github_repository_metadata >/dev/null || existing_rc=$?
    if [ "$existing_rc" -eq 0 ]; then
      printf 'dev-new-repo: remote_creation_preexisting_refused\n' >&2
      return 1
    fi
    [ "$existing_rc" -eq 4 ] || return "$existing_rc"
    update_operation_state "$state_file" remote-create-attempted
    phase="remote-create-attempted"
  fi

  if [ "$FIXTURE_INTERRUPT_AFTER" = "remote-create-attempted" ] &&
    [ "$phase" = "remote-create-attempted" ]; then
    printf 'dev-new-repo: interrupted after durable remote creation intent; no remote was created\n' >&2
    return 75
  fi

  if [ "$phase" = "remote-create-attempted" ]; then
    validate_remote_creation_metadata "" ""
    local remote_metadata remote_rc=0
    "$GITHUB_CLI" auth status -h github.com >/dev/null 2>&1 ||
      { printf 'dev-new-repo: gh is not authenticated; remote creation attempt is retained for --resume\n' >&2; return 75; }
    remote_metadata="$(github_repository_metadata)" || remote_rc=$?
    if [ "$remote_rc" -eq 4 ]; then
      local create_args=(
        repo create "$OM_GH_USER/$NAME" "--$VIS"
        --homepage "$REMOTE_MARKER"
      )
      [ -z "$DESC" ] || create_args+=(--description "$DESC")
      "$GITHUB_CLI" "${create_args[@]}" >/dev/null
      remote_metadata="$(github_repository_metadata)" ||
        {
          printf 'dev-new-repo: remote_creation_identity_unavailable\n' >&2
          return 75
        }
    elif [ "$remote_rc" -ne 0 ]; then
      return "$remote_rc"
    fi
    if [ "$FIXTURE_INTERRUPT_AFTER" = "remote-create-landed" ]; then
      printf 'dev-new-repo: interrupted after remote creation; --resume will validate the durable attempt marker and exact remote identity without recreating it\n' >&2
      return 75
    fi
    GITHUB_REPOSITORY_ID="$(
      validate_remote_creation_metadata "$remote_metadata" "$REMOTE_MARKER"
    )" ||
      {
        printf 'dev-new-repo: remote_creation_recovery_inconsistent\n' >&2
        return 1
      }
    update_operation_state "$state_file" remote-created-marked "$GITHUB_REPOSITORY_ID"
    phase="remote-created-marked"
  fi

  if [ "$phase" = "remote-created-marked" ]; then
    validate_remote_creation_metadata "" ""
    local marked_metadata marked_homepage
    marked_metadata="$(github_repository_metadata)" ||
      {
        printf 'dev-new-repo: remote_creation_recovery_inconsistent\n' >&2
        return 1
      }
    marked_homepage="$(
      printf '%s' "$marked_metadata" |
        python3 -c 'import json,sys; print(json.load(sys.stdin).get("homepage") or "")'
    )"
    if [ -n "$marked_homepage" ] && [ "$marked_homepage" != "$REMOTE_MARKER" ]; then
      printf 'dev-new-repo: remote_creation_recovery_inconsistent\n' >&2
      return 1
    fi
    validate_remote_creation_metadata \
      "$marked_metadata" "$marked_homepage" "$GITHUB_REPOSITORY_ID" >/dev/null ||
      {
        printf 'dev-new-repo: remote_creation_recovery_inconsistent\n' >&2
        return 1
      }
    if [ -n "$marked_homepage" ]; then
      clear_remote_creation_marker
      if [ "$FIXTURE_INTERRUPT_AFTER" = "remote-marker-cleared" ]; then
        printf 'dev-new-repo: interrupted after clearing the remote operation marker; persisted repository ID is retained for --resume\n' >&2
        return 75
      fi
      marked_metadata="$(github_repository_metadata)"
      validate_remote_creation_metadata \
        "$marked_metadata" "" "$GITHUB_REPOSITORY_ID" >/dev/null ||
        {
          printf 'dev-new-repo: remote_creation_recovery_inconsistent\n' >&2
          return 1
        }
    fi
    update_operation_state "$state_file" remote-created "$GITHUB_REPOSITORY_ID"
    phase="remote-created"
  fi

  if [ "$FIXTURE_INTERRUPT_AFTER" = "remote-created" ] && [ "$phase" = "remote-created" ]; then
    printf 'dev-new-repo: interrupted after remote creation; resume is safe, automatic remote deletion is forbidden, and deletion requires an explicit external deletion gate\n' >&2
    return 75
  fi

  if [ "$phase" = "remote-created" ]; then
    if [ -z "$GITHUB_REPOSITORY_ID" ]; then
      [ -z "$FIXTURE_ROOT" ] ||
        { printf 'dev-new-repo: fixture remote identity is unavailable\n' >&2; return 75; }
      "$GITHUB_CLI" auth status -h github.com >/dev/null 2>&1 ||
        { printf 'dev-new-repo: gh is not authenticated; remote identity observation is retained for --resume\n' >&2; return 75; }
      GITHUB_REPOSITORY_ID="$(
        "$GITHUB_CLI" api "repos/$OM_GH_USER/$NAME" --jq .id
      )"
      update_operation_state "$state_file" remote-created "$GITHUB_REPOSITORY_ID"
    fi
    if [ "$PERSONAL_CODEX" -eq 1 ]; then
      validate_remote_creation_metadata "$(github_repository_metadata)" "" "$GITHUB_REPOSITORY_ID" >/dev/null
    fi
    exact_remote_observation_apply

    delivery_json="$(delivery_preview)"

    run_doc_warden_v2 greenfield verify \
      --repo "$TARGET" \
      --authority-root "$DEV_ROOT" \
      --repository-key "$REPOSITORY_KEY" \
      --repository-id "$GITHUB_REPOSITORY_ID" >/dev/null
    stage_scaffold "$REMOTE_OPERATION_ID" remote
    if ! git -C "$TARGET" diff --cached --quiet; then
      git -C "$TARGET" commit -m "chore: observe GitHub repository identity" >/dev/null
    fi
    update_operation_state "$state_file" second-committed "$GITHUB_REPOSITORY_ID"
    phase="second-committed"
  fi

  # DOC_WARDEN_FIXTURE_PUSH_REMOTE is fixture-mode-only: exercising this block without
  # a real SSH remote by pointing origin at a local bare repo.  The origin rewrite is
  # gated on FIXTURE_ROOT so it never fires in production (low-finding safety gate).
  if { [ -z "$FIXTURE_ROOT" ] || [ -n "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}" ]; } && \
      [ "$phase" = "second-committed" ] && [ "$PUSH" -eq 1 ]; then
    if [ -n "${FIXTURE_ROOT:-}" ] && [ -n "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}" ]; then
      git -C "$TARGET" remote set-url origin "${DOC_WARDEN_FIXTURE_PUSH_REMOTE}"
    fi
    if [ "$DELIVERY_CLASS" = native-github ] || [ "$PERSONAL_CODEX" -eq 1 ]; then
      [ "$(git -C "$TARGET" remote get-url --all origin)" = "$SSH_URL" ] &&
        [ "$(git -C "$TARGET" remote get-url --push --all origin)" = "$SSH_URL" ] ||
        { printf 'dev-new-repo: native push destination changed; refusing publication\n' >&2; return 1; }
    fi
    if [ "$PERSONAL_CODEX" -eq 1 ]; then
      validate_remote_creation_metadata "$(github_repository_metadata)" "" "$GITHUB_REPOSITORY_ID" >/dev/null
    fi
    # Idempotent push: skip when origin/main already matches HEAD so --resume does not
    # re-push after interruption left phase at second-committed.
    if ! git -C "$TARGET" rev-parse --verify refs/remotes/origin/main >/dev/null 2>&1 || \
        [ "$(git -C "$TARGET" rev-parse HEAD)" != \
          "$(git -C "$TARGET" rev-parse refs/remotes/origin/main)" ]; then
      git -C "$TARGET" push -u origin main
    fi
    # Publishing source never grants settings or controller enrollment authority.
    printf 'dev-new-repo: source pushed; repository-owned delivery admission remains pending\n' >&2

  fi

  delivery_json="$(delivery_preview)"
  doctor_json="$(
    run_doc_warden_v2 doctor repo --repo "$TARGET"
  )"
  update_operation_state "$state_file" waiting-external "$GITHUB_REPOSITORY_ID"
  emit_born_v2_result "$delivery_json" "$resumed" "$doctor_json"
}

if [ "$CAPABILITY" -eq 0 ] && [ "$LEGACY_V1" -eq 0 ]; then
  run_born_v2
  exit $?
fi
[ -z "$FIXTURE_ROOT" ] ||
  { printf 'dev-new-repo: --legacy-v1 is not supported in fixture mode\n' >&2; exit 2; }

echo   "dev-new-repo plan:"
printf '  name        : %s\n' "$NAME"
printf '  remote      : %s/%s (%s)\n' "$OM_GH_USER" "$NAME" "$VIS"
printf '  origin (SSH): %s\n' "$SSH_URL"
printf '  local path  : %s\n' "$TARGET"
printf '  identity    : %s <%s> (LOCAL)\n' "$OM_GH_USER" "$OM_NOREPLY"
printf '  guard       : install identity-guard pre-commit\n'
printf '  baseline    : repo-baseline apply (SECURITY.md, CODEOWNERS, .gitignore block, dependabot.yml)\n'
printf '  verification: sharding required; activation blocked while the foundation is pending\n'
printf '  PR profile  : unenrolled; repository-owned admission pending\n'
printf '  settings    : pending repository-owned admission; no automatic settings mutation\n'
printf '  push        : %s\n' "$([ "$PUSH" -eq 1 ] && echo yes || echo no)"
if [ "$CAPABILITY" -eq 1 ]; then
  printf '  capability  : yes (kind=%s%s)\n' "$KIND" "$([ "$KIND" = tool ] && printf ', shape=%s' "$SHAPE")"
  printf '  lockkit     : vendored eco-lock.sh + initial .eco-registry.lock + CI parity workflow\n'
fi

if [ "$DRYRUN" -eq 1 ]; then
  scaffold_note="README.md"
  [ "$CAPABILITY" -eq 1 ] && scaffold_note="README.md, capability payload, lockkit, CI workflow"
  cat <<EOF

[dry-run] would run, in order:
  mkdir -p "$TARGET" && cd "$TARGET"
  git init -b main
  git config --local user.name  "$OM_GH_USER"
  git config --local user.email "$OM_NOREPLY"
  git remote add origin "$SSH_URL"
  bash "$INSTALL_GUARD" "$TARGET"
  bash "$REPO_BASELINE" apply "$TARGET"   # uniform baseline floor — see _ops/baseline/README.md
  scaffold $scaffold_note
  python3 "$TEST_SHARDING" bootstrap --repo "$TARGET"
  git add . && git commit -m "init: scaffold $OM_GH_USER/$NAME (born compliant)"
  bash "$DEV_ROOT/_ops/bin/doc-warden.sh" repair "$TARGET" --approve --greenfield   # doc-warden baseline inheritance (§7)
  cd "$TARGET" && git add docs/ AGENTS.md 2>/dev/null && git diff --cached --quiet || git commit -m "chore: doc-warden greenfield documentation inheritance"
  cd "$DEV_ROOT" && \
      git add "_ops/doc-warden/state/$NAME/" && git diff --cached --quiet -- "_ops/doc-warden/state/$NAME/" || git commit -m "chore: doc-warden greenfield receipt for $OM_GH_USER/$NAME" -- "_ops/doc-warden/state/$NAME/"
  gh repo create "$OM_GH_USER/$NAME" --$VIS ${DESC:+--description "$DESC"}
$([ "$PUSH" -eq 1 ] && echo '  git push -u origin main' || echo '  # (push skipped: --no-push)')
[dry-run] no changes made.
EOF
  exit 0
fi

# ---- real run ----
[ "$CAPABILITY" -eq 1 ] && {
  printf 'dev-new-repo: --capability is currently dry-run only until config/lockkit.yml has a governed target registration path for new capability repos.\n' >&2
  printf 'dev-new-repo: rerun with --dry-run to preview, then add the repo to lockkit inventory before creating it.\n' >&2
  exit 2
}
[ -e "$TARGET" ] && { printf 'dev-new-repo: %s already exists — refusing to clobber.\n' "$TARGET" >&2; exit 1; }
command -v gh >/dev/null 2>&1 || { printf 'dev-new-repo: gh CLI not found.\n' >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { printf 'dev-new-repo: gh not authenticated (run: gh auth login).\n' >&2; exit 1; }

mkdir -p "$TARGET"; cd "$TARGET"
git init -b main >/dev/null
git config --local user.name  "$OM_GH_USER"
git config --local user.email "$OM_NOREPLY"
git remote add origin "$SSH_URL"
bash "$INSTALL_GUARD" "$TARGET"
bash "$REPO_BASELINE" apply "$TARGET"   # uniform baseline floor — see _ops/baseline/README.md

shelf_for_kind() {
  case "$1" in
    skill) printf 'skills\n' ;;
    rule) printf 'rules\n' ;;
    sub-agent) printf 'sub-agents\n' ;;
    tool) printf 'tools\n' ;;
  esac
}

if [ "$CAPABILITY" -eq 1 ]; then
  shelf="$(shelf_for_kind "$KIND")"
  unit="global/$shelf/$NAME"
  mkdir -p "$unit" .github/scripts .github/workflows
  cat > README.md <<EOF
# $NAME

Private $OM_GH_USER capability repo, scaffolded born-compliant with lockkit parity.
EOF
  cat > "$unit/meta.yml" <<EOF
schema: kp-capability/v1
id: $NAME
kind: $KIND
flavor: 1
scope: global
owner: $OM_GH_USER
install: install.sh
post_mgmt: none
expose: cursor claude codex
EOF
  [ "$KIND" = "tool" ] && {
    printf 'shape: %s\nsync_policy: record-only\n' "$SHAPE" >> "$unit/meta.yml"
  }
  cat > "$unit/install.sh" <<'INSTALL'
#!/usr/bin/env bash
set -euo pipefail
exit 0
INSTALL
  chmod +x "$unit/install.sh"
  case "$KIND" in
    skill) printf '# %s\n' "$NAME" > "$unit/SKILL.md" ;;
    rule) printf '# %s\n' "$NAME" > "$unit/$NAME.mdc" ;;
    sub-agent) printf '# %s\n' "$NAME" > "$unit/$NAME.md" ;;
    tool) printf 'id: %s\nshape: %s\nsync_policy: record-only\n' "$NAME" "$SHAPE" > "$unit/tool.yml" ;;
  esac
  lock_master="$DEV_ROOT/personal/ecosystem-orchestrator/templates/eco-lock/eco-lock.sh"
  [ -f "$lock_master" ] || { printf 'dev-new-repo: lockkit master missing at %s\n' "$lock_master" >&2; exit 1; }
  cp "$lock_master" .github/scripts/eco-lock.sh
  chmod +x .github/scripts/eco-lock.sh
  bash .github/scripts/eco-lock.sh write
  cat > .github/workflows/verify-capability.yml <<'YAML'
name: verify-capability
on:
  pull_request:
  push:
    branches: [main]
jobs:
  lock-parity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bash .github/scripts/eco-lock.sh check
YAML
else
  printf '# %s\n\nPrivate %s repo, scaffolded by `dev-new-repo` (born compliant: LOCAL noreply identity + identity-guard).\n' "$NAME" "$OM_GH_USER" > README.md
fi

python3 "$TEST_SHARDING" bootstrap --repo "$TARGET" --aggregate 'ci-required' >/dev/null
git add .
git commit -m "init: scaffold $OM_GH_USER/$NAME (born compliant)" >/dev/null

# doc-warden greenfield inheritance: run after the first real commit exists so the
# rollback contract (§12: receipt binds a real, revertable HEAD) is satisfiable.
# --greenfield is refused on any non-MISSING/CONFORMANT repo, so this is a safe no-op
# if the scaffold somehow already has docs. The receipt is written to ~/dev's own
# _ops/doc-warden/state/<name>/, mirroring how baseline state/ is committed back.
DOC_WARDEN_CLI="$DEV_ROOT/_ops/bin/doc-warden.sh"
if [ -f "$DOC_WARDEN_CLI" ]; then
  gf_rc=0
  bash "$DOC_WARDEN_CLI" repair "$TARGET" --approve --greenfield || gf_rc=$?
  # Exit 2 = applied with NEEDS_AUTHORING skeletons (POLICY §8); docs still need committing.
  if [ "$gf_rc" -eq 0 ] || [ "$gf_rc" -eq 2 ]; then
    # Greenfield writes inherited docs into the new repo; commit them here so the
    # initial push includes the documentation structure (not only ~/dev's receipt).
    if ! ( cd "$TARGET" && \
      if [ ! -d docs ] && [ ! -f AGENTS.md ]; then
        printf 'dev-new-repo: doc-warden greenfield produced no documentation files\n' >&2
        exit 1
      fi && \
      git add docs/ AGENTS.md && \
      if git diff --cached --quiet; then
        printf 'dev-new-repo: doc-warden docs commit failed — nothing staged after git add\n' >&2
        exit 1
      fi && \
      git commit -m "chore: doc-warden greenfield documentation inheritance" >/dev/null ); then
      printf 'dev-new-repo: doc-warden docs commit failed — aborting scaffold (local tree at %s)\n' "$TARGET" >&2
      exit 1
    fi
    ( cd "$DEV_ROOT" && \
      RECEIPT_DIR="_ops/doc-warden/state/$(basename "$TARGET")" && \
      git add "$RECEIPT_DIR/" >/dev/null 2>&1 && \
      git diff --cached --quiet -- "$RECEIPT_DIR/" || \
      git -C "$DEV_ROOT" commit -m "chore: doc-warden greenfield receipt for $OM_GH_USER/$NAME" -- "$RECEIPT_DIR/" >/dev/null ) \
      || printf 'dev-new-repo: warning — doc-warden receipt commit in ~/dev failed (non-fatal); continuing scaffold\n' >&2
  else
    printf 'dev-new-repo: doc-warden greenfield repair failed (rc=%s) — aborting scaffold (local tree at %s)\n' "$gf_rc" "$TARGET" >&2
    exit 1
  fi
fi

gh repo create "$OM_GH_USER/$NAME" --"$VIS" ${DESC:+--description "$DESC"} >/dev/null
git remote set-url origin "$SSH_URL"   # ensure SSH regardless of gh's default protocol
if [ "$PUSH" -eq 1 ]; then
  git push -u origin main >/dev/null && echo "pushed main -> origin"
else
  echo "(push skipped: --no-push)"
fi
printf 'dev-new-repo: repository-owned delivery/settings admission pending; no controller enrollment\n'

echo "dev-new-repo: created $TARGET (origin $SSH_URL, identity-guard installed)."
