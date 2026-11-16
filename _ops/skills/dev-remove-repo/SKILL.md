---
name: dev-remove-repo
description: Safely remove a retired repository checkout from ~/dev (affirm/src, affirm/vendor, personal, capabilities) with a plain-English preview, exact operator approval, a tamper-evident journal and independent verification. Use when the user wants to delete, retire, remove, clean up or get rid of a local repo checkout, a dead clone or an old project folder, asks what removing one would lose, or wants to resume or verify a removal. Home-specific control plane; it never touches GitHub, the PR-automation fleet, DNS or another subsystem's private state.
---

# /dev-remove-repo

Thin operator layer over `_ops/bin/dev-remove-repo.sh`. The script owns inspection, the
operation record, confirmation, execution, resume and verification. This skill only
routes ordinary requests to it and keeps the operator in control of every destructive
step. Method and observed failure modes: `docs/runbooks/dev-repo-removal.md`.

## Ordinary-language routes

| Say this | Exact command |
|---|---|
| `What would removing X lose?` / `Is X safe to delete?` | `bash _ops/bin/dev-remove-repo.sh view <path>...` (read-only) |
| `Remove X.` / `Retire X.` / `Get rid of the X clone.` | `bash _ops/bin/dev-remove-repo.sh remove <path>...` (preview only), then the confirm command after approval |
| `Go ahead and remove it.` (after a preview) | the exact command printed at the end of that preview, with its named waivers |
| `The removal got interrupted.` / `Pick it up again.` | `bash _ops/bin/dev-remove-repo.sh view` (lists operations), then `... resume --operation <id>` |
| `Did it really work?` / `Is it gone?` | `bash _ops/bin/dev-remove-repo.sh verify --operation <id>` |
| `Is the removal tool healthy?` | `bash _ops/bin/dev-remove-repo.sh doctor` |

A path is always `affirm/src/<name>`, `affirm/vendor/<name>`, `personal/<name>` or
`capabilities/<name>`. A repository name alone never authorises anything; if the
operator gives only a name, find the one matching folder and confirm it with them.

## The approval protocol (never skip)

1. **Preview first, always.** Run `remove <path>...` and read the result. Nothing has
   been changed yet; a blocked preview creates nothing.
2. **Say it in plain English before asking.** For each checkout: what will be deleted,
   what would be lost forever (name every risk in plain words, for example "3 commits
   that exist only on this laptop", "files you have not committed", "a stash", "some
   files the leftover search could not read"), what extra cleanup comes with it (client
   skill links, scheduled jobs, Cursor caches), and what stays (Cursor chat history is
   never deleted). Then ask one question: "Remove these N folders, and discard <each
   named risk>?"
3. **Blockers are not negotiable.** A blocked item (someone is writing there, a lock
   or lease is present, the folder is protected, a link or config still points at it,
   the repo is still enrolled in the PR-automation fleet) cannot be waived. Explain it
   in one sentence and stop. Do not work around it, and do not edit another tool's
   files to make it go away.
4. **Approval must name each risk.** Run the confirm command only after the operator
   has said yes to this specific preview and has accepted every listed risk by name.
   A bare "yes", "ok" or "go ahead" does not accept a risk you did not read out.
   Pass exactly the printed `--waive` and `--attest` values, never more. The tool cannot
   tell an agent from a person, so never run it on your own initiative or with a token
   from anywhere else.
5. **Anything changed, expired or ambiguous means a new preview.** A preview is valid
   for 60 minutes and only for the state it showed. Never reuse a token from another
   preview or conversation.
6. **Verify, then report.** After execution run `verify --operation <id>`. Every
   remaining mention of a removed checkout must map to an exception the operator has
   agreed to and described honestly (`--exception CLASS:SCOPE:REASON`, reason in your
   own words, no secrets). The scope is the specific leftover path (or one subsystem name
   for `subsystem-stale`); a broad, unmatched or credential-shaped exception is refused.
   Never invent an exception to get a green result.

## What the operator still owns

The tool detects these, explains them and refuses or asks for an attestation; it never
automates them in v1: PR-automation fleet and controller changes, GitHub App
repository scope, GitHub rulesets and repository archival, GitHub Pages, DNS and
registrar steps, and any change inside a separately governed repo such as the card
platform repo (use that repo's own governed change path).

## Never do this

- Hand-edit AWA state, ShadowSync records, the agent-route index, local-jobs files,
  generated `~/AGENTS.md` or `agent-learnings.md`. The tool composes each owner's own
  verbs; anything left over is reported for the owner to refresh.
- Run `rm`, `git clean` or `git worktree remove` yourself on a checkout, or use
  `--no-verify`/`DATA_GUARD_ALLOW` to get past a guard.
- Paste tokens, credentials, raw config or transcript text into a preview summary, an
  exception reason or a message.
- Leave an operation half-finished without saying so: `resume`, or report that it is
  paused and why.

## When something fails

Say what you **checked**, what is **still uncertain**, and the **one next action**.
An interrupted or paused operation is safe: the journal is intact and `resume` is
idempotent. A failed step stops the run before anything later happens; fix the
named cause and resume, or preview again if the state changed. A `legacy-record` line in
`view` or `doctor` is closed history from before this tool (the first retirement), not an
interrupted operation: never `resume` or `verify` it.
