# Agent Worktree Automation (AWA): verified end-state architecture — v2

> **Status.** This is the hardened **v2** planning deliverable. It supersedes
> `agent-worktree-automation-end-state.md` (v1, kept intact for diffing) as the current
> source of truth for the AWA end-state design. It is a **planning document**, not an
> implementation: no daemon/engine is built here.
>
> **What changed from v1.** Every material assertion in the v1 plan and the v1 shipped shims was
> checked against reality (Cursor's real hook/MCP API, macOS, git, SQLite, and the `~/dev`
> governance model). Refuted assertions are corrected inline; the full evidence is in the
> **Assumption & Assertion Verification Ledger** below, and the headline corrections are in
> **Corrections from v1**.
>
> **Verification date / environment.** 2026-07-03 on macOS 26.5.1 (Darwin 25.5.0, arm64),
> git 2.50.1 (Apple Git-155), python 3.14.2 / sqlite 3.53.2, Cursor hooks doc `cursor.com/docs/hooks`.

## Corrections from v1 (changelog)

The v1 plan is architecturally strong; these are the **material corrections** where v1 asserted
something that reality refutes or under-specifies. Each links to a ledger row (Lxx) with evidence.

| # | v1 assertion | v2 correction | Severity | Ledger |
|---|---|---|---|---|
| C1 | "user-scoped **systemd/launchd** daemon with socket activation." | macOS has **no systemd** (`systemctl` absent; `launchctl` present). Service model is **launchd only**. Prefer on-demand CLI-spawns-daemon + Unix socket, with an optional launchd agent reusing the existing `local-jobs` launchd framework rather than a bespoke plist. launchd socket activation exists (`Sockets` key) but is optional complexity. | High | L1 |
| C2 | Agent-created path: create durable worktree on a new local branch, then `move_agent_to_root`, then attest. | `move_agent_to_root` **runs `git fetch origin <branch>` + ff-merge against the destination and fails on local-only branches** ("Remote branch not found on origin"). The relocation transaction MUST **publish the branch to origin before the move** (or use the Cursor-native Agents-Window worktree, or `move_agent_to_cloned_root` for verbatim clones). This is the single biggest technical flaw in v1. | Critical | L5, L6 |
| C3 | Dashboard: "in-canvas refresh **without launching chat**." | A `.canvas.tsx` is **render-only** (no `fetch`, no shell, imports only `cursor/canvas`). The only refresh levers are `useCanvasAction` → `newComposerChat` (which **does** launch a chat) or an external `make worktree-dashboard`. Keep the v1-shipped honest "Refresh via agent" model; drop "without launching chat." | Medium | L7, L8 |
| C4 | Hooks give "fail-closed" protection incl. `afterFileEdit`; `stop/sessionEnd` "fail closed for cleanup." | `afterFileEdit` is **observation-only** (Input schema only; no permission output) — it cannot ask/deny/prevent an edit. `stop` **cannot block**; it only supports `followup_message` continuation (loop_limit default 5). There is **no `beforeFileEdit`** event, so pre-write prevention of the agent's native edit tool is impossible; only `beforeShellExecution`/`beforeReadFile` can block pre-action. | High | L2, L3, L4 |
| C5 | Environment matrix: Cloud is "partial until a local service bridge exists." | Deeper truth: **user-level `~/.cursor/hooks.json` hooks do not run in cloud agents at all**, and `sessionStart`, `beforeSubmitPrompt`, `beforeMCPExecution`, `stop` are **not available in cloud**. Cloud protection must use **repo-committed project hooks** (`beforeShellExecution`/`afterFileEdit` only) + PR-first flow; no local daemon, no MCP gating, no yield-check. | High | L9, L10 |
| C6 | `~/.local/state`, `~/.local/share`, `~/.config` presented as the state/config roots. | Correct-with-nuance: those dirs exist but `$XDG_*` env vars are **unset** and these are **not macOS-native** (`~/Library/...`). Honor `$XDG_STATE_HOME`/`$XDG_DATA_HOME`/`$XDG_CONFIG_HOME` when set, else default to `~/.local/...`. State DBs are globally gitignored (`*.db`,`*.sqlite`), satisfying "never source-tracked." | Low | L11, L12 |
| C7 | "Intent detection" as if Cursor classifies intent. | `beforeSubmitPrompt` hands you only the **raw prompt text + attachments**; there is no built-in intent classifier, and this hook is **Desktop-only** (not in cloud). Intent detection is DIY heuristics on prompt/command text, best-effort, Desktop-only. | Medium | L3, L9 |
| C8 | Packaging matrix: AWA CLI/engine/watcher = `kind: tool, scope: global` on a "global tools shelf." | The `capabilities/skills/global/tools/` shelf **does not exist yet** (only `skills/` is present); it must be created. cpp `enabled_kinds` for `tool`/`rule`/`sub-agent` are **not yet flipped** (blocked on the cpp-governed reconciler PR), so AWA-as-tool cpp vendoring is gated even after local trust. | Medium | L13, L14 |
| C9 | Installed hooks assumed fail-closed for shell mutation. | The **deployed** `~/.cursor/hooks.json` sets `failClosed: false` for the guard, while `install-worktree-hooks.sh` writes `failClosed: true` → real deployment drift. Note `failClosed` only affects **hook-failure** behavior (crash/timeout/invalid JSON), not the normal-path decision. | Low | L2, L15 |
| C10 | Hook response fields referenced loosely (`user_message` vs `userMessage`). | Cursor's real response field is **`user_message`** (snake_case) — the v1 guard hook is correct. (`agentMessage`/`userMessage` seen in third-party blogs are not Cursor's schema.) `failClosed` is a **hook-definition** field, `additional_context` is real for `sessionStart`. This is a *confirmation*, not a defect. | Info | L2 |

