#!/usr/bin/env bash
# _ops/eco/manifest.sh — read / validate / plan / scaffold a per-artifact meta.yml (WS-1).
#
# Subcommands:
#   validate <artifact-dir>   exit 0 if the manifest is valid, else 1 (+ reasons)
#   scope    <artifact-dir>   print inferred scope (global|local|unknown) from the path
#   plan     <artifact-dir>   print the inferred local + remote plumbing (the directory paradigm)
#   scaffold [artifact-dir] --flavor N --scope S --kind K --id ID [--shape SHAPE]
#            [--sync-policy none|record-only|standalone-release] [--source SRC]
#                            write a meta.yml (+ stub install.sh if missing)
#   scaffold-standalone-tool <id> [--scope global] [--source SRC] [--ref SHA]
#                            scaffold a Flavor-2 standalone-release GCB shelf (SSP binding)
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib.sh
. "$SELF_DIR/lib.sh"

usage() { sed -n '2,15p' "$0"; }

_meta_path() { printf '%s/meta.yml' "$1"; }

cmd_validate() {
  local dir="$1" meta; meta="$(_meta_path "$dir")"
  local errs=0
  err() { printf '  FAIL  %s\n' "$1"; errs=1; }
  ok()  { printf '  PASS  %s\n' "$1"; }
  [ -d "$dir" ] || { err "not a directory: $dir"; return 1; }
  [ -f "$meta" ] || { err "missing meta.yml in $dir"; return 1; }

  local schema id kind flavor scope install src dirscope shelf expected_shelf shape sync_policy
  schema="$(eco_meta_get "$meta" schema)"
  id="$(eco_meta_get "$meta" id)"
  kind="$(eco_meta_get "$meta" kind)"
  flavor="$(eco_meta_get "$meta" flavor)"
  scope="$(eco_meta_get "$meta" scope)"
  install="$(eco_meta_get "$meta" install)"
  src="$(eco_meta_get "$meta" provenance_source)"
  dirscope="$(eco_scope_of_dir "$dir")"
  shelf="$(eco_shelf_of_dir "$dir")"
  expected_shelf="$(eco_kind_shelf "$kind")"
  shape="$(eco_meta_get "$meta" shape)"
  sync_policy="$(eco_meta_get "$meta" sync_policy)"

  [ "$schema" = "kp-capability/v1" ] && ok "schema $schema" || err "schema must be kp-capability/v1 (got '$schema')"
  [ -n "$id" ] && ok "id $id" || err "id empty"
  case "$kind" in skill|mcp|rule|tool|workflow|sub-agent|asset|doc) ok "kind $kind" ;; *) err "kind must be one of skill|mcp|rule|tool|workflow|sub-agent|asset|doc (got '$kind')" ;; esac
  case "$flavor" in 1|2) ok "flavor $flavor" ;; *) err "flavor must be 1|2 (got '$flavor')" ;; esac
  case "$scope" in global|local) ok "scope $scope" ;; *) err "scope must be global|local (got '$scope')" ;; esac
  # Scope-paradigm enforcement (Option A; 2026-06-26):
  #   * Eco-owned roots use the directory paradigm: scope MUST match the containing dir.
  #   * Independently-governed sibling repos whose layout we don't dictate (today: kp-mcp at
  #     capabilities/mcp/) carry a flat artifact root. For those, eco_scope_of_dir returns
  #     'unknown'; we then HARD-GATE on the manifest's explicit scope:
  #       - kind:mcp under an unknown-scope dir MUST declare scope:global (no mcp/local
  #         partition exists today; vendor.sh refuses non-global masters as defense in depth).
  if [ "$dirscope" != "unknown" ]; then
    if [ "$scope" = "$dirscope" ]; then
      ok "scope matches containing dir ($dirscope)"
    else
      err "scope '$scope' does not match containing dir ('$dirscope')"
    fi
  else
    # dirscope unknown -> apply kind-specific gate.
    case "$kind" in
      mcp)
        if [ "$scope" = "global" ]; then
          ok "scope:global gated for kind:mcp under sibling-repo root (no mcp/local today)"
        else
          err "kind:mcp under capabilities/mcp/ must declare scope: global (got '$scope'); no mcp/local partition exists"
        fi ;;
      *)
        ok "scope $scope (dir is scope-agnostic; manifest is authoritative)" ;;
    esac
  fi
  if [ "$dirscope" != "unknown" ] && [ "$shelf" != "unknown" ]; then
    case "$shelf" in skills|rules|sub-agents|tools) ok "known shelf $shelf" ;; *) err "unknown shelf '$shelf' (allowed: skills|rules|sub-agents|tools)" ;; esac
    if [ -n "$expected_shelf" ]; then
      [ "$shelf" = "$expected_shelf" ] && ok "shelf matches kind ($shelf)" || err "kind '$kind' belongs on shelf '$expected_shelf' (got '$shelf')"
    fi
  fi
  case "$install" in
    "")       err "install contract missing (empty)" ;;
    *..*|*/*) err "install must be a bare filename inside the artifact dir (got '$install')" ;;
    *) if [ -f "$dir/$install" ]; then
         [ -x "$dir/$install" ] && ok "install $install present + executable" || err "install $install not executable"
       else err "install contract missing ($dir/$install)"; fi ;;
  esac
  local pm; pm="$(eco_meta_get "$meta" post_mgmt)"
  case "${pm:-none}" in none|launchd|cron|systemd) ok "post_mgmt ${pm:-none}" ;; *) err "post_mgmt must be none|launchd|cron|systemd (got '$pm')" ;; esac
  if [ "$flavor" = "2" ]; then
    [ -n "$src" ] && ok "provenance_source $src" || err "flavor 2 requires provenance_source"
  fi
  case "$kind" in
    skill) [ -f "$dir/SKILL.md" ] && ok "payload SKILL.md present" || err "skill payload requires SKILL.md" ;;
    rule) [ -f "$dir/$id.mdc" ] && ok "payload $id.mdc present" || err "rule payload requires $id.mdc" ;;
    sub-agent) [ -f "$dir/$id.md" ] && ok "payload $id.md present" || err "sub-agent payload requires $id.md" ;;
    tool)
      [ -f "$dir/tool.yml" ] && ok "payload tool.yml present" || err "tool payload requires tool.yml"
      case "$shape" in snapshot|release-descriptor|descriptor-only) ok "tool shape $shape" ;; *) err "tool requires shape snapshot|release-descriptor|descriptor-only (got '$shape')" ;; esac
      # Flavor-2 sync_policy taxonomy (MANIFEST-CONTRACT split, 2026-07-05):
      #   none | record-only     the shelf records a pin/descriptor and installs NO runtime bytes.
      #   standalone-release      a Global Capability Binding (GCB) to a Standalone System Package
      #                           (SSP): install.sh clones the pinned release, then delegates to the
      #                           release's OWN install.sh. Fetching git + exec'ing the pinned
      #                           installer is its whole contract — it carries the pinned pointer,
      #                           never the runtime bytes (those live in the standalone repo).
      case "$sync_policy" in
        none|record-only|standalone-release|"") ok "tool sync_policy ${sync_policy:-<absent>}" ;;
        *) err "tool sync_policy must be none|record-only|standalone-release (got '$sync_policy')" ;;
      esac
      # The "no fetch / no PATH-install / no chmod-exec / no exec" prohibition applies ONLY to a
      # record-only shelf (which installs nothing). A standalone-release GCB is EXEMPT by design:
      # clone-at-pin + delegate to the release installer is exactly what it is supposed to do.
      if [ "$sync_policy" = "record-only" ]; then
        [ ! -d "$dir/bin" ] && ok "record-only tool has no bin/" || err "record-only tool must not carry bin/"
        if grep -REnI '(curl|wget|PATH=|/usr/local/bin|~/\.local/bin|chmod[[:space:]]+\+x|exec[[:space:]])' "$dir/install.sh" "$dir/tool.yml" 2>/dev/null; then
          err "record-only tool must not fetch, PATH-install, chmod executable, or exec"
        else
          ok "record-only tool has no executable install claims"
        fi
      elif [ "$sync_policy" = "standalone-release" ]; then
        [ -f "$dir/install.sh" ] && ok "standalone-release GCB (clone-at-pin + delegate to the release installer)" || err "standalone-release GCB requires an install.sh (the binding)"
        [ -n "$src" ] || err "standalone-release GCB requires provenance_source (the release repo)"
      fi
      ;;
  esac
  return "$errs"
}

cmd_scope() { eco_scope_of_dir "$1"; }

cmd_plan() {
  local dir="$1" meta; meta="$(_meta_path "$dir")"
  [ -f "$meta" ] || { eco_err "no meta.yml in $dir"; return 1; }
  local id kind flavor scope src ref
  id="$(eco_meta_get "$meta" id)"; kind="$(eco_meta_get "$meta" kind)"
  flavor="$(eco_meta_get "$meta" flavor)"
  # Directory is the source of truth for scope (D-2); fall back to the manifest only if the path is ambiguous.
  scope="$(eco_scope_of_dir "$dir")"; [ "$scope" = unknown ] && scope="$(eco_meta_get "$meta" scope)"
  src="$(eco_meta_get "$meta" provenance_source)"; ref="$(eco_meta_get "$meta" provenance_ref)"
  printf 'artifact   : %s (%s, flavor %s, scope %s)\n' "$id" "$kind" "$flavor" "$scope"
  # Inferred REMOTE plumbing (where commits/pushes go) — driven purely by scope (the paradigm).
  if [ "$scope" = "global" ]; then
    case "$kind" in
      mcp) printf 'remote     : KleinPerkins/kp-mcp (global master)\n' ;;
      *)   printf 'remote     : KleinPerkins/skills (global master)\n' ;;
    esac
    printf 'shared->cpp: YES (orchestrator vendors an ld-agnostic copy into cpp quiver)\n'
  else
    printf 'remote     : the artifact'\''s own/local workspace repo (NOT shared to cpp)\n'
    printf 'shared->cpp: no\n'
  fi
  # Inferred LOCAL plumbing (what install does).
  if [ "$flavor" = "1" ]; then
    printf 'local setup: Flavor-1 — symlink master into ~/.cursor /.claude /.codex per install.sh\n'
  else
    printf 'local setup: Flavor-2 — clone/pull %s @ %s + install post-mgmt, then expose per install.sh\n' "${src:-<source>}" "${ref:-<ref>}"
  fi
}

cmd_scaffold() {
  local dir=""
  if [ $# -gt 0 ] && [[ "${1:-}" != --* ]]; then dir="$1"; shift; fi
  local flavor="1" scope="" kind="skill" id="" source="" shape="" sync_policy="" shelf="" dirscope="" dirshelf=""
  while [ $# -gt 0 ]; do case "$1" in
    --flavor)      shift; flavor="$1" ;;
    --scope)       shift; scope="$1" ;;
    --kind)        shift; kind="$1" ;;
    --id)          shift; id="$1" ;;
    --shape)       shift; shape="$1" ;;
    --sync-policy) shift; sync_policy="$1" ;;
    --source)      shift; source="$1" ;;
    *) eco_err "unknown scaffold flag $1"; return 2 ;;
  esac; shift; done
  [ -n "$id" ] || { [ -n "$dir" ] && id="$(basename "$dir")"; }
  [ -n "$id" ] || { eco_err "id required (pass --id)"; return 2; }
  [ -n "$scope" ] || scope="$(eco_scope_of_dir "$dir")"
  case "$scope" in global|local) : ;; *) eco_err "scope unknown; pass --scope global|local"; return 2 ;; esac
  # Tool-kind Flavor-2 sync_policy: default record-only; a standalone-release GCB is a first-class
  # shape (clone-at-pin + delegate to a Standalone System Package's own installer).
  if [ "$kind" = "tool" ]; then
    case "$sync_policy" in
      "") sync_policy="record-only" ;;
      none|record-only|standalone-release) : ;;
      *) eco_err "tool --sync-policy must be none|record-only|standalone-release (got '$sync_policy')"; return 2 ;;
    esac
    if [ "$sync_policy" = "standalone-release" ]; then
      [ -n "$shape" ] || shape="release-descriptor"
      [ "$flavor" = "2" ] || { eco_err "standalone-release tool must be --flavor 2 (a GCB to a pinned release)"; return 2; }
      [ -n "$source" ] || eco_warn "standalone-release tool: set provenance_source (the release repo) + provenance_ref (the pin) before use"
    fi
  fi
  if [ -z "$dir" ]; then
    shelf="$(eco_kind_shelf "$kind")"
    [ -n "$shelf" ] || { eco_err "scaffold supports kind skill|rule|sub-agent|tool for kind shelves (got '$kind')"; return 2; }
    dir="$ECO_REPO_ROOT/capabilities/skills/$scope/$shelf/$id"
  else
    shelf="$(eco_kind_shelf "$kind")"
    [ -n "$shelf" ] || { eco_err "scaffold supports kind skill|rule|sub-agent|tool for kind shelves (got '$kind')"; return 2; }
    dirscope="$(eco_scope_of_dir "$dir")"
    dirshelf="$(eco_shelf_of_dir "$dir")"
    if [ "$dirscope" != "unknown" ] && [ "$dirshelf" != "$shelf" ]; then
      eco_err "explicit scaffold dir must include the kind shelf: expected $dirscope/$shelf/<id>, got shelf '$dirshelf'"
      return 2
    fi
  fi
  mkdir -p "$dir"
  local meta; meta="$(_meta_path "$dir")"
  {
    printf 'schema: kp-capability/v1\n'
    printf 'id: %s\n' "$id"
    printf 'kind: %s\n' "$kind"
    printf 'flavor: %s\n' "$flavor"
    printf 'scope: %s\n' "$scope"
    printf 'owner: %s\n' "${OM_GH_USER:-KleinPerkins}"
    printf 'install: install.sh\n'
    printf 'post_mgmt: none\n'
    [ "$kind" = "tool" ] && printf 'shape: %s\n' "${shape:-descriptor-only}"
    [ "$kind" = "tool" ] && printf 'sync_policy: %s\n' "${sync_policy:-record-only}"
    printf 'provenance_source: "%s"\n' "$source"
    printf 'provenance_ref: ""\n'
    printf 'provenance_trust: ""\n'
  } > "$meta"
  if [ ! -f "$dir/install.sh" ]; then
    cat > "$dir/install.sh" <<'INSTALL'
#!/usr/bin/env bash
# install.sh — idempotent local install for this artifact (WS-1 contract stub).
set -euo pipefail
exit 0
INSTALL
    chmod +x "$dir/install.sh"
  fi
  case "$kind" in
    skill) [ -f "$dir/SKILL.md" ] || printf '# %s\n' "$id" > "$dir/SKILL.md" ;;
    rule) [ -f "$dir/$id.mdc" ] || printf '# %s\n' "$id" > "$dir/$id.mdc" ;;
    sub-agent) [ -f "$dir/$id.md" ] || printf '# %s\n' "$id" > "$dir/$id.md" ;;
    tool) [ -f "$dir/tool.yml" ] || printf 'id: %s\nshape: %s\nsync_policy: %s\n' "$id" "${shape:-descriptor-only}" "${sync_policy:-record-only}" > "$dir/tool.yml" ;;
  esac
  eco_log "scaffolded $meta (flavor $flavor, scope $scope, kind $kind)"
}

# Convenience wrapper: scaffold a Flavor-2 standalone-release GCB (the SSP+GCB paradigm) in one verb.
cmd_scaffold_standalone_tool() {
  local id="" source="" ref="" scope="global"
  if [ $# -gt 0 ] && [[ "${1:-}" != --* ]]; then id="$1"; shift; fi
  while [ $# -gt 0 ]; do case "$1" in
    --id)     shift; id="$1" ;;
    --source) shift; source="$1" ;;
    --ref)    shift; ref="$1" ;;
    --scope)  shift; scope="$1" ;;
    *) eco_err "unknown scaffold-standalone-tool flag $1"; return 2 ;;
  esac; shift; done
  [ -n "$id" ] || { eco_err "scaffold-standalone-tool requires <id>"; return 2; }
  cmd_scaffold --kind tool --flavor 2 --scope "$scope" --id "$id" \
    --shape release-descriptor --sync-policy standalone-release --source "$source" || return $?
  if [ -n "$ref" ]; then
    local meta; meta="$ECO_REPO_ROOT/capabilities/skills/$scope/tools/$id/meta.yml"
    [ -f "$meta" ] && { sed -i.bak 's|^provenance_ref: .*|provenance_ref: "'"$ref"'"|' "$meta"; rm -f "$meta.bak"; eco_log "pinned provenance_ref=$ref in $meta"; }
  fi
}

main() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    validate) [ $# -ge 1 ] || { usage; exit 2; }; cmd_validate "$1" ;;
    scope)    [ $# -ge 1 ] || { usage; exit 2; }; cmd_scope "$1" ;;
    plan)     [ $# -ge 1 ] || { usage; exit 2; }; cmd_plan "$1" ;;
    scaffold) [ $# -ge 1 ] || { usage; exit 2; }; cmd_scaffold "$@" ;;
    scaffold-standalone-tool) [ $# -ge 1 ] || { usage; exit 2; }; cmd_scaffold_standalone_tool "$@" ;;
    -h|--help|"") usage ;;
    *) eco_err "unknown subcommand: $sub"; usage; exit 2 ;;
  esac
}
main "$@"
