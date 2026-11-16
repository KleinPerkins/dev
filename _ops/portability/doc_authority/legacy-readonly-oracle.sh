# Disposable-test oracle only. Current owner blob 29d734d52270c0a03e9924ef9781c3a42ec5d9b3.
# Only the eleven named read-only functions below were extracted. No library
# source, writers, recovered scripts or destination state is executed.
# Receipt lookup is deliberately a known-empty synthetic fixture stub.
set -o pipefail
DWL_CONFORMANT=CONFORMANT
DWL_MISSING=MISSING
DWL_NEEDS_AUTHORING=NEEDS_AUTHORING
DWL_DRIFTED=DRIFTED
DWL_NEEDS_OPERATOR=NEEDS_OPERATOR
DWL_CONTRADICTORY=CONTRADICTORY
DWL_BLOCK_BEGIN='<!-- doc-warden:begin -->'
DWL_BLOCK_END='<!-- doc-warden:end -->'
dwl_plans_dir() { printf docs/plans; }
dwl_receipt_content_digest_for_path() { :; }

dwl_has_local_convention_authority() {
  local repo="$1" plans_rel="$2"
  local readme_abs="$repo/$plans_rel/README.md"
  [ -f "$readme_abs" ] || return 1
  grep -qE '(## The convention|The convention \(already|planning-document convention)' \
    "$readme_abs" 2>/dev/null
}

dwl_hand_authored_agents_md_ok() {
  local repo="$1" plans_rel="$2"
  local agents_abs="$repo/AGENTS.md"
  [ -f "$agents_abs" ] || return 1
  grep -qF "${plans_rel}/README.md" "$agents_abs" 2>/dev/null \
    && grep -qE '(Planning documents|planning-document|execution/design plan)' "$agents_abs" 2>/dev/null
}

dwl_plans_readme_has_index_table() {
  local readme_abs="$1"
  grep -qE '\|\s*(Plan|File)\s*\|' "$readme_abs" 2>/dev/null \
    && grep -qE '^\|[-[:space:]|]+\|' "$readme_abs" 2>/dev/null
}

dwl_policy_drift_ids_for_plans_readme() {
  local readme_abs="$1"
  [ -f "$readme_abs" ] || return 0
  # Drift #2 (POC 3b): status-bullet edit allowance — looser than byte-identical-forever (§13)
  if grep -qF 'now frozen historical' "$readme_abs" 2>/dev/null \
     && grep -qF 'superseded file' "$readme_abs" 2>/dev/null \
     && grep -qF '**Status:**' "$readme_abs" 2>/dev/null; then
    printf 'status_bullet_exception\n'
  fi
  # Drift #1 (POC 3b): stale cross-reference claiming docs/adr/ lacks an index
  if grep -qE '(no index/README of its own yet|has the same gap|lacks an index)' "$readme_abs" 2>/dev/null; then
    printf 'stale_adr_index_crossref\n'
  fi
}

dwl_plan_has_unfilled_author_todos() {
  local fpath="$1"
  if grep -qE '^\*\*Status:\*\*[[:space:]]*ACCEPTED([[:space:]]|$|-)' "$fpath" 2>/dev/null; then
    return 1
  fi
  grep -qE '(^|[[:space:]])<!-- TODO: author|^\*\*[^*]+\*\*:[[:space:]]*<!-- TODO: author|^# TODO: author' "$fpath" 2>/dev/null
}

dwl_plan_header_area() {
  local fpath="$1"
  awk '
    /^## / { exit }
    { print }
  ' "$fpath"
}

dwl_adr_has_unfilled_author_todos() {
  local fpath="$1"
  if grep -qiE '^Status:[[:space:]]*accepted([[:space:]]|$|-)' "$fpath" 2>/dev/null; then
    return 1
  fi
  grep -qE '(^|[[:space:]])<!-- TODO: author|^\*\*[^*]+\*\*:[[:space:]]*<!-- TODO: author|^# TODO: author' "$fpath" 2>/dev/null
}

