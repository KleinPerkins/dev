# Capability local opt-out registry — bootstrap preserve operator choice

**Version:** v1
**Status:** ACCEPTED — 2026-08-07. Operator-approved in the same session that requested plan → approve → implement (Gate: operator message authorizing implementation after this document).
**Date:** 2026-08-07
**Owning repository:** `KleinPerkins/dev` (policy) + `KleinPerkins/skills` (implementation)
**Review provenance:** Prior-session investigation established root cause (`bootstrap.sh --reconcile` re-runs `install.sh --apply` for `kind: plugin`, re-enabling keep-awake after `--uninstall`). This plan records the approved fix; no `/swarm` review (narrow, machine-local scope).

---

## Changelog

- v1 (2026-08-07) — Initial accepted plan: machine-local opt-out registry, bootstrap gate, keep-awake uninstall hook, `--reset-local-config` override. Overlay merge documented but deferred from v1 implementation.

---

## 1. Purpose

Stop skills bootstrap `--reconcile` / `--repair` from undoing an operator's explicit plugin uninstall. Machine-local opt-out is recorded once at uninstall time and honored on every subsequent bootstrap reconcile unless the operator explicitly resets local config.

## 2. Scope and non-goals

**In scope**

- Schema and file location for machine-local capability preferences (`kp-capability-local/v1`).
- Shared read/write helper used by bootstrap and plugins.
- Bootstrap gate in `capabilities/skills/bootstrap.sh` `maybe_run_install` before plugin `--apply` / `--repair`.
- `keep-awake` `install.sh --uninstall` writes opt-out after successful teardown.
- `--reset-local-config` flag on `capabilities/bootstrap.sh` and `capabilities/skills/bootstrap.sh` to bypass opt-out (operator recovery).
- Unit tests + verify-skills integration for the helper and bootstrap gate.

**Out of scope (v1)**

- cpp sync / quiver delivery (machine-local only; never tracked in git).
- WF1 registry enrollment changes.
- Overlay merge (`capability-overlays/<id>.json`) — documented in §6 for a future v1.1; not implemented in v1 (not required to fix keep-awake regression).
- Changing non-plugin `install.sh` behavior (Flavor-2 / `post_mgmt` paths unchanged).

## 3. Problem statement

`capabilities/skills/bootstrap.sh` calls `maybe_run_install`, which for `kind: plugin` always runs `install.sh --apply` on `--install`, `--reconcile`, and `--repair`. An operator who runs `keep-awake/install.sh --uninstall` removes hooks, timer, and owned state — but the next `bootstrap.sh --reconcile` (including via `capabilities/bootstrap.sh` or skills `--repair`) re-applies the plugin and re-enables keep-awake. Bootstrap must respect an operator opt-out recorded at uninstall time.

## 4. Machine-local registry

**Path:** `~/.local/share/kleinperkins/capability-local.yml`

**Permissions:** file `0600`, parent directory `0700` (created on first write).

**Schema:** `kp-capability-local/v1`

```yaml
schema: kp-capability-local/v1
opt_out:
  - keep-awake
```

Rules:

