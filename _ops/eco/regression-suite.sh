#!/usr/bin/env bash
# _ops/eco/regression-suite.sh — full-coverage reorg-v2 regression suite (Phase 4).
#
# One runnable gate over the whole ecosystem operating model. Hermetic where possible (tmpdirs,
# isolated $HOME); reuses the real verifier/gate scripts elsewhere. Coverage:
#   manifests/flavor · INV-zero-link · sync repair/replace/rebuild(+backup+confirm+sentinel) ·
#   orchestrator vendor add/delete + zero-link abort · dedup symlink(+idempotent+tracked-guard) ·
#   trigger firing (session-hook fail-open + installed artifacts) · self-heal · clean-room fresh
#   clone+install gate.
# Exit 0 = all green. ECO_KEEP_TMP=1 keeps scratch dirs.
# ECO_RS_HERMETIC_ONLY=1 restricts the suite to the SELF-CONTAINED fixture tests that pass on a bare
#   KleinPerkins/dev checkout (CI): manifest scaffold/validate + sync repair/replace/rebuild. It SKIPS
#   the gates that need sibling repos or the installed env (verify-manifests over managed roots,
#   self-heal, clean-room). The orchestrator/trigger sections already self-skip when the orchestrator
#   repo is absent. ECO_RS_SKIP_CLEANROOM=1 skips only the clean-room gate (e.g. a pre-commit run).
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$SELF_DIR/lib.sh"
ROOT="$ECO_REPO_ROOT"
ORCH="$ROOT/personal/ecosystem-orchestrator"
HERMETIC="${ECO_RS_HERMETIC_ONLY:-0}"
PASS=0 FAIL=0 SKIP=0
sec()  { printf '\n== %s ==\n' "$*"; }
T()    { local n="$1"; shift; if "$@" >/tmp/rs.$$ 2>&1; then printf '  PASS  %s\n' "$n"; PASS=$((PASS+1)); else printf '  FAIL  %s\n' "$n"; FAIL=$((FAIL+1)); sed 's/^/        | /' /tmp/rs.$$ | tail -10; fi; }
SKIPT(){ printf '  SKIP  %s\n' "$1"; SKIP=$((SKIP+1)); }
prompt_master() {
  printf '%s\n' "$ROOT/capabilities/skills/global/skills/prompt-architect"
}

