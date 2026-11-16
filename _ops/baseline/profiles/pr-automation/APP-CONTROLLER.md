# PR automation — Phase B App controller

> **Status (2026-07-10): fleet lifecycle available; qualification evidence is digest-bound.**
> `fleet.py` renders and operates the Phase B controller/ruleset pair. Phase A remains App-free and
> available for compatibility. Validation evidence: `KP-PR-BOT-CANARY-2026-07-10.md` plus the
> current `phase-b.evidence.schema.json` qualification bundle.

Phase B pairs a trusted default-branch **controller** (`controller.yml.tmpl`) with a two-ruleset
GitHub configuration. It exists to obtain genuine self-serve auto-merge on **user-owned private**
repos, which the App-free Phase A ruleset cannot deliver, while keeping protected automation paths
review-gated and CI mandatory even under owner break-glass.

## (a) Why the App path is required on user-owned private repos

Phase A wanted one ruleset expressing *"ordinary PRs need zero human approvals, but a PR that
touches a CODEOWNERS-protected path needs a code-owner review."* GitHub does not provide that on a
private user-owned repo. Proven live on `KleinPerkins/kp-mcp`
([canary record](KP-MCP-CANARY-2026-07-10.md)): a ruleset with
`required_approving_review_count: 0` **does not enforce** `require_code_owner_review: true` — a
self-authored PR changing a CODEOWNERS-protected workflow merged with **zero reviews** and no
`--admin`. Raising the count to `1` closes the hole but review-gates *every* PR, and the author
cannot approve their own PR, so self-serve auto-merge dies. The only escapes are an **org transfer**
or a **GitHub App** that supplies the missing approval for trusted PRs. Phase B is the App escape.

The App (`kleinperkins-review-bot`) is a third party to the PR: it can post the approving review the
author cannot, satisfying a `required_approving_review_count: 1` review-gate for ordinary changes,
while protected-path PRs still fall to the code owner (`@KleinPerkins`) — see (e)/(g).

## (b) App creation and the minimum-permissions verdict

Create one GitHub App (`kleinperkins-review-bot`) owned by the account. It needs **no** webhook and
**no** OAuth user flow — the controller mints installation tokens on demand.

**Minimum installation permissions — `metadata: read` + `administration: read` +
`pull-requests: write` + `contents: write`.**
Do **not** trim to PR-only. Proven by an A/B test on the canary:

