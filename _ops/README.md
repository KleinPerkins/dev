# `_ops/` — the KleinPerkins/dev control plane

This directory owns shared policy, source checks, host guards and bootstrap tools.
The retired controller is historical source, not a running capability. CI and
independent agent review use the repository-owned Actions/App delivery process.
Source validation and installed-host qualification remain separate.

The authoritative policy is **[`POLICY.md`](POLICY.md)**.

## What's here

| Path | Role | Hand-edit? |
|---|---|---|
| `POLICY.md` | canonical, enforced operating-model policy | yes |
| `README.md` | this file | yes |
| `rules/agent-context.md` | **single source** of the distilled, tool-agnostic operating context | yes |
| `rules/dev-operating-model.mdc` | Cursor rule = frontmatter + a copy of `agent-context.md` body | regenerate (see below) |
| `bin/lib.sh` | shared shell helpers (sha256, `.mdc` + managed-block builders) | yes |
| `bin/install-agent-rules.sh` | idempotent installer: Cursor symlink + Codex/Claude managed blocks | yes |
| `bin/install-hooks.sh` | installs the local `pre-commit` verify hook | yes |
| `checks/verify-operating-model.sh` | read-only verifier (repo + installed-rule assertions) | yes |
| `hooks/pre-commit` | local commit gate that runs the verifier (`--ci` repo-only) | yes |

## Single source → generated rule surfaces

`rules/agent-context.md` is the **one** place the operating context is written. Two surfaces
are derived from it, so they can never silently drift:

- **Cursor:** `rules/dev-operating-model.mdc` = fixed YAML frontmatter + the exact
  `agent-context.md` body. The installer symlinks it to `~/.cursor/rules/`.
- **Codex / Claude:** a hash-stamped **managed block** (`<!-- BEGIN dev-operating-model … -->`
  … `<!-- END dev-operating-model -->`) injected into `~/.codex/AGENTS.md` and
  `~/.claude/CLAUDE.md`. The block embeds `sha256(agent-context.md)`.

Regenerate source only during preparation with:

```bash
_ops/bin/install-agent-rules.sh --gen-only
```

The installer is idempotent: a second run with nothing changed writes nothing. The verifier
fails if any surface is missing or its hash is stale.

## Verification (local + remote)

```bash
_ops/checks/verify-operating-model.sh           # full: repo + this machine's installed rules
_ops/checks/verify-operating-model.sh --ci      # repo-only (no ~/.cursor /.codex /.claude)
```

- **Local hook:** `bin/install-hooks.sh` symlinks `.git/hooks/pre-commit` → `hooks/pre-commit`,
  which runs the verifier in `--ci` (repo-only) mode on every commit.
- **Remote:** the public cohort uses meaningful sharded GitHub Actions checks and the
  qualified Chaos Scheduler App, with one automatically triggered independent review
  from the PR's originating account. The six private/no-CI exceptions receive no CI.
  Current-main checks, account admission and actual App delivery must be observed;
  source-only success does not establish those outcomes.

See [`POLICY.md`](POLICY.md) for the full tracked-vs-ignored contract, identity convention,
drift-prevention model, and the bootstrap contract.
