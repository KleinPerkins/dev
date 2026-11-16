# Capability Lock Runbook

Use this when a capability repo changes `meta.yml`, lock parity fails, hooks look stale, or the
orchestrator is missing.

## Quick Repairs

| Situation | Command |
| --- | --- |
| "Is the capability system healthy?" | `cd ~/dev && make capability-health` |
| Metadata lock parity failed in `skills` or `mcp` | `cd <repo> && bash .github/scripts/eco-lock.sh write && git add .eco-registry.lock && bash <verify-script>` |
| Lockkit master/copy drift across capability repos | `cd ~/dev && make eco-lockkit-write && make eco-lockkit-check` |
| Stale or missing `registration-guard` | `cd ~/dev && make fix-hooks && make doctor` |
| Orchestrator missing | `cd ~/dev && bash bootstrap.sh` |
| After kind-shelf migration | `cd ~/dev && make eco-lockkit-write && make eco-verify && make eco-lockkit-check` |

## Expected Layout

Capabilities in `KleinPerkins/skills` live under kind shelves:

```text
global|local/
  skills/<id>/        meta.kind: skill, requires SKILL.md
  rules/<id>/         meta.kind: rule, requires <id>.mdc
  sub-agents/<id>/    meta.kind: sub-agent, requires <id>.md
  tools/<id>/         meta.kind: tool, requires tool.yml and shape
```

The lock record includes `scope`, `shelf`, `kind`, and `source_path`. It is a metadata lock over
normalized `meta.yml`, not a payload-content lock. Do not hand-edit consumer `eco-lock.sh` copies;
update the orchestrator master and propagate with lockkit.

## Safety Notes

- `orchestrator lockkit write` refuses dirty target repos by default.
- Use `orchestrator lockkit --allow-dirty write <target>` only after inspecting and classifying the
  dirty state as compatible.
- cpp remains out of lockkit scope. Verify cpp routing read-only; do not hand-vendor into cpp.

## Branch Protection Reality (superseded — GitHub Pro upgrade, see below)

Originally checked 2026-06-29 with `gh api repos/KleinPerkins/{skills,kp-mcp}/branches/main/protection`,
which 403'd ("Upgrade to GitHub Pro...") on both private repos. The account has since upgraded to
GitHub Pro. Merge-gating branch protection (required status checks / PR review) is still **not**
enabled for `skills` or `kp-mcp` — both stay solo, direct-push repos by design, same rationale as
`~/dev` (`_ops/POLICY.md` §6). What Pro did unlock and what is now active is a narrower history-integrity
**ruleset** (block force-push + branch deletion on the default branch, repo-admin always-bypass) applied
via `~/dev`'s `_ops/bin/repo-baseline.sh enforce` — `skills` and `cpp` were enforced remote-only (their
local checkouts were on non-default branches at rollout time); re-run `enforce` if either falls behind.
Treat local `verify-*`, `lockkit check`, and CI workflow presence as the operational gate for lock
parity specifically — the ruleset protects history, not lock correctness.

## Born-Compliant Capability Repos

Use `~/dev/_ops/bin/dev-new-repo.sh --capability <name> --kind skill|rule|sub-agent|tool --dry-run`
to preview a new capability repo. Real creation is intentionally deferred until the new repo is added
to the central lockkit target inventory; otherwise lockkit would not be able to check or repair it.
