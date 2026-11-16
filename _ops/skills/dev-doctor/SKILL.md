---
name: dev-doctor
description: Read-only cross-repo health check for the ~/dev personal workspace. Use anytime something feels off, before important work, or to audit identity/placement/sync across every git repo under ~/dev. Reports a verdict per repo on the ladder OK < ADVISORY < DRIFT < VIOLATION (KleinPerkins repos must author as the canonical noreply; cpp self-governs; third-party tools under personal/ flagged ADVISORY). Never modifies any repo. The proportional, single-user analog of /cpp-doctor.
---

# /dev-doctor

Diagnose, never change. Walks every git repo under `~/dev` and reports identity / placement /
origin / sync compliance. Advisory-only — it never blocks a commit and never pushes.

## Run

```bash
cd ~/dev && make doctor              # plain read-only report (recommended)
# or directly, with options:
bash _ops/checks/dev-doctor.sh                 # read-only
bash _ops/checks/dev-doctor.sh --remote        # also live-check parity via git ls-remote
bash _ops/checks/dev-doctor.sh --write-matrix   # refresh the living matrix in git-hygiene-audit.md
bash _ops/checks/dev-doctor.sh --fix-hooks      # install the identity-guard across eligible repos
```

## What it asserts (per repo)
- **Placement** — owner (from `origin`) matches its location (`Affirm/*`→`affirm/{src,vendor}`;
  `KleinPerkins/*`→`personal`/`capabilities`/root; third-party→`vendor` or personal run-in-place).
- **Identity** — `KleinPerkins/*` personal+cap repos MUST resolve to the canonical noreply
  (`49759187+KleinPerkins@users.noreply.github.com`); Affirm repos inherit `@affirm`; **cpp**
  self-governs (noreply per its own `people.yml`); a third-party tool under `personal/` authoring
  as `@affirm` is an ADVISORY latent leak, not a violation.
- **Origin** — a defined `origin` remote exists.
- **Sync** — clean tree + not ahead/behind (ADVISORY nudge; never auto-push).

## Read the result
- Summarize verdict counts; call out any **VIOLATION** (only an identity breach in a
  `KleinPerkins/*` repo) or **DRIFT** (placement / missing origin) in plain language with the fix.
- ADVISORY/DRIFT are nudges, not failures. Exit is non-zero **only** on a VIOLATION.
- To make the audit record living, run with `--write-matrix` (updates `git-hygiene-audit.md`).
- To structurally prevent the work-email leak, offer `--fix-hooks` (installs the M2 guard).
