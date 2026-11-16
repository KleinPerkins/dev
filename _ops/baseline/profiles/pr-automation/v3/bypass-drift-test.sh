#!/usr/bin/env bash
# _ops/baseline/profiles/pr-automation/v3/bypass-drift-test.sh
#
# D3 (2026-07-30) mocked-response tests for the merge-safety admin-bypass durability tooling —
# the fail-before / pass-after mirror of #92's (live-only) bl_check_no_required_reviews smoke test,
# but hermetic: it stubs `gh` on PATH so it never touches the network and runs in `make verify`.
#
# Covers:
#   • bl_check_bypass_missing     — BYPASS_MISSING (no admin bypass) -> CLEAN (bypass present); NOT_ENROLLED
#   • bl_check_stale_fingerprint  — STALE_FINGERPRINT (drifted) -> CLEAN (matches APP_VISIBLE); NOT_STAGED
#   • reconcile-merge-safety      — dry-run upserts-by-id and emits the RepositoryRole:5 pull_request bypass
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEV_ROOT="$(cd "$HERE/../../../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }
assert_eq() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3 (got '$1', want '$2')"; fi; }
assert_contains() { case "$1" in *"$2"*) ok "$3" ;; *) bad "$3 (missing '$2')" ;; esac; }
assert_not_contains() { case "$1" in *"$2"*) bad "$3 (unexpected '$2')" ;; *) ok "$3" ;; esac; }

# ---- Stub gh on PATH (inherited by bl_gh_timeout's python subprocess via the exported env) ------
mkdir -p "$TMP/bin"
cat > "$TMP/bin/gh" <<'GH'
#!/usr/bin/env bash
# Minimal fake gh for the drift-check tests. Behaviour is driven entirely by FAKE_* env vars so a
# single stub serves every scenario. Only the exact calls baseline-lib.sh makes are handled.
if [ "$1" = "--version" ]; then echo "gh version 0.0.0 (fake)"; exit 0; fi
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi
if [ "$1" = "api" ]; then
  shift
  path=""
  jq=""
  method="GET"
  while [ $# -gt 0 ]; do
    case "$1" in
      --jq) shift; jq="${1:-}" ;;
      -X) shift; method="${1:-GET}" ;;
      --input|-f) shift ;;
      -*) ;;
      *) path="$1" ;;
    esac
    shift
  done
  if [ -n "${FAKE_GH_LOG:-}" ]; then
    printf '%s\t%s\n' "$method" "$path" >> "$FAKE_GH_LOG"
  fi
  case "$path" in
    repos/*/rulesets/*)
      if [ "${FAKE_EXACT_RULESET_MISSING:-0}" = "1" ]; then
        echo "gh: Not Found (HTTP 404)" >&2
        exit 1
      fi
      requested_id="${path##*/}"
      repo_path="${path%/rulesets/*}"
      full_name="${repo_path#repos/}"
      if [ "$method" = "PUT" ]; then
        response_id="${FAKE_PUT_RULESET_RESPONSE_ID:-$requested_id}"
        [ -z "${FAKE_MUTATION_MARKER:-}" ] || : >"$FAKE_MUTATION_MARKER"
        printf '{"id":%s,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"active","source_type":"Repository","source":"%s"}\n' \
          "$response_id" "$full_name"
        exit 0
      else
        response_id="${FAKE_EXACT_RULESET_RESPONSE_ID:-$requested_id}"
      fi
      FAKE_RESPONSE_ID="$response_id" FAKE_RESPONSE_REPO="$full_name" python3 -c '
