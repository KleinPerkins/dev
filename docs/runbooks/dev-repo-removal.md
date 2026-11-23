# Removing retired repositories from `~/dev`

How to retire whole local checkouts under `~/dev` without losing work by accident and
without leaving a half-wired machine behind. It is the synthesis of the first real
operation (the closed journal `ret-20261023-2210`: 14 checkouts, a remote-automation
retirement, a domain teardown) turned into a repeatable method. The operator-facing
entry point is `/dev-remove-repo` (`_ops/skills/dev-remove-repo/SKILL.md`), backed by
`_ops/bin/dev-remove-repo.sh`. The sanitised, source-tracked record of that operation
is `_ops/tests/fixtures/dev-remove-repo/m1-replay.sanitized.jsonl`; every consequential
step in it is an acceptance case in `_ops/tests/dev-remove-repo.sh`.

This runbook contains no tokens, credentials, raw configuration, transcript text or
private payloads, and neither may anything you add to it, to a journal, a fixture, a
test, a PR or a log.

## What is automated and what is not

| Phase | Owner | How |
|---|---|---|
| Inspect, preview, confirm, execute, resume, verify | the tool | `view`, `remove`, `resume`, `verify`, `doctor` |
| Whole-checkout deletion, client skill links, scheduled jobs, Cursor caches, linked worktrees, index refresh | the tool, by composing each owner's own verb | one operation, bounded cohorts |
| Changes inside a separately governed repo (for example the card platform repo) | that repo's governed change path | a PR there, merged before the checkout is removed |
| PR-automation fleet and controller, GitHub App repository scope, GitHub rulesets and archival, GitHub Pages, DNS, registrar deletion | the operator | detected and explained; refused or attested, never automated |
| Subsystem-private state (AWA, ShadowSync, the agent-route index, generated memory) | the owning subsystem | its own verb; leftovers become ledger exceptions |

The tool removes only whole checkouts at `affirm/src/<name>`, `affirm/vendor/<name>`,
`personal/<name>` and `capabilities/<name>`. It never writes inside a checkout, never
follows a symlink, never uses the network, and never infers authority from a repository
name. `affirm/src/card-platform-product`, `capabilities/skills`, `capabilities/mcp` and
`personal/chaos-scheduler` are refused outright, whatever the letter case or Unicode form
of the folder name (macOS volumes ignore both). Under `affirm/` it acts only while the
narrow policy exception in `_ops/POLICY.md` (§7) is in force and it can prove that
nothing is writing to the checkout; otherwise those targets stay operator gates.

### Inspect a personal scaffold before retirement

The personal view accepts the exact path of a product created with
`dev-new-repo.sh --personal-codex` whose name is still unenrolled in Dev policy.

```sh
_ops/bin/dev-remove-repo.sh view --personal-codex personal/src/KleinPerkins/sample.product
```

The view compares the saved creation binding with the checkout path and the
identities of both the checkout directory and its Git directory. It checks the
origin stored in the local Git config and counts registration records in that
Git directory. Registered destinations can be offline. The JSON field
`recorded_repository_id` comes from the local creation record. A local-only
scaffold can have an empty ID. For a disposable exercise, pass the same
`--fixture-root` and, if selected at creation, the same `--fixture-repository-id`.
This allows inspection even when the creator stopped before recording the provider ID.

To check whether a retained scaffold uses files in the selected checkout,
name the retained scaffold explicitly. The same command can compare the
configuration reported by the installed Local Jobs engine.

```sh
"$HOME/.codex/skills/local-jobs/scripts/local-jobs.sh" view-jobs --config-only --json |
  _ops/bin/dev-remove-repo.sh view --personal-codex --jobs-stdin \
    --retained-scaffold sample.reader personal/src/KleinPerkins/sample.product
```

Both options are independent. Repeat `--retained-scaffold NAME` for up to eight
distinct peers. Each peer must match its original creation record. In a
disposable fixture, `--retained-scaffold NAME=FIXTURE_ID` supplies that peer's
original ID, including leading zeros, even after an interrupted creation.
The target's `--fixture-repository-id` applies only to the target. The view reads
symlink text at and beneath the peer's `.agents/skills`, including links to an
individual skill's resources. An alias at `.agents` or `.agents/skills` is itself
reported. The inspection leaves all link destinations unopened. A nested checkout,
an unreadable directory or a scan limit stops the inspection. The job comparison
uses declared fetch paths and the root reported by Local Jobs. The input digest
identifies the specific report supplied, which can become stale.

