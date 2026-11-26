# AGENTS.md — `~/dev` Entrypoint

You are in **`~/dev`**, the `KleinPerkins/dev` operating-model source (successor preparation uses `dev-temp`). Read this first, then defer in order:

1. [`OPERATING-MANUAL.md`](OPERATING-MANUAL.md) — full source of truth for the `~/dev` structure.
2. [`_ops/POLICY.md`](_ops/POLICY.md) — enforced repo policy: tracked files, identity, rules, bootstrap, verification.
3. [`_ops/rules/agent-context.md`](_ops/rules/agent-context.md) — installed AI-tool context.

## Essentials

- `affirm/src/` is authoritative work; `affirm/vendor/` is reference-only. Promote vendor clones before contributing.
- New KleinPerkins personal products belong under `~/dev/personal/src/KleinPerkins/<repo>`.
- The target personal/work layout is `<container>/<src-or-vendor>/<git-owner>/<repo>`. `capabilities/` holds reusable and ecosystem-maintenance repositories. Existing paths stay in place until their released migration; most subtrees are separate repositories and are not tracked here.
- `affirm/src/card-platform-product` (`cpp`) is separately governed; read its own `AGENTS.md` and `_ops/POLICY.md` before working there.
- Work/Affirm repos use the global `laurence.duggan@affirm.com` identity unless their own `_ops` says otherwise. Personal/KleinPerkins repos, capabilities, and this repo use local `KleinPerkins <49759187+KleinPerkins@users.noreply.github.com>`.
- Never commit secrets, work repo contents, personal repo contents, generated memories, or machine-local config into `KleinPerkins/dev`; the allow-list `.gitignore` is intentional.
- After source instruction edits, run `make gen` and source verification. `make install-rules` and installed-host `make verify` belong to separately released host work.
- The old controller is retired; PAC mini actions remains planned. Use the repository-owned CI/App and automatic same-origin-account review procedure in `docs/github-delivery.md`. No human technical review gate. Never infer source publication, activation or host-cutover authority from passing local tests.

## Continual-Learning Memory

Machine-mined workspace facts live in machine-local, git-ignored `agent-learnings.md`. Agents may load it as ancestor context, but this `AGENTS.md` must remain hand-authored and must not grow generated `## Learned User Preferences` or `## Learned Workspace Facts` sections.

<!-- doc-warden:begin -->
## Documentation governance

This repo's documentation structure is governed by `doc-warden`.

| Artifact type | Location |
|---|---|
| Plans | `_ops/plans/` — index at `_ops/plans/README.md` |
| ADRs | `docs/adr/` for successor records; `_ops/adr/` is immutable predecessor provenance |
| Runbooks | `docs/runbooks/` |
| Glossary | `docs/GLOSSARY.md` (created when genuine terminology ambiguity arises) |

**Policy:** `~/dev/_ops/doc-warden/POLICY.md`
**Engine:** `~/dev/_ops/bin/doc-warden.sh check .` (read-only health check)
<!-- doc-warden:end -->