import json, os
value = json.loads(os.environ["FAKE_RULESET_JSON"])
value.update({
    "id": int(os.environ["FAKE_RESPONSE_ID"]),
    "name": os.environ.get("FAKE_EXACT_RULESET_NAME", "kleinperkins-merge-safety"),
    "target": os.environ.get("FAKE_EXACT_RULESET_TARGET", "branch"),
    "enforcement": "active",
    "source_type": "Repository",
    "source": os.environ.get("FAKE_EXACT_RULESET_SOURCE", os.environ["FAKE_RESPONSE_REPO"]),
})
if "FAKE_BYPASS" in os.environ:
    value["bypass_actors"] = (
        [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
        if os.environ["FAKE_BYPASS"] == "1"
        else []
    )
marker = os.environ.get("FAKE_MUTATION_MARKER")
drift = os.environ.get("FAKE_REREAD_DRIFT")
if marker and os.path.exists(marker):
    if drift == "missing-required-check":
        for rule in value["rules"]:
            if rule.get("type") == "required_status_checks":
                rule["parameters"]["required_status_checks"] = []
    elif drift == "missing-non-required-rule":
        value["rules"] = [rule for rule in value["rules"] if rule.get("type") != "deletion"]
    elif drift == "missing-bypass":
        value["bypass_actors"] = []
print(json.dumps(value, separators=(",", ":")))
'
      exit 0 ;;
    repos/*/rulesets|repos/*/rulesets\?*)
      if [ "$method" = "POST" ]; then
        full_name="${path#repos/}"
        full_name="${full_name%/rulesets}"
        [ -z "${FAKE_MUTATION_MARKER:-}" ] || : >"$FAKE_MUTATION_MARKER"
        printf '{"id":%s,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"active","source_type":"Repository","source":"%s","bypass_actors":[]}\n' \
          "${FAKE_CREATED_RULESET_ID:-999999}" "$full_name"
        exit 0
      fi
      page="${path##*page=}"
      [ "$page" != "$path" ] || page=1
      if [ "$page" = "2" ] && {
        [ "${FAKE_PAGE2_DUPLICATE:-0}" = "1" ] ||
        { [ "${FAKE_POST_CREATE_PAGE2_DUPLICATE:-0}" = "1" ] &&
          [ -n "${FAKE_MUTATION_MARKER:-}" ] && [ -e "$FAKE_MUTATION_MARKER" ]; }
      }; then
        printf '[{"id":777,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"disabled"}]\n'
      elif [ "$page" != "1" ]; then
        printf '[]\n'
      elif [ "${FAKE_PAGE2_DUPLICATE:-0}" = "1" ]; then
        FAKE_PRIMARY_RULESET_ID="${FAKE_RULESET_LIST_ID:-18819090}" python3 -c '
import json, os
values = [{
    "id": int(os.environ["FAKE_PRIMARY_RULESET_ID"]),
    "name": "kleinperkins-merge-safety",
    "target": "branch",
    "enforcement": "active",
}]
values.extend({
    "id": 30000000 + index,
    "name": "unrelated-%d" % index,
    "target": "branch",
    "enforcement": "active",
} for index in range(99))
print(json.dumps(values, separators=(",", ":")))
'
      elif [ "${FAKE_POST_CREATE_PAGE2_DUPLICATE:-0}" = "1" ] &&
        [ -n "${FAKE_MUTATION_MARKER:-}" ] && [ -e "$FAKE_MUTATION_MARKER" ]; then
        FAKE_PRIMARY_RULESET_ID="${FAKE_CREATED_RULESET_ID:-999999}" python3 -c '
import json, os
values = [{
    "id": int(os.environ["FAKE_PRIMARY_RULESET_ID"]),
    "name": "kleinperkins-merge-safety",
    "target": "branch",
    "enforcement": "active",
}]
values.extend({
    "id": 40000000 + index,
    "name": "unrelated-created-%d" % index,
    "target": "branch",
    "enforcement": "active",
} for index in range(99))
print(json.dumps(values, separators=(",", ":")))
'
      elif [ -n "${FAKE_MUTATION_MARKER:-}" ] && [ -e "$FAKE_MUTATION_MARKER" ] && [ "${FAKE_RULESET_ABSENT:-0}" = "1" ]; then
        printf '[{"id":%s,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"active"},{"id":111,"name":"kleinperkins-dev-baseline","target":"branch","enforcement":"active"}]\n' \
          "${FAKE_CREATED_RULESET_ID:-999999}"
      elif [ "${FAKE_RULESET_ABSENT:-0}" = "1" ]; then
        printf '[{"id":111,"name":"kleinperkins-dev-baseline"}]\n'
      elif [ "${FAKE_DUPLICATE_RULESET:-0}" = "1" ]; then
        printf '[{"id":%s,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"active"},{"id":777,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"disabled"},{"id":111,"name":"kleinperkins-dev-baseline"}]\n' \
          "${FAKE_RULESET_LIST_ID:-18819090}"
      else
        printf '[{"id":%s,"name":"kleinperkins-merge-safety","target":"branch","enforcement":"active"},{"id":111,"name":"kleinperkins-dev-baseline"}]\n' \
          "${FAKE_RULESET_LIST_ID:-18819090}"
      fi
      exit 0 ;;
    repos/*/contents/.github/pr-automation.json*)
      if [ "${FAKE_CONTENTS_ABSENT:-0}" = "1" ]; then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi
      if [ -n "${FAKE_CONTENTS_B64:-}" ]; then
        printf '{"content":"%s"}\n' "$FAKE_CONTENTS_B64"
      else
        repo_path="${path#repos/}"
        full_name="${repo_path%%/contents/*}"
        owner="${full_name%%/*}"
        name="${full_name#*/}"
        FAKE_POLICY_REPOSITORY_ID="${FAKE_POLICY_REPOSITORY_ID:-${FAKE_REPOSITORY_ID:-12345}}" \
          FAKE_POLICY_OWNER="${FAKE_POLICY_OWNER:-$owner}" \
          FAKE_POLICY_NAME="${FAKE_POLICY_NAME:-$name}" \
          FAKE_POLICY_DEFAULT_BRANCH="${FAKE_POLICY_DEFAULT_BRANCH:-${FAKE_DEFAULT_BRANCH:-main}}" \
          python3 -c '