`selected-path` flags a spelling equal to or beneath the selected checkout after
component normalization and case folding. Investigate it before retirement.
`other-spelling` can still refer to the checkout through another alias.
`unresolved` identifies declarations the view cannot place. The report covers
only the named peers' skill links and the supplied base job configuration.
It does not establish use by other clients, historical snapshots, active jobs or
other repositories. The view always reports `removal_ready: false`.

On macOS, add `--open-files` to the personal view to find visible processes
holding objects in the selected checkout. It checks regular files and directories,
including the checkout's Git administration files. Each batch must include a
known descriptor for every selected object. The result reports process IDs and
distinguishes a working directory, a writable descriptor and other open references.
A hard link can identify a process that opened the same file at another location.
The observer leaves symlink targets and linked working directories unopened.
Unsupported filesystems, incomplete observations, nested repositories, changes
during the scan and size or time limits stop the operation. An empty process list
describes a point-in-time observation with the invoking account's visibility.
Repeat the observation after resolving a writer and before acting on a checkout.

The same scan reports `open_files.external_hard_links` for regular files and
symlinks with additional names outside the checkout. Each group lists its
checkout-relative paths and the number of outside names, even when the file is
closed. The scan compares inode link counts with the names found inside the
checkout. Outside paths stay unopened. Restoring an archive of this checkout
alone can give the restored file a different inode from a retained outside name.

Preserve the original directories if the creation operation must resume after
recovery. A byte copy receives new directory identities. This inspection leaves
the checkout and retirement journals untouched. Personal removal still requires
separate evidence for unshared work, consumers, active writers and recovery.

## 1. Preflight: freeze the manifest

1. Name the exact checkouts as canonical paths under `~/dev`. A bare repository name is
   never enough; resolve it to the one matching folder and confirm with the operator.
2. `view <path>...` is read-only and creates nothing. `remove <path>...` writes a
   private preview under `${XDG_STATE_HOME:-$HOME/.local/state}/dev-repo-removal/<operation-id>/`
   (mode 0700 directory, 0600 files) and changes nothing else.
3. The preview freezes: the manifest (path, directory identity, remote slugs), a digest
   of every thing that will be acted on (tree fingerprint, Git facts, links, job rows,
   Cursor project folders, worktrees), the plan, and the exact confirmation command.
   It records digests and locations, never file contents. It is valid for 60 minutes.
4. A health baseline is taken at confirmation from the doctors that exist on the machine
   (control-plane doctor, local-jobs, agent-route, ShadowSync, worktree doctor). Verify
   later compares against it, so drift that existed before the work is not mistaken for
   a regression, and new problems are not excused as "already broken".
5. Every action revalidates its own preimage immediately before it runs. If anything
   changed since the preview (a new file, an edit, a commit, a stash, a swapped
   directory, a new writer) the tool refuses and a new preview is required. It never
   proceeds on a best guess.

Abort and re-preview on: newly discovered targets, an active writer, an unknown
worktree, a changed remote identity, a changed manifest, or an expired preview.

## 2. Content risk and the destruction waiver

Unshared local state is the real cost of deleting a checkout. The tool classifies it
and refuses to proceed until each class is **accepted by name**.

