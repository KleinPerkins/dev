# Plan — CI cost control + outage-immune local test signal (fleet defaults + ongoing mgmt)

**Version:** v2
**Status:** DRAFT — CI cost control + outage-immune local test signal (v2 post-review)
**Date:** 2026-07-26
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard

Scope: private KleinPerkins repos under `~/dev`. Excludes cpp, `affirm/*`, `chaos-scheduler` (hard no-touch).

## 1. Problem

A GitHub **Actions billing/payment failure** on the `KleinPerkins` account took down CI across
every **private** repo (jobs fail at startup, `steps: []`; annotation: "recent account payments
have failed **or** your spending limit needs to be increased"). Public `chaos-scheduler` is immune
(public repos = free unlimited Actions minutes).

The deeper issue exposed: **runnerless PR-automation v3 migrated the merge _gate_, not the _tests_.**
Merges gate only on the local `pr-automation / verify` contract check, which kept auto-merging through
the outage. The **real test suites still run in GitHub Actions** (`ci.yml`, `verify.yml`, …) — never
required, never turned off. That legacy Actions CI is what shows red and consumes minutes (see §3).

### Objective (revised after review)
Keep Actions minute spend comfortably **under the 3,000/mo Pro allotment**, keep a **real test
signal** even during a billing outage, make the pattern the **default for new repos**, and give it
**proportionate ongoing management** (data-driven coverage + at-a-glance dashboard + one active
alert). *Not* a from-scratch CI re-architecture; *not* "zero minutes" as a goal (that was gold-plating).

## 2. GATE 0 — Confirm the billing cause BEFORE building (decisive)

The annotation is a literal OR. The fix and the justification for any build both hinge on which:

- **Measured volume (last 30d):** 585 runs fleet-wide — awa 175 (99 × the 4-job `ci` matrix), dev 171,
  skills 150, eco 73, chaos-labs 16. awa's matrix alone ≈ 800–2000 billed min/mo (jobs round UP to
  1 min). So **exhaustion is credible but unproven**.
- **The definitive check** (needs `user` scope, a user action):
  `gh auth refresh -h github.com -s user` then
  `gh api /users/KleinPerkins/settings/billing/actions` → compare `total_minutes_used` vs
  `included_minutes`. (Or eyeball Settings → Billing & plans.)
- **Branch:**
  - **Payment failed** (card declined / expired) and minutes not exhausted → **30-second fix**
    (update payment method). Then do **Phase 1** (cheap, durable) and treat Phase 2+ as optional.
  - **Minutes exhausted** ($0 budget hard-stop) → Phase 1 is necessary; Phase 2+ is the durable answer.

**Do not build Phase 2+ until Gate 0 says exhaustion (or a recurrence is expected).**

> **DECISION (2026-07-12, operator):** proceed **assuming exhaustion** — build the full plan. The
> `user`-scope billing check remains a recommended one-time confirmation but is not a build blocker.

## 3. Load-bearing facts (verified on disk)

