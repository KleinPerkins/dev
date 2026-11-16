# Context Efficiency Program — measured projections without authority drift

**Version:** v1
**Status:** ACCEPTED — 2026-08-15
**Date:** 2026-08-15
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard
**Review provenance:** remote-first audit of four owner/default branches plus one valid reconnaissance probe, followed by independent final review and source-level adjudication of F-01–F-05. Owner refs were refreshed on 2026-08-15 to Dev `549e332d`, AWA `536f9cc0`, Skills `9fa02b9c`, and CPP `44106b9c`. Four earlier bounded reviewer outputs appended prose outside their required JSON contract, so none counted as evidence; their territories were reviewed directly. Operator acceptance remains outstanding.
**Governing decision:** draft [ADR-0004](../adr/0004-optimize-context-projections-without-moving-authority.md)

**Goal:** Reduce recurring agent context by at least 30% for the frozen seven-payload static baseline, then reduce capability-discovery overhead, without losing safety, learned preferences, ordinary-language routing, or client access.
**Architecture:** Repair projection eligibility first, freeze exact installed evidence, and optimize only owner-controlled render/install projections. Source authority stays in each owner repository; `KleinPerkins/dev` coordinates evidence and rollout but creates no context registry or runtime.
**Tech stack:** Markdown/ADRs, Git/GitHub, existing Dev/Skills/AWA/CPP installers and verifiers, Cursor/Claude/Codex fresh-client evidence.

> **Pre-implementation gate:** accepting this standard program plan and ADR would approve architecture and sequence only. Every implementation change requires the owning repository's current plan/change classification and approval path from §5; machine-local learned-data repair separately requires explicit operator authorization. No cross-repository marker grants implementation authority.

---

## Changelog

- v1 (2026-08-15) — Current-state refresh of the draft first published 2026-08-09: verifies live owner refs, defines deterministic measurement, moves Skills/CPP/operator-memory eligibility before the denominator freeze, removes unowned MCP and unrelated Save-Game work, applies owner-specific plan governance, and binds the program to draft ADR 0004. Version remains v1 because the plan is still DRAFT and mutable.

---

## Global Constraints

- Do not implement this program from this artifact.
- Do not edit generated projections, installed links, hooks, machine-local memory, plugin caches, or implementation files during plan approval.
- Do not move or duplicate source authority. Dev coordinates; each owner repository authors and lands its own changes.
- Do not hand-vendor global capability payloads into CPP. Global capability changes flow through Skills and the existing orchestrator lifecycle; CPP changes only its CPP-owned surfaces through CPP governance.
- Do not let any repository plan classify, rewrite, delete, or repair operator-owned `~/agent-learnings.md` or workspace `agent-learnings.md` data. An explicit machine-local operator gate owns those actions.
- Preserve AWA worktree/finish safety, fail-open global-hook behavior, exact-digest approval gates, Save-Game authority, continual-learning source authority, ordinary-language routing, and repository-owner authorization.
- Never delete learned facts or preferences to meet a size target. Generated memory remains non-authoritative and must be reproducible from preserved sources.
- Never treat source tests, character counts, or a local install as fresh-client proof.
- Never describe a word/character reduction as an exact token or latency reduction. Cursor's live context view is supporting evidence, not the deterministic denominator.
- No program work may merge until its owner-classified plan/change artifact is accepted and its predecessor gates are green.

## 1. Purpose

The operator repeatedly pays for guidance that is loaded before a task begins: workspace `AGENTS.md`, global/always-applied rules, generated machine memory, capability descriptions, and client catalogs. The prior draft correctly identified the opportunity, but ecosystem changes and live machine drift expose three problems:

1. installed projections can be stale or sourced from disposable roots;
2. two repositories can believe they own the same hook rows while other required rows disappear on a clean path; and
3. source-file size does not prove what a client actually injects.

This plan treats context efficiency as a measured projection problem. It repairs the projection path, freezes reproducible evidence, makes the smallest owner-local reductions, and proves behavior in each affected client.

## 2. Scope and non-goals

### In scope

- The seven deterministic, recurring static payloads listed in §3.3.
- The installed capability-discovery projection for Cursor, Claude, and Codex.
- Eligibility blockers that prevent honest measurement or rollback:
  - capability links/pointers rooted in disposable workspaces;
  - overlapping AWA/Dev hook writers;
  - a continual-learning source that blocks deterministic `~/AGENTS.md` generation.
- Owner-local source changes in `KleinPerkins/dev`, `KleinPerkins/awa`, `KleinPerkins/skills`, and the CPP-owned discovery surface in `Affirm/card-platform-product`, only through separately accepted owner-classified plan/change artifacts.
- Deterministic measurement, exact-digest approvals, isolated install tests, fresh-client canaries, rollback evidence, and an evidence-only program ledger.

### Out of scope