| Kind | Examples | Rule |
|---|---|---|
| Waivable risk (named in `--waive`) | `dirty-tracked`, `untracked-files`, `ignored-data` (env files, local data), `unpushed-commits`, `stashes`, `nested-repos`, `operation-in-progress`, `linked-worktree-work`, `consumer-mentions`, `scan-incomplete` (the search for mentions could not read or finish everything), `writer-proof-unavailable` (outside `affirm/` only) | the waiver list must equal the required list exactly: a missing or an extra name is refused |
| Blocker (never waivable) | protected target, malformed or escaping path, symlinked or special-file content, mount point inside, cross-device, wrong owner, the running shell inside the checkout, an active writer, a live editing-session lock, a Git index lock, an AWA lease, unreadable Git, a still-enrolled PR-automation repo, a client config or launchd/shell file that still references it, a symbolic link in another repository that points into it, a shared scheduled job that still lists it, a linked worktree in an unknown place, that is locked, that is not really a linked worktree, or that was not in the preview (section 6), an unfinished-removal marker beside a path that looks already gone (a marker that a recorded operation made for a different checkout does not count against this path; one that no recorded operation made does), more than 25 targets | fix the cause, then preview again |
| Operator gate (named in `--attest`) | `github-pages` (a Pages site or CNAME is present) | the operator states the external step is done; the tool records that and nothing else |

Observed in the closed operation: untracked deck files, one unpushed commit, a
git-ignored environment file, authentication/environment files, and a local-only commit
in a linked worktree. All of them were destroyed under an explicit, recorded waiver.
Nothing is ever pushed to "save" work as a side effect of removal; if the operator wants
it kept, they preserve it before waiving.

## 3. Detach retained consumers before deleting

A retained repository is in scope only if it resolves a target checkout path. The tool
reports mentions (`consumer-mentions`, with counts per retained repository) but never
edits them. The mention scan covers retained work, personal and capability repositories,
the umbrella repository, generated-memory files and the home configuration surfaces.
Reference clones under `affirm/vendor` are pristine and never edited, so they are not
scanned. Only path references can dangle, so only they count as mentions and can need a
waiver. The preview also counts, as notes that change nothing, the other files that name
the repository by its remote or by a distinctive name (six or more characters containing
a dash or underscore), because `verify` searches for all three and each file it finds
needs cleanup or an exception.

- Update only positively identified **current** references: live configuration, current
  source-of-truth text, mutable fleet or projection files, active hooks and checks.
- Preserve frozen historical records, audit chains, checkpoint and rollout evidence,
  attribution and licence bytes, and generated rule mirrors.
- Each retained repository changes through its own governed path (separate PRs, never
  combined across work and personal control planes). For the card platform repo that
  means a governed PR merged by its own automation **before** the checkout is removed.
- A reference that is a client config or a launchd/shell file is a blocker, not a risk:
  fix it through that client's own lifecycle (for example the client's own CLI for MCP
  registrations), confirm the effect in the config, and preview again. A completion that
  was reported but not observed is not a completion (see section 13).

After the journal sets a checkout aside, it checks for writers again before removing
its contents. If the check becomes unavailable, the set-aside directory stays in
place. Restore the process check and resume the same operation. Outside `affirm/`,
an explicit `writer-proof-unavailable` waiver in the original confirmation covers
that outage. An observed writer always blocks removal.

## 4. Retire remote automation (operator-owned)

Do this before any checkout whose automation would otherwise start failing, and before
local state is destroyed.

- **PR-automation fleet.** A repository still enrolled in the fleet blocks removal.
  Shrink the fleet in the proven order, as one short paused interruption:
  stage a complete replacement config from the live preimage (never edit in place) →
  pause and drain the controller → install the staged config with the running binary's
  own verb → merge the authority change in the dev repo (an unarmed draft, owner/admin
  merge only inside the pause) → reduce the GitHub App's repository scope (the
  controller needs every configured repository inside the App scope, not the reverse) →
  prove live parity while the old rules still exist → resume and run one bounded poll.
  Never resume while the repository sets differ; if parity fails, restore the exact
  prior config, scope and authority, prove the old state with the live doctor, then retry.
  Never leave the controller paused across sessions without an open, journaled intent.
- **Rulesets.** Delete an old protection ruleset only after its replacement is verified
  active live. If the replacement could not be created, keep the old ruleset and record
  it as an exception.
- **Never** try an API route for a step the operator deliberately did in a UI, or the
  reverse. A permission boundary is a stop, not a puzzle (section 13).

## 5. Local wiring (what the tool automates)

All of this runs through the owner's own verb; none of it hand-edits private state.