# ---------- sync modes (hermetic) ----------
rs_sync_modes() {
  local t; t="$(mktemp -d)"; local S="$SELF_DIR/sync.sh"
  mkdir -p "$t/src" "$t/dst"; printf 'a\n' >"$t/src/a"; printf 'b\n' >"$t/src/b"; : >"$t/dst/.eco-managed"
  printf 'OLD\n' >"$t/dst/a"; printf 'extra\n' >"$t/dst/extra"
  ECO_ARCHIVE_DIR="$t/arch" bash "$S" repair  --from "$t/src" --to "$t/dst" >/dev/null 2>&1 || { echo "repair rc!=0"; return 1; }
  [ "$(cat "$t/dst/a")" = "OLD" ] || { echo "repair overwrote a"; return 1; }     # additive only
  [ -f "$t/dst/b" ] || { echo "repair missed b"; return 1; }
  ECO_ARCHIVE_DIR="$t/arch" bash "$S" replace --from "$t/src" --to "$t/dst" >/dev/null 2>&1 || { echo "replace rc!=0"; return 1; }
  [ "$(cat "$t/dst/a")" = "a" ] || { echo "replace didn't fix a"; return 1; }      # overwrite drift
  [ -f "$t/dst/extra" ] || { echo "replace deleted undeclared"; return 1; }        # keep undeclared
  ls "$t/arch"/*.tar.gz >/dev/null 2>&1 || { echo "replace no backup"; return 1; }
  # backup-RESTORABILITY (not just presence): the archive must actually extract AND carry the
  # pre-replace content ("OLD"), so a destructive sync is genuinely recoverable.
  local ax; ax="$(ls -t "$t/arch"/*.tar.gz | head -1)"; mkdir -p "$t/restore"
  tar -xzf "$ax" -C "$t/restore" 2>/dev/null || { echo "backup not extractable"; return 1; }
  grep -qxF "OLD" "$t/restore/$(basename "$t/dst")/a" 2>/dev/null || { echo "backup missing pre-replace content (not restorable)"; return 1; }
  local rc=0; ECO_ARCHIVE_DIR="$t/arch" bash "$S" rebuild --from "$t/src" --to "$t/dst" >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || { echo "rebuild ran without --confirm"; return 1; }            # refuse w/o confirm
  ECO_ARCHIVE_DIR="$t/arch" bash "$S" rebuild --from "$t/src" --to "$t/dst" --confirm >/dev/null 2>&1 || { echo "rebuild --confirm rc!=0"; return 1; }
  [ ! -f "$t/dst/extra" ] || { echo "rebuild kept undeclared"; return 1; }          # delete undeclared
  mkdir -p "$t/dst-unmanaged"; local rc2=0                                          # no .eco-managed sentinel
  bash "$S" replace --from "$t/src" --to "$t/dst-unmanaged" >/dev/null 2>&1 || rc2=$?
  [ "$rc2" -ne 0 ] || { echo "sentinel guard didn't fire"; return 1; }             # no sentinel => refuse
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$t"; return 0
}

# ---------- manifest scaffold + validate (flavor handling) ----------
rs_manifest() {
  local t; t="$(mktemp -d)/global/skills/demo-skill"; mkdir -p "$t"
  bash "$SELF_DIR/manifest.sh" scaffold "$t" --id demo-skill --kind skill --flavor 1 --scope global >/dev/null 2>&1 || { echo "scaffold failed"; return 1; }
  [ -f "$t/meta.yml" ] || { echo "no meta.yml scaffolded"; return 1; }
  bash "$SELF_DIR/manifest.sh" validate "$t" >/dev/null 2>&1 || { echo "validate failed"; return 1; }
  [ "$(bash "$SELF_DIR/manifest.sh" scope "$t")" = "global" ] || { echo "scope!=global"; return 1; }
  local flat; flat="$(mktemp -d)/global/demo-flat"; mkdir -p "$flat"
  if bash "$SELF_DIR/manifest.sh" scaffold "$flat" --id demo-flat --kind skill --flavor 1 --scope global >/dev/null 2>&1; then
    echo "explicit flat scaffold unexpectedly succeeded"; return 1
  fi
  local tool; tool="$(mktemp -d)/global/tools/demo-tool"; mkdir -p "$tool"
  bash "$SELF_DIR/manifest.sh" scaffold "$tool" --id demo-tool --kind tool --flavor 1 --scope global --shape descriptor-only >/dev/null 2>&1 || { echo "tool scaffold failed"; return 1; }
  printf 'export PATH="$HOME/.local/bin:$PATH"\n' >> "$tool/install.sh"
  if bash "$SELF_DIR/manifest.sh" validate "$tool" >/dev/null 2>&1; then
    echo "record-only tool executable install claim unexpectedly passed"; return 1
  fi
  return 0
}

# ---------- SSP + GCB standalone-release smoke (hermetic) ----------
# Asserts the Standalone System Paradigm manifest contract (Part 0): a Flavor-2 standalone-release
# GCB scaffolds with shape=release-descriptor, validates, and — UNLIKE a record-only shelf — is
# EXEMPT from the "no fetch/exec" prohibition (clone-at-pin + delegate to the release's own installer
# is its entire contract). Toggling ONLY the sync_policy on the SAME exec-bearing install.sh flips
# the verdict, proving the prohibition is scoped to record-only. Self-contained (CI/hermetic-safe).
rs_ssp() {
  local M="$SELF_DIR/manifest.sh" base; base="$(mktemp -d)"
  local t="$base/global/tools/demo-ssp"; mkdir -p "$t"
  bash "$M" scaffold "$t" --id demo-ssp --kind tool --flavor 2 --scope global \
      --sync-policy standalone-release --source github.com/KleinPerkins/demo >/dev/null 2>&1 \
      || { echo "standalone-release scaffold failed"; return 1; }
  grep -q '^sync_policy: *standalone-release' "$t/meta.yml" || { echo "meta sync_policy not standalone-release"; return 1; }
  grep -q '^shape: *release-descriptor' "$t/meta.yml" || { echo "meta shape default not release-descriptor"; return 1; }
  # A GCB install.sh legitimately clones (git) + EXECs the pinned release's own installer.
  cat > "$t/install.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
git clone --quiet "$SRC" "$CHECKOUT"
exec bash "$CHECKOUT/install.sh" "$@"
SH
  bash "$M" validate "$t" >/dev/null 2>&1 || { echo "standalone-release GCB with clone+exec failed validate (exemption missing)"; return 1; }
  # Flip ONLY sync_policy to record-only; the SAME exec-bearing install.sh must now be REJECTED.
  sed -i.bak 's/^sync_policy: *standalone-release/sync_policy: record-only/' "$t/meta.yml"; rm -f "$t/meta.yml.bak"
  if bash "$M" validate "$t" >/dev/null 2>&1; then echo "record-only tool with exec unexpectedly validated (prohibition not scoped)"; return 1; fi
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$base"; return 0
}

# ---------- orchestrator vendor add/delete/zero-link (hermetic fixture) ----------
rs_vendor() {
  local VEN="$ORCH/lib/vendor.sh" f; f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts quiver/skills && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  bash "$VEN" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "vendor add rc!=0"; return 1; }
  [ -f "$f/quiver/skills/prompt-architect/meta.yml" ] || { echo "no translated meta"; return 1; }
  [ -f "$f/quiver/skills/prompt-architect/install.sh" ] && { echo "ld-mgmt install.sh leaked"; return 1; }
  bash "$VEN" --delete --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "vendor delete rc!=0"; return 1; }
  [ -d "$f/quiver/skills/prompt-architect" ] && { echo "delete left dir"; return 1; }
  # zero-link abort on a dirty payload
  local d; d="$(mktemp -d)/g/dirty"; mkdir -p "$d"; printf 'see ~/dev/capabilities\n' >"$d/SKILL.md"
  if ( . "$ORCH/lib/common.sh"; orch_zero_link cpp "$d" ) >/dev/null 2>&1; then echo "zero-link missed dirty"; return 1; fi
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f"; return 0
}

# ---------- dedup: Decision-A contract (symlink-dedup ABANDONED) ----------
# Decision A retired live symlink-dedup. The dedup engine must now REFUSE --apply/--reassert (rc=3,
# no symlink created) and retain only --reverse to un-arm a pre-Decision-A symlink. Master<->payload
# integrity is enforced by the consistency verify (tested separately in rs_consistency).
rs_dedup() {
  local DD="$ORCH/lib/dedup.sh" m; m="$(prompt_master)"; local rel="quiver/skills/prompt-architect"
  # (1) --apply is HARD-DISABLED: rc=3 and NO symlink is created.
  local a rc=0; a="$(mktemp -d)"; mkdir -p "$a/$rel"; printf 'x\n' >"$a/$rel/SKILL.md"
  bash "$DD" --apply --cpp-dir "$a" prompt-architect >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 3 ] || { echo "apply not hard-disabled (rc=$rc)"; return 1; }
  [ -L "$a/$rel" ] && { echo "apply created a symlink (should be disabled)"; return 1; }
  # (2) --reassert is HARD-DISABLED too.
  local rc2=0; bash "$DD" --reassert --cpp-dir "$a" prompt-architect >/dev/null 2>&1 || rc2=$?
  [ "$rc2" -eq 3 ] || { echo "reassert not hard-disabled (rc=$rc2)"; return 1; }
  # (3) --reverse un-arms a LEGACY tracked symlink: build a tracked vendored copy, arm it by hand
  #     (skip-worktree + symlink, simulating a pre-Decision-A machine), then reverse it to pristine.
  local g; g="$(mktemp -d)"
  ( cd "$g" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p "$rel/assets" && printf 'SKILL vendored\n' >"$rel/SKILL.md" && printf 't\n' >"$rel/assets/t.txt" \
      && git add -A && git commit -qm i )
  ( cd "$g" && git ls-files -z -- "$rel" | git update-index --skip-worktree -z --stdin \
      && rm -rf "$rel" && ln -s "$m" "$rel" )   # arm a legacy symlink
  [ -L "$g/$rel" ] || { echo "fixture: legacy symlink not armed"; return 1; }
  bash "$DD" --reverse --cpp-dir "$g" prompt-architect >/dev/null 2>&1 || { echo "reverse rc!=0"; return 1; }
  [ -L "$g/$rel" ] && { echo "reverse: still a symlink"; return 1; }
  [ "$(cat "$g/$rel/SKILL.md")" = "SKILL vendored" ] || { echo "reverse: vendored content not restored"; return 1; }
  [ -n "$(git -C "$g" status --porcelain -- "$rel")" ] && { echo "reverse: rel still dirty"; return 1; }
  local ef; ef="$(git -C "$g" rev-parse --git-path info/exclude)"; grep -qxF "/$rel" "$ef" 2>/dev/null && { echo "reverse: exclude line not dropped"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$a" "$g"; return 0
}

# ---------- payload kind/category map <-> live cpp schema contract (P0-1) ----------
# Assert lib/payload.sh's kp->cpp kind map (a) emits ONLY kinds in cpp's LIVE meta.schema.json enum,
# (b) is shelf-consistent (mapped kind == the kind cpp's engine requires on the mapped category's
# shelf), and (c) FAILS CLOSED for kp-only/retired kinds (asset|doc|data) instead of silently
# coercing them onto a cpp shelf. Reads the schema from the cpp checkout; self-skips on a bare
# KleinPerkins/dev checkout where the cpp sibling is absent (CI) — same pattern as rs_vendor_mcp.
rs_payload_kindmap() {
  local schema="$ROOT/affirm/src/card-platform-product/_ops/schemas/meta.schema.json"
  [ -f "$schema" ] || { echo "skip: cpp sibling absent ($schema)"; return 0; }
  [ -f "$ORCH/lib/payload.sh" ] || { echo "skip: orchestrator absent"; return 0; }
  . "$ORCH/lib/payload.sh"
  local enum; enum="$(python3 -c "import json; print(' '.join(json.load(open('$schema'))['properties']['kind']['enum']))")" \
    || { echo "could not parse cpp kind enum from $schema"; return 1; }
  local in_enum=" $enum "
  # shelf(category) -> the kind cpp's engine requires on that quiver shelf.
  _shelf_kind() { case "$1" in skills) echo skill;; workflows) echo workflow;; sub-agents) echo sub-agent;; mcp) echo mcp;; tooling) echo tool;; rules) echo rule;; *) echo UNKNOWN;; esac; }
  local k ck cat sk
  for k in skill workflow sub-agent mcp tool rule; do
    ck="$(payload_cpp_kind_for_kind "$k")" || { echo "kind map FAILED for live kind '$k'"; return 1; }
    case "$in_enum" in *" $ck "*) ;; *) echo "mapped kind '$ck' (from '$k') NOT in cpp enum: $enum"; return 1;; esac
    cat="$(payload_cpp_category_for_kind "$k")"; sk="$(_shelf_kind "$cat")"
    [ "$sk" = "$ck" ] || { echo "shelf mismatch: kp '$k' -> kind '$ck' but category '$cat' shelf wants '$sk'"; return 1; }
  done
  local bad
  for bad in asset doc data bogus; do
    if payload_cpp_kind_for_kind "$bad" >/dev/null 2>&1; then echo "kind map did NOT fail closed for non-vendorable kind '$bad'"; return 1; fi
  done
  return 0
}

# ---------- orchestrator vendor for kind:mcp (descriptor mode) ----------
# Vendor a real `kind: mcp` master (google-kit) into a fresh hermetic cpp fixture and assert the
# DESCRIPTOR contract: only README.md + VENDORED.md + meta.yml exist; NO source files leak; the cpp
# payload is zero-link clean. Self-skips when the kp-mcp sibling repo (capabilities/mcp/google-kit)
# is absent — same pattern as rs_vendor / rs_consistency relying on the skills sibling repo.
rs_vendor_mcp() {
  local VEN="$ORCH/lib/vendor.sh" mcpmaster="$ROOT/capabilities/mcp/google-kit" rel="quiver/mcp/google-kit" f
  [ -d "$mcpmaster" ] || { echo "skip: kp-mcp sibling absent ($mcpmaster)"; return 0; }
  f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts quiver/mcp && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  ORCH_SKIP_CPP_EXEC=1 bash "$VEN" --cpp-dir "$f" google-kit >/dev/null 2>&1 || { echo "vendor mcp rc!=0"; return 1; }
  # Descriptor contract (SSP era): the three required discoverability files are always present, AND
  # the descriptor stays SOURCE-FREE — the MCP runtime itself is never vendored (its masters carry
  # forbidden-ld tokens). google-kit ALSO ships a source-free suite bootstrap (SUITE.md + a blank
  # template + an installer/guard) added 2026-07-01 (orchestrator payload_emit_google_kit_suite);
  # those are generated docs/templates, NOT runtime source, so they are allowed — but no runtime
  # SOURCE (install.sh / pyproject / *.py / tests / conftest) may leak, and the whole descriptor
  # must stay zero-link clean (asserted below).
  for fn in README.md VENDORED.md meta.yml; do
    [ -f "$f/$rel/$fn" ] || { echo "missing $fn in cpp mcp descriptor"; return 1; }
  done
  local leaked
  leaked="$(cd "$f/$rel" && find . -type f ! -path '*/.git/*' | sed 's|^\./||' \
    | grep -E '(^|/)(install\.sh|pyproject\.toml|conftest\.py)$|\.py$|^tests/' || true)"
  [ -z "$leaked" ] || { echo "runtime source leaked into cpp mcp descriptor: $leaked"; return 1; }
  # Zero-link clean (defense in depth — vendor.sh already gates on this, but assert it here too).
  ( . "$ORCH/lib/common.sh"; orch_zero_link cpp "$f/$rel" ) >/dev/null 2>&1 || { echo "cpp zero-link failed on mcp descriptor"; return 1; }
  # Re-vendor is byte-stable across the WHOLE descriptor (idempotency assertion).
  local snap; snap="$(mktemp -d)"; cp -R "$f/$rel"/. "$snap/"
  ORCH_SKIP_CPP_EXEC=1 bash "$VEN" --cpp-dir "$f" google-kit >/dev/null 2>&1 || { echo "re-vendor mcp rc!=0"; return 1; }
  diff -r "$snap" "$f/$rel" >/dev/null 2>&1 || { echo "re-vendor produced a non-byte-stable descriptor"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f" "$snap"; return 0
}

# ---------- data-plane manifest writer (WF2/B5) ----------
# manifest.sh writes quiver/tooling/eco-capability-sync/eco-capability-manifest.yml from the ok set:
# (a) correct shape (schema, owned_ids, sorted items, normalized comma-expose), (b) ONLY the manifest
# path is staged (control-plane/scope guard), (c) a re-emit with identical inputs is BYTE-STABLE (no-op,
# generated_at preserved), (d) a changed item set bumps the file. Self-skips if the skills sibling absent.
rs_manifest_sync() {
  local MAN="$ORCH/lib/manifest.sh" rel="quiver/tooling/eco-capability-sync/eco-capability-manifest.yml" f
  [ -d "$(prompt_master)" ] || { echo "skip: skills sibling absent"; return 0; }
  f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  ORCH_SKIP_CPP_EXEC=1 bash "$MAN" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "manifest emit rc!=0"; return 1; }
  [ -f "$f/$rel" ] || { echo "manifest not written"; return 1; }
  grep -q '^schema: eco-manifest/v1$' "$f/$rel" || { echo "missing/incorrect schema stamp"; return 1; }
  grep -q '^owned_ids: \[eco-capability-sync\]$' "$f/$rel" || { echo "owned_ids missing the denylisted tooling id"; return 1; }
  grep -q '^  - id: prompt-architect$' "$f/$rel" || { echo "prompt-architect missing from items"; return 1; }
  # (b) control-plane/scope guard: only the manifest path was committed in the branch's HEAD commit.
  local staged; staged="$(git -C "$f" show --name-only --format= HEAD)"
  [ "$staged" = "$rel" ] || { echo "manifest commit staged extra paths: $staged"; return 1; }
  # (c) byte-stable re-emit (commit it to a base ref first so prepare_clone-equivalent sees it).
  ( cd "$f" && git checkout -q -B base 2>/dev/null )
  cp "$f/$rel" "$f/.man-snap"
  sleep 1
  ORCH_SKIP_CPP_EXEC=1 bash "$MAN" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "re-emit rc!=0"; return 1; }
  cmp -s "$f/.man-snap" "$f/$rel" || { echo "manifest not byte-stable on identical re-emit (generated_at not preserved)"; diff "$f/.man-snap" "$f/$rel"; return 1; }
  # (d) changed item set must change the file.
  ORCH_SKIP_CPP_EXEC=1 bash "$MAN" --cpp-dir "$f" prompt-architect google-kit >/dev/null 2>&1 || { echo "emit-2 rc!=0"; return 1; }
  cmp -s "$f/.man-snap" "$f/$rel" && { echo "manifest unchanged after adding an item"; return 1; }
  grep -q '^  - id: google-kit$' "$f/$rel" || { echo "google-kit not added on second emit"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f"; return 0
}

# ---------- consistency for kind:mcp (regen-and-cmp, Phase 3) ----------
# After a fresh vendor: consistency reports OK. Mutate the cpp README -> must FAIL (regen-and-cmp).
# Mutate the cpp meta.yml -> must FAIL. Drop a required descriptor file -> must FAIL. Add a stray
# source file in the descriptor -> must FAIL.
rs_consistency_mcp() {
  local VEN="$ORCH/lib/vendor.sh" CS="$ORCH/lib/consistency.sh" mcpmaster="$ROOT/capabilities/mcp/google-kit" rel="quiver/mcp/google-kit" f
  [ -d "$mcpmaster" ] || { echo "skip: kp-mcp sibling absent ($mcpmaster)"; return 0; }
  f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts quiver/mcp && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  ORCH_SKIP_CPP_EXEC=1 bash "$VEN" --cpp-dir "$f" google-kit >/dev/null 2>&1 || { echo "vendor mcp rc!=0"; return 1; }
  # In-sync.
  bash "$CS" --cpp-dir "$f" google-kit >/dev/null 2>&1 || { echo "consistency flagged a fresh mcp descriptor as drift"; return 1; }
  # Drift: hand-edit the cpp README (the very failure mode regen-and-cmp exists to catch).
  printf '\nDRIFTED LINE\n' >> "$f/$rel/README.md"
  local rc=0; bash "$CS" --cpp-dir "$f" google-kit >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 1 ] || { echo "consistency missed a hand-edit to mcp README (rc=$rc)"; return 1; }
  ( cd "$f" && git checkout -- "$rel/README.md" 2>/dev/null || true )
  # Drift: hand-edit the cpp meta.yml.
  printf '\n# manually inserted comment\n' >> "$f/$rel/meta.yml"
  local rc2=0; bash "$CS" --cpp-dir "$f" google-kit >/dev/null 2>&1 || rc2=$?
  [ "$rc2" -eq 1 ] || { echo "consistency missed a hand-edit to mcp meta.yml (rc=$rc2)"; return 1; }
  ( cd "$f" && git checkout -- "$rel/meta.yml" 2>/dev/null || true )
  # Drift: drop a required file.
  rm -f "$f/$rel/README.md"
  local rc3=0; bash "$CS" --cpp-dir "$f" google-kit >/dev/null 2>&1 || rc3=$?
  [ "$rc3" -eq 1 ] || { echo "consistency missed a missing required descriptor file (rc=$rc3)"; return 1; }
  ( cd "$f" && git checkout -- "$rel/" 2>/dev/null || true )
  # Drift: stray source file in the descriptor (zero-link AND descriptor shape violation).
  printf 'print("hello")\n' > "$f/$rel/leaked.py"
  local rc4=0; bash "$CS" --cpp-dir "$f" google-kit >/dev/null 2>&1 || rc4=$?
  [ "$rc4" -eq 1 ] || { echo "consistency missed a stray source file in mcp descriptor (rc=$rc4)"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f"; return 0
}

# ---------- content digest primitive (follow-on f1 / Decision G1) ----------
# payload_content_digest must (a) be EQUAL between an ld master and its freshly-vendored cpp payload
# (digest-equality == consistency-equality), (b) be STABLE across repeated calls, and (c) FLIP when any
# shared file is mutated. Self-skips when the skills sibling repo is absent (same pattern as rs_consistency).
rs_content_digest() {
  local VEN="$ORCH/lib/vendor.sh" master; master="$(prompt_master)"; local rel="quiver/skills/prompt-architect" f
  [ -d "$master" ] || { echo "skip: skills sibling absent"; return 0; }
  . "$ORCH/lib/common.sh"; . "$ORCH/lib/payload.sh"
  f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts quiver/skills && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  ORCH_SKIP_CPP_EXEC=1 bash "$VEN" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "vendor rc!=0"; return 1; }
  local dm dp
  dm="$(payload_content_digest "$master")"; dp="$(payload_content_digest "$f/$rel")"
  [ -n "$dm" ] || { echo "empty master digest"; return 1; }
  [ "$dm" = "$dp" ] || { echo "digest(master) != digest(payload): $dm vs $dp"; return 1; }
  [ "$dm" = "$(payload_content_digest "$master")" ] || { echo "digest not stable across repeated calls"; return 1; }
  printf '\n# drift\n' >> "$f/$rel/SKILL.md"
  [ "$(payload_content_digest "$f/$rel")" != "$dp" ] || { echo "digest did NOT flip after mutating a shared file"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f"; return 0
}

# ---------- registry journal + approval gate (follow-on f2/f3) ----------
rs_registry_journal() {
  local rf valid invalids
  rf="$(mktemp)"
  valid="$(printf 'a%.0s' {1..64})"
  cat > "$rf" <<EOF
schema: eco-registry/v1
items:
  - id: prompt-architect
    state: enrolled
    reason: "keep this"
    kind: skill
    cpp_category: skills
    approved_digest: "$valid"
EOF
  (
    ORCH_REGISTRY="$rf"
    . "$ORCH/lib/registry.sh"
    reg_journal_set prompt-architect content_digest "$valid" || exit 1
    [ "$(reg_journal_get prompt-architect content_digest)" = "$valid" ] || { echo "journal get failed"; exit 1; }
    [ "$(reg_state prompt-architect)" = "enrolled" ] || { echo "state not preserved"; exit 1; }
    [ "$(reg_reason prompt-architect)" = "keep this" ] || { echo "reason not preserved"; exit 1; }
    [ "$(reg_kind prompt-architect)" = "skill" ] || { echo "kind not preserved"; exit 1; }
    [ "$(reg_cpp_category prompt-architect)" = "skills" ] || { echo "cpp_category not preserved"; exit 1; }
    reg_journal_clear prompt-architect approved_digest || exit 1
    [ -z "$(reg_journal_raw prompt-architect approved_digest)" ] || { echo "journal clear failed"; exit 1; }
    if reg_journal_set prompt-architect approved_digest BAD >/dev/null 2>&1; then echo "invalid digest accepted"; exit 1; fi
  ) || { rm -f "$rf"; return 1; }
  printf '    approved_digest: "BAD"\n' >> "$rf"
  invalids="$(ORCH_REGISTRY="$rf" bash -c '. "'"$ORCH"'/lib/registry.sh"; reg_journal_invalid_fields prompt-architect')"
  printf '%s\n' "$invalids" | grep -q '^approved_digest=BAD$' || { echo "malformed journal field not reported"; rm -f "$rf"; return 1; }
  rm -f "$rf"; return 0
}

rs_approval_gate() {
  local rf digest bad
  [ -d "$(prompt_master)" ] || { echo "skip: skills sibling absent"; return 0; }
  . "$ORCH/lib/payload.sh"
  digest="$(payload_content_digest "$(prompt_master)")"
  bad="$(printf '0%.0s' {1..64})"
  rf="$(mktemp)"
  cat > "$rf" <<'EOF'
schema: eco-registry/v1
items:
  - id: prompt-architect
    state: enrolled
    reason: "f2/f3 test"
EOF
  local rc=0
  ORCH_REGISTRY="$rf" ORCH_CPP_SYNC_PREFLIGHT_ONLY=1 bash "$ORCH/lib/selfmanage.sh" cpp-sync >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || { echo "missing approved_digest did not block flavor-2"; rm -f "$rf"; return 1; }
  printf '    approved_digest: "BAD"\n' >> "$rf"
  rc=0; ORCH_REGISTRY="$rf" ORCH_CPP_SYNC_PREFLIGHT_ONLY=1 bash "$ORCH/lib/selfmanage.sh" cpp-sync >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || { echo "malformed approved_digest did not block flavor-2"; rm -f "$rf"; return 1; }
  ORCH_REGISTRY="$rf" bash "$ORCH/bin/orchestrator.sh" approve prompt-architect >/dev/null 2>&1 || { echo "approve rc!=0"; rm -f "$rf"; return 1; }
  grep -q "approved_digest: \"$digest\"" "$rf" || { echo "approve did not pin current digest"; rm -f "$rf"; return 1; }
  ORCH_REGISTRY="$rf" ORCH_CPP_SYNC_PREFLIGHT_ONLY=1 bash "$ORCH/lib/selfmanage.sh" cpp-sync >/dev/null 2>&1 || { echo "approved flavor-2 preflight did not pass"; rm -f "$rf"; return 1; }
  python3 - "$rf" "$bad" <<'PY'
import sys
p, bad = sys.argv[1], sys.argv[2]
s = open(p).read()
s = s.replace(next(line for line in s.splitlines() if "approved_digest:" in line), f'    approved_digest: "{bad}"')
open(p, "w").write(s)
PY
  rc=0; ORCH_REGISTRY="$rf" ORCH_CPP_SYNC_PREFLIGHT_ONLY=1 bash "$ORCH/lib/selfmanage.sh" cpp-sync >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || { echo "digest drift did not block flavor-2"; rm -f "$rf"; return 1; }
  cat > "$rf" <<'EOF'
schema: eco-registry/v1
items:
  - id: agent-route
    state: enrolled
    reason: "flavor-1 advisory"
EOF
  ORCH_REGISTRY="$rf" ORCH_CPP_SYNC_PREFLIGHT_ONLY=1 bash "$ORCH/lib/selfmanage.sh" cpp-sync >/dev/null 2>&1 || { echo "flavor-1 required approval unexpectedly"; rm -f "$rf"; return 1; }
  rm -f "$rf"; return 0
}

# ---------- status matrix + recovery blockers (follow-on f4/f5) ----------
rs_status_recovery() {
  local rf out f rc
  rf="$(mktemp)"
  cat > "$rf" <<'EOF'
schema: eco-registry/v1
items:
  - id: prompt-architect
    state: enrolled
    reason: "status test"
    approved_digest: "BAD"
  - id: agent-route
    state: enrolled
    reason: "rollback test"
    last_synced_cpp_sha: "BAD"
EOF
  out="$(mktemp)"
  ORCH_REGISTRY="$rf" ORCH_STATUS_SKIP_GH=1 bash "$ORCH/bin/orchestrator.sh" status --matrix --json > "$out" 2>/dev/null || { echo "status --matrix --json rc!=0"; rm -f "$rf" "$out"; return 1; }
  python3 - "$out" <<'PY' || { rm -f "$rf" "$out"; return 1; }
import json, sys
rows = {r["id"]: r for r in json.load(open(sys.argv[1]))}
assert rows["prompt-architect"]["approval_state"] == "malformed"
assert rows["prompt-architect"]["next_action"] == "approve"
assert "current_digest" in rows["prompt-architect"]
PY
  rc=0; ORCH_REGISTRY="$rf" bash "$ORCH/bin/orchestrator.sh" rollback prompt-architect >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || { echo "rollback without last_synced_cpp_sha did not block"; rm -f "$rf" "$out"; return 1; }
  rc=0; ORCH_REGISTRY="$rf" bash "$ORCH/bin/orchestrator.sh" rollback agent-route >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 0 ] || { echo "rollback with malformed last_synced_cpp_sha did not block"; rm -f "$rf" "$out"; return 1; }
  f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  ORCH_REGISTRY="$rf" ORCH_SKIP_CPP_EXEC=1 ORCH_SKIP_GH_PR_CLOSE=1 bash "$ORCH/bin/orchestrator.sh" quarantine --dry-run --cpp-dir "$f" agent-route -- test-reason >/dev/null 2>&1 \
    || { echo "quarantine dry-run rc!=0"; rm -rf "$f"; rm -f "$rf" "$out"; return 1; }
  grep -q 'state: excluded' "$rf" || { echo "quarantine did not mark excluded"; rm -rf "$f"; rm -f "$rf" "$out"; return 1; }
  grep -q 'reason: "quarantine: test-reason"' "$rf" || { echo "quarantine reason missing"; rm -rf "$f"; rm -f "$rf" "$out"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f"
  rm -f "$rf" "$out"; return 0
}

# ---------- consistency verify (Decision-A compensating control) ----------
# A real vendored payload (built by vendor.sh) must read as IN SYNC; mutating a shared payload file must
# be detected as DRIFT; an orphan payload file (absent in master) must be detected as DRIFT.
rs_consistency() {
  local CS="$ORCH/lib/consistency.sh" VEN="$ORCH/lib/vendor.sh" rel="quiver/skills/prompt-architect" f
  f="$(mktemp -d)"
  ( cd "$f" && git init -q && git config user.email c@e.com && git config user.name C \
      && mkdir -p _ops/facts quiver/skills && printf 'people:\n  - github: KleinPerkins\n    email: kp@e.com\n' >_ops/facts/people.yml \
      && printf 'verify:\n\t@echo ok\n' >Makefile && git add -A && git commit -qm init )
  ORCH_SKIP_CPP_EXEC=1 bash "$VEN" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "vendor add rc!=0"; return 1; }
  # in-sync: a freshly vendored payload matches the master shared content.
  bash "$CS" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || { echo "consistency flagged a fresh payload as drift"; return 1; }
  # drift: mutate a shared payload file (SKILL.md) -> must FAIL.
  printf '\nDRIFTED LINE\n' >> "$f/$rel/SKILL.md"
  local rc=0; bash "$CS" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 1 ] || { echo "consistency missed a mutated shared file (rc=$rc)"; return 1; }
  # restore + add an orphan -> must FAIL.
  ( cd "$f" && git checkout -- "$rel/SKILL.md" 2>/dev/null || true ); printf 'orphan\n' >"$f/$rel/ORPHAN.txt"
  local rc2=0; bash "$CS" --cpp-dir "$f" prompt-architect >/dev/null 2>&1 || rc2=$?
  [ "$rc2" -eq 1 ] || { echo "consistency missed an orphan payload file (rc=$rc2)"; return 1; }
  [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$f"; return 0
}

# ---------- triggers (hermetic) ----------
# REAL fail-open: the hook must exit 0 EVEN when it cannot write its log (a genuine adverse condition),
# proving it never blocks a session. We point HOME at a NON-writable dir so the log-dir mkdir + the log
# redirect both fail, and assert exit 0 regardless. (The old test ran against the live HOME where the
# log always succeeds, so it asserted 0==0 and proved nothing.)
rs_trigger_failopen() {
  local ro rc=0; ro="$(mktemp -d)"; chmod 555 "$ro"
  HOME="$ro" bash "$ORCH/bin/session-hook.sh" >/dev/null 2>&1 || rc=$?
  chmod 755 "$ro" 2>/dev/null || true; rm -rf "$ro"
  [ "$rc" -eq 0 ] || { echo "session-hook did NOT fail-open under an unwritable HOME (rc=$rc)"; return 1; }
  return 0
}
# HERMETIC install: run the trigger installer into an ISOLATED HOME with launchctl suppressed, then
# assert the artifacts appear UNDER that HOME + a re-install is idempotent. (The old test asserted the
# LIVE ~/.cursor + ~/Library state, so it was machine-specific, mutated nothing under test, and could
# not run in CI.)
rs_trigger_installed() {
  local h n; h="$(mktemp -d)"
  HOME="$h" ORCH_NO_LAUNCHCTL=1 bash "$ORCH/lib/selfmanage.sh" install >/dev/null 2>&1 || { echo "install rc!=0"; rm -rf "$h"; return 1; }
  [ -L "$h/.cursor/hooks/orchestrator-session.sh" ] || { echo "hook symlink missing under isolated HOME"; rm -rf "$h"; return 1; }
  [ -f "$h/Library/LaunchAgents/com.kleinperkins.orchestrator.plist" ] || { echo "launchd plist missing under isolated HOME"; rm -rf "$h"; return 1; }
  python3 -c "import json;d=json.load(open('$h/.cursor/hooks.json'));assert any(x.get('command')=='./hooks/orchestrator-session.sh' for x in d['hooks'].get('sessionStart',[]))" 2>/dev/null || { echo "hooks.json entry missing"; rm -rf "$h"; return 1; }
  HOME="$h" ORCH_NO_LAUNCHCTL=1 bash "$ORCH/lib/selfmanage.sh" install >/dev/null 2>&1 || { echo "reinstall rc!=0"; rm -rf "$h"; return 1; }
  n="$(python3 -c "import json;d=json.load(open('$h/.cursor/hooks.json'));print(sum(1 for x in d['hooks'].get('sessionStart',[]) if x.get('command')=='./hooks/orchestrator-session.sh'))" 2>/dev/null)"
  [ "$n" = 1 ] || { echo "hooks.json sessionStart not idempotent (n=$n)"; rm -rf "$h"; return 1; }
  rm -rf "$h"; return 0
}
# hooks.json wipe-guard: a CORRUPT pre-existing hooks.json must be backed up and LEFT UNTOUCHED (never
# overwritten), so a parse error can't silently wipe other tools' hooks.
rs_trigger_corrupt_hooks() {
  local h; h="$(mktemp -d)"; mkdir -p "$h/.cursor"
  printf '{ this is : not json' > "$h/.cursor/hooks.json"
  HOME="$h" ORCH_NO_LAUNCHCTL=1 bash "$ORCH/lib/selfmanage.sh" install >/dev/null 2>&1 || true
  [ "$(cat "$h/.cursor/hooks.json")" = '{ this is : not json' ] || { echo "corrupt hooks.json was overwritten (should be preserved)"; rm -rf "$h"; return 1; }
  ls "$h/.cursor/hooks.json".bak-* >/dev/null 2>&1 || { echo "corrupt hooks.json not backed up"; rm -rf "$h"; return 1; }
  rm -rf "$h"; return 0
}
# session-hook run via the INSTALLED SYMLINK must resolve common.sh. Real-world wiring is
# ~/.cursor/hooks/orchestrator-session.sh -> <repo>/bin/session-hook.sh; if SELF_DIR isn't
# symlink-resolved, common.sh is missed → ORCH_ROOT/ORCH_CONFIG unbound under `set -u` → fail-open
# BREAKS. Assert exit 0 AND that the run actually resolved the config (common.sh was sourced).
rs_trigger_symlink() {
  local h rc=0; h="$(mktemp -d)"; mkdir -p "$h/.cursor/hooks"
  ln -s "$ORCH/bin/session-hook.sh" "$h/.cursor/hooks/orchestrator-session.sh"
  ( cd "$h/.cursor" && HOME="$h" bash ./hooks/orchestrator-session.sh ) >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || { echo "hook via symlink did not exit 0 (rc=$rc)"; rm -rf "$h"; return 1; }
  grep -q "orchestrator ready" "$h"/.orchestrator-work/orchestrator.log 2>/dev/null \
    || { echo "hook via symlink did not resolve config (common.sh not sourced through the symlink)"; rm -rf "$h"; return 1; }
  rm -rf "$h"; return 0
}

_hlabel=""; [ "$HERMETIC" = 1 ] && _hlabel=" (hermetic-only)"
echo "reorg-v2 regression suite$_hlabel"
sec "manifests + zero-link"
# verify-manifests requires ≥1 manifest under a managed root; those roots live in sibling repos, so in
# hermetic-only (CI) mode we skip it rather than fail on an empty checkout.
if [ "$HERMETIC" = 1 ]; then SKIPT "verify-manifests (hermetic-only: managed roots live in sibling repos)"
else T "verify-manifests"      bash "$SELF_DIR/verify-manifests.sh"; fi
# Zero-link across ALL managed roots (Decision C). Each lives in its own repo, so scan those present.
_zl_any=0
for _r in $(eco_managed_roots); do
  if [ -d "$ROOT/$_r" ]; then _zl_any=1; T "zero-link ($_r)" bash "$SELF_DIR/verify-zero-link.sh" --mode global "$ROOT/$_r"; fi
done
[ "$_zl_any" = 1 ] || SKIPT "zero-link (no managed roots present — separate repos)"
T "manifest scaffold+validate"  rs_manifest
T "SSP+GCB standalone-release smoke (exemption scoped)" rs_ssp
sec "sync engine"
T "repair/replace/rebuild/sentinel" rs_sync_modes
sec "orchestrator (ld->cpp)"
if [ -d "$ORCH" ]; then
  T "payload kind/category map <-> live cpp schema contract"        rs_payload_kindmap
  T "vendor add/delete + zero-link abort"                  rs_vendor
  T "vendor kind:mcp descriptor (no source, zero-link, idempotent)" rs_vendor_mcp
  T "data-plane manifest writer (shape, scope-guard, byte-stable, change)" rs_manifest_sync
  T "content digest (master==payload, stable, flips on drift)"     rs_content_digest
  T "registry journal helpers (preserve fields, validate)"         rs_registry_journal
  T "approval gate (flavor-2 digest-bound, flavor-1 advisory)"     rs_approval_gate
  T "status matrix + recovery blockers"                            rs_status_recovery
  T "dedup Decision-A contract (apply disabled / reverse)" rs_dedup
  T "consistency verify (in-sync / drift / orphan)"        rs_consistency
  T "consistency kind:mcp regen-and-cmp (README/meta byte-compare + shape)" rs_consistency_mcp
else SKIPT "orchestrator tests (repo absent)"; fi
sec "triggers (hermetic)"
if [ -d "$ORCH" ]; then
  T "session-hook fail-open (unwritable HOME)"      rs_trigger_failopen
  T "session-hook resolves via installed symlink"   rs_trigger_symlink
  T "trigger install + idempotent (isolated HOME)"  rs_trigger_installed
  T "corrupt hooks.json preserved (no wipe)"        rs_trigger_corrupt_hooks
else SKIPT "trigger tests (orchestrator absent)"; fi
sec "self-heal + clean-room gates"
if [ "$HERMETIC" = 1 ]; then
  SKIPT "self-heal (hermetic-only: needs the installed operating-model env)"
  SKIPT "clean-room (hermetic-only: needs the skills sibling repo)"
else
  T "self-heal (N=3)"             bash "$SELF_DIR/self-heal.sh"
  # clean-room clones the COMMITTED tree, so it only reflects fixes once committed. ECO_RS_SKIP_CLEANROOM=1
  # lets a pre-commit run validate everything else; CI + the post-commit run exercise the full gate.
  if [ "${ECO_RS_SKIP_CLEANROOM:-0}" = 1 ]; then SKIPT "clean-room (ECO_RS_SKIP_CLEANROOM=1)"
  else T "clean-room fresh clone+install" bash "$SELF_DIR/clean-room.sh"; fi
fi

printf '\n== summary == PASS=%d FAIL=%d SKIP=%d\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