## Assumption & Assertion Verification Ledger

Status legend: **Verified** (evidence attached), **Refuted** (correction + evidence),
**Unverifiable-now** (open risk + the exact method to verify later). Evidence types: `doc`
(official Cursor docs), `descriptor` (installed MCP tool schema), `probe` (command run + observed
output), `file:line` (source in this repo), `os` (OS probe).

### Cluster A — Cursor API surface (hooks, MCP, canvas)

| ID | Assertion (from v1 / end-state) | Status | Evidence | Correction / note |
|---|---|---|---|---|
| L1 | Service is a "systemd/launchd daemon." | **Refuted** | `os`: `command -v systemctl` → none; `launchctl version` present; `sw_vers` → macOS 26.5.1. | launchd only on this machine. Drop systemd. See C1. |
| L2 | Hooks support `permission`, `failClosed`, `user_message`; `sessionStart` injects `additional_context`. | **Verified** | `doc` cursor.com/docs/hooks: `failClosed` (default false) blocks only on hook **failure**; before-hooks return `{permission: allow|deny|ask, user_message}`; `sessionStart` output `additional_context`. `file:line` `_ops/cursor-hooks/worktree-guard.sh:64-78` emits `permission`+`user_message` (correct schema). | Field is `user_message` (snake_case). v1 correct. |
| L3 | Hook set: `sessionStart, beforeSubmitPrompt, beforeShellExecution, afterFileEdit, beforeMCPExecution, stop/sessionEnd`. | **Verified (events exist) / Refuted (capabilities)** | `doc`: real events incl. `sessionStart`/`sessionEnd` (distinct), `beforeSubmitPrompt`, `beforeShellExecution`/`afterShellExecution`, `beforeMCPExecution`/`afterMCPExecution`, `beforeReadFile`/`afterFileEdit`, `preToolUse`/`postToolUse`, `subagentStart/Stop`, `preCompact`, `stop`, `workspaceOpen`, tab hooks. | No `beforeFileEdit`. `afterFileEdit` observation-only. `stop` ≠ blocking. See L4. |
| L4 | `afterFileEdit` can "ask/deny" primary edits; `stop` can "fail closed for cleanup." | **Refuted** | `doc` §afterFileEdit shows **Input only** (`file_path`,`edits`) — no permission output. `doc` §stop: returns `followup_message`, subject to `loop_limit` (default 5); "about what happens after the agent loop ends… not the same as blocking a shell command." | `afterFileEdit` = detect + recover only. `stop` = followup nudge, cannot block a git deletion. |
| L5 | Agent creates worktree on a new branch, then `move_agent_to_root`. | **Refuted** | `descriptor` `move_agent_to_root.json`: "runs `git fetch origin <branch>` against the destination and will fail with 'Remote branch not found on origin' on local-only branches." | Must publish branch to origin before the move. See C2. |
| L6 | `move_agent_to_root` is a pure workspace-root switch. | **Refuted** | `descriptor`: it performs a "migration-path `git fetch` + ff-merge"; `move_agent_to_cloned_root` exists precisely to **skip** that. `probe`: `git fetch origin awa/test-branch` on a local-only branch → `fatal: couldn't find remote ref awa/test-branch`. | The move mutates the destination (fetch+ff-merge); treat it as such in the relocation transaction. |
| L7 | Canvas can self-refresh / call back into the engine. | **Refuted** | `file:line` `.cursor/skills-cursor/canvas/SKILL.md:52-53` ("Import only from `cursor/canvas`… No `fetch()`, no network calls"); `file:line` `_ops/dashboards/awa-dashboard.canvas.tsx:312-325` refresh dispatches `newComposerChat`. | Canvas is render-only; refresh = agent/command. |
| L8 | Dashboard offers "in-canvas refresh without launching chat." | **Refuted** | Same as L7: the only in-canvas lever (`useCanvasAction`) opens a composer chat; v1 already labels the button "Refresh via agent" and states "This canvas cannot execute shell directly." | Keep honest agent-command refresh (`make worktree-dashboard`). |
| L9 | Intent detection + `beforeSubmitPrompt` work everywhere. | **Refuted (scope)** | `doc` lines 77-78: `beforeSubmitPrompt` "can't run in the cloud environment"; input is raw prompt text + `attachments` only (no classifier). | Desktop-only, DIY heuristics. |
| L10 | Cloud agents run the AWA hook surface. | **Refuted** | `doc` lines 56-97: user-level `~/.cursor/hooks.json` **not loaded in cloud**; unavailable in cloud: `sessionStart/sessionEnd`, `beforeSubmitPrompt`, `beforeMCPExecution/afterMCPExecution`, `stop`, `workspaceOpen`, tab hooks. Cloud runs command-based **project** hooks only. | Cloud protection = committed project hooks (`beforeShellExecution`/`afterFileEdit`) + PR-first. |
| L15 | Deployed hooks are fail-closed for shell mutation. | **Refuted (drift)** | `file:line` `~/.cursor/hooks.json:24-37` → `failClosed:false`; `file:line` `_ops/bin/install-worktree-hooks.sh:47-56` writes `failClosed:True`. | Installer not re-run (or hand-edited). Reconcile; note `failClosed` only affects failure path. |
| L16 | An AWA MCP server can be registered/run here. | **Verified (Desktop) / Refuted (cloud)** | `probe` `~/.cursor/mcp.json`: 13 servers incl. local **stdio** (`openflowkit`,`playwright`,`snowflake`,`google-kit`); `file:line` `_ops/bin/install-mcp.sh:5-9` mirrors stdio→Codex, all→Claude. Cloud: `beforeMCPExecution` not wired + local stdio process absent on the VM. | Register AWA MCP as a local stdio server in `mcp.json`; Desktop-local only. |