| Wiring | What the tool does | If the owner is unavailable |
|---|---|---|
| Client skill, rule and command links that resolve into the checkout | removes exactly those symlinks, one step each; a symbolic link anywhere else that points into the checkout is a blocker: at any depth in a retained repo or the umbrella's own folders (not in reference-only `affirm/vendor` clones or the dependency and cache folders), or as one of the home configuration surfaces of section 3 (a client config, shell startup file or launch agent) | refuses; links are never guessed |
| Scheduled jobs that exist only for the checkout | asks Local Jobs to delete the previewed fetch revision, then verifies its absence; a shared job that merely lists the checkout (a fetch job covering several repos) is a blocker: update it with the local-jobs update verbs first | scans the job files and notes it; leftover registry mentions block |
| Cursor project folders for the checkout | removes only the allow-listed cache folders (`agent-tools`, `assets`, `canvases`, `mcps`, `terminals`), one step per folder, reached from the home folder without following any link (a symlinked `.cursor`, `projects` or project folder is skipped); chat history (`agent-transcripts`) is always kept and unrecognised entries are left alone; Cursor spells paths into folder names by turning every run of other characters into one dash, so when a checkout that stays (`foo_bar`, or `personal-foo-bar` at the dev root) maps to the same project folder as the one being removed (`foo-bar`) no cache in it is touched, at preview or at the step itself | n/a (file operation) |
| Linked worktrees | see section 6 | see section 6 |
| Generated route index | runs the agent-route full rediscovery once, after the last cohort | reported; refresh it later |
| Processes, shell shims, package installs, virtual environments, containers | detected and explained only when positively attributed to the checkout; removed through their own lifecycle by the operator | reported |

Local Jobs reports may mention a path in arguments, descriptions or shared scheduler
metadata. Retirement holds those jobs for their owner to update. Automatic detachment
requires a unique fetch ID, the exact checkout path, an inherited schedule and
the owner’s removal revision. Local Jobs compares that revision under its store
lock during deletion. A reassigned ID, an older inventory without revisions or
a dedicated launch agent requires owner reconciliation. For an older interrupted
operation, resume can recognize an already-removed record. A remaining record
without a bound revision needs a new preview.

Shared stores (transcripts, shared caches, runtimes) are never deleted merely because
they mention a name.

## 6. Linked worktrees and unshared work

1. AWA-managed worktrees are removed with `_ops/bin/dev-worktree.sh clean --path`.
   That verb refuses by design when the worktree holds a local-only commit. The tool
   then falls back to a plain `git worktree remove`, which leaves the worktree's refs in
   the checkout, where they are deleted with it under the checkout's `unpushed-commits`
   waiver. Cursor-managed and plain linked worktrees use `git worktree remove` directly.
2. Uncommitted work in a linked worktree needs its own named waiver,
   `linked-worktree-work`. Only then does the tool escalate to a forced removal of
   exactly that linked worktree. The path is verified gone and the registration removed.
   Nothing is pushed.
3. A worktree whose path is a symlink is a blocker, and one that lives inside the
   checkout is handled with it; the tool never follows the link. Git's worktree list is
   metadata that a repository controls, so the tool does not trust it on its own: an
   outside worktree is removed only when it sits under `~/dev`, the Cursor worktree
   folder or the AWA worktree folder, does not contain home or `~/dev`, and has a plain
   `.git` file (a `.git` directory would make it a repository of its own). Anything else
   is a blocker: check it yourself, remove or move it with `git worktree remove`, then
   preview again. The same check runs again immediately before each removal, together with
   a fresh proof that no program is using the worktree and that no live session lock sits
   in its own Git directory.
   A linked worktree that is registered after the preview is not part of the approved
   plan: confirmation, the rescan between cohorts and the check right before each
   deletion all refuse it, and a new preview is required. One more look is taken after
   the checkout has been set aside and before anything inside it is removed, by reading
   the checkout's own Git records of linked worktrees: one that was added in the last
   moment stops the removal with nothing deleted, and `resume` waits until you have
   removed that worktree.
   A locked linked worktree (`git worktree lock`) outside the checkout is a blocker too:
   a lock is somebody's explicit protection, and the tool never overrides one. If the lock
   is stale, unlock it yourself with `git worktree unlock`, then preview again.