import base64, json, os
policy = {
    "repository_id": int(os.environ["FAKE_POLICY_REPOSITORY_ID"]),
    "owner": os.environ["FAKE_POLICY_OWNER"],
    "name": os.environ["FAKE_POLICY_NAME"],
    "default_branch": os.environ["FAKE_POLICY_DEFAULT_BRANCH"],
}
print(json.dumps({"content": base64.b64encode(json.dumps(policy).encode()).decode()}))
'
      fi
      exit 0 ;;
    repos/*)
      full_name="${path#repos/}"
      case "$jq" in
        .owner.login)     echo "KleinPerkins" ;;
        .default_branch)  echo "${FAKE_DEFAULT_BRANCH:-main}" ;;
        .id)              echo "${FAKE_REPOSITORY_ID:-12345}" ;;
        *) printf '{"id":%s,"full_name":"%s","default_branch":"%s","owner":{"login":"KleinPerkins"}}\n' \
             "${FAKE_REPOSITORY_ID:-12345}" "${FAKE_FULL_NAME:-$full_name}" \
             "${FAKE_DEFAULT_BRANCH:-main}" ;;
      esac
      exit 0 ;;
  esac
  echo "fake gh: unhandled api path: $path" >&2
  exit 1
fi
echo "fake gh: unhandled: $*" >&2
exit 1
GH
chmod +x "$TMP/bin/gh"
export PATH="$TMP/bin:$PATH"
# Hermeticity: each scenario runs `bash repo-baseline.sh`, and a non-interactive bash
# sources $BASH_ENV at startup. A "keep Homebrew ahead in non-login shells" PATH shim
# there re-prepends the real gh in front of "$TMP/bin", defeating the stub and letting
# mocked reconcile calls escape to live GitHub. Unset it so the stub stays authoritative
# (matches the clean CI environment).
unset BASH_ENV ENV

# shellcheck source=../../../../bin/baseline-lib.sh
. "$DEV_ROOT/_ops/bin/baseline-lib.sh"
export BL_GH_TIMEOUT=5

FAUX="KleinPerkins/faux"
REMOTE_TARGET="KleinPerkins/awa"
FAKE_RULESET_JSON="$(bl_render_merge_safety main 1289571438 "$REMOTE_TARGET")"
export FAKE_RULESET_JSON

echo "== shared merge-safety resolver wiring =="
render_source="$(declare -f bl_render_merge_safety)"
assert_contains "$render_source" "profile.py" \
  "reconcile render delegates to the profile.py repository resolver"
assert_not_contains "$render_source" "sed " \
  "reconcile has no forked template-only render path"

echo "== bl_check_bypass_missing (mocked) =="
# NOTE: a `FAKE=1 assert_eq "$(cmd)"` prefix does NOT reach the child `gh` — the command
# substitution is expanded in the current env before the prefix applies. Export instead.
export FAKE_REPOSITORY_ID=1289571438 FAKE_BYPASS=0
assert_eq "$(bl_check_bypass_missing "$REMOTE_TARGET" | cut -f1)" "BYPASS_MISSING" "fail-before: empty bypass_actors -> BYPASS_MISSING"
export FAKE_BYPASS=1
assert_eq "$(bl_check_bypass_missing "$REMOTE_TARGET" | cut -f1)" "CLEAN"          "pass-after: RepositoryRole:5 bypass -> CLEAN"
export FAKE_EXACT_RULESET_MISSING=1
assert_eq "$(bl_check_bypass_missing "$REMOTE_TARGET" | cut -f1)" "UNKNOWN" \
  "missing exact authority ruleset -> UNKNOWN"
assert_eq "$(bl_check_bypass_missing "" | cut -f1)" "UNKNOWN" "no owner/repo -> UNKNOWN"
unset FAKE_EXACT_RULESET_MISSING FAKE_BYPASS

echo "== bl_check_stale_fingerprint (mocked) =="
APP_VISIBLE_JSON="$(bl_app_visible_fingerprints 1289571438 "KleinPerkins/awa" main)"
[ -n "$APP_VISIBLE_JSON" ] || { echo "  FAIL  could not read APP_VISIBLE from controller.json"; exit 1; }
current_b64="$(APP_VISIBLE_JSON="$APP_VISIBLE_JSON" python3 -c '
import base64, json, os
fps = json.loads(os.environ["APP_VISIBLE_JSON"])
policy = {
    "repository_id": 1289571438,
    "owner": "KleinPerkins",
    "name": "awa",
    "default_branch": "main",
    "ruleset_fingerprints": fps,
}
print(base64.b64encode(json.dumps(policy).encode()).decode())
')"
stale_b64="$(APP_VISIBLE_JSON="$APP_VISIBLE_JSON" python3 -c '
import base64, json, os
fps = json.loads(os.environ["APP_VISIBLE_JSON"]) + ["sha256:0000000000000000000000000000000000000000000000000000000000000000"]
policy = {
    "repository_id": 1289571438,
    "owner": "KleinPerkins",
    "name": "awa",
    "default_branch": "main",
    "ruleset_fingerprints": fps,
}
print(base64.b64encode(json.dumps(policy).encode()).decode())
')"
wrong_policy_identity_b64="$(APP_VISIBLE_JSON="$APP_VISIBLE_JSON" python3 -c '
import base64, json, os
policy = {
    "repository_id": 1289571438,
    "owner": "KleinPerkins",
    "name": "awa",
    "default_branch": "trunk",
    "ruleset_fingerprints": json.loads(os.environ["APP_VISIBLE_JSON"]),
}
print(base64.b64encode(json.dumps(policy).encode()).decode())
')"
export FAKE_CONTENTS_ABSENT=0 FAKE_CONTENTS_B64="$stale_b64"
assert_eq "$(bl_check_stale_fingerprint "$REMOTE_TARGET" | cut -f1)" "STALE_FINGERPRINT" "fail-before: extra fingerprint -> STALE_FINGERPRINT"
export FAKE_CONTENTS_B64="$current_b64"
assert_eq "$(bl_check_stale_fingerprint "$REMOTE_TARGET" | cut -f1)" "CLEAN"             "pass-after: matches APP_VISIBLE -> CLEAN"
export FAKE_CONTENTS_B64="$wrong_policy_identity_b64"
assert_eq "$(bl_check_stale_fingerprint "$REMOTE_TARGET" | cut -f1)" "UNKNOWN" \
  "deployed policy identity drift fails closed"
export FAKE_CONTENTS_ABSENT=1
assert_eq "$(bl_check_stale_fingerprint "$REMOTE_TARGET" | cut -f1)" "NOT_STAGED"        "no deployed policy -> NOT_STAGED"
assert_eq "$(bl_check_stale_fingerprint "" | cut -f1)" "UNKNOWN" "no owner/repo -> UNKNOWN"
unset FAKE_CONTENTS_ABSENT FAKE_CONTENTS_B64

echo "== retired reconciliation refuses before API calls =="
repo="$TMP/retired-fixture"
git init -q "$repo"
git -C "$repo" remote add origin git@github.com:KleinPerkins/awa.git
for mode in normal dry-run create; do
  args=()
  [ "$mode" != dry-run ] || args+=(--dry-run)
  [ "$mode" != create ] || args+=(--create)
  output="$(bash "$DEV_ROOT/_ops/bin/repo-baseline.sh" reconcile-merge-safety "$repo" ${args[@]+"${args[@]}"} 2>&1 || true)"
  assert_contains "$output" "REFUSED" "$mode retired reconcile refuses"
  assert_contains "$output" "retired controller" "$mode names the retired boundary"
done
if [ "$fail" -eq 0 ]; then
  echo "historical bypass observations and retirement refusals: PASS"
else
  echo "historical bypass observations and retirement refusals: FAIL"
  exit 1
fi