- `opt_out` is a YAML list of capability `id` strings (from each artifact's `meta.yml` `id:`).
- Duplicate entries are normalized away on write.
- Missing file or empty/malformed file → no opt-outs (bootstrap behaves as today).
- Unknown `schema` value → treat as no opt-outs (fail-safe for forward compatibility; do not block bootstrap).

**Helper:** `KleinPerkins/skills` ships `scripts/capability-local.py` with subcommands:

| Subcommand | Behavior |
|---|---|
| `is-opted-out <id>` | exit 0 if opted out, 1 if not |
| `opt-out <id>` | append id to registry (idempotent) |
| `clear-opt-out <id>` | remove one id |
| `reset` | remove registry file (used by `--reset-local-config`) |
| `path` | print registry path |

Environment override for tests: `CAPABILITY_LOCAL_REGISTRY=<path>`.

## 5. Bootstrap gate behavior

**Location:** `capabilities/skills/bootstrap.sh` → `maybe_run_install`.

**Before** `install.sh --apply` or `--repair` for `kind: plugin`:

1. If `--reset-local-config` was passed on this bootstrap invocation → skip opt-out check (and run `capability-local.py reset` once at start of `main`).
2. Else if `capability-local.py is-opted-out <id>` → log `SKIP <id> (plugin opt-out)` and return without calling `install.sh`.
3. Else → existing behavior unchanged.

**Flag passthrough**

- `capabilities/bootstrap.sh` accepts `--reset-local-config` and forwards it to `skills/bootstrap.sh`.
- `capabilities/skills/bootstrap.sh` accepts `--reset-local-config` on all modes that run install/reconcile/repair.

**Default:** preserve operator opt-out across reconcile/repair. **Override:** `--reset-local-config` clears the registry and re-applies all plugins.

## 6. Plugin contract change

Plugins with machine-local side effects (hooks, launchd, GUI apps) that support `--uninstall` **should** record opt-out on successful uninstall:

```python
# after successful teardown
subprocess.run([capability_local_script, "opt-out", "<id>"], check=True)
```

**v1 implementer:** `keep-awake/scripts/manage.py` → `run_uninstall()` calls opt-out only when uninstall exits 0 (after fence cleared and hooks removed).

Future plugins adopt the same pattern; bootstrap gate applies to all `kind: plugin` regardless.

### Overlay merge (deferred — v1.1)

Optional per-capability JSON at `~/.local/share/kleinperkins/capability-overlays/<id>.json` may deep-merge into `plugin.json` at apply time. Not in v1 — opt-out alone fixes the reported regression.

## 7. Test and verify plan

| Check | Command / location |
|---|---|
| Helper unit tests | `python3 -m unittest discover -s scripts/tests -p 'test_capability_local*.py'` |
| keep-awake uninstall writes opt-out | extend `test_manage.py` |
| Bootstrap skips opted-out plugin | `scripts/tests/test_bootstrap_opt_out.sh` (hermetic `$HOME` + `$CAPABILITY_LOCAL_REGISTRY`) |
| Simulated reconcile | opt-out keep-awake → `bootstrap.sh --reconcile --dry-run` must log SKIP, not APPLY |
| Fleet verify | `bash .github/scripts/verify-skills.sh` (skills repo) |
| Home verify | `make verify-ci` in `~/dev` worktree (repo-only gate) |

## 8. Migration and backward compatibility

- **Greenfield:** no registry file → zero behavior change until first uninstall.
- **Existing machines:** operators who already uninstalled keep-awake manually may still be re-enabled on reconcile until they run `--uninstall` once more (or add `keep-awake` to the registry by hand). Acceptable one-time gap; documented here.
- **Recovery:** `bootstrap.sh --reset-local-config --reconcile` clears opt-outs and re-applies plugins.
- **No git-tracked state:** registry lives under `~/.local/share/` only.

## 9. Work items (implementation checklist)

1. [x] This plan (ACCEPTED).
2. [ ] `scripts/capability-local.py` + unit tests.
3. [ ] `bootstrap.sh` gate + `--reset-local-config`.
4. [ ] `capabilities/bootstrap.sh` flag passthrough.
5. [ ] `keep-awake` uninstall → opt-out.
6. [ ] Bootstrap opt-out integration test + verify-skills wiring.
7. [ ] Simulated reconcile verification.

## 10. Acceptance criteria

- With `keep-awake` in opt-out registry, `bootstrap.sh --reconcile` does not invoke `keep-awake/install.sh --apply`.
- `keep-awake/install.sh --uninstall` adds `keep-awake` to the registry on success.
- `bootstrap.sh --reset-local-config --reconcile` clears registry and applies plugins.
- `verify-skills.sh` passes including new tests.

## 11. Rollback

- Revert `KleinPerkins/skills` commits (bootstrap gate + helper + keep-awake hook).
- Delete `~/.local/share/kleinperkins/capability-local.yml` manually if desired.
- No fleet registry or cpp rollback required.