4. The tool does not toggle AWA protection modes and never edits AWA state. The first
   operation temporarily switched protection off for exact paths, with operator
   approval, to force one removal, then had to restore it. The tool needs no such
   switch: it removes the worktree itself under its own preview and exact-approval
   protocol, and the live shell guard still judges whatever an agent types directly.
   If the guard blocks the tool call itself, stop at an operator gate and never route
   around the hook. Diagnose a command with the AWA guard tool; do not guess.
5. Records that only an AWA verb can retire (append-only detections, clean receipts) are
   audit history. List them in the ledger; never edit them.

## 7. Pages, DNS and registrar gates (operator-owned)

The proven order, so a domain never points at an unclaimed site:

1. Delete the DNS records that point at the Pages site; cancel zone add-ons first and
   turn DNSSEC off if it was on.
2. Remove the Pages custom-domain binding, then disable Pages. Verify the site is offline.
3. Archive the GitHub repositories only after remote automation is retired.
4. Registrar deletion is a final, operator-confirmed, non-refundable step that uses a
   short-lived emailed authorisation. Never record the token. A domain older than five
   days enters redemption before release; the zone may have to stay until the first
   permitted checkpoint.
5. Only then remove the local site checkouts.

The tool's part is the attestation: when a Pages site or CNAME is present it requires
`--attest github-pages` and records only that the operator did it. A registrar state that
is still pending is an `external-pending` ledger exception, with an honest reason.

## 8. Ordered cohorts

- Order is fixed: vendor references (`affirm/vendor`), work checkouts (`affirm/src`),
  personal (`personal`), then `capabilities`. A cohort is at most 5 checkouts
  (`--cohort-size 1..5`); an operation covers at most 25.
- Dependency order beats cohort order: consumers detached, remote automation retired,
  and gates attested before a checkout whose state they protect is deleted.
- Before every cohort the tool re-proves, for each target, no active writer and no
  concurrent agent (under `affirm/` this proof is mandatory), then rescans after the
  cohort instead of after every deletion. If a writer appears between cohorts the
  operation pauses and the remaining cohorts stay untouched; `resume` continues once the
  cause is gone and each remaining preimage still matches. The complete search of retained
  files runs at confirmation, after each cohort and on resume; inside a cohort, the check
  right before each deletion looks again at the AI-client configs, launch agents and shell
  startup files, at symbolic links into the checkout and at scheduler entries, and refuses a
  checkout that any of them has begun to name.
- Deletion is a rename-then-delete: the checkout is atomically renamed to a hidden
  marker beside it (`.drr-<id>.removing`), so the real path disappears at once, then the
  marker's contents are removed through a no-follow descriptor chain with identity and
  owner checks. Right after the rename, and before any content is removed, the writer proof
  is taken once more against the set-aside copy and the checkout's own Git records are read
  for any linked worktree added since the last look: if a program started using the checkout,
  or a worktree appeared, in between, the tool stops and leaves the marker for `resume` to
  finish once the cause is gone. An interrupted run continues deleting that exact marker; a swapped marker, a
  different checkout at the path before the rename, or something new at the original path while the old checkout waits
  under its marker is refused, never trusted. A checkout that waits under its marker is not a retained repository:
  its own files, links and notes are not searched, and the marker is never counted as a place that mentions or links
  to anything.
- After each deletion the tool checks path and Git-worktree absence itself; it does not
  take a subsystem's word for it.

## 9. Execution record, resume and interruption

- The operation has one writer: a lock (`.writer.lock`) serialises operations; a second
  concurrent run refuses.
- `events.jsonl` is append-only and hash-chained (each event carries the digest of the
  previous line). Intent is journaled before every action and completion only after the
  effect is observed. A torn final line is kept inert and the next event is marked
  `torn_recovered`. `operation.json` is immutable and bound into the `open` event.
- Statuses: `previewed`, `expired-preview`, `confirmed`, `interrupted`, `paused`,
  `failed`, `executed`, `closed`. Exit codes: 0 ok, 1 refused, 2 usage, 69 unavailable,
  75 interrupted.