- Implementing any reduction, repair, hook, installer, rule, skill, or memory change in this planning PR.
- A central context manager, runtime, metadata registry, or second capability-delivery channel.
- Editing generated `~/AGENTS.md`, installed symlinks, `~/.cursor/hooks.json`, or plugin caches directly.
- Rewriting AWA, Save-Game, continual learning, agent-route, or CPP governance.
- Optimizing MCP instructions/tool catalogs. No current owner dependency justifies the historical MCP benchmark; MCP access remains a protected non-regression surface.
- Re-proving Save-Game's compaction lifecycle as a separate project. It remains unchanged and participates only as an affected-client discovery/invocation canary.
- CPP's large agent-policy payload or other workspace-specific `AGENTS.md` files. CPP is implicated here only because its CPP-local skills are currently projected globally.
- A performance SLA for model latency, cost, or context-compaction timing. The program measures bytes/words/characters and client-visible categories, not provider internals.

## 3. Background and current-state audit

### 3.1 Remote default branches reviewed

| Authority | Default-branch ref reviewed | Material current fact |
|---|---|---|
| `KleinPerkins/dev` | [`549e332d`](https://github.com/KleinPerkins/dev/commit/549e332deef5bbd5dcf6efaf9f81cee129477c9e) | Historical [PR #229](https://github.com/KleinPerkins/dev/pull/229) merged the plan; historical branch head `38c70aff` became merge commit `fe7dd394`. PR #230 added the Dev `Plan-type` marker. The plan body remains DRAFT. Changes through current main are doc-warden/PR-automation work, not program implementation. |
| `KleinPerkins/awa` | [`536f9cc0`](https://github.com/KleinPerkins/awa/commit/536f9cc0ebfd6bc1d7308603bf6e62c80c624d17) | AWA remains the SSP/product owner. Published `v1.5.1` at `f4b3c9b8` adds Git read-only command-policy hardening; no context reduction or external hook-owner mode shipped. |
| `KleinPerkins/skills` | [`9fa02b9c`](https://github.com/KleinPerkins/skills/commit/9fa02b9c0d34a554e32994e9258e6241fc1f3c90) | PR #124 pins AWA `v1.5.1`; PR #125 changed continual-learning cadence to 40 turns / 8 hours. Linked-worktree source resolution exists, but standalone nested clones remain untreated. |
| `Affirm/card-platform-product` | [`44106b9c`](https://github.com/Affirm/card-platform-product/commit/44106b9cb047fbb78bba360c4633221709d79b48) | CPP now governs substantial repository-wide installer/projection work as `Class: control-plane` under `_ops/plans/` (ADR 0014). Its installer surfaces `_ops/skills` and `quiver/skills` to Cursor, Claude, and Codex from the checkout that invokes it, so a disposable invoking worktree can become the installed target. CPP is not part of the seven-payload static denominator. |
| Cursor product behavior | Official [Rules](https://cursor.com/docs/rules), [Skills](https://cursor.com/docs/skills), [Prompting/context](https://cursor.com/docs/agent/prompting), and [Hooks](https://cursor.com/docs/hooks) docs, reviewed 2026-08-15 | Always-applied rules enter every chat; skill descriptions are injected in a distinct Skills category; MCP is separate. Cloud can run supported project hooks, including `beforeSubmitPrompt`, but not `sessionStart`; user-level `~/.cursor/hooks.json` is unavailable in Cloud. |

No relevant implementation dependency was proven in another repository. The current branch was created cleanly from then-current Dev `origin/main` `95aa41f7`; live main is now `549e332d`, whose intervening changes are unrelated PR-automation required-check selection/policy. The merged historical remote branch is gone.

### 3.2 Built-versus-planned delta

| Historical premise | Current finding | Program consequence |
|---|---|---|
| Seven-payload baseline is 8,704 words / 66,965 characters | Reproduced from the seven raw digests in §3.3 with `kp-context-measurement/v1` in §4.2. A previously calculated 8,694 / 66,891 omitted AWA's projected frontmatter and is invalid. This remains a machine-local preflight, not the official denominator, until Release 0 eligibility passes. | Preserve the 30% goal and deterministic algorithm; re-freeze exact eligible bytes after Release 0. |
| Save-Game is shipped | Still true: source evidence records 370 tests and live Cursor discovery/invocation; Claude discovery is evidenced, while Codex and a real post-compaction reconcile remain unproven. | Remove duplicate Save-Game implementation/reproof work. Keep affected-client discovery/invocation and unchanged-authority checks. |
| AWA authority is settled but hook ownership drifts | Still true, with a sharper gap: AWA's direct installer writes five rows; Dev redirects those writes then installs only three. A clean Dev path can omit two AWA product rows; a later direct repair recreates three duplicate policy rows. | Preserve settled product/host authority, but add an explicit external-writer contract and an ordered five-row transition. |
| Capability source resolution must be created | Partly shipped. Skills already resolves a linked Skills worktree to its primary checkout and tests it. It accepts a standalone Skills clone nested under a disposable parent worktree. | Narrow work to the unhandled trust/ancestry case and standard reconciliation; do not build a new source registry. |
| Continual learning runs on a 20-turn / 4-hour cadence and one named path blocks generation | Cadence is now 40 turns / 8 hours. A different agent-route-discovered workspace now blocks on nonempty content with no exact machine bullets. | Replace volatile path repair with a defect-class contract. Preserve fail-closed parsing and source content. |
| Skills descriptions need budgets | Confirmed, but prior exact character/threshold totals are withdrawn. Skills current `local/skills/update-skills/SKILL.md` has invalid YAML frontmatter (`argument-hint` flow syntax), so plausible parsers do not produce one authoritative catalog. CPP separately owns a globally projected catalog. | Require valid YAML 1.2 frontmatter and `skill-description-normalization/v1` before quoting totals; then measure the installed projection and prefer scoping before shortening. |
| CPP-installed projections are durable before baselining | False on the observed machine. Cursor and Claude each have 54, and Codex 52, skill links resolving under disposable CPP worktree `pkru`. CPP's current installer resolves the invocation checkout and can legitimately repoint sibling-worktree links there. | Add a CPP-owned, all-client durable-root reconciliation gate before the official baseline; Dev documents evidence but cannot mutate CPP. |
| Cloud/Background can be excluded as one cohort | Too coarse. Current Cursor docs distinguish project hooks from unavailable user-home hooks and support `beforeSubmitPrompt` in Cloud while omitting `sessionStart`. | Classify every client/projection combination as eligible, ineligible, or contract-only; do not make event-wide Desktop-only claims. |
| MCP descriptor benchmarking belongs in this program | No current owner/ref or planned implementation dependency supports it. | Remove it. Preserve MCP availability as a non-regression only. |

### 3.3 Verified preliminary static denominator

Counts below are a reproducible machine-local preflight captured on 2026-08-15. They use `kp-context-measurement/v1` (§4.2), include full projected files and AWA frontmatter, and are bound to raw SHA-256. They are not the official denominator until Release 0 passes.

| Projection ID | Words | Characters | Raw SHA-256 | Authority |
|---|---:|---:|---|---|
| Workspace `AGENTS.md` | 496 | 3,939 | `d3a037470f79d19d46078d448820daa6f8b6fb891759158314552784fc3a820b` | Dev |
| `dev-operating-model.mdc` | 2,102 | 16,876 | `733a2ae0e1f655f9bcfe4b42bab12c2629e411de4516ec9168efe2ab87142f74` | Dev |
| `subagent-orchestration.mdc` | 414 | 2,907 | `8befffb6cda555a1d173ac94b536ebcae224b50f3b129eb82008a7b098133b18` | Skills |
| `terse-output.mdc` | 1,358 | 9,221 | `73d38bcb04d52d615654309644ff809727ee45b3c359576bce30da1255a80b66` | Dev |
| `worktree-default.mdc` | 212 | 1,439 | `81a6ebf78935c36f6deb531eb0581874271d173f0c584598d95437b66be7dc22` | Dev |
| `awa-operator.mdc` | 1,016 | 8,206 | `bf92d59e7dcd6b57a094bf656e2cb9ebd39ea5f2380c1e3f9a8c666d8c226d05` | AWA |
| Generated `~/AGENTS.md` | 3,106 | 24,377 | `50e1801ddd5bcc57b0bba4603bde1862dd7f98eaf8a4063e1ed38e2e7a0e74f3` | Operator-owned machine inputs; Skills-owned generator |
| **Total** | **8,704** | **66,965** | — | |

If the post-eligibility baseline is unchanged, Release 1 requires at most **6,092 words** and **46,875 characters**. The formula, not these illustrative absolute values, is authoritative:

```text
after_words <= floor(0.70 * baseline_words)
after_characters <= floor(0.70 * baseline_characters)
```

### 3.4 Machine-local observations (not source authority)

Observed on 2026-08-15 and kept separate from origin facts:

- 16 active skill/sub-agent links and one inactive backup link resolve under `~/.cursor/worktrees/dev/359u`; the AWA GCB pointer's recorded shelf also resolves there.
- CPP-installed skill links resolve under `~/.cursor/worktrees/card-platform-product/pkru`: 54 in Cursor, 54 in Claude, and 52 in Codex. These are installed-state observations, not CPP origin facts.
- Installed AWA checkout/runtime is `v1.5.0` at `331e6330`, while current Skills origin pins published `v1.5.1` at `f4b3c9b8`.
- Dev's hook check reports two copies of each of the three policy rows; the Dev overlay doctor fails.
- Continual-learning consolidation leaves `~/AGENTS.md` unchanged because an agent-route-discovered source is nonempty but contains no exact machine Learned bullets.
- Source and installed static payload bytes currently match despite those eligibility failures. That coincidence does not make the projection path durable.

No machine-local state is modified by this planning change.

### 3.5 Authority boundaries

| Owner | Owns in this program | Does not own |
|---|---|---|
| Dev | Program plan/ADR/evidence; Dev rule sources; host policy/delegators; final five-row hook-file reconciliation | AWA product semantics, global capability payloads, CPP-local skills, machine memory content |
| AWA | SSP, operator/finish semantics, generic hook scripts/installer contract, release | Dev host policy literals or the live host's final hook matrix |
| Skills | Global capability source/exposure, bootstrap source resolution, continual-learning generator/runtime, Save-Game, AWA GCB pin, Skills-owned descriptions | CPP-local skill bodies, direct CPP vendoring, or operator-owned learned-data repair |
| CPP | CPP-local skill scope/descriptions and its governed local installation surface | Global capability master bytes; those flow from Skills through the orchestrator |
| Operator / machine-local gate | `~/agent-learnings.md`, workspace `agent-learnings.md`, retained private repair artifacts, and authorization to classify or repair them | Skills code, generated-output hand edits, or repository authority |
| Cursor/Claude/Codex | Client discovery/injection behavior | Program authority; their behavior is an external constraint proved by current docs/live clients |

## 4. Approach

### 4.1 Governing architecture

Draft ADR 0004 makes six choices:

1. optimize recurring projections, not source authority;
2. repair projection eligibility before measuring;
3. keep evidence/coordination in Dev without creating a runtime or registry; and
4. require owner-local changes, exact-digest approval, and projection-specific client proof;
5. reserve learned-data repair for an explicit operator-owned machine-local gate; and
6. reject ambiguous measurement inputs through versioned static and description-normalization contracts.

The program inventory and evidence ledger are audit artifacts only. They never decide what a client loads and never become a second enrollment, exposure, hook, or memory authority.

### 4.2 Measurement contract

`kp-context-measurement/v1` is the binding static algorithm:

1. Each manifest entry identifies either one full projected file or one exact managed region. Count every distinct injected projection once, even when two projections have identical text.
2. Read raw bytes, record their SHA-256, and decode strict UTF-8. Invalid UTF-8 is `BLOCKED_PREREQUISITE`.
3. Normalize `CRLF` to `LF`, then remaining `CR` to `LF`. Preserve every other Unicode scalar value exactly: no NFC/NFKC normalization, trimming, final-newline insertion/removal, tab expansion, or frontmatter removal.
4. `characters` is the number of Unicode scalar values after newline normalization. Frontmatter, delimiters, and managed-region boundaries count when the client receives them.
5. `words` is the number of maximal runs separated by this pinned Unicode 15.0 `White_Space` set: U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, and U+3000.
6. Order entries by the manifest's unique projection ID; totals are integer sums. Comparison refuses different algorithm versions, projection identities/order, client/root classes, or baseline IDs.

`skill-description-normalization/v1` is separate from static measurement:

1. The first exact frontmatter document must be valid YAML 1.2 Core schema. Missing/malformed frontmatter or a missing/non-string `description` is `BLOCKED_PREREQUISITE`; no fallback line parser may emit a total.
2. Extract the YAML string after native block-scalar folding/chomping, preserve Unicode scalars without normalization, replace each maximal run of the pinned whitespace set above with U+0020, and trim leading/trailing U+0020.
3. Count Unicode scalar values; compare exact normalized strings for duplicates. The inventory records parser/conformance-fixture version and source digest.

The post-eligibility `static-context-manifest/v1` record must contain:

- capture timestamp and eligible client/root;
- each of the seven projection paths;
- category (`rules` or `generated-memory`);
- owner repository, exact default-branch commit, source path, and source blob/digest;
- raw and normalized SHA-256, bytes, words, and characters;
- `kp-context-measurement/v1`, pinned whitespace-set version, ordered projection IDs, client/root class, and baseline ID;
- for generated memory, input-source digests/counts and output digest only—never learned content in tracked evidence;
- total words/characters and the exact 30% target.

Evidence splits cleanly:

- **Deterministic/source evidence:** exact refs/blobs/digests, installed byte equality, size counts, tests, isolated-HOME install, rollback/ref proof.
- **Live-client evidence:** context-category observation where available, discovery, ordinary-language invocation, positive/negative routing, and changed behavior in a fresh eligible client.

The Cursor Context tray may corroborate Rules/Skills/MCP category movement. It cannot replace the manifest because its tokenization and UI are not a stable cross-client contract. Description totals remain unavailable until every candidate passes strict YAML and the versioned description normalizer.

### 4.3 Protected invariants

Every owner plan/change artifact must bind its changes to these invariants:

- AWA denies confirmed protected-primary mutations and preserves v1.5.1 read-only Git classifications.
- Global hooks remain fail-open on hook failure; `afterFileEdit` remains observation-only.
- Finish-current exact-literal safety, recovery maintenance, and session heartbeat behavior remain available.
- No user loses a skill, MCP tool, sub-agent, ordinary-language route, or explicit invocation path.
- `agent-route` remains the global root-selection primitive; no context-specific router is added.
- Save-Game remains the checkpoint/reconcile authority and is not coupled to continual-learning memory.
- `agent-learnings.md` files remain machine-local sources; `~/AGENTS.md` remains generated output and is never hand-edited or treated as input.
- Work-only/private facts are not promoted, committed, printed into evidence, or removed to satisfy size goals.
- Model-tier/orchestration semantics and exact model-catalog ownership remain unchanged.
- CPP global capability payloads remain byte-consistent with their owner source and are never hand-edited in CPP.

### 4.4 Release 0 — eligibility and hook transition

Eligibility is a release, not pre-work hidden inside the baseline.

#### Durable Skills source

Extend the existing Skills resolver only enough to reject a standalone Skills clone whose trusted source sits below a disposable Cursor-worktree ancestor. Resolve to the established primary Skills checkout or refuse with a plain diagnostic. Then run the standard bootstrap/reconciler to relink owned projections and refresh pointers. Do not add a registry.

#### Durable CPP projection

CPP must classify this repository-wide installer/projection change under its current governance. At CPP `44106b9c`, that means a CPP-owned `_ops/plans/` control-plane plan with `Class: control-plane`, not a Dev-authored plan or direct Dev mutation. Its accepted change must define a durable approved checkout/root, reconcile Cursor/Claude/Codex links away from disposable worktrees, cover invocation from primary and linked worktrees, preserve foreign-link non-clobbering, and prove idempotence. Dev consumes only the resulting installed evidence.

#### Operator-owned memory source gate

For every agent-route-discovered `agent-learnings.md` that is nonempty but unparsable:

1. stop before mutation and present the exact path, failure class, privacy boundary, and proposed preservation/repair action to the operator;
2. after explicit operator authorization, classify whether it is a real machine-learning source, a header-only/generated residue, or malformed content;
3. preserve private bytes and permissions before any authorized change;
4. repair only the authorized operator-owned source or its discovery eligibility;
5. retain fail-closed behavior for genuinely malformed nonempty input; and
6. prove deterministic generation plus restore without hand-editing `~/AGENTS.md`.

Skills owns a plan/change artifact only if the operator-authorized reproduction demonstrates a generator, parser, discovery, or installer code defect against preserved fixtures. A data-specific failure alone creates no Skills mutation authority. No exact volatile workspace path appears in a repository implementation contract.

#### Hook ownership

Target live matrix:

| Event | Command owner/path class | Required policy |
|---|---|---|
| `sessionStart` | Dev `worktree-session.sh` delegator | `failClosed: false` |
| `beforeShellExecution` | Dev `worktree-guard.sh` delegator | `failClosed: false` |
| `afterFileEdit` | Dev `worktree-guard.sh` delegator | `failClosed` absent |
| `sessionStart` | Installed AWA `awa-recovery-maintenance.sh` | `failClosed: false` |
| `beforeSubmitPrompt` | Installed AWA `before-submit-prompt.sh` | `failClosed: false`; `matcher: UserPromptSubmit` |

Exactly one entry of each role may exist. Transition order is fixed:

1. AWA adds an explicit external-host hook-owner mode whose default preserves standalone direct ownership; external mode writes no real hook file and doctor reports the selected owner.
2. AWA publishes a tested release preserving all v1.5.1 hook/product behavior.
3. Skills advances the GCB by exact release commit through its normal governed lifecycle.
4. Dev takes ownership only after the installed runtime advertises the external-owner contract and its checkout/runtime/pointer match the approved release digest.
5. Dev reconciles five logical hook roles atomically, replacing known direct/delegated variants while preserving unrelated hooks.
6. Clean install, in-place `v1.5.0` upgrade, current `3+3+2` repair, repeated direct/GCB repair under external mode, failure, and rollback fixtures prove no missing/duplicate interval. The same Git command corpus must produce the same classification and fail-open behavior through direct and Dev-delegated v1.5.1 paths.

Rollback must restore a complete direct AWA five-row owner before retiring Dev ownership; never remove the active owner first.

User-home AWA hooks are ineligible in Cursor Cloud because the home file is absent there. This does not make the `beforeSubmitPrompt` event Desktop-only: repository hooks currently support it in Cloud. Cohort claims must name the projection and scope.

### 4.5 Optimization order

#### Static payloads

Apply reductions in this order:

1. remove duplicated explanations already available from a one-hop owner source;
2. replace rarely needed detail with a precise pointer and trigger for progressive disclosure;
3. consolidate repeated facts while retaining every safety/authority decision;
4. shorten generated wording only after source-bullet identity and restore are proved; and
5. touch safety-critical AWA content only if Dev/Skills reductions cannot meet the target and the operator approves the exact candidate digest.

The target is portfolio-level, not a mandatory per-file haircut. Small already-efficient payloads may remain byte-identical.

#### Capability discovery

Apply discovery reductions in this order:

1. reconcile stale, duplicate, or wrongly rooted installed projections through existing installers;
2. for repository-bound capabilities, test existing exposure/project/path scoping before shortening;
3. preserve out-of-root ordinary-language routing through existing `agent-route`, then prove the destination client loads the project capability;
4. shorten remaining auto-discovery descriptions with positive, negative, and collision routing tests; and
5. use manual-only invocation only when the capability's existing authority already declares it manual-only.

After strict YAML eligibility and the versioned normalizer pass, owner verifiers enforce:

- over 300 characters: warning and justification;
- over 600 characters: failure;
- over 1,024 characters: immediate failure during migration as well;
- exact duplicate normalized descriptions: failure.

Block-scalar YAML must be parsed correctly; malformed YAML blocks the inventory. The current frontmatter verifier's deliberate non-measurement cannot be replaced by line-oriented truncation or permissive fallback.

#### Explicit subtraction

This version contains no MCP optimization and no dedicated Save-Game compaction project. AWA operator compaction is conditional, not mandatory. These removals eliminate work without weakening the 30% static target or fresh-client gates.

### 4.6 Client evidence matrix

Each owner plan/change artifact declares only affected rows:

| Cohort | Evidence when eligible | Ineligibility rule |
|---|---|---|
| Cursor Desktop, fresh Dev root | Rules/Skills category observation, discovered IDs, ordinary-language and explicit invocation, changed behavior | None for current local projections |
| Cursor Desktop, fresh CPP root and fresh non-CPP root | CPP-local project-scope/discovery contrast plus agent-route handoff | Required only if CPP scope changes |
| Cursor Cloud | Repository-scoped rules/skills/hooks only | User-home rules/hooks/skills are ineligible because the VM lacks local home state; `sessionStart` is unsupported |
| Cursor background or multi-root | Synthetic contract regression when hook parsing/ownership changes | No blanket context-size claim without a stable projection measurement |
| Claude, fresh process | Installed/discovered rules and skills, affected ordinary-language invocation | Only capabilities exposed to Claude |
| Codex, fresh process | Installed/discovered rules and skills, affected ordinary-language invocation | Only capabilities exposed to Codex |

Fresh means after the new owner source is merged, the standard installer/reconciler has run, and the client has started a new process/chat that cannot reuse a prior catalog. A source test or current conversation is not fresh evidence.

### 4.7 Rollout and approval gate

For every context-changing candidate:

1. owner-classified plan/change artifact is accepted;
2. candidate source/rendered digests and semantic inventory are presented;
3. operator approves the exact candidate digest where the owner plan/change artifact classifies semantic/safety risk;
4. owner source tests and isolated-HOME install pass;
5. one fresh eligible client canary passes;
6. owner change lands through its normal PR path;
7. standard reconciliation updates the machine;
8. remaining eligible clients pass; and
9. evidence ledger records refs, digests, results, and rollback point.

Any capability-discovery, safety, memory, or routing regression stops rollout and restores the last known-good owner ref/projection. Autonomous rollout never substitutes for an approval or owner permission.

## 5. Work items

Every repository item below produces or consumes its owner's accepted plan/change artifact; the operator machine-local gate is not a repository child plan. None is directly executable from this document.

### Gate A — approve program authority

| ID | Owner | Objective | Prerequisites | Definition of done |
|---|---|---|---|---|
| A-01 | Dev/operator | Decide draft ADR 0004 and this v1 plan | Draft PR evidence and review complete | Operator explicitly accepts both or requests revision; no implementation implied |
| A-02 | Each implementation owner | Author an owner-classified zero-context plan/change artifact | A-01 accepted | Exact files/interfaces/tests/commands/rollout/rollback; accepted independently under the owner's current convention |

Owner classification is explicit:

| Owner | Current required planning/change classification |
|---|---|
| Dev | `_ops/plans/` with `Plan-type: agentic-execution` for implementation |
| AWA | `docs/plans/` under AWA's current convention; current agentic plans use `Plan-type: agentic-execution` |
| Skills | `docs/plans/` under Skills' current convention; no Dev-only marker is imposed |
| CPP | Repository-wide installer/projection work is a CPP `_ops/plans/` control-plane plan with `Class: control-plane`, per accepted ADR 0014 |
| Operator machine-local gate | Explicit operator authorization and private retained evidence; no repository plan substitutes |

### Release 0 — make measurement trustworthy

| ID | Owner | Objective | Prerequisites | Definition of done |
|---|---|---|---|---|
| E-01 | Skills | Close the standalone-under-disposable Skills source gap and reconcile owned links/pointers | Accepted Skills plan | Primary, linked-worktree, nested-standalone, missing-primary, dry-run, and idempotence fixtures pass; no active Skills-owned projection targets a disposable root |
| E-02 | CPP | Reconcile CPP-owned Cursor/Claude/Codex projections to a durable approved root | Accepted CPP `Class: control-plane` plan/change | Every relevant client link is inventoried; none targets a disposable root; primary/linked invocation, foreign-link preservation, dry-run, and idempotence pass |
| E-03 | Skills | Establish strict description-inventory eligibility | Accepted Skills plan | Every candidate has valid YAML 1.2 Core-schema frontmatter; current `update-skills` syntax defect is resolved; conformance fixtures prove `skill-description-normalization/v1`; no fallback parser emits totals |
| E-04 | AWA | Add explicit external hook-owner contract and publish a tested release | Accepted AWA plan | Direct mode remains default; external mode writes no real hook file; doctor/fixtures cover both; v1.5.1 behavior preserved |
| E-05 | Skills | Advance AWA GCB to E-04 exact release | E-04 merged/released; accepted Skills delivery plan | Pin, checkout, pointer, runtime, and doctor agree |
| E-06 | Dev | Reconcile the exact five-row host hook matrix | E-05 merged; accepted Dev plan | Clean install/upgrade/direct repair/rollback converge to five rows with no owner gap or duplicate |
| E-07 | Operator / machine-local | Classify and, only with explicit authorization, repair invalid learned-data sources | Private preservation and operator GO | Authorized source action recorded privately; source bytes/permissions restorable; official dry-run succeeds; generated output not hand-edited |
| E-08 | Skills (conditional) | Correct a reproduced continual-learning code defect, if E-07 proves one | E-07 reproduction; accepted Skills plan | Code-owned defect and fixtures are source-backed; dry-run/write/idempotence/restore pass; no operator data is embedded or modified by repository work |
| E-09 | Dev | Freeze `static-context-manifest/v1` | E-01, E-02, E-03, E-06, E-07 and conditional E-08 green | Seven installed bytes match owner refs and `kp-context-measurement/v1`; strict description inventory is valid; private content absent; denominator and rollback points frozen |

`E-01`, `E-02`, `E-03`, and the operator-gated `E-07` may proceed independently. `E-04 → E-05 → E-06` is serial. `E-08` activates only for a reproduced code defect. `E-09` waits for every applicable eligibility item.

### Release 1 — reduce the seven static payloads

| ID | Owner | Objective | Prerequisites | Definition of done |
|---|---|---|---|---|
| S-01 | Dev | Reduce Dev-owned static projections by removing duplication and adding precise progressive-disclosure pointers | E-09; accepted Dev plan | Protected invariant map passes; exact before/after digests and client canary recorded |
| S-02 | Skills | Reduce generated/global projection wording while preserving learned bullets, routing, and model-tier behavior | E-09; accepted Skills plan | Private restore proof, semantic inventory, source/install parity, and affected client canaries pass |
| S-03 | AWA (conditional) | Reduce AWA operator projection only if S-01/S-02 cannot meet the target | Measured shortfall; explicit operator decision; accepted AWA plan | Exact-digest review and full finish/hook/operator regression pass |
| S-04 | Dev/program | Converge and freeze Release 1 evidence | S-01/S-02 and, only if approved, S-03 | Both word and character totals are at least 30% below E-09 baseline; no protected regression |

The operator may decline S-03. That does not silently lower the 30% target; it requires further Dev/Skills reduction or an explicit plan revision.

### Release 1.1 — reduce capability discovery

| ID | Owner | Objective | Prerequisites | Definition of done |
|---|---|---|---|---|
| D-01 | Dev/program | Inventory the actual injected/discovered catalog by client/root and bind it to owner source | E-01, E-02, E-03; Release 1 evidence stable | Strict YAML eligibility, unique IDs, source owner, exposure, installed path/digest, normalized description size, and client eligibility recorded without assuming filesystem overlap equals injection |
| D-02 | Skills | Scope first, then shorten Skills-owned descriptions and add proper budget verification | D-01; accepted Skills plan | Existing 1,024 debt removed; all auto-discovery values meet 600 cap; no duplicates; routing eval/canaries pass |
| D-03 | CPP | Test project-scoping for CPP-local skills, then shorten only remaining globally necessary descriptions | D-01; accepted CPP `Class: control-plane` plan/change | Non-CPP overhead falls without losing agent-route → CPP → skill flow; CPP-root discovery/invocation passes; all remaining auto-discovery descriptions meet budget |
| D-04 | Skills/orchestrator/CPP | Reconcile global capability projections through the standard lifecycle | D-02 merged; normal registry/orchestrator approvals | No hand-vendored edits; owner-source/CPP payload consistency and client projection parity pass |

If project scoping fails an ordinary-language or client-parity canary, D-03 retains global exposure and applies description-only reductions. No new router is introduced.

### Release 2 — close the program

| ID | Owner | Objective | Prerequisites | Definition of done |
|---|---|---|---|---|
| C-01 | Dev/program | Run final projection-specific client matrix | Releases 1 and 1.1 merged/reconciled | Every eligible row passes; every ineligible row cites current product constraint; no stale current-chat evidence |
| C-02 | Dev/program | Freeze evidence and built-versus-planned ledger | C-01 | Exact owner refs/digests, static result, catalog result, residuals, and rollback refs recorded |
| C-03 | Owner repositories | Update only owner docs/policy touched by implementation | Corresponding child plan | No stale authority statement, duplicate registry, or superseded process remains |

## 6. Acceptance criteria

This program is complete only when all of the following are true:

1. The operator has accepted draft ADR 0004 and this plan; all owner-classified implementation plan/change artifacts were separately accepted before work.
2. Release 0 proves durable Skills and CPP client projections, valid strictly normalized description inputs, current AWA pin/runtime, the exact five-row hook matrix, operator-authorized memory-source eligibility, and reproducible continual-learning generation.
3. The official post-eligibility manifest is complete, content-safe, bound to exact owner refs/blobs, and reproducible under `kp-context-measurement/v1`; malformed description YAML cannot produce totals.
4. Release 1 reduces both words and characters by at least 30% from that manifest.
5. Every protected invariant in §4.3 has deterministic and, where affected, fresh-client evidence.
6. Learned facts/preferences remain source-preserved and restore-proven; no tracked evidence contains their content.
7. Every active owned capability link/pointer resolves to a durable approved source.
8. No AWA hook role is missing or duplicated; clean install, upgrade, repair, and rollback converge.
9. Skills and CPP description budgets are parsed from YAML correctly, existing debt is gone, exact duplicates fail, and ordinary-language routing passes.
10. CPP-owned scoping either passes the agent-route/client matrix or is rolled back to global exposure with description-only reduction.
11. Cursor, Claude, Codex, Cloud, background, and multi-root claims are projection-specific and current; no blanket exclusion hides an affected surface.
12. MCP and Save-Game remain available, but neither has acquired a duplicate program subsystem.
13. All owner changes are merged on their live default branches through normal governance, then reconciled through standard installers.
14. The final ledger contains no unresolved P0/P1 finding, unknown owner, stale ref, unproved rollback, or unclassified client cohort.

Acceptance of this plan is not implementation clearance. Completion of a child plan is not acceptance of the program. Only C-02/C-03 evidence supports a later operator completion decision.

## 7. Rollback and supersession

### Planning PR

Closing or reverting this draft documentation PR changes no runtime state. Because v1 remains DRAFT, it may be revised in place. Once accepted, v1 becomes byte-immutable; a material future change requires `context-efficiency-program-v2.md` with `Supersedes:` and a new ADR only if the architectural decision changes.

### Future implementation

- **Static source reduction:** revert the owner commit/ref, run the standard installer/render, and re-run affected fresh-client checks.
- **Generated memory:** only under operator authorization, restore the private pre-change source snapshot, regenerate, compare digest/semantic inventory, and retain failed artifacts for diagnosis without committing content. Repository rollback never mutates operator-owned source data.
- **Capability links:** reconcile from the last approved durable primary source; never restore a disposable target.
- **Hook ownership:** establish the complete prior owner first, prove all five rows, then retire the failed owner. Never delete rows before replacement is live.
- **Description/scoping:** restore prior source/exposure and reconcile through the same Skills/orchestrator/CPP path; re-run out-of-root and in-root canaries.
- **Evidence manifest/ledger:** regenerate or retire it freely; it has no runtime authority.

If an owner repository changes its authority or client behavior invalidates ADR-0004, stop rollout and supersede the decision/plan rather than adding a compatibility layer to this draft.

## Appendix A — material current-state corrections

### Removed

- Historical MCP optimization/benchmark work: no current owner dependency.
- Dedicated Save-Game compaction implementation/reproof: authority is already shipped and unchanged.
- Mandatory AWA operator compaction: now conditional on a measured static-target shortfall.
- Volatile machine-path work items and duplicate milestone/state-machine prose.

### Corrected

- The reproducible machine-local preflight is 8,704 words / 66,965 characters under `kp-context-measurement/v1`; 8,694 / 66,891 was a frontmatter-counting error. The official denominator waits for Release 0.
- Prior description character/threshold totals are withdrawn because current Skills frontmatter is not uniformly valid YAML.
- Continual-learning cadence is 40 turns / 8 hours.
- Skills source resolution is partial shipped work, not a greenfield resolver.
- AWA source is `v1.5.1` while the observed machine is stale at `v1.5.0`.
- `beforeSubmitPrompt` is supported for repository hooks in Cloud; user-home hooks remain unavailable there.
- DRAFT ADR status is `draft` under doc-warden, not a nonstandard `Proposed` marker.

### Added

- CPP as owner of its globally projected skill catalog and a pre-baseline durable-root reconciliation across Cursor, Claude, and Codex.
- Actual injected/discovered catalog evidence rather than source-file counts alone.
- Scope-first discovery reduction through existing exposure/project mechanisms and `agent-route`.
- Clean-install continuity for AWA's two product rows.
- Content-safe evidence requirements for private machine memory.

### Resequenced

```text
accept plan + ADR
  -> repair Skills + CPP projections; validate YAML; operator-authorized memory eligibility
  -> AWA contract -> Skills pin -> Dev five-row hooks
  -> freeze official baseline
  -> owner-local static reductions + per-change canaries
  -> capability scope/description reductions
  -> final client matrix and evidence closure
```

## Appendix B — owner plan/change contract

Every repository implementation plan/change artifact must:

- use the owner-specific classification in §5; Dev's `Plan-type` never overrides AWA, Skills, or CPP governance;
- bind current `origin/<default>` and exact dependency refs before authoring;
- name exact files, interfaces consumed/produced, tests, commands, expected failures/passes, rollout, and rollback;
- include clean install, in-place upgrade, repair, idempotence, failure, and client-evidence cases proportional to its surface;
- keep one writer per working tree and use the repository's governed PR path;
- preserve owner authorization and exact-digest approval gates;
- stop if a fresh ref invalidates this program's assumption; and
- update only documentation/policy its implementation actually makes stale.

## Appendix C — residual operator decisions

1. Accept, reject, or revise draft ADR-0004 and this v1 program plan.
2. Approve each semantic/safety candidate by exact digest when its accepted owner plan/change artifact requires it.
3. If Dev/Skills work cannot meet the 30% static target, choose between additional Dev/Skills reduction, conditional AWA work, or a formal plan revision—never an implicit target reduction.
4. Accept CPP project-scoping only after the ordinary-language/client matrix proves no access loss; otherwise retain global exposure and use description-only reduction.
5. Separately authorize or decline each machine-local learned-data classification/repair proposal; plan or ADR acceptance does not grant that authority.