dwl_classify_plan_file() {
  local repo="$1" plans_rel="$2" fname="$3"
  local fpath="$repo/$plans_rel/$fname"
  [ -f "$fpath" ] || { printf '%s' "$DWL_MISSING"; return; }
  # Naming: <slug>-vN.md (POLICY.md §10 rule 1)
  if ! grep -qE '^[a-z0-9-]+-v[0-9]+\.md$' <<<"$fname"; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # NEEDS_AUTHORING: unfilled template placeholder slots (not prose citations in ACCEPTED plans)
  if dwl_plan_has_unfilled_author_todos "$fpath"; then
    printf '%s' "$DWL_NEEDS_AUTHORING"; return
  fi
  local header_area
  header_area="$(dwl_plan_header_area "$fpath")"
  # Check for plan-header metadata (POLICY.md §10 rule 1). Header markers must be declared in the
  # header/preamble area only; later body lines that happen to start with the same token do not count.
  #
  # Marker probes below use here-strings (grep -qE 'PAT' <<<"$VAR"), never `printf … | grep -q`.
  # Under `set -o pipefail` (this lib enables it) a `printf "%s\n" "$VAR" | grep -q PAT` pipe is
  # SIGPIPE-susceptible: grep -q exits on first match, closes the read end, and if $VAR is larger
  # than the OS pipe buffer printf is killed by SIGPIPE (141); pipefail then propagates 141 as the
  # pipeline status, so `if ! …` falsely reads the marker as ABSENT → false DRIFTED on large plans.
  # A here-string feeds grep from a regular fd (no early-closing reader), so grep's own exit status
  # is authoritative. Matching semantics are identical (both append a trailing newline to $VAR).
  if ! grep -qE '^\*\*Status:\*\*|^\*\*Date:\*\*|^\*\*Owning repository:\*\*' <<<"$header_area"; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # Every non-ACCEPTED plan must declare an explicit closed-vocabulary Plan-type. Accepted legacy
  # plans may remain markerless to preserve byte-identical immutability. If the marker is present,
  # only `standard` and `agentic-execution` are valid values.
  local is_accepted_plan=0 is_agentic_plan=0
  if grep -qE '^\*\*Status:\*\*[[:space:]]*ACCEPTED([[:space:]]|$|-)' <<<"$header_area"; then
    is_accepted_plan=1
  fi
  if grep -qE '^\*\*Plan-type:\*\*[[:space:]]*standard([[:space:]]|$)' <<<"$header_area"; then
    :
  elif grep -qE '^\*\*Plan-type:\*\*[[:space:]]*agentic-execution([[:space:]]|$)' <<<"$header_area"; then
    is_agentic_plan=1
  elif grep -qE '^\*\*Plan-type:\*\*' <<<"$header_area"; then
    printf '%s' "$DWL_DRIFTED"; return
  elif [ "$is_accepted_plan" -ne 1 ]; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # Agentic-execution plans must additionally carry the writing-plans task-block shape WITHIN
  # their "## 5. Work items" section (POLICY.md §10 rule 10 / §12): a **Files:** block, an
  # **Interfaces:** block, and at least one checkbox step. Structural / presence-only; a marked-
  # but-unfilled skeleton is caught by the TODO→NEEDS_AUTHORING check above and never reaches here,
  # so a marker with a missing shape means a filled-but-malformed plan → DRIFTED. The shape must be
  # INSIDE the Work items section only — tokens in another section (an appendix, a work-item ledger,
  # background prose) do not satisfy the rule.
  if [ "$is_agentic_plan" -eq 1 ]; then
    local workitems
    workitems="$(awk '
      $0 ~ /^## +([0-9]+\.? *)?[Ww]ork [Ii]tems/ { in_wi=1; next }
      in_wi && $0 ~ /^## / { in_wi=0 }
      in_wi { print }
    ' "$fpath")"
    # Here-strings (not `printf … | grep -q`): $workitems can far exceed the OS pipe buffer, which
    # is exactly where the SIGPIPE-under-pipefail false-DRIFTED bug bit (see the header note above).
    if ! grep -qE '^[[:space:]]*\*\*Files:\*\*' <<<"$workitems" \
       || ! grep -qE '^[[:space:]]*\*\*Interfaces:\*\*' <<<"$workitems" \
       || ! grep -qE '^[[:space:]]*- \[[ xX]\]([[:space:]]|$)' <<<"$workitems"; then
      printf '%s' "$DWL_DRIFTED"; return
    fi
  fi
  # Byte-stability: receipt-bound content must match (POLICY.md §12 step 5)
  local rel_path="${plans_rel}/${fname}" receipt_digest current_digest
  receipt_digest="$(dwl_receipt_content_digest_for_path "$repo" "$rel_path")"
  if [ -n "$receipt_digest" ]; then
    current_digest="$(dwl_content_digest "$fpath")"
    if [ "$current_digest" != "$receipt_digest" ]; then
      printf '%s' "$DWL_DRIFTED"; return
    fi
  fi
  printf '%s' "$DWL_CONFORMANT"
}