- `resume --operation <id>` reads the last open intent first and reconciles by observing
  real effects, so a repeated run is idempotent. A step is `completed` only when its
  effect is seen; a step whose owner lied or failed is `failed` and stops the run. A step
  whose result cannot be checked right now (its owning tool did not answer) is also
  `failed`, with a reason that says so rather than claiming the result is missing. A step
  that is still open or was reported failed is observed again before anything else: if its
  effect is in fact there it is completed, not repeated.
- For new checkout removals the journal records the emptied directory and its parent.
  It records final unlink separately after observing removal through the open directory
  descriptor. Resume checks that observation and that both names are absent from the
  same parent. If the checkout was moved, restore its original location before resuming.
  If new files appeared in the emptied marker, preserve them elsewhere first. The final
  step removes only an empty directory. An interruption between unlink and its journal
  record leaves the outcome unverified. Preserve that journal and any backup for
  reconciliation. Older operations retain their original recovery behavior.
- A resume does not trust the old approval blindly. It first re-assesses every
  checkout that is still pending (blockers, new unwaived risks, wiring and the
  preview's recorded state) and stops with a `rescan` entry if anything changed. A
  checkout already renamed to its removal marker is finished only after the same
  writer proof that applied before the rename holds again, no new linked worktree has
  appeared, nothing new occupies the original path, and nothing has begun to name the old
  path (a launch agent, startup file or AI-client config, a symbolic link into it, a
  scheduler entry); if something does, the tool stops before deleting anything more and
  the marker stays until the new item or reference is moved away. A fresh preview of a path
  that looks gone but has an unfinished-removal marker beside it is refused, so a
  half-deleted checkout is never reported as "nothing to do". The rescan also stops if a
  checkout that was already removed exists again, and never touches what came back.
- The journal is validated strictly before `remove --confirm`, `resume` and `verify` act
  on it. An empty or old-format journal, a broken hash chain, unreadable records (a
  torn final line excepted), a gap in the sequence, a record from another operation, a
  missing opening record, a close record that does not account for the journal, or any
  change after the close marks the operation damaged and is refused. `view` and
  `doctor` still open a damaged operation to show why.
- A state folder this tool did not make (an `events.jsonl` in the older hand-run format
  and no `operation.json`, such as the closed Milestone 1 journal) is history, not an
  operation. `doctor` and `view` list it as a record from before the tool: `ok` when it is
  closed and its close record still accounts for the journal, a warning (never a failure)
  when it was not closed or no longer replays cleanly. `view --operation`, `resume`,
  `verify` and `remove` refuse to act on it and say why; read it with
  `doctor --journal <path>`. A native operation that has lost its `operation.json` is not
  mistaken for one: it stays a failure.
- Confirmation is exact: it binds the operation id, the target manifest, the action
  digest, every current preimage, the waived risk names and the attested gates. A bare
  yes, a boolean, a stale, truncated, uppercased or copied token from another operation
  is invalid. The journal stores only the token's hash.

## 10. Verify: the scan proves absence, doctors prove health

These answer different questions and neither substitutes for the other.

- `verify --operation <id>` checks: every step's observed result; path and marker absence
  (including leftover removal markers); registered and physical worktrees absent; every
  remaining mention of a removed checkout (an `rg` fixed-string search with a pure-Python
  fallback, both reading every file in the retained checkouts whether or not Git ignores
  it, and reading a client config or shell startup file through a symbolic link) maps to an
  exception, where a file or folder the search could not read (a surface folder that is
  itself a symbolic link is never walked and is listed as not searched), or a search that
  reached its 10-minute limit, counts as an unexplained finding and never as clean; and
  subsystem health compared with the baseline taken at confirmation. A healthy subsystem
  that now reports a problem, a violation that was not there before, or a pre-existing
  problem whose report changed is a failure; a pre-existing problem that is unchanged is
  not. A subsystem with no baseline (not installed, or timed out at confirmation) that
  now reports a problem is a failure too, because nothing shows the problem predates the
  work. Accept an unrelated change in a pre-existing problem with a `subsystem-stale`
  exception.
- It never edits another subsystem. The agent-route index is refreshed through its own
  verb. Generated memory and learnings are cleaned by their owning updater, then
  rechecked with the scan. Do the operation's own transcripts last.
- Close only when every check passes, or each permitted pending item has an honest
  ledger entry. `verify --discard-preview` discards a preview that will not be used.
  Verifying an operation that is already closed first validates its journal (one that
  changed after it closed is refused with an integrity error), then reports the outcome
  recorded when it closed; it does not run the checks again.
- Doctors do not prove absence: a healthy index can still hold a stale path.

## 11. Exception ledger and closeout

An exception is `CLASS:SCOPE:REASON`.

- The scope is a canonical path (no `.`, `..`, `//` or trailing `/`): relative to `~/dev`,
  written `~/path` for a file in the home folder (for example `~/.cursor/mcp.json`), or an
  absolute path inside either. A scope that is, or contains, the dev root, the home folder,
  `affirm`, `affirm/src`, `affirm/vendor`, `personal`, `capabilities` or a client's
  configuration folder (`~/.cursor`, `~/.claude`, `~/.codex`, ...) is too broad and refused.
- `subsystem-stale` names exactly one subsystem instead: `dev-doctor`, `local-jobs`,
  `agent-route`, `shadowsync` or `awa`.
- The reason is 12 to 300 characters of honest, single-line text that does not look like a
  credential.
- An exception must match something `verify` actually reports: a remaining mention, a file
  that could not be searched, or a subsystem that is worse than its baseline. One that
  matches nothing is refused and nothing is recorded. `external-pending` is the only
  declarative class: it records something outside this machine that `verify` cannot see.

| Class | Use for |
|---|---|
| `immutable-evidence` | Git/PR history, audit chains, checkpoint evidence, this operation's own journal |
| `historical-record` | frozen governed records, past audits and runbooks, generated memory that mentions a name |
| `retained-reference` | a retained repo that intentionally still names the target, such as a broken-by-design link |
| `shared-store` | shared transcripts or mixed-content backups that cannot be cleaned without harming retained state |
| `external-pending` | a registrar redemption window, a scope reduction only the owner can perform |
| `subsystem-stale` | records only the owning subsystem can retire (for example stale authority records in a private-state tool, once its owning lifecycle was tried or reported) |

Never claim literal zero residue beyond the ledger or unrelated pre-existing drift.

## 12. Rollback and refusal

There is no undo for a deleted checkout. Recovery is whatever already exists elsewhere:
a pushed remote to re-clone, or a filesystem snapshot. That is why every unshared item
is a named waiver, and why verification proves path and ref absence, not forensic
erasure.

- Before the first deletion nothing destructive has happened: a preview can be discarded.
- After it, the only direction is forward: `resume`, or stop and leave the remaining
  cohorts intact. Never hand-restore a half-deleted tree.
- Refusals are normal outcomes (`{"ok": false, "refused": "..."}`, exit 1): read the
  sentence, fix the cause, preview again. Do not bypass a guard, use `--no-verify`, or
  route around a blocked hook; stop and report it.
- Tests and rehearsals use only isolated temporary roots and never the real `~/dev`,
  user configuration, GitHub, the PR-automation controller, Cloudflare, launchd or any
  live subsystem. `make dev-remove-repo-verify` runs the whole suite (isolated fixtures
  plus the sanitized replay of the closed operation); `make verify` runs its fast
  `--smoke` tier, which includes the skill-installation proof.

## 13. Failure modes observed in the closed operation

| What happened | Why | What the tool does now |
|---|---|---|
| A step was recorded complete although the owner had refused it (an out-of-date client tool) | success was inferred from the exit status | a completion is journaled only after the effect is observed at the owning surface; a lying adapter is a failed step, never a completion |
| The live controller check refused while the external App scope did not match the fleet | the three pieces (config, authority, scope) moved at different times | they are one short operator-owned interruption; never resume while the sets differ; rollback is documented in section 4 |
| An API equivalent of a step the owner declined in the UI was forbidden | a permission boundary, not a bug | treated as a stop and an operator gate; the fallback is recorded as a ledger exception |
| The owner's clean verb refused a worktree holding a local-only commit | by design: it protects unshared work | the tool falls back to a plain `git worktree remove`; the commit stays in the checkout's refs and is covered by the checkout's `unpushed-commits` waiver. Only uncommitted work in the worktree needs the named `linked-worktree-work` waiver, and then a forced removal of exactly that worktree |
| Doctors were already non-OK before the work (a control-plane doctor, a private-state sync tool) | pre-existing drift | health is compared with the baseline taken before the first change |
| Stale authority records for removed checkouts remained in a private-state tool | only its own lifecycle may retire them | never hand-edit; report and ledger it as `subsystem-stale` |
| A retained governed repository still referenced a target | its own change path had not run | consumers are reported as a risk; detach through that repo's governed PR first |
| A generated memory file mentioned removed repos | machine-mined and regenerated | never hand-edit; refresh through its owner and ledger what remains as `historical-record` |
| Secret-bearing preimages and staged configs existed on a remote host during a transaction | needed only for rollback | delete them as soon as the final verification passes; record only digests and locations |
| Unpushed, untracked and ignored data existed in several checkouts | normal | surfaced before confirmation and accepted by name, never inferred from "clean" |

## 14. Secret handling

- Preimages are recorded as location plus digest, never as contents.
- The journal stores the confirmation token's SHA-256 only. State directories are mode
  0700 and files 0600; no preview, journal, log or exception carries file contents,
  tokens, credentials, raw configuration or transcript text.
- Confirmation commands and exception reasons are plain text the operator can read:
  keep secrets out of them. Reasons that look like credentials are rejected.
- Temporary staged files that held restricted-mode content are deleted by their creator
  once the transaction is verified; the tool itself creates none.
- As a backstop, the tool scrubs credential-shaped text (well-known token formats,
  `key=value` secrets, URLs with embedded passwords, private-key headers, long opaque
  strings) from everything it journals and prints, and keeps no URL query or fragment.
  The backstop is not permission to paste secrets.

## 15. Known limits (accepted, not hidden)

- **The confirmation proves the exact preview was presented back, not that a person typed
  it.** Anything able to run the confirm command can run it. What protects the operator is
  the binding (any change since the preview refuses), the live shell guard, and the
  skill's rule that the confirm command runs only after the operator's explicit yes to
  that preview in the current conversation. A human-only approval channel is a candidate
  for a later version.
- **The tree fingerprint is metadata, not a content hash.** It records name, type, size,
  modification and change times, inode and mode for everything in the checkout outside
  `.git`. `.git` is covered by the Git facts the preview records (HEAD, branch, status,
  refs, remotes, unpushed commits, stashes, operation state) plus the same kind of stat
  digest of the repository's own settings and scripts (`config`, `HEAD`, `shallow`,
  `info/`, `hooks/` apart from samples, submodule names). Git's index, packs, loose
  objects and logs are not fingerprinted: Git rewrites them on its own. Ordinary programs
  cannot set a change time; a change that preserves all of it (for example by someone with
  raw disk access) would not be seen.