- **Merge gating never depended on `ci.yml`.** v3 `merge-safety` ruleset requires only
  `pr-automation / verify`. Deleting/pausing heavy Actions workflows breaks **no** merge gate
  (proof: awa PR #38/#39 auto-merged during the outage with all 5 Actions checks red).
- **`baseline.yml` is templated** (`_ops/baseline/template/workflows/baseline.yml`, `cat`-rendered by
  `repo-baseline.sh apply`). One template edit reaches ~12 repos but marks each committed copy
  **STALE** (advisory) until per-repo re-`apply` + commit (`apply` refuses a dirty tree). The vendored
  `baseline-verify.sh` checks file **presence** + `permissions: contents: read` only — it does **not**
  diff the `on:` block, so a `paths-ignore` edit won't fail it.
- **`ci.yml` is per-repo hand-authored** (only awa, kp-mcp, intent-router). No shared template.
  `dev-new-repo.sh` **never** scaffolds a heavy `ci.yml` → "born without heavy Actions CI" already holds.
- **awa's 4-job matrix is the dominant cost** (99 ci runs × {verify,router-seam}×{3.9,3.12}); most
  other heavy suites are cheap bash. **This is largely a one-repo cost problem.**
- **CI change PRs are protected-path PRs.** `.github/**`, `CODEOWNERS`, `_ops/**` are in the v3
  controller's `PROTECTED_PATHS` → the controller will **NOT auto-merge** them. Every Phase 1/2 CI
  edit is a **manual merge** (the `verify` check may show green while the PR sits unmerged).
- **`paths-ignore` clean targets are narrow:** fleet `baseline.yml`, `dev/verify.yml`,
  `skills/verify-capabilities.yml`. **Not safe:** eco `verify.yml` (keys on `config/registry.yml`,
  touched by both journal noise and real enroll changes — indistinguishable). **Cannot:**
  `skills/swarm.yml`+`verify.yml` (already `paths:`-include). Preserve awa `tags: ['v*']` unfiltered.
- **`chaos-labs` is already at end-state** (no heavy Actions workflow; tests run via local hooks).
- **Local sandbox-ability:** awa `make verify`/`verify-install` = YES (stdlib+sqlite3, headless);
  awa `router-seam` = **skips to false-green** unless `PYTHONPATH`=<awa>:<router> +
  `AWA_SEAM_REQUIRE_ROUTER=1` + pinned ref; `dev/verify.yml` = YES (it *is* `make verify-ci`); eco =
  YES (needs `shellcheck` binary); skills verify-skills/swarm = YES, agent-route needs PyYAML.
  **Python parity caveat:** local `python3` = 3.14; awa targets {3.9, 3.12} and **3.9 isn't installed**
  → local can't reproduce the 3.9 leg.
- **`local-jobs` gives the runner for free.** `pr-automation-controller` is already a plain
  `command` instance polling all repos every 60s; the dashboard auto-surfaces any run records from
  `events.jsonl`. → a **second `command` instance** is the whole mechanism (no new job type needed).
- **GitHub reporting without new infra:** `gh` is authed (classic `ghp_` PAT, `repo` scope → can POST
  commit statuses). True Check Runs need an App token — **do not** reuse `verifier.pem` (attested to
  the pr-automation control plane). Token lives in the **macOS keychain**.

## 4. Design decisions (post-review)

- **Separate merge-gate from test-signal, permanently.** Merge safety = runnerless contract
  (unchanged; never run PR code / heavy tests in that hardened, no-network controller). Test signal =
  a separate local runner. *This split is the plan's best-reasoned call and is retained.*
- **Use ONE `command` poller, not a new `repo-verify` job type.** Data-driven off `fleet.json`; loops
  repos in one process; emits a per-instance runlog the dashboard fan-outs. (Cuts the schema /
  `cardinality=multi` / `registry.d` / `install-overlay` machinery — simplest durable design, reuses
  the proven controller pattern.)
- **Report via `gh` commit status** (`local/ci`), surfaced on the dashboard. No new App. Tokens stay in
  the keychain — never in the job env/plist.
- **Isolate test checkouts** with `git clone --reference <local> --dissociate` (or a per-repo bare
  mirror) into `$TMPDIR` — **not** `git worktree add` (which writes into the primary `.git` and orphans
  on SIGKILL). Reaper at run start.
- **Keep Actions as a free fallback; do NOT delete.** Trim the cost driver (awa matrix) and, only after
  Gate 0 + parity soak + billing healthy, **reversibly pause** heavy push/PR triggers (comment `on:` /
  convert to `workflow_dispatch`) rather than delete — Actions works fine whenever billing is healthy
  and is a zero-maintenance belt-and-suspenders.
- **`local/ci` is never a GitHub _required status check_** (a sleep-gated required check would stall
  merges forever with "Expected — waiting"). **Arm-gate is enforced controller-side instead** (§6): the
  reviewer bot arms auto-merge only after a fresh `local/ci` green for the exact head. If the poller
  hasn't run (Mac asleep), the PR simply isn't armed yet — no stuck GitHub state — and manual squash
  merge is always available as the override.
- **Accept the sleep-gap honestly.** launchd `StartInterval` does not fire while asleep and needs an
  active GUI login; realistic duty cycle ≈ 30–50% with overnight/weekend/travel blackouts. The poller
  is a **clean-env backstop**, and the real pre-merge guard remains the strong local pre-push checks
  (`make verify` + commit guards) this dev already runs. Documented, not hand-waved.

## 5. Phased plan

### Phase 1 — Cost control (do first; reversible; no new infra)
- **Trim awa's `ci.yml` matrix** — the dominant lever: run the single primary interpreter on push/PR;
  keep the full {3.9,3.12} matrix **and** `router-seam` **only** on `tags: ['v*']`. (Cuts ≈50–75% of
  awa's billed jobs.)
- **`paths-ignore: ['**/*.md']`** on the clean targets only: `baseline.yml` template (→ per-repo
  re-`apply`+commit), `dev/verify.yml`, `skills/verify-capabilities.yml`. Leave eco `verify.yml` and
  skills `swarm.yml`/`verify.yml` (see §3).
- **Ordering (avoids the dirty-tree self-deadlock):** (1) open+**manually merge** the `dev` template
  PR (touches `_ops`, protected); (2) `repo-baseline.sh apply` each STALE repo from a **clean** tree,
  **manually merge** each; (3) `apply dev` last. Every one is a protected-path → **manual** merge.
- **Reversibility:** each is a single-commit `git revert`, no cross-repo state.
- **Likely outcome:** this alone plausibly keeps the fleet under 3,000 min with **no build**. This is
  the baseline any further phase must beat.

### Phase 2 — One `command` poller for an outage-immune test signal (optional; gated on Gate 0)
- **Prereqs, checked INSIDE the launchd env (not the interactive shell):** `gh auth status` OK;
  `python3 -c "import yaml"`; `shellcheck` present (pin version); `intent-router` clone at pinned SHA;
  a watchdog binary — **`brew install coreutils` for `gtimeout`** (neither `timeout` nor `gtimeout`
  exists today).
- **Author one script** (in the source-tracked overlay `personal/local-jobs/bin/repo-verify-poll.sh`),
  registered as a `command` local-jobs instance (interval ≥ realistic runtime, e.g. 900s). Per tick,
  for each `fleet.json` target with a verify command:
  1. discover open-PR heads + latest `main` via `gh`; **dedup SHAs already reported** (cheap no-op polls);
  2. `git clone --reference --dissociate` the head into `$TMPDIR`; run its verify under `gtimeout`
     (hard cap, e.g. 600s; kill process group on cap → `conclusion=timeout`);
  3. `gh api POST /statuses/{sha}` `context=local/ci`; **a status-POST failure IS a run failure**
     (never "tests passed, status silently missing");
  4. `rm -rf` the temp clone; emit one `@@RUNLOG@@` line with per-instance fields `{repo, head,
     conclusion, duration_s, status_url}`.
  Start each tick with a **reaper**: prune stale `$TMPDIR` clones + `git worktree prune`.
- **Per-repo verify commands:** awa `make verify` (+ export `PYTHONPATH`/`AWA_SEAM_REQUIRE_ROUTER=1`
  if running router-seam locally; else document it's skipped and covered by the tag-only Actions job);
  `dev` `make verify-ci` (NOT `make verify` — fails in a worktree); eco fixtures; skills
  `verify-skills.sh` + swarm + agent-route; chaos-labs already local.
- **Parity honesty:** local runs the **primary interpreter only**; the full python matrix +
  router-seam remain on the **tag-only Actions job** (route matrix coverage there). Do not claim
  "reproduces Actions" beyond that.
- **Do not** name the script/instance with `pr-automation`/`kleinperkins-review-bot` (v3 string-scan).

### Phase 3 — Active alert + keep Actions as fallback (the "don't get silently burned" layer)
- **Active deadman** (not pull-only): a tiny check (piggyback the existing 60s controller tick or a
  second cheap `command` job) that fires an `osascript` notification / writes a red sentinel when: the
  poller is not `launchd_loaded`, last-success age > threshold, `consecutive_failures ≥ 3`, or
  `gh auth` is broken/expired. **This must exist before Phase 4 pauses any Actions workflow.**
- **Keep Actions floors + fallback:** `baseline.yml` everywhere; awa slim **tag-only** release job.
  Heavy push/PR workflows: **reversibly pause** (comment `on:`/`workflow_dispatch`), never delete,
  and only after billing healthy + a quantified parity soak.

### Phase 4 — Fleet defaults + proportionate ongoing management (per the explicit ask)
- **Coverage is data-driven — this IS the "default/rollout".** The poller reads `fleet.json`; a new
  private repo enrolled in the fleet is **automatically** covered — no `dev-new-repo.sh` code change
  required. Document that new private repos get local CI by virtue of fleet membership.
- **One light doctor check** (extend `dev-doctor`, surfaced via the Phase-3 alert, not a new engine):
  repos with heavy Actions still live-on-push, testable repos missing from poller coverage, and
  stale/failing poller instances.
- **Dashboard** = the at-a-glance surface (per-repo pass/fail/duration/history/next-run) — auto.
- **Docs:** `OPERATING-MANUAL.md` + `_ops/baseline/README.md` record the three tiers: Actions floor
  (`baseline.yml` + tag-only release) · local test signal (`local-jobs` poller) · runnerless merge gate.

## 6. The quality hole — DECISION: arm-gate (option B)
Merges auto-fire on the thin contract while real tests are advisory → broken code can auto-merge
unnoticed (demonstrated by PR #38/#39). **DECISION (2026-07-12, operator): arm-gate.**
- **Implementation (controller-side, NOT a GitHub required check):** extend the `pr-automation`
  reviewer bot's arming predicate to also require `local/ci = success` for the exact head SHA before
  it arms native squash auto-merge. Keeps GitHub's required set = the contract check only (no
  sleep-stall footgun); the poller's green is a controller-enforced prerequisite; manual merge is the
  override when CI hasn't run.
- **Scope note:** this touches the versioned `pr-automation-controller` release (new minor, e.g.
  v0.1.7) — a distinct workstream that lands in **Phase 3/4**, after the poller exists and emits
  `local/ci`. It does **not** block Phase 1–2.
- **Consequence to accept:** merges become effectively gated on the Mac having run CI for the head;
  for a solo dev who is usually the merger, this is acceptable, with manual merge as the escape hatch.

## 7. Alternatives considered & rejected (so they're not re-litigated)
- **Self-hosted Actions runner** — REJECTED. As of **2026-03-01**, self-hosted runners on **private**
  repos consume your included minutes **+ $0.002/min** (verified: GitHub 2026 Actions pricing change).
  So it does not solve cost; only *not running an Actions job at all* (local execution) is zero-minute.
- **Make repos public** — rejected (leaks the private operating model).
- **Do nothing / wait for monthly reset** — valid **iff** Gate 0 = payment failure; otherwise recurs.
- **Collapse to one gate** (run real tests inside the runnerless contract) — rejected (breaks the
  hardened, no-network, credential-free controller threat model).
- **New `repo-verify` job type** — rejected in favor of one `command` poller (simpler, proven pattern).
- **Delete heavy Actions workflows** — rejected in favor of reversible pause + keep as free fallback.

## 8. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Premise wrong (payment, not exhaustion) → build is wasted | **Gate 0** measures before building |
| Silent CI stall (hung verify, poller dead, keychain locked, all-red) | Watchdog/`gtimeout`; **active deadman alert** before pausing Actions; status-POST-fail = run-fail |
| Sleep-gap = CI only when Mac awake | Keep `local/ci` **non-required**; poller is a backstop; pre-push checks are the real guard; document |
| False parity (python 3.9 absent; router-seam skips green) | Primary interpreter locally; matrix + router-seam on tag-only Actions job; set router env explicitly |
| Worktree writes into primary `.git`; orphans on crash | `git clone --reference --dissociate` into `$TMPDIR`; reaper at run start; EXIT/INT/TERM trap |
| Common-mode SPOF (controller + poller share local-jobs / gh keychain / Mac-awake) | Acknowledge; deadman covers the shared failure; not "separate fault domains" |
| Every CI PR is protected-path → **manual merge** | State it; sequence merges by hand; don't expect auto-merge |
| Template edit ⇒ whole fleet STALE | Per-repo `apply`+commit from clean trees (advisory, non-blocking) |
| Deleting Actions removes free fallback / can't validate parity while billing down | **Pause, don't delete**; parity soak is billing-gated |
| launchd env skew (PATH, python w/ PyYAML, `LOCAL_JOBS_HOME`) | Prereqs checked inside launchd env |
| Reusing `verifier.pem` breaks attestation | `gh` commit status, not the pr-automation App |
| `chaos-scheduler` | Hard no-touch everywhere |

## 9. Sequencing gates / acceptance criteria
- **Phase 1:** AC1 ordering (template PR merged → apply STALE repos from clean trees → dev last), all
  manual merges; AC2 each change single-commit revertible.
- **Phase 2:** AC3 prereqs pass **inside launchd env**; AC4 dry-run `run` under launchd (not just
  interactive); AC5 dedup + reaper + watchdog present.
- **Phase 3:** AC6 active deadman fires on poller-dead/stale/auth-broken **before** any Actions pause;
  AC7 pause is reversible (`workflow_dispatch` re-enable proven).
- **Phase 4 (pause/parity):** AC8 per repo, ≥N consecutive green poller runs on live heads **and** a
  proven **true-negative** (poller FAILS on a known-bad head); AC9 billing healthy; AC10 rollback
  runbook (revert the pause PR; note it only restores signal once billing is up).

## 10. Out of scope
- Fixing the billing payment (user action; external dependency, explicitly de-coupled from the build).
- Making `local/ci` a required merge check (revisit only via a cloud-smoke path, not a sleep-gated poller).
- A new GitHub App for true Check Runs.
- cpp / `affirm/*` repos.

## 11. Changelog
- v1 (2026-07-12) — initial draft (4 phases: paths-ignore → repo-verify job type → delete Actions → drift engine).
- v2 (2026-07-12) — folded 4-reviewer swarm: added **Gate 0** (measure billing cause; +30d volume
  evidence); replaced the `repo-verify` job type with **one `command` poller**; **keep Actions
  (reversible pause, not delete)**; added **watchdog + active deadman + worktree-isolation/reaper +
  launchd-env prereqs + status-fail=run-fail**; fixed **parity honesty** (python matrix + router-seam
  → tag-only Actions); made **`local/ci` non-required an invariant**; right-sized defaults/mgmt to
  **data-driven fleet.json coverage + one doctor check**; added **alternatives-rejected** (self-hosted
  killed by 2026 pricing) and **sequencing ACs**; surfaced the **auto-merge quality-hole** decision.
- v2.1 (2026-07-12) — subtractive polish: de-duplicated the problem statement against §3; no scope change.
- v3 (2026-07-12) — operator decisions locked: **assume exhaustion / build full plan**; **Phase 1 now**;
  quality hole = **arm-gate** (controller-side, Phase 3/4). Plan frozen for execution; worklist tracked
  via to-dos, not further edits to this file.