dwl_classify_plans_readme() {
  local repo="$1" plans_rel="$2"
  local readme_abs="$repo/$plans_rel/README.md"
  if [ ! -f "$readme_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  # M2: local convention authority — index table + policy drift only
  if dwl_has_local_convention_authority "$repo" "$plans_rel"; then
    if ! dwl_plans_readme_has_index_table "$readme_abs"; then
      printf '%s' "$DWL_DRIFTED"
      return
    fi
    local drifts
    drifts="$(dwl_policy_drift_ids_for_plans_readme "$readme_abs")"
    if [ -n "$drifts" ]; then
      printf '%s' "$DWL_DRIFTED"
    else
      printf '%s' "$DWL_CONFORMANT"
    fi
    return
  fi
  # Default: canonical table header (POLICY.md §10 rule 4)
  if grep -qE '\|\s*Plan\s*\|' "$readme_abs" 2>/dev/null; then
    printf '%s' "$DWL_CONFORMANT"
  else
    printf '%s' "$DWL_DRIFTED"
  fi
}

dwl_classify_adr_readme() {
  local repo="$1" adr_rel="$2"
  local readme_abs="$repo/$adr_rel/README.md"
  if [ ! -f "$readme_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  # Check for required table header (POLICY.md §10 rule 5)
  if grep -qE '\|\s*ADR\s*\|' "$readme_abs" 2>/dev/null; then
    printf '%s' "$DWL_CONFORMANT"
  else
    printf '%s' "$DWL_DRIFTED"
  fi
}

dwl_classify_agents_md_block() {
  local repo="$1"
  local agents_abs="$repo/AGENTS.md"
  local plans_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  if [ ! -f "$agents_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  # M2: hand-authored AGENTS.md with local convention pointer (POC 3b)
  if dwl_has_local_convention_authority "$repo" "$plans_rel" \
     && dwl_hand_authored_agents_md_ok "$repo" "$plans_rel"; then
    printf '%s' "$DWL_CONFORMANT"
    return
  fi
  local begin_count end_count
  begin_count="$(grep -cF "$DWL_BLOCK_BEGIN" "$agents_abs" 2>/dev/null || true)"
  end_count="$(grep -cF "$DWL_BLOCK_END" "$agents_abs" 2>/dev/null || true)"
  # Duplicate markers → CONTRADICTORY (e.g. two separate doc-warden blocks merged)
  if [ "${begin_count:-0}" -gt 1 ] || [ "${end_count:-0}" -gt 1 ]; then
    printf '%s' "$DWL_CONTRADICTORY"
    return
  fi
  # END before BEGIN → CONTRADICTORY (markers in wrong order)
  if [ "${begin_count:-0}" -eq 1 ] && [ "${end_count:-0}" -eq 1 ]; then
    local begin_line end_line
    begin_line="$(grep -nF "$DWL_BLOCK_BEGIN" "$agents_abs" 2>/dev/null | head -1 | cut -d: -f1)"
    end_line="$(grep -nF "$DWL_BLOCK_END" "$agents_abs" 2>/dev/null | head -1 | cut -d: -f1)"
    if [ -n "$begin_line" ] && [ -n "$end_line" ] && [ "$end_line" -le "$begin_line" ]; then
      printf '%s' "$DWL_CONTRADICTORY"
      return
    fi
    printf '%s' "$DWL_CONFORMANT"
    return
  fi
  printf '%s' "$DWL_DRIFTED"
}