### Cluster B — OS, SQLite, git reality

| ID | Assertion | Status | Evidence | Correction / note |
|---|---|---|---|---|
| L11 | State/config live at `~/.local/state`, `~/.local/share`, `~/.config`. | **Verified (dirs) / nuance** | `os`: all three dirs exist; but `XDG_STATE_HOME`/`XDG_DATA_HOME`/`XDG_CONFIG_HOME` are **unset**; macOS-native is `~/Library/...`. | Honor `$XDG_*` if set, else `~/.local/...`. Document non-native choice. |
| L12 | Recovery/state DBs are never source-tracked. | **Verified** | `file:line` `.gitignore:73-75` ignores `*.sqlite`,`*.sqlite3`,`*.db`; allow-list root `/*` ignores all under `~/dev` by default. | State under `~/.local/...` is outside the repo anyway; belt-and-suspenders holds. |
| L17 | SQLite WAL is available with concurrency. | **Verified** | `probe` file DB: `PRAGMA journal_mode=WAL` → `wal`; `busy_timeout=5000` set; `-wal` sidecar created. sqlite 3.53.2. | WAL = 1 writer + N readers; serialize writers via `busy_timeout` + the per-common-git-dir lock. |
| L18 | `--git-common-dir` vs `--git-dir` distinguishes primary vs linked worktree. | **Verified** | `probe`: primary → equal; linked worktree → git-dir `…/.git/worktrees/wt1`, common-dir `…/.git`. `file:line` `_ops/bin/dev-worktree.sh:57-70` uses this. | Correct in v1. |
| L19 | `git rev-list --left-right --count base...HEAD` yields ahead/behind. | **Verified** | `probe`: after 2 commits ahead of `main`, output `0\t2` = `behind<TAB>ahead`. `file:line` `_ops/bin/awa-dashboard-data.py:214-216` parses `behind, ahead = parts[0], parts[1]` (correct order). | Correct in v1. |
| L20 | Worktree add/list/prune + detached HEAD behave as assumed. | **Verified** | `probe`: `worktree list --porcelain` blocks parse; `--detach` → `rev-parse --abbrev-ref HEAD`=`HEAD`; manual dir removal → `prunable`, `git worktree prune` reclaims. | Correct in v1. |

### Cluster C — Governance, packaging, prior claims

