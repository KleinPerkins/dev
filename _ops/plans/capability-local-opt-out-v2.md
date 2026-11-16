# Capability local opt-out registry — bootstrap preserve operator choice

**Version:** v2
**Status:** ACCEPTED — 2026-08-07. Supersedes `capability-local-opt-out-v1.md` (v1 remains frozen for diff/provenance). Operator-approved after `/swarm` plan hardening in the same session as v1 implementation (skills PR open; dev passthrough PR #200).
**Date:** 2026-08-07
**Owning repository:** `KleinPerkins/dev` (policy) + `KleinPerkins/skills` (implementation)
**Supersedes:** `_ops/plans/capability-local-opt-out-v1.md` (v1, ACCEPTED 2026-08-07 — do not edit)

---

## Changelog

- v2 (2026-08-07) — Swarm-hardened plan: reconciles §9 with shipped implementation; documents self-heal / eco-reconcile entry points; strengthens plugin contract (MUST + CI), schema forward-compat policy, operator recovery/discoverability, test matrix gaps, and v1.1 overlay-merge trigger criteria. Adds swarm review provenance.
- v1 (2026-08-07) — Initial accepted plan (frozen). See `capability-local-opt-out-v1.md`.

---

## Swarm review provenance

| Field | Value |
|---|---|
| **Run date** | 2026-08-07 |
| **Subject fingerprint** | `KleinPerkins/dev` @ `7c8c4ad` (worktree `cursor/3393e067`, clean); `KleinPerkins/skills` @ `d34d4ca` (branch `feat/capability-local-opt-out`, clean) |
| **Band / cohort** | standard · 1 probe + 3 reviewers (api-contract-compat, data-integrity-migration, reliability-failure) |
| **Verifier** | not run (`gate-verifier`: `run: false`) |
| **Waived territories** | testing-evidence, architecture-maintainability, policy-governance, generic-surface (findings folded into v2 prose below) |

**Key findings folded into v2**

1. **Plugin contract enforcement** — v1 "should" upgraded to MUST for plugins with `--uninstall`; verify-skills static check planned (§6, §9 item 10).
2. **Self-heal path** — `_ops/eco/self-heal.sh` `heal()` calls `capabilities/bootstrap.sh` → gated reconcile; plan now documents this flow and observability gap (§5, §7, §10).
3. **Legacy bootstrap bypass** — `capabilities/bootstrap.sh` fallback manifest loop (when `skills/bootstrap.sh` absent) has no opt-out gate; documented as known gap + v2 follow-up (§5, §9 item 11).
4. **Schema forward-compat** — unknown major schema must not silently discard opt-outs; policy specified (§4).
5. **Operator recovery** — `clear-opt-out` selective recovery and registry inspection documented; `--reset-local-config` remains blunt override (§5, §8, §10).
6. **Test matrix** — repair-mode gate, live reconcile, write-failure semantics added as acceptance/follow-up items (§7, §10, §9).
7. **v1.1 overlay merge** — explicit trigger criteria and v1 coexistence contract (§6).
8. **Lifecycle verbs** — `--disable` vs `--uninstall` contract defined (§6).

---

## 1. Purpose

Stop skills bootstrap `--reconcile` / `--repair` (and the `~/dev` passthrough paths that delegate to it) from undoing an operator's explicit plugin uninstall. Machine-local opt-out is recorded once at uninstall time and honored on every subsequent bootstrap reconcile unless the operator explicitly resets or clears local config.

**v2 addition:** The same gate must be reasoned about for `_ops/eco/self-heal.sh`, `capabilities/bootstrap.sh`, and any future eco-reconcile entry point that eventually calls plugin `install.sh`.

## 2. Scope and non-goals

**In scope**

- Schema and file location for machine-local capability preferences (`kp-capability-local/v1`).
- Shared read/write helper used by bootstrap and plugins.
- Bootstrap gate in `capabilities/skills/bootstrap.sh` `maybe_run_install` before plugin `--apply` / `--repair`.
- `keep-awake` `install.sh --uninstall` writes opt-out after successful teardown.
- `--reset-local-config` flag on `capabilities/bootstrap.sh` and `capabilities/skills/bootstrap.sh` to bypass opt-out (operator recovery).
- Unit tests + verify-skills integration for the helper and bootstrap gate.
- **v2:** Document all bootstrap entry points (direct, passthrough, self-heal) and operator-facing recovery/discovery paths.
- **v2:** Plugin contract MUST + verify-skills enforcement plan for future plugins.

**Out of scope (v1 implementation — unchanged)**

- cpp sync / quiver delivery (machine-local only; never tracked in git).
- WF1 registry enrollment changes.
- Overlay merge implementation (`capability-overlays/<id>.json`) — trigger criteria in §6; implementation remains v1.1.
- Changing non-plugin `install.sh` behavior (Flavor-2 / `post_mgmt` paths unchanged except where noted for legacy fallback gap).

**Known gap (documented, v2 follow-up — not blocking v1 ship)**

- `capabilities/bootstrap.sh` **legacy fallback** (lines ~62–146 when `skills/bootstrap.sh` is absent) runs flavor=2/post_mgmt `install.sh` with **no** opt-out gate. Normal machines delegate to `skills/bootstrap.sh` and are protected.

## 3. Problem statement

`capabilities/skills/bootstrap.sh` calls `maybe_run_install`, which for `kind: plugin` always runs `install.sh --apply` on `--install`, `--reconcile`, and `--repair`. An operator who runs `keep-awake/install.sh --uninstall` removes hooks, timer, and owned state — but the next `bootstrap.sh --reconcile` (including via `capabilities/bootstrap.sh`, `_ops/eco/self-heal.sh`, or skills `--repair`) re-applies the plugin and re-enables keep-awake. Bootstrap must respect an operator opt-out recorded at uninstall time.

### Bootstrap entry points (v2)

| Entry point | Path | Opt-out gate today |
|---|---|---|
| Direct | `capabilities/skills/bootstrap.sh --reconcile\|--repair\|--install` | **Yes** (`maybe_run_install`) |
| Dev passthrough | `capabilities/bootstrap.sh` → delegates `--reconcile` + `--reset-local-config` | **Yes** when `skills/bootstrap.sh` exists |
| Eco self-heal | `_ops/eco/self-heal.sh` `heal()` → `capabilities/bootstrap.sh` | **Yes** on normal path; output discarded (`>/dev/null 2>&1 \|\| true`) |
| Legacy fallback | `capabilities/bootstrap.sh` manifest loop (no `skills/bootstrap.sh`) | **No** — documented gap |
| Stale skills clone | Passthrough uses file-existence check only; pre-gate `skills/bootstrap.sh` | **No** until skills repo updated |

## 4. Machine-local registry

**Path:** `~/.local/share/kleinperkins/capability-local.yml`

**Permissions:** file `0600`, parent directory `0700` (created on first write).

**Schema:** `kp-capability-local/v1`

```yaml
schema: kp-capability-local/v1
opt_out:
  - keep-awake
```

**Write semantics (v2 — matches shipped implementation):** atomic write via temp file + `os.replace` in the same directory; no external YAML dependency.

Rules:

- `opt_out` is a YAML list of capability `id` strings (from each artifact's `meta.yml` `id:`).
- Duplicate entries are normalized away on write.
- Missing file or empty file → no opt-outs (bootstrap behaves as today).
- Malformed content (unrecognized lines inside `opt_out` block) → WARN and treat as no opt-outs for that read (fail-safe for hand edits).
- **v2 schema forward-compat policy:**
  - **Same major** (`kp-capability-local/v1`, including future minor field additions under the same major tag): preserve any parsable `opt_out:` list.
  - **Unknown major** (e.g. `v2` before tooling upgrade): WARN loudly; **do not** silently treat as zero opt-outs on production machines — v1.1 migration work must define read/write upgrade before bumping major. Until then, operators should not hand-edit the schema tag.
  - Rationale: silently discarding opt-outs on schema skew reproduces the original regression class.

**Helper:** `KleinPerkins/skills` ships `scripts/capability-local.py` with subcommands:

| Subcommand | Behavior |
|---|---|
| `is-opted-out <id>` | exit 0 if opted out, 1 if not |
| `opt-out <id>` | append id to registry (idempotent); exit 0 on success |
| `clear-opt-out <id>` | remove one id; delete file when list empty |
| `reset` | remove registry file (used by `--reset-local-config`) |
| `path` | print registry path |

**Exit codes (v2):** mutating subcommands return 0 on success or idempotent no-op; non-zero only on genuine I/O failure.

Environment override for tests: `CAPABILITY_LOCAL_REGISTRY=<path>`.

## 5. Bootstrap gate behavior

**Location:** `capabilities/skills/bootstrap.sh` → `maybe_run_install`.

**Before** `install.sh --apply` or `--repair` for `kind: plugin`:

1. If `--reset-local-config` was passed on this bootstrap invocation → skip opt-out check (and run `capability-local.py reset` once at start of `main`, **not** on `--dry-run` apply — registry preserved until real apply).
2. Else if `capability-local.py is-opted-out <id>` → log `SKIP <id> (plugin opt-out)` and return without calling `install.sh`.
3. Else → existing behavior unchanged.

**Modes covered:** `--install`, `--reconcile`, and `--repair` all honor the gate (same check before `--apply` or `--repair`).

**Flag passthrough**

- `capabilities/bootstrap.sh` accepts `--reset-local-config` and forwards it to `skills/bootstrap.sh`.
- `capabilities/skills/bootstrap.sh` accepts `--reset-local-config` on all modes that run install/reconcile/repair.

**Default:** preserve operator opt-out across reconcile/repair. **Override:** `--reset-local-config` clears the registry and re-applies all plugins.

### Operator recovery paths (v2)

| Goal | Command | Scope |
|---|---|---|
| Re-enable **one** plugin | `python3 …/capability-local.py clear-opt-out <id>` then `bootstrap.sh --reconcile` | Selective |
| Re-enable **all** plugins | `bootstrap.sh --reset-local-config --reconcile` | Destructive (clears entire registry) |
| Inspect registry path | `python3 …/capability-local.py path` | Read-only |
| Inspect one id | `python3 …/capability-local.py is-opted-out <id>`; echo `$?` | Read-only |
| Manual edit | Edit `~/.local/share/kleinperkins/capability-local.yml` (0600) | Advanced |

**Operator discoverability (v2 follow-up — §9 item 12):** surface registry path + opt-out list via `dev-doctor` advisory or `OPERATING-MANUAL.md` §capability bootstrap; optional thin skill wrapping the helper subcommands.

### Self-heal interaction (v2)

`_ops/eco/self-heal.sh` `heal()` invokes `bash "$ROOT/capabilities/bootstrap.sh"` (stdout/stderr discarded). On a normal machine this runs the gated `skills/bootstrap.sh --reconcile` path. **Observability gap:** opt-out SKIP lines are not visible in self-heal logs today — v2 follow-up (§9 item 13) to tee opt-out-relevant bootstrap lines into `eco_log`/`eco_warn`.

## 6. Plugin contract change

Plugins with machine-local side effects (hooks, launchd, GUI apps) that support `--uninstall` **MUST** record opt-out on successful uninstall:

```python
# after successful teardown — WARN on failure, do not fail uninstall (shipped keep-awake pattern)
record_plugin_opt_out()  # calls capability-local.py opt-out <id>; WARN if helper missing or I/O fails
```

**v1 shipped behavior:** `keep-awake/scripts/manage.py` calls `record_plugin_opt_out()` after successful teardown; failures are WARN-only so uninstall still exits 0. Plan accepts this — operator sees `WARN capability opt-out not recorded` and can run `opt-out` manually or re-run uninstall.

**Lifecycle verbs (v2)**

| Verb | Must record opt-out? | Notes |
|---|---|---|
| `--uninstall` | **MUST** (after successful teardown) | Primary operator off-switch |
| `--disable` | **MUST** if implemented | If a plugin exposes disable as a persistent off state, it must write opt-out; no plugin ships `--disable` today |
| `--apply` / `--repair` | Must **not** clear opt-out | Bootstrap gate skips these when opted out |

Future plugins adopt the same pattern; bootstrap gate applies to all `kind: plugin` regardless.

**Reference implementation:** `keep-awake` (sole plugin with `--uninstall` today). Second plugin: `continual-learning` (local) — when/if it gains `--uninstall`, it MUST wire opt-out.

**Enforcement (v2 follow-up — §9 item 10):** verify-skills static check: every `kind: plugin` with executable `install.sh` that advertises `--uninstall` in `--help` or docs must invoke `capability-local.py opt-out` (or declare `optout_on_uninstall: true` in `meta.yml` cross-checked by CI).

### Overlay merge (deferred — v1.1)

Optional per-capability JSON at `~/.local/share/kleinperkins/capability-overlays/<id>.json` may deep-merge into `plugin.json` at apply time. **Not in v1.**

**v1.1 trigger criteria (start work when any holds):**

1. A second `kind: plugin` needs per-machine config overrides without full uninstall (keep-awake is the only plugin today).
2. Operator requests selective re-enable with non-default plugin config (not merely on/off).
3. A plugin ships `--disable` that should persist config but stop side effects (overlay + opt-out interaction must be designed together).

**v1.1 readiness contract (plan now, implement later):**

- v1 `capability-local.py` and bootstrap **must ignore** a pre-existing `capability-overlays/` directory without error (forward-compatible directory presence).
- Overlay schema is **sibling** to registry schema (not embedded in `capability-local.yml`); registry major stays `v1` until opt-out list shape changes.
- Overlay merge must not clear or bypass opt-out entries.

## 7. Test and verify plan

| Check | Command / location | v1 ship status |
|---|---|---|
| Helper unit tests | `python3 -m unittest discover -s scripts/tests -p 'test_capability_local*.py'` | **Shipped** |
| keep-awake uninstall writes opt-out | `global/plugins/keep-awake/tests/test_manage.py` | **Shipped** |
| Bootstrap skips opted-out plugin | `scripts/tests/test_bootstrap_opt_out.sh` (hermetic `$HOME` + `$CAPABILITY_LOCAL_REGISTRY`) | **Shipped** (dry-run reconcile) |
| Simulated reconcile | opt-out keep-awake → `bootstrap.sh --reconcile --dry-run` logs SKIP, not APPLY | **Shipped** |
| reset-local-config dry-run ordering | registry preserved on dry-run; cleared on apply | **Shipped** |
| Fleet verify | `bash .github/scripts/verify-skills.sh` | **Shipped** |
| Home verify | `make verify-ci` in `~/dev` worktree | **Required on dev PR** |

**v2 gaps (follow-up work items — §9)**

| Gap | Planned test |
|---|---|
| `--repair` skips opted-out plugin | extend `test_bootstrap_opt_out.sh` |
| Live reconcile (non-dry-run) does not re-apply | hermetic `$HOME` apply path |
| Opt-out write failure surfaces WARN | simulate read-only registry dir in `test_manage.py` |
| Legacy `capabilities/bootstrap.sh` fallback | fixture without `skills/bootstrap.sh`; assert gate or document skip |
| Plugin contract CI | verify-skills scan for opt-out call in uninstall paths |
| Self-heal observability | optional integration note in eco regression (when log tee lands) |

## 8. Migration and backward compatibility

- **Greenfield:** no registry file → zero behavior change until first uninstall.
- **Existing machines — registry gap:** operators who already uninstalled keep-awake manually may still be re-enabled on reconcile until they run `--uninstall` once more (or add `keep-awake` to the registry by hand). Acceptable one-time gap; documented here.
- **Existing machines — skills repo gap:** machines whose `capabilities/skills` checkout predates the bootstrap gate will passthrough to an ungated `skills/bootstrap.sh` until `git pull` on skills main. **Recovery:** update skills repo, re-run `capabilities/bootstrap.sh` or `make fix-hooks` / self-heal.
- **v1.1 optional backfill (deferred):** bootstrap could detect an already-torn-down plugin (absent hooks/launchd) and auto-seed opt-out on first post-upgrade run — not required for v1 ship.
- **Recovery:** see §5 operator recovery table.
- **No git-tracked state:** registry lives under `~/.local/share/` only.

## 9. Work items (implementation checklist)

### v1 core (shipped on `feat/capability-local-opt-out` @ `d34d4ca`)

1. [x] Plan v1 ACCEPTED (`capability-local-opt-out-v1.md`).
2. [x] `scripts/capability-local.py` + unit tests (`test_capability_local.py`).
3. [x] `skills/bootstrap.sh` gate + `--reset-local-config` (`maybe_run_install`, `RESET_LOCAL_CONFIG`).
4. [x] `capabilities/bootstrap.sh` `--reset-local-config` passthrough to skills `--reconcile`.
5. [x] `keep-awake` uninstall → opt-out (`manage.py:record_plugin_opt_out`).
6. [x] Bootstrap opt-out integration test + verify-skills wiring (`test_bootstrap_opt_out.sh`).
7. [x] Simulated reconcile verification (dry-run SKIP/APPLY assertions).

### v2 plan + follow-up (this document)

8. [x] Plan v2 ACCEPTED (this file) after `/swarm` review.
9. [ ] Merge skills implementation PR; verify `make verify-ci` on dev passthrough PR #200.
10. [ ] verify-skills: static check that `kind: plugin` uninstall paths call `capability-local.py opt-out`.
11. [ ] Gate or document legacy `capabilities/bootstrap.sh` manifest loop (no `skills/bootstrap.sh`).
12. [ ] Operator discoverability: `dev-doctor` and/or `OPERATING-MANUAL.md` + recovery table.
13. [ ] Self-heal: tee opt-out-relevant bootstrap log lines (stop swallowing under `/dev/null`).
14. [ ] Tests: `--repair` skip, live reconcile, write-failure WARN (`test_bootstrap_opt_out.sh`, `test_manage.py`).
15. [ ] v1.1 overlay merge (only when §6 trigger criteria met).

## 10. Acceptance criteria

### v1 core (verified against shipped branch)

- With `keep-awake` in opt-out registry, `bootstrap.sh --reconcile` and `--repair` do not invoke `keep-awake/install.sh --apply` or `--repair`.
- `keep-awake/install.sh --uninstall` adds `keep-awake` to the registry on success (WARN-only if helper I/O fails).
- `bootstrap.sh --reset-local-config --reconcile` clears registry and applies plugins; dry-run preserves registry until apply.
- `verify-skills.sh` passes including new tests.

### v2 additions (follow-up — not all required for v1 merge)

- `capability-local.py clear-opt-out <id>` selectively re-enables one plugin while preserving others (manual + documented path).
- Operator can discover registry location without reading source (doctor/manual/skill — §9 item 12).
- Self-heal path documented; opt-out SKIP visible in self-heal output when item 13 lands.
- verify-skills plugin-contract check fails CI if a new plugin adds `--uninstall` without opt-out wiring.
- Repair-mode and live-reconcile tests pass (§9 item 14).

## 11. Rollback

- Revert `KleinPerkins/skills` commits (bootstrap gate + helper + keep-awake hook).
- Delete `~/.local/share/kleinperkins/capability-local.yml` manually if desired.
- No fleet registry or cpp rollback required.
- **Operator data:** no automatic backup today; `--reset-local-config` is destructive to the full opt-out list — operators should note opted-out ids before reset if selective recovery matters.