- **Dependency and cache folders are not searched for mentions.** Both search methods
  skip, at any depth, folders named `node_modules`, `.venv`, `venv`, `__pycache__` and
  `.tox`, and Git's own `.git` folder. Everything else is searched, including files Git
  ignores (environment files, local data, build output), and a linked worktree's
  `.git` pointer file.
- **Symbolic links inside searched folders are not read through.** In a retained checkout,
  and inside the launch-agent, local-jobs and ShadowSync folders, a linked file is never
  followed, so its contents are searched only where the file itself lives inside a
  retained checkout. A link that points into a removed checkout is still found and
  blocks (section 5). The walk of links stops at a 2-minute limit and then reports the
  search as incomplete.
- **Files over 8 MB are not searched for mentions.** The scan coverage always states the
  limit (`size_limit_bytes`). It counts the skipped files (`oversized_skipped`) only when
  the built-in search ran; ripgrep skips them without counting, and the field is then empty
  rather than zero.
- **The writer proof is a snapshot.** It lists what running programs have open, and where
  they are working, at one instant. A program that deliberately opens the set-aside folder
  by its hidden random name in the instant between that look and the first deletion would
  not be seen; no ordinary program knows that name.
- **The close record is not covered by its own digest.** It binds every earlier event;
  editing only the last line of a closed journal would not be detected.