- With `pull-requests: write` **only** (canary PR #8), the App mints a token and posts an exact-head
  approving review successfully, but `enablePullRequestAutoMerge(SQUASH, expectedHeadOid)` returns
  **`FORBIDDEN` — `Resource not accessible by integration`**. Arming/executing native auto-merge is
  a `contents`-gated action.
- Restoring `contents: write` (canary PR #10, controller requesting
  `permission-contents: write` + `permission-pull-requests: write`) makes arming and squash-merge
  succeed. `metadata: read` is the implicit baseline read scope.
- The hardened v2 controller additionally mints a separate `administration: read` token to compare
  complete live ruleset semantics, including bypass actors. GitHub omits bypass actors from
  ruleset reads made by tokens without repository write/administration visibility. This inspection
  token is never used for PR, contents, settings, or ruleset mutation.

**Propagation-delay caveat:** a newly granted permission is **not** effective immediately. Observed
a real **multi-minute** delay (several minutes) before a freshly granted scope became usable for
token mints. After changing App permissions, wait and re-accept the installation before testing;
do not conclude a scope is insufficient until propagation has elapsed.

Note the two **distinct** App ids the system uses — keep them straight:

| Role | App | Where |
|---|---|---|
| Produces the required `required / ci` check | **GitHub Actions** app, id `15368` | `{{REQUIRED_INTEGRATION_ID}}` in the controller + `integration_id` in `merge-safety` |
| Mints token, approves, arms auto-merge | **`kleinperkins-review-bot`** | `vars.AUTOMERGE_APP_ID` / `secrets.AUTOMERGE_APP_PRIVATE_KEY` |

## (c) Installation scope

Install `kleinperkins-review-bot` **org/account-wide** (all repositories) so any enrolled repo can
mint a token without a per-repo install step. The controller still narrows every token at mint time
to the **current repo only** via `actions/create-github-app-token` with
`owner: ${{ github.repository_owner }}` and `repositories: ${{ github.event.repository.name }}`, so
each minted token is repository-scoped. This does **not** narrow the PEM's authority: while the App
is installed on all repositories, compromise of any per-repo PEM copy can mint tokens for every
installed repository allowed by the App. After rollout, restrict the App installation to the
enrolled fleet plus the validation canary in GitHub's installation UI.

## (d) Per-repo credential provisioning (via `gh`)

Personal accounts have no account-wide Actions secrets, so each enrolled repo carries its own
**variable** (App id, non-secret) and **secret** (PEM private key). Provision with `gh`, reading the
key from a local file — **never echo or inline key material**, never commit the PEM:

```bash
# App id is not secret -> repository variable.
gh variable set AUTOMERGE_APP_ID --repo <owner>/<repo> --body "<numeric-app-id>"

# Private key is secret -> repository secret, piped from a local PEM (never printed).
gh secret set AUTOMERGE_APP_PRIVATE_KEY --repo <owner>/<repo> < /path/to/kleinperkins-review-bot.private-key.pem
```

Keep the PEM outside any repo working tree (e.g. `~/.config/...`), `chmod 600`, and delete scratch
copies after provisioning. The `data-guard` pre-commit hook will refuse an accidentally-staged key,
but the primary defense is never placing it in the tree.

These identifier **names** (`AUTOMERGE_APP_ID`, `AUTOMERGE_APP_PRIVATE_KEY`) are the fleet standard
and are therefore **not** tokenized in `controller.yml.tmpl`; only their per-repo *values* differ.

## (e) Ruleset pairing for the App path

Phase B replaces Phase A's single `kleinperkins-pr-automation` ruleset with **two** rulesets on the
default branch. GitHub composes co-targeting rulesets as the **union** of their rules, but evaluates
**bypass per ruleset** — that split is the whole point.

**`kleinperkins-review-gate`** — the human/App review requirement, owner-bypassable:

- `pull_request`: `required_approving_review_count: 1`, `require_code_owner_review: true`,
  `dismiss_stale_reviews_on_push: true`, `require_last_push_approval: true`,
  `required_review_thread_resolution: false`, `allowed_merge_methods: [merge, squash, rebase]`.
- `bypass_actors`: **admin** — `RepositoryRole` id `5`, `bypass_mode: pull_request`.

**`kleinperkins-merge-safety`** — the always-on mechanical + CI floor, **no bypass**:

- `pull_request`: `required_approving_review_count: 0`, `allowed_merge_methods: [squash]`,
  `required_review_thread_resolution: true`, `require_code_owner_review: false`.
- `required_status_checks`: `required / ci` bound to integration `15368`,
  `strict_required_status_checks_policy: true`.
- `required_linear_history`, `deletion`, `non_fast_forward`.
- `bypass_actors`: **none**.

How it composes:

- **Ordinary PR** (touches no CODEOWNERS-protected path): review-gate needs 1 approval; the App
  supplies it (no matching CODEOWNERS entry, so code-owner review is vacuously satisfied).
  merge-safety needs squash + resolved threads + green strict `required / ci`. Both satisfied →
  native squash auto-merge fires. Happy path validated: canary merges `0d65ce5b` / `dbbcb9a3`.
- **Protected-path PR** (`.github/workflows/**` etc.): review-gate additionally needs a
  **code-owner** approval. The App is a `Bot`, not `@KleinPerkins`, and cannot be a CODEOWNER; the
  author cannot approve themselves; and the controller's preflight **refuses to authorize protected
  paths** regardless. So it cannot auto-merge — see (g).

> On the disposable canary the required check was named `ci`; in this profile it is `required / ci`
> (see `config.json`). Substitute `{{REQUIRED_CHECK_CONTEXT}}` accordingly when wiring a real repo.

The exact pair is source-tracked in `review-gate.ruleset.json.tmpl` and
`merge-safety.ruleset.json.tmpl`; the Phase B lifecycle owns only returned ids and refuses same-name
unowned resources.

## (f) Arm-before-approve rationale

The controller triggers on `workflow_run` **after** `required / ci` is already green. If it approved
**first**, the fresh approval would immediately satisfy every gate, the PR would enter *clean*
status, and GitHub then **refuses to arm** native auto-merge
(`UNPROCESSABLE` — *"Pull request is in clean status"*). So the controller:

1. **Arms** native squash auto-merge first (pinned to the exact head via `expectedHeadOid`) while the
   bot approval is still the last unmet gate — GitHub accepts arming a still-blocked PR.
2. **Approves** (exact-head pinned), which fires the armed merge.

Supporting safety, all validated on the canary:

- **Idempotent arm:** if arming errors, the controller inspects the *actual* `auto_merge` state
  rather than trusting the message; an already-armed PR (re-run/after-push) is treated as armed.
- **Clean-status fallback:** if the PR is already clean (e.g. a re-run where a prior bot approval
  stands), arming returns *clean status*; the controller falls back to a **direct pinned squash
  merge** (`?sha=<head>`), race-safe like `expectedHeadOid`. The two finalize paths are mutually
  exclusive (no double-merge).
- **h1/h2 head re-check:** it re-verifies the PR head SHA immediately **before** any mutation (`h1`)
  and again **after** approving (`h2`), aborting if the head moved — preventing approval/merge of a
  stale head.

## (g) Owner break-glass for protected `.github/workflows/**` changes

Protected automation changes cannot ride the App path (controller refuses them; the App is not a
code owner). To land them, the **owner** merges directly with admin:

```bash
gh pr merge <pr> --squash --admin
```

`--admin` exercises the **`kleinperkins-review-gate`** admin `bypass_mode: pull_request`, waiving the
*review* requirement (the owner's own PR that the owner cannot self-approve). It does **not** waive
`kleinperkins-merge-safety`, which has **no bypass**: `required / ci` must still be green and the
merge must still be squash on a linear history. So break-glass bypasses **review**, never **CI or
merge mechanics**. Because the bypass is `pull_request` mode (not full push bypass), the owner still
cannot push directly to the default branch outside a PR.

## Managed lifecycle

1. `phase-b apply` renders the policy, controller, protected CODEOWNERS block, and starter
   aggregator if no producer exists. Activation is absent/false.
2. Bootstrap those files by green PR, then `preflight`.
3. `enforce-canary` creates merge-safety first and review-gate second on an exact non-default head.
4. `credential-provision` records names/ownership only and leaves activation false.
5. `activate-canary` enables only the exact canary-bound pair/controller. Exercise generation 1,
   pause/drain, `rollback`, recreate generation 2, repeat the live scenarios, pause/drain, and submit
   a closed evidence bundle to `qualify`.
6. `promote` retargets the same generation-2 ids—merge-safety first—then `activate` verifies the
   pair, credential names, and an actual literal-success Actions check before enabling last.
7. `pause` sets activation false, disables and drains the workflow, disables repository auto-merge,
   and exact-head disarms every request while keeping rulesets active.

`credential-revoke` deletes only task-owned per-repository variable/secret storage. It does not
invalidate the shared App private key; fleet-wide cryptographic revocation requires rotating the
App key and replacing every retained repository secret (or uninstalling the App from that repo).