| ID | Assertion | Status | Evidence | Correction / note |
|---|---|---|---|---|
| L13 | AWA package source belongs in a global capability repo, not `_ops`. | **Verified** | `file:line` `_ops/POLICY.md:33-38` (capabilities/skills & mcp are their own repos, never tracked here); end-state doc line 830. `probe`: `capabilities/mcp/` is the MCP monorepo (has `template`, `tools`). | `_ops` keeps only plans/runbooks/verifier wrappers. |
| L14 | AWA = `kind: tool, scope: global` on a global tools shelf; cpp rollout via orchestrator. | **Verified-with-gaps** | `probe`: `capabilities/skills/global/` has only `skills/` (no `tools/`,`rules/`,`sub-agents/` shelves yet). `file:line` AGENTS.md/agent-context: `tool`/`rule`/`sub-agent` `enabled_kinds` not flipped until cpp reconciler PR merges. | Must create the `tools/` shelf; cpp vendoring of a `tool` is gated. |
| L21 | ecosystem-orchestrator is the only sanctioned cpp writer. | **Verified** | `file:line` `_ops/POLICY.md:185-189`; `probe`: `personal/ecosystem-orchestrator/bin/orchestrator.sh` present + executable. | Correct. |
| L22 | `.gitignore` allow-list will track a new `_ops/plans/*.md` doc. | **Verified** | `file:line` `.gitignore:21` `!/_ops/`; `make verify` passes the allow-list integrity check with this doc added. | v2 doc under `_ops/plans/` is tracked. |
| L23 | Prior claim: "18 governed repos." | **Verified (≈)** | `probe` dashboard-data: live count 24 = 18 real + 6 transient `.awa-verify.*` fixtures from the verify run. Real set: 1 umbrella + 10 `personal/*` + 2 `capabilities/*` + 5 `affirm/src/*`. | Count is dynamic, not fixed; ~18 real repos. |
| L24 | Prior claim: `make verify` and `make worktree-verify` are green. | **Verified** | `probe`: both exit 0; `worktree-verify: OK` (32 PASS incl. 8 disposable UATs), `verify-operating-model: OK`. | Confirmed on 2026-07-03. |
| L25 | v1 shims map onto the engine without regressing the green verifiers. | **Verified (path) / Unverifiable-now (engine)** | The verifiers assert **file presence, executability, schema, and behavior of the shims** (`_ops/checks/worktree-verify.sh:17-108`). As long as `dev-worktree.sh`/`awa-dashboard-data.py` keep their CLI + JSON contract as thin wrappers, the engine can back them. | Keep the shim CLI/JSON contracts frozen; add a contract test before re-pointing them at the engine. |

## Preserved from v1 (unchanged, verified sound)

The following v1 sections stand as-is and remain the design intent; v2 does not restate them in
full. Read them in the v1 doc, subject to the corrections above:

- **Executive goal & operator journeys** (the Safe Workspace promise; "fix this bug" / "try three
  approaches" / "bring that into main" / dirty-primary rescue / crash recovery / GitHub-down).
- **Product model, modes (`ON`/`ASK_ON`/`OFF`), operator contract, and copy** — the plain-English
  surface. Verified sound; the only change is *where* enforcement can actually happen (Cluster A).
- **Bounded subsystems** ("engine decides, adapters execute, watcher observes, dashboard explains")
  and the **lease/state model**, **lifecycle state machine**, **cleanup blockers**, and
  **recovery artifact requirements** — all internally consistent and implementable on SQLite/git.
- **Engine API decision/error taxonomy** (`allow/ask/deny/warn/unavailable`, reason codes).
- **Security & privacy posture** (local-first, `700`/`600`, no telemetry, redaction) — reinforced
  by L12 (state is un-trackable by construction).

The sections below **replace** the corresponding v1 sections.

## Corrected Cursor integration surface (replaces v1 "Cursor hooks" + "Enforcement layers")

**What Cursor actually exposes (verified L2–L4, L9, L10, L16):**

| Capability | Reality | AWA consequence |
|---|---|---|
| Block a **shell** mutation pre-exec | `beforeShellExecution` → `permission: deny/ask/allow` | The one true pre-mutation gate for git/`rm`/install commands in the primary checkout. |
| Block a **file read** | `beforeReadFile` → `permission: deny` (+`failClosed`) | Optional (e.g., protect secrets); not core to worktree isolation. |
| Block a **native file edit** pre-write | **Not possible** — no `beforeFileEdit` event | AWA cannot prevent the agent's own edit tool touching primary. Detection + recovery only. |
| Detect a file edit after the fact | `afterFileEdit` (Input `file_path`,`edits`; **no permission output**) | Trigger recovery-diff / "you edited primary" receipt. Cannot ask/deny. |
| Inject session context | `sessionStart` → `additional_context` (**fire-and-forget, non-blocking**) | Load AWA receipt; never rely on it to block. |
| Gate an MCP call | `beforeMCPExecution` → `permission` (recommend `failClosed:true`) | Gate destructive `awa.*` MCP calls **on Desktop only** (not wired in cloud). |
| Continue after completion | `stop` → `followup_message` (loop_limit 5; **cannot block**) | Yield-safety = a followup nudge ("push/bundle before you stop"), not a hard cleanup gate. |
| Classify intent | none built in; `beforeSubmitPrompt` gives raw text + attachments, **Desktop-only** | Intent detection = DIY keyword/command heuristics, best-effort. |

**Enforcement layering (honest):** policy engine → MCP tools → `beforeShellExecution` (real gate) →
rule/skill (agent behavior) → `afterFileEdit` detection → watcher/git invariants →
recovery/cleanup refusal. AWA **guarantees detection, recovery, cleanup refusal, and safe
lifecycle decisions**; it does **not** guarantee pre-write prevention of every mutation path
(only shell mutations are truly gated). This matches, and tightens, v1's own caveat.

**Deployment note (L15):** re-run `install-worktree-hooks.sh` so the deployed `failClosed`
matches intent, and decide the policy deliberately: `failClosed:true` on `beforeShellExecution`
means a hook crash/timeout **blocks** the mutating command (safe but can wedge the agent if the
guard is slow); `false` fails open. Recommend `true` for `beforeShellExecution`/`beforeMCPExecution`,
irrelevant for `afterFileEdit`/`sessionStart` (no gate).

## Corrected relocation transaction (replaces v1 "Agent-created path" / "Relocation transaction")

Root cause (L5/L6): `move_agent_to_root` fetches + ff-merges the destination's branch from
`origin` and **fails on a local-only branch**. The v1 flow (create local branch → print move
instruction) is therefore broken for the common "agent creates a fresh worktree" case.

**Corrected agent-created flow:**

1. Resolve eligibility + mode; pin `base_sha`.
2. Allocate lease; create worktree + branch off the pinned base (`git worktree add -b`).
3. Write `.awa/lease.json` and the state-DB lease record (`relocation_pending`).
4. **Publish the branch to origin** (`git push -u origin <branch>`) *before* the move — this is the
   new required step that makes `move_agent_to_root` succeed. If push fails (offline / no remote /
   GitHub down): **do not call the move**; surface `REMOTE_UNAVAILABLE`, keep the worktree, and offer
   "open the worktree manually" — never leave the agent believing it relocated when it did not.
5. Invoke `move_agent_to_root {rootPath}` (agent-only; a shell/daemon cannot call MCP — L16 corollary).
6. `awa attest` (root, repo, git-dir≠common-dir, branch, HEAD, base, lease, primary≠worktree path).
7. Mark `attested` only after all checks pass; any lease stuck in `relocation_pending` is
   resumable/abortable without deleting the worktree.

**Preferred flow (avoids the fetch problem entirely):** the **Cursor-native Agents-Window
Worktree dropdown** — Cursor creates *and* moves into the worktree; AWA **adopts** it (records
lease, verifies, attests). Recommend this as the default operator path; the agent-created path is
the mid-session fallback.

**Environment matrix (corrected — replaces v1 table):**

| Environment | Hooks that run | Relocation | AWA posture |
|---|---|---|---|
| Cursor Desktop, local repo | all (user + project) | agent-created (publish-then-move) or native dropdown | Full: daemon + hooks + MCP + watcher + dashboard. |
| Agents Window Worktree dropdown | all | Cursor-native (adopt) | Full; **preferred** relocation path. |
| Editor Window | all | native `/worktree` or agent-created | Full; engine via rule/hooks/MCP/CLI. |
| **Cloud agent** | **project `.cursor/hooks.json` only**; no `sessionStart`/`beforeSubmitPrompt`/`beforeMCPExecution`/`stop` | branch already on origin (cloud branch) → move works | **No local daemon, no user hooks, no MCP gating, no yield-check.** Rely on committed project `beforeShellExecution`/`afterFileEdit` + PR-first. Show "local AWA unavailable." |
| CLI-only terminal | n/a (no agent loop) | manual | CLI ↔ engine / local-guard fallback. |
| Non-git / vendor / cpp | n/a | none | Advisory only; never mutate hidden state. |

## Corrected dashboard / refresh model (replaces v1 "Dashboard refresh")

A canvas is a render-only React app (L7): it embeds a JSON snapshot inline and **cannot** run
git, shell, or network. The v1 dashboard already implements the honest model and it is kept:

- The rendered canvas is produced by `install-awa-dashboard.sh`, which runs the **read-only**
  `awa-dashboard-data.py` emitter and injects the snapshot between `AWA_DATA` markers; the
  source-tracked seed stays data-free (asserted by `--check` in `worktree-verify`).
- "Refresh" has exactly two honest levers: (a) an external `make worktree-dashboard`
  (agent/automation/local-jobs), or (b) the in-canvas button, which dispatches
  `newComposerChat` — i.e. it **launches a chat** that asks an agent to run the refresh. It can
  show pending/updated/stale states by comparing `generated_at`, but it cannot self-execute.
- Engine-backed evolution: the emitter becomes a thin `awa status --json` client of the engine;
  the canvas contract (schema `awa-worktree/v1` → future `awa-status/v2`) stays versioned and the
  `worktree-verify` seed/marker checks stay green. **Never** claim self-refresh or in-canvas shell.

Optional hands-free freshness is the **`local-jobs`** launchd framework (already integrated via
`install-awa-dashboard.sh --schedule`), not a canvas capability.

## Corrected service model, paths, and state (replaces v1 "Engine defaults")

- **Service model (L1):** launchd only. Default to **on-demand**: the CLI/first client starts the
  daemon; the daemon idles down. Optional always-on = a launchd LaunchAgent, and to avoid a bespoke
  plist, register it through the existing **`local-jobs`** framework (`com.kleinperkins.*`
  namespace). launchd socket activation (`Sockets` key + `launch_activate_socket`) is available but
  is optional complexity; the on-demand model is simpler and sufficient.
- **Transport:** Unix domain socket under the state dir (mode `600`), localhost only if ever needed.
  A shell/daemon **cannot** invoke Cursor MCP tools (L16 corollary; confirmed by
  `dev-worktree.sh` header, `_ops/bin/dev-worktree.sh:4-6`), so `move_agent_to_root` remains an
  agent-only step — the daemon prepares state and the agent performs the move.
- **Paths (L11/L12):** resolve `${XDG_STATE_HOME:-$HOME/.local/state}/awa` (state + audit + recovery),
  `${XDG_DATA_HOME:-$HOME/.local/share}/awa/worktrees` (durable roots),
  `${XDG_CONFIG_HOME:-$HOME/.config/awa}` (config). Document that these are XDG-style, not
  macOS-native; a future macOS-native mode may map to `~/Library/Application Support/awa`.
- **State store (L17):** SQLite WAL, `busy_timeout` set on every connection, one writer + N readers,
  plus a per-`--git-common-dir` advisory lock for cross-process serialization. Forward-only
  migrations with a pre-migration backup and `doctor --repair --dry-run` preview.

## Corrected availability & degraded-mode matrix (replaces v1 matrix)

Now aligned to what can actually block (only `beforeShellExecution`/`beforeMCPExecution`) and to
cloud limits.

| Component / failure | Real mechanism | `ON` behavior | Operator-visible state |
|---|---|---|---|
| Engine unavailable | local guard reads policy snapshot + `.awa/lease.json` | `beforeShellExecution` denies mutating git/install in eligible **primary** checkout; allow in attested worktree | "Protection degraded — primary mutations blocked." |
| MCP unavailable | CLI/local-guard fallback | deny destructive lifecycle that needs attestation; shell gate still works | "Agent API unavailable; using fallback." |
| `beforeShellExecution` slow/crashes | `failClosed` decides | `failClosed:true` → block the command; `false` → allow | "Safety check unavailable" (only if failClosed). |
| `afterFileEdit` (primary edited) | detection only | cannot prevent; create recovery diff + receipt, propose adopt-into-worktree | "You edited your main folder — I saved a recovery patch." |
| Watcher stale | timestamp check | allow attested work; **block cleanup/apply-back** | "Watcher stale — cleanup blocked." |
| GitHub/remote down | push/PR fail | continue local work; block PR/cleanup + **block relocation** (publish-before-move fails, L5) | "Remote unavailable — work preserved locally; not relocating." |
| **Cloud agent** | user hooks + MCP + stop absent (L10) | only committed project `beforeShellExecution`/`afterFileEdit`; PR-first | "Local AWA unavailable in cloud — using PR-safe flow." |
| State DB unhealthy | validation on open | read-only recovery mode; cleanup/apply-back denied | "Recovery mode active." |

## Corrected packaging & governance (replaces v1 "Installation" + "Governance")

Verified against `_ops/POLICY.md`, `AGENTS.md`/`agent-context.md`, and the live tree (L13,L14,L21,L22):

- **Where source lives.** AWA capability code must **not** be committed under `KleinPerkins/dev`
  except plans/runbooks/verifier wrappers (this doc + the `_ops/bin` shims + `_ops/checks`
  wrappers). The reusable engine/CLI/watcher = a **`kind: tool, scope: global`** capability, and the
  MCP server = a **`kind: mcp`** capability. Concretely:
  - CLI/engine/watcher/rule/skill → `capabilities/skills/global/` — but the **`tools/`,`rules/`,
    `sub-agents/` shelves do not exist yet** (only `skills/` is present). Creating them is a
    prerequisite (C8/L14).
  - MCP server → `capabilities/mcp/` (the `KleinPerkins/kp-mcp` monorepo; has `template/`).
  - Both repos are **their own git repos**, never tracked by `KleinPerkins/dev` (`.gitignore`
    allow-list, verified L13). Local state/config is never source-tracked (L12).
- **Registration.** WF1 enrollment in `ecosystem-orchestrator/config/registry.yml` applies only to
  **global-scope** artifacts; `.eco-registry.lock` is CI inventory/parity, not cpp enrollment.
- **cpp rollout is gated (L14).** cpp `enabled_kinds` for `tool`/`rule`/`sub-agent` are **not yet
  flipped** (blocked on the cpp-governed reconciler PR). So even after local trust, AWA-as-`tool`
  cannot be cpp-vendored until that lands; the MCP runtime is not vendored into cpp unless
  cpp-owned runtime support exists. `ecosystem-orchestrator` is the **only** sanctioned cpp writer
  (L21); no hand-vendoring; it never touches cpp `_ops/`/`.github/`.
- **Local registration path (Desktop).** The AWA MCP server registers as a **local stdio** entry in
  `~/.cursor/mcp.json` (verified mechanism, L16); `install-mcp.sh` then mirrors it (stdio→Codex,
  all→Claude). Not available to cloud agents.

## Open risks (Unverifiable-now) — with the exact method to close each

These are **not** treated as facts anywhere above. Each must be verified before the dependent
phase ships.

| ID | Open question | Why unverifiable now | Method to verify later |
|---|---|---|---|
| R-A | Exact trigger + failure mode of `move_agent_to_root`'s fetch/ff-merge (always? only migration path? hard-fail vs warn?). | Running it would **relocate this very agent session** (destructive to the run); descriptor text is authoritative but not exhaustive. | In a throwaway repo + a disposable Desktop agent: create a local-only branch worktree, call `move_agent_to_root`, observe. Then repeat after `git push -u`. Capture the error string + post-state. |
| R-B | Whether `afterFileEdit` fires for **all** agent write paths (Write/Edit/apply-model) and its latency under large diffs. | Requires instrumenting a live Desktop agent; not observable from docs alone. | Install a logging `afterFileEdit` project hook; drive edits via each tool; record which fire + p50/p95 latency. |
| R-C | Robust, stable **session/agent identity** across Desktop / Agents Window / Cloud (for lease ownership). | No documented hook field guarantees a stable cross-surface session id; cloud omits `sessionStart`. | Log every hook's stdin across the three surfaces; look for a durable id; else derive identity from worktree path + branch + pid and accept weaker guarantees. |
| R-D | Real `beforeShellExecution` p95 with a warm vs cold daemon on large repos (the <100 ms budget). | Depends on the unbuilt engine + machine load. | Micro-benchmark the guard against the engine socket over N=1000 calls on `chaos-labs`-sized repos; enforce a local-guard timeout fallback. |
| R-E | Whether committed **project** `.cursor/hooks.json` is acceptable in each governed repo (esp. Affirm repos with their own conventions) and in cloud. | Policy + per-repo ownership question, not a code fact. | Confirm with each repo's ownership/CODEOWNERS before committing project hooks; cpp is excluded by policy regardless. |
| R-F | launchd socket-activation vs plain on-demand reliability across sleep/resume/login. | Behavior is environment/timing dependent. | Prototype both under `local-jobs`; test sleep/resume, logout/login, and daemon-crash restart. |
| R-G | Cursor SDK/plugin surface for a richer control dashboard (beyond render-only canvas). | Cursor plugin/SDK capabilities evolve; not fully documented for control surfaces. | Re-check `cursor.com/docs` + the canvas SDK `.d.ts` at build time; treat richer control as optional enhancement, never a safety dependency. |

## Revised, dependency-correct rollout

Ordering enforces: safety kernel before enhancements; the `move_agent_to_root` fetch fix (C2)
before any agent-created relocation; verifiers stay green at every step; cloud/cpp gated last.

| Phase | Deliverable | Hard dependency / gate | Verifier that must stay green |
|---|---|---|---|
| 0 | **This v2 plan** + shim contract test freezing `dev-worktree.sh` CLI + `awa-worktree/v1` JSON. | — | `make verify`, `make worktree-verify` |
| 1 | Engine core + SQLite WAL state + policy resolver + per-common-dir lock (behind existing shims). | L17, L18, L25 | worktree-verify (shims unchanged) |
| 2 | Git/worktree lifecycle **with publish-before-move** (C2/L5) + attestation + `.awa/lease.json`. | Phase 1; **R-A closed** before enabling agent-created relocation by default | worktree-verify UATs |
| 3 | Recovery manager (bundles/patches/quarantine/restore) — **before** any destructive cleanup. | Phase 1 | new recovery suite |
| 4 | Watcher/enforcer (bounded loops; event-first) + health surfaced to decisions. | Phase 2-3 | new watcher suite |
| 5 | Minimal local guard + CLI fallback (works when engine/MCP down). | Phase 1 | degraded-mode tests |
| 6 | Cursor hooks/rule/skill adapters — **honest capabilities only** (shell gate + afterFileEdit detect + sessionStart context); reconcile `failClosed` (L15). | Phases 1,5; L2-L4 | worktree-verify (guard behavior) |
| 7 | AWA MCP server (local stdio in `mcp.json`) + `beforeMCPExecution` gate (Desktop-only). | Phase 6; L16 | MCP contract tests |
| 8 | Engine-backed dashboard (render-only + agent-command refresh, C3). | Phase 4 | worktree-verify seed/marker checks |
| 9 | PR + SHA-bound apply-back (preview-first; recovery before mutation). | Phases 2-4 | apply-back suite |
| 10 | Packaging: create `capabilities/skills/global/tools/` shelf + `meta.yml`/`install.sh`; no-clobber install/repair/uninstall; clean-room. | L13, L14 | eco-verify / clean-room |
| 11 | Dogfood on one governed `~/dev` repo, then expand. | Phases 1-10 | dev-doctor advisory |
| 12 | **Cloud**: committed project `.cursor/hooks.json` (shell+afterFileEdit) + PR-first. | R-E; L10 | project-hook test in cloud |
| 13 | Orchestrator enrollment (WF1) → cpp reconciler support → flip `enabled_kinds` → cpp bootstrap. | L14, L21; cpp reconciler PR merged | eco-regression / cpp integrity |

## Non-negotiable invariants (tightened)

- Engine decides; adapters execute; watcher observes; dashboard explains.
- No destructive transition without recovery proof and exact state/SHA checks.
- **Relocation never completes on an unpublished branch** — publish to origin (or verify base on
  origin) before `move_agent_to_root`; on failure, keep the worktree and report it, never fake a move.
- Primary-checkout **shell** mutation is denied in `ON` when AWA can determine eligibility; primary
  **file edits** are detected and recovered (pre-write prevention is not claimed).
- Degraded/cloud protection is **explicit**, never implied (esp. "user hooks don't run in cloud").
- Local config and user work are never silently overwritten or deleted; state is never source-tracked.
- Every claim in this plan carries a ledger status; nothing is asserted as fact without evidence.

## Reconciliation: v1 shipped shims → engine (no verifier regression)

The v1 assets stay as the compatibility boundary; the engine backs them without changing their
observable contract (L25):

| v1 asset | Role after engine | Contract to freeze (verifier depends on it) |
|---|---|---|
| `_ops/bin/dev-worktree.sh` | thin CLI over engine (`status/ensure/clean/dashboard-data`) | verbs + `ensure --json` action shapes (`created`/`noop`/`setup_failed`) + quiet `worktree add -q` |
| `_ops/bin/awa-dashboard-data.py` | thin `awa status --json` client | `awa-worktree/v1` schema incl. `summary.orphan_branches`, read-only, bounded, resilient |
| `_ops/cursor-hooks/worktree-guard.sh` | thin engine/local-guard adapter | `permission: allow/ask` JSON, `DEV_WORKTREE_GUARD_ALLOW_PRIMARY` override |
| `_ops/cursor-hooks/worktree-session.sh` | thin context adapter | `additional_context` output; fail-open |
| `_ops/dashboards/awa-dashboard.canvas.tsx` | engine-backed status seed | data-free seed + `AWA_DATA` markers + "Refresh via agent" copy |
| `_ops/policy/worktree-policy.yml` | seed for engine policy resolver | required keys asserted by `policy-check` |
| `_ops/checks/worktree-verify.sh` | stays the regression gate | all current PASS lines + 8 disposable UATs |

Rule: **add a contract test that pins these shapes before re-pointing any shim at the engine.**
If the engine ever needs to change a contract, version it (`awa-worktree/v1` → `/v2`) and update the
verifier in the same change.

## How this document was verified (method)

Read-only file reads, official-doc fetch (`cursor.com/docs/hooks`, saved locally), the installed
MCP descriptors, OS probes (`uname`/`sw_vers`/`launchctl`/`systemctl`), a disposable temp git repo
(worktree/rev-list/detached/prune, cleaned up; `~/dev` not polluted), an in-memory-then-file SQLite
WAL probe, and a baseline run of `make verify` + `make worktree-verify` (both green). No engine was
built; no `move_agent_to_root` was executed (see R-A). Evidence is attached per ledger row.

