# dev/ Operating Manual

Single source of truth for the shared `~/dev` operating model. This successor source
separates current policy from retained predecessor designs and observed host state.
Source preparation is not evidence of installation, hosted activation or migration.

## 1. The `~/dev` tree

`~/dev` is the master operating-model repository. `capabilities/` is a sub-umbrella
for actively developed reusable tooling and ecosystem maintenance. `personal/` is
the permanent personal container; the employer-specific work container is fungible
and currently named `affirm`.

```text
~/dev/
├── OPERATING-MANUAL.md
├── _ops/                         shared policy and supporting tools
├── capabilities/<repo>/         global/local tooling and ecosystem services
├── personal/
│   ├── src/<git-owner>/<repo>/
│   └── vendor/<git-owner>/<repo>/
└── <work-container>/
    ├── src/<git-owner>/<repo>/
    └── vendor/<git-owner>/<repo>/
```

This is the agreed destination convention, not a claim that existing checkouts
have moved. Establish functional mac-mini operation first. Keep functioning work-Mac
paths until the later reorganization. The work Mac receives the full ecosystem;
mac-mini receives the personal ecosystem and excludes work. Data placement follows
the accepted personal/work classification, not an inference from the Git remote.

Nested repositories are independent. This master tracks operating-model source,
not their contents, private project data or generated machine state. Managed
applications/plugins remain in their managed locations. Retired-project content
and unfinished work are preserved through the accepted private recovery process;
removal is never inferred from absence in this target tree.

## 2. Placement decision tree

1. Shared governance belongs in the master `dev` repository.
2. Reusable tooling or ecosystem-maintenance source belongs under `capabilities/`.
3. Other repository clones belong in the accepted personal or work container.
4. Within either container use `src/<git-owner>/<repo>` when contribution is intended,
   or `vendor/<git-owner>/<repo>` for read-only reference.

`src` means fetch/push and active authoring. `vendor` means no contribution from that
checkout; promote it through a governed path/configuration change before editing.
Both may supply a baseline for a separately adapted utility, feature or capability.
Keep upstream provenance and licenses with adaptations.

### Global and local capabilities

Global capabilities are packaged for governed delivery to another repository;
local capabilities remain within this ecosystem. Either may be homegrown or borrowed
and adapted from vendor source. Capability source remains actively developed.
The owning registry and orchestrator govern transport; clone presence or registration
alone never triggers synchronization. See §10 for the existing owner boundaries.

### Legacy host compatibility

Existing absolute paths, workspace files, runtime bindings and paused WIP may still
use predecessor locations. They are compatibility inputs, not permission to move
checkouts opportunistically. Reconcile them in the accepted migration transaction;
never overwrite a dirty primary tree or discard unfinished work. Chaos Labs remains
private/no-CI. Scheduler source converges later on the common framework while its
public release process is preserved.

## 3. Workspaces

| File | Roots |
|------|-------|
| `~/dev/affirm/cpp.code-workspace` | `affirm/src`, `affirm/vendor`, `capabilities/mcp` |
| `~/dev/personal/KleinPerkins.code-workspace` | `personal`, `capabilities/mcp` |
| `~/dev/capabilities/mcp.code-workspace` | `capabilities/mcp` |
| `~/dev/capabilities/skills.code-workspace` | `capabilities/skills` |

(`skills.code-workspace` surfaces the global skills repo — see §4.)

---

## 4. Skills: tiers, the global repo, and the dedup rule

### 4a. Skill tiers
| Tier | Meaning | Home | Members (2026-06) |
|------|---------|------|-------------------|
| **Global** | useful everywhere, all orgs/tools, **shared into cpp via the orchestrator** | **`KleinPerkins/skills`** repo → `~/dev/capabilities/skills/global/` | `agent-route`, `prompt-architect` |
| **Local** | installed locally on operator machines but **NOT** vendored downstream to cpp | **`KleinPerkins/skills`** repo → `~/dev/capabilities/skills/local/` | `frontend-design`, `session-close`, `update-skills`, `continual-learning` plugin governor |
| **Work / Affirm-shared** (home-policed) | Affirm-specific, shared across Affirm work; the home dedup rule (§4c) applies to this set | `~/.cursor/skills` canonical + Claude/Codex symlinks; surfaced via `cpp.code-workspace` | `affirm-app-setup`, `affirm-checkout-setup`, `affirm-design`, `latency`, `snowflake-netskope-reset`, `customer-ops` |
| **Work / cpp-surfaced** (NOT home-policed) | Affirm-shared but surfaced into `~/.{cursor,claude,codex}/skills` by cpp's `_ops/bin/cpp-install-skills.sh` (not by `bootstrap.sh`); the home dedup rule deliberately does **not** apply | `cpp/quiver/skills/<name>` (cpp is the authoritative installer); operator copies are managed by cpp | `affirm-brand` (cpp-surfaced **LINK/subscription wrapper**; canonical = BOSS Notion), `council` (cpp-**owned** self-contained fork), `quickhost` (cpp-**owned** fork; the Cursor real-dir keeps the LD-local `quickhost-suggest.py` hook that cpp's fork dropped — genuine divergence pending reconciliation) |
| **Bespoke** | only meaningful in one project/context | with that project | `numenor-automation`, `vision-intake` |

> **Global vs local scope (reorg-v2 D-2/D-3).** Eligibility for orchestrator → cpp vendoring is decided **by directory**: a capability under `capabilities/skills/global/` is **global** (shared into cpp quiver), one under `capabilities/skills/local/` is **local** (installed locally on operator machines but never vendored to cpp). The eco engine (`_ops/eco/manifest.sh validate`) enforces that each `meta.yml`'s `scope:` field matches its containing directory.

(`customer-ops` was reclassified bespoke → Work-general in this reorg.)

> **`create-mlops-page` + `deploy-mlops-page` retired (2026-06):** these two were **removed from the personal `~/.cursor/skills` shelf** and ultimately **retired as redundant** — the underlying need was solved another way, so they are no longer maintained in this workspace. (They remain team-owned in `ai-product`, where they clone `Affirm/mlops` on demand; this workspace holds no copy.) An earlier attempt to vendor them **into the `Affirm/mlops` repo** via **`Affirm/mlops` PR #2038** was **closed and its branch deleted**, so the relocation never landed. They are no longer global/personal skills here.

### 4b. Global skills repo (Model A — repo is the single source, tools link in)
- **Repo:** `KleinPerkins/skills` (personal GitHub, **PRIVATE**) — <https://github.com/KleinPerkins/skills>.
- **Local clone:** `~/dev/capabilities/skills` (real capability content lives under `global/<shelf>/<name>/` or `local/<shelf>/<name>/`).
- **Every tool reference is an ABSOLUTE symlink into the repo** — never a second real copy. The symlink resolves to whichever scope dir holds the skill:
  ```
  ~/.cursor/skills/<name>  ->  ~/dev/capabilities/skills/{global,local}/<name>
  ~/.claude/skills/<name>  ->  ~/dev/capabilities/skills/{global,local}/<name>
  ~/.codex/skills/<name>   ->  ~/dev/capabilities/skills/{global,local}/<name>
  ```
- **Pre-INT-008 retained-exposure baseline** (current until a separately authorized retained migration) is independent of scope; Cursor is the complete hub:
  - Cursor: `agent-route`, `prompt-architect`, `frontend-design`, `session-close`, `update-skills` (all 5)
  - Claude: `agent-route`, `session-close`, `update-skills`
  - Codex: `agent-route`, `frontend-design`
- **`agent-route`** is symlinked like other globals, but **state + hooks require a one-time `bash global/agent-route/install.sh`** (creates `~/.agent-route/`, Cursor `sessionStart` hook, optional launchd maintain). `bootstrap.sh` relink alone is not a full install.
- **Edit flow:** change `global/<name>/...` in the repo, commit, push — all symlinked tools see it immediately (no copy step).
- **Local plugin governors:** `local/plugins/<name>/` is for Cursor marketplace/IDE plugin governance (`kind: plugin`, `flavor: 2`, `scope: local`). These carry `plugin.json`, `SKILL.md`, and `install.sh --apply|--doctor|--repair`; `bootstrap.sh` surfaces their skill interface and calls the installer intentionally. They are never registry-enrolled for cpp vendoring.
- **New machine:** `gh repo clone KleinPerkins/skills ~/dev/capabilities/skills && ~/dev/capabilities/skills/bootstrap.sh`. `bootstrap.sh` is idempotent (clones if missing, relinks the per-tool symlinks, activates local plugin governors, and never clobbers a real dir).

### 4c. Dedup rule for Work / Bespoke skills (Cursor canonical)
For the **home-policed** non-global skills, **Cursor stays canonical**: each lives once as a real dir at `~/.cursor/skills/<name>`; Claude/Codex consume it via a **symlink into the Cursor copy** — never a second real copy. This rule is enforced by `~/dev/capabilities/verify-capabilities.sh`.

- Claude symlinks into Cursor: `affirm-app-setup`, `affirm-checkout-setup`, `affirm-design`, `latency`
- To add a home-policed Work/Bespoke skill to another tool: `ln -s ~/.cursor/skills/<name> ~/.<tool>/skills/<name>`.

**Excluded from the rule (cpp-surfaced, NOT home-policed):** `affirm-brand`, `council`, `quickhost`. cpp's `_ops/bin/cpp-install-skills.sh` surfaces these into **all three** tool dirs (Cursor, Claude, Codex); Cursor is skipped only because a real dir already exists there (its `relink()` refuses to clobber real dirs). cpp is the authoritative installer for these — their Claude/Codex copies may resolve into any cpp checkout (incl. ephemeral worktrees), and home verification deliberately ignores them to respect repo sovereignty.

Codex-managed, do not touch: `~/.codex/skills/.system`, `~/.codex/vendor_imports/skills`.

### 4d. Bounded Codex required-skill migration

INT-008 has one narrow host entrypoint, dispatched before clone or full Skills reconciliation:

```text
bash capabilities/bootstrap.sh --codex-skill-migration preview  --operation-dir <private-path> --host-build <build> [--source-mode retained|canary|pinned-retained] [--skills-source <owner-git-root>] [--portability-manifest <approved-manifest>]
bash capabilities/bootstrap.sh --codex-skill-migration apply    --operation-dir <private-path> --approve <preview-action-sha256>
bash capabilities/bootstrap.sh --codex-skill-migration verify   --operation-dir <private-path>
bash capabilities/bootstrap.sh --codex-skill-migration rollback --operation-dir <private-path> --approve <preview-action-sha256>
```

The fixed allowlist is only `prompt-architect` and `verification-before-completion`. The transaction
creates their exact `~/.codex/skills` links and removes only proven-owned matching `.agents/skills`
aliases. It refuses foreign or dangling links, real paths, changed preimages, relevant native
skill-policy drift, stale source, and later edits. Cursor links, plugin/system roots, other skills,
unmanaged config bytes, and native opt-outs are preserved; missing overrides never prove enablement.
Operation records and exact preimages are mode-private and must live outside Git.

`retained` mode requires the clean durable primary `~/dev/capabilities/skills` checkout to be on its
current `origin/main` with the exact merged INT-005/006 payload. Updating that primary checkout is a
separate live consequence and this interface never performs it. `canary` mode instead exports only
the two byte-verified merged Git-object payloads into the private operation directory; those links
are temporary, are not retained source authority, and require the bounded native canary approval,
rollback, verification, and exact-root cleanup. Filesystem verification does not prove native
discovery, activate INT-021, change downstream enrollment, or establish AWA registration.

`pinned-retained` is a separate personal-migration contract: it requires the exact approved
portability manifest (SHA-256 `e6e9bf948d1f664367456fffe06e408a08b50933466022b8b7dc2e30a35bf725`),
the clean detached Skills pin `f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a`, and the same fixed
65-file payload. It links only to that durable primary checkout and never updates its branch,
HEAD or remote refs. The ordinary `retained` current-`main` checks remain unchanged. Build 23880
uses the separately merged Skills PR #248 observations; `--skills-source` must contain their
immutable merge `acfa04128c9451f66f7d1bad18c71d32b895ee1e`. Every apply rechecks the manifest,
source, payload and exact target preimages. A fresh operation-bound approval remains required.

#### Separate Codex-only Isokit canary

The personal migration has a separate canary interface; the two-skill INT-008
allowlist above is unchanged:

```text
python3 _ops/interoperability/isokit_migration.py preview --operation-dir <new-private-path> --portability-manifest <approved-manifest>
python3 _ops/interoperability/isokit_migration.py apply --operation-dir <private-path> --approve <exact-action-sha256>
python3 _ops/interoperability/isokit_migration.py verify --operation-dir <private-path>
python3 _ops/interoperability/isokit_migration.py rollback --operation-dir <private-path> --approve <exact-action-sha256>
```

Owner source acceptance is a prerequisite to host publication. Candidate preview
and disposable fixture tests grant no publication authority. Preview binds the approved personal
manifest, clean detached `f2301ce` primary checkout, all 123 tracked Isokit files,
the already qualified Playwright runtime and approved browser binary hashes, and
Codex macOS arm64 build 23880. It preserves the two installed required skills,
Cursor/Claude paths, native aliases and all configuration; relevant explicit native
opt-outs refuse publication. Missing overrides are not proof of enablement.

This transaction may create only an absent `~/.codex/skills/isokit` link to the
pinned `local/skills/isokit` directory, plus its named transient staging link.
It never adopts or replaces an existing target. The private operation records the
created link inode before atomic no-clobber publication. Exact rollback requires
that inode and refuses later path edits. The CLI serializes cooperating invocations
of the same operation; it does not exclude unrelated filesystem writers. Do not
run concurrent native skill publishers. Interrupted ownership/staging conflicts
remain visible and fail closed. A rolled-back operation cannot be replayed.

A preview digest is not consequence consent. Obtain exact temporary-publication
and worker/model-route approval separately; the interface starts no worker. The
bounded native check has a 120-second deadline and must be followed by exact
rollback and preimage verification. A process interruption can leave an owned link
requiring explicit rollback; no background cleanup service is installed. Retain
private operation evidence; cleanup needs a separate exact-root review.

This is canary authority only. It does not qualify native discovery, activate
INT-021, enroll downstream consumers, establish AWA registration, or grant retained
installation. Native discovery/use and rollback observations need immutable owner
acceptance before a separately reviewed retained interface and fresh exact approval.
The original migration journals and skill-operation bindings are never rebound.

#### Separate retained Isokit installation after native qualification

The retained interface is distinct from the canary above:

```text
python3 _ops/interoperability/isokit_retained.py preview --operation-dir <new-private-path> --portability-manifest <approved-manifest> --native-evidence <exact-owner-evidence-file>
python3 _ops/interoperability/isokit_retained.py apply --operation-dir <private-path> --approve <retained-action-sha256>
python3 _ops/interoperability/isokit_retained.py verify --operation-dir <private-path>
python3 _ops/interoperability/isokit_retained.py rollback --operation-dir <private-path> --approve <retained-action-sha256>
```

Owner source acceptance is required for this interface and for the exact Skills
native evidence revision compiled into it. Export only the evidence file at that
immutable revision; verify its bytes against the compiled SHA-256. Do not update
the approved primary checkout to obtain evidence. The accepted canary qualifies
only the unchanged f2301ce Isokit payload on Codex macOS arm64 build 23880.

Preview creates a separate private retained operation around the unchanged
accepted canary transaction. Its action digest binds that transaction, accepted
native evidence, current source/manifest/config/preimages, native CLI bytes and
shared-session consequences. The canary action digest cannot approve retention.
Obtain separate exact retained consequence approval before apply; do not infer it
from prior temporary-publication or model-worker approvals.

Apply publishes the same single absent Codex link with the accepted inode-owned
transaction, then makes a bounded read-only native `skills/list` request using
the qualified bundled CLI. It adds no extra skill roots and starts no model worker,
thread, account refresh or tool call. Exactly one enabled Isokit entry must appear
at the retained home-link path or its exact canonical source path: the native
loader may canonicalize a symlinked skill. Both forms must identify the same
existing `SKILL.md` file as the verified owned link. A different alias, a copied
file with identical bytes, a missing file or a retargeted link cannot satisfy the
catalog check. Record the actual reported path and its verified link/source
identity. Source, config and exact link ownership are rechecked afterward.
Only then is the retained receipt written and the link left installed. Native or
receipt failure triggers exact rollback; foreign edits are preserved and any
recovery refusal remains visible. Failed/rolled-back operations cannot be replayed.

Verify rechecks source, host, config, link ownership, accepted evidence and fresh
native discovery. It reports the accepted canary as the native-use qualification,
not a new retained-worker execution. Rollback does not require evidence or a
working native CLI, and removes only the recorded inode. Keep the private wrapper
and child transaction records together; invocation locking excludes cooperating
calls only. No other client, original migration journal, source pin, service,
INT-021 rollout, downstream enrollment or AWA authority changes.

#### Separate temporary canary for capability and frontend-design

Two other required personal payloads have their own fixed, temporary-only entrypoint:

```text
python3 _ops/interoperability/selected_skill_canary.py preview --operation-dir <new-private-path> --portability-manifest <approved-manifest>
python3 _ops/interoperability/selected_skill_canary.py apply --operation-dir <private-path> --approve <exact-action-sha256>
python3 _ops/interoperability/selected_skill_canary.py verify --operation-dir <private-path>
python3 _ops/interoperability/selected_skill_canary.py rollback --operation-dir <private-path> --approve <exact-action-sha256>
```

Use Python 3.11 or newer. Owner source acceptance is a prerequisite to publication;
candidate tests and a read-only preview grant none. Export only this entrypoint,
its three hash-bound transaction helpers and its two authored fixture/workload
files at the exact accepted owner revision. Verify every exported Git blob and
file digest. This path never clones the mixed dev repository or invokes bootstrap.

The allowlist is exactly `capability` and `frontend-design`, at the unchanged
approved detached Skills pin `f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a`.
The seven tracked regular files bind inventory SHA-256
`41f71eacf1f1c5452b238ffb6fc761ca81078f4f0a125f57de571bf35280b1c2`.
No earlier INT-005/006 or Isokit native-use observation qualifies these payloads.
The original portability-manifest digest remains required. The ordinary INT-008
allowlist and the Isokit interfaces above are unchanged.

Preview binds actual Codex macOS arm64 build 23880, its fixed app/CLI bytes,
the running interpreter, implementation/fixture/workload bytes, source/manifest,
config enablement, parent identities and preserved paths. Explicit native opt-outs
and existing native aliases refuse. Only two absent `~/.codex/skills` targets and
their named transient staging links can be published. Nothing is adopted,
replaced or pruned. Existing retained skills, plugin/system roots, other clients,
source refs, configuration and original migration journals remain untouched.
Operation records stay private and outside Git, pinned source/tool roots and
the verified runtime export itself.

Obtain fresh exact temporary-publication and one-worker/model-override consent
for the real preview and complete packet. A digest or general setup authorization
is not proof of that consent. This interface starts no worker. The parent must:

1. Recheck accepted source/export and every bound preimage, apply through the
   interface and verify both exact owned links. Never run concurrent native
   skill publishers. Publication is no-clobber and records each inode before
   visibility. An interrupted apply can resume only its already-owned inodes;
   a missing owned link is never recreated under an old receipt.
2. Create a new private `fixture` directory beneath the operation. Seed only a
   mode-0600 `fixture-owner.json` with schema
   `interoperability/selected-skill-fixture/v1`, the operation UUID and action
   digest. Require all three worker outputs to be absent. The authored fixture
   CLI permits only its synthetic lifecycle state; it installs no real service.
3. Verify fresh native discovery without extra roots or account/token refresh.
   Require one enabled entry per selected name, identifying its owned home link
   or exact canonical same-file `SKILL.md`. A copied file or different alias is
   insufficient. Discovery alone is not functional qualification.
4. Follow the hash-bound workload with exactly one fresh
   `collaboration.spawn_agent` worker, requested `gpt-6.1-sol` / `high`, with
   `fork_turns: none` and no nested delegation. Immediately wait at most 60 seconds;
   interrupt if unfinished, leaving margin before the strict actual 120-second
   deadline. Observe that same handle to a terminal result; an observation timeout
   is not a reason to start another worker. An unavailable route, overrun, missing
   source reads or failed artifact is a failed canary. Do not silently substitute
   a model or infer serving identity/AWA registration. Repeated link apply never
   authorizes an additional worker.
5. In a parent `finally` path after every outcome, roll back through this exact
   interface and verify restored preimages/source/preservation before local
   artifact checks. Rollback uses only recorded inode ownership and remains
   available after source/config drift, preserving those later edits. A foreign
   slot is held while other exact owned slots are removed. A held/started rollback
   prevents replay; any recovery refusal must remain visible. Locks serialize
   cooperating calls only, not unrelated filesystem writers or a hostile same-user
   agent. Interrupted processes can leave owned links needing explicit recovery;
   no cleanup daemon is installed. Never execute changed runtime bytes to recover.
6. Check the untouched HTML locally with existing dependencies/browser only:
   real filtering/counts, keyboard/focus, responsive/reduced-motion behavior,
   source-specific design and visual quality. Verify the fixture's actual
   install/one-repair/Ready outcome and both native instruction reads. Retain
   private traces and hashes; publish only a closed owner observation summary.

There is no retained mode. Only actual native-use, timing, artifact and exact
rollback evidence can support later owner qualification; source delivery and
disposable tests cannot. Immutable acceptance of that evidence, a separately
reviewed retained interface and fresh retained consent remain prerequisites.
No other host, service, download, work/Affirm system, protected component,
INT-021 rollout, downstream enrollment or model-routing configuration changes.

### 4e. Personal-only reconstruction

An explicit `bootstrap.sh --profile personal-codex` (alias `personal`) dispatches to the
manifest-driven personal reconstruction engine before every legacy installation step. See
[`_ops/portability/README.md`](_ops/portability/README.md) for its closed manifest, commands,
package builder, and separate source/operational completion states. No-argument bootstrap
retains the existing work-machine behavior; never run it on a personal-only target.

The personal kit is a curated export of named portability files. It excludes this repository's
work-authored content and Git history, all host configuration and credentials. The full dev
clone remains an explicit mixed-content blocker. It reconstructs eligible personal sources
without executing their installers; host-native capability, local-state preservation and
single-writer service gates remain visible. It does not change capability enrollment, retire
the legacy MCP writer, activate AWA, or qualify a new Codex account/build.

#### Closed personal source selection for Dev projections

`_ops/portability/personal_scope.py` supplies a read-only target-selection dependency
for the remaining personal Dev projections. It binds the exact approved `17e962df`
destination manifest bytes and the twelve named personal repository IDs, relative
paths and source pins. An unknown, duplicate, held or excluded ID refuses before
any home/manifest/target access. The operator must be non-root, without a privilege
mismatch, and `HOME` must match the OS account home. Target selection never discovers repositories by
walking `~/dev`, linked worktrees, a fleet registry or other roots.

After immutable owner source acceptance, a bounded export can inspect those exact
directory identities with Python 3.10 or newer:

```text
python3 -I -B personal_scope.py inspect --portability-manifest <exact-operator-home-manifest>
python3 -I -B personal_scope.py inspect --repository KleinPerkins/skills
```

It opens only selected lexical directory chains with no-follow descriptors. Its
read helper accepts bounded, operator-owned, unshared regular files beneath one
selected root; visible file/parent/root replacements refuse and preserve edits.
Callers must construct a fresh scope per observation, verify the expected personal
origin before further repository reads/probes, and still restrict every helper's
paths, Git subprocesses, policies, remote reads and side effects. This
module is not a sandbox against a hostile same-user caller or concurrent writer.
It neither runs Git nor checks pins/cleanliness, and grants no write, native skill,
model worker, service, registry or retained-installation authority.

This dependency is not an installed or qualified `dev-doctor`, `dev-new-repo`,
`dev-remove-repo` or `doc-warden`, and does not resolve the mixed-source repository
requirement. Keep the complete doctor verdict/identity/placement/origin/sync,
hook, baseline/profile, linked-worktree and documentation semantics in the owner
projection; surface missing proof explicitly. Current v2 greenfield and document
authority, exact external gates and per-risk destructive consent remain required.
Do not run the broad legacy doctor/removal scripts behind a filtered top-level
target list: their internal discovery and helper closures must also be scoped.
The existing bootstrap, six-file kit, manifests and journals stay unchanged.

#### Bounded personal Git metadata dependency

`_ops/portability/personal_git.py` builds on the unchanged hash-bound personal
scope module. Its current macOS route binds the exact installed CLT Git bytes.
After immutable owner source acceptance, export only these two Python modules
and verify both accepted Git blobs before running the read-only observation:

```text
python3 -I -B personal_git.py inspect
python3 -I -B personal_git.py inspect --repository KleinPerkins/skills
```

The stdin config parser disables includes and uses a new empty private temporary
directory. It establishes the expected local personal origin before other Git
metadata/probes, supports the primary's per-worktree config overlay and refuses
unclassified remotes/rewrites, includes, filters, partial-clone or storage modes.
Global/system Git config, inherited Git overrides and credentials are not used.
Before repository probes it checks no-follow owned metadata, object/ref storage,
external alternates and primary/common-dir boundaries. Config path identity and
bytes are rechecked before each probe; metadata inventories are checked afterward.
Repository queries use a new private metadata view with copied HEAD, index,
shared indexes, refs and selected data/normalization/tracking configuration. They
read the audited personal object store in place. Raw repository auth, credentials,
hooks and helper settings are not copied. This also contains Git's split-index
timestamp refreshes inside the disposable view. Source index/shared-index facts
are checked before and after; bounded copies and temporary views are removed.
Visible later edits refuse without modifying or adopting them. These checks are
cooperating observation hygiene, not protection from a hostile same-user writer.

The closed verbs observe HEAD, branch, local upstream counts and two index names
(`agent-learnings.md`, `AGENTS.md`). They do not read generated-memory contents.
Every process has a four-second bound and per-stream output limits; timeout or
overflow terminates that same process group and never starts a replacement.
The fixed Git invocation disables lazy fetch, optional locks, object replacement,
network transports and executable helpers relevant to these probes. Missing or
refused evidence remains unavailable. No raw config or stderr is reported.

Observed HEAD/personal identity/local tracking facts do not prove a clean working
tree or live remote parity. This dependency deliberately exposes no worktree
status, linked-checkout traversal, arbitrary verb, root/tool override or writer.
Complete scoped worktree, hook, baseline/profile and active documentation checks
and actual native discovery/use remain required for `dev-doctor`; the other Dev
capabilities and mixed-source distribution requirement also remain open. Existing
bootstrap/package behavior, source pins, original records and shared skills stay
unchanged. Private temporary config-parser directories are removed after use.

#### Scoped primary working-tree dependency

`_ops/portability/personal_worktree.py` adds working-tree status to the metadata
dependency above. After immutable owner source acceptance, export and verify all
three exact Python modules together; `personal_worktree.py` binds its metadata
dependency by SHA-256, and that module binds the unchanged scope module.

```text
python3 -I -B personal_worktree.py inspect
python3 -I -B personal_worktree.py inspect --repository KleinPerkins/skills
```

This is the same closed twelve-primary selection, not a scan of `~/dev` or a
linked-worktree/fleet registry. Descriptor-based traversal checks control files,
ownership, links and visible later edits before a bounded porcelain status query.
Tracked generated-memory names and Gitlinks hold before tree/status inspection.
Unclassified nested checkouts and untracked work/protected names hold before
their contents are entered; symlink targets are never traversed. Missing or
refused evidence stays unavailable rather than becoming a clean result.

Git's own ignore engine applies repository `.gitignore`, `.git/info/exclude` and
a classified `core.excludesFile` inside that exact repository. Ignored untracked
directories are pruned before reading their child rules; tracked descendants
remain checked. External excludes and generated-memory control pointers are held.
Global/system config
and implicit global excludes are disabled, so cleanliness is explicitly under
this personal repository policy. It is not parity with arbitrary ambient Git
configuration. Local attributes/sparse controls are validated, and every query
uses the disposable metadata/index view above. No filters, hooks, fsmonitor,
network transport or lazy fetch is enabled. NUL-delimited filenames preserve
spaces, newlines and Unicode without treating names as pathspec magic.

Two bounded tree/control observations surround status. Results retain counts,
status codes and name digests without raw worktree bodies/config/stderr. Sparse
and split-index fixtures, ignored special files, control aliases, rename/conflict
records and visible later edits are tested, including source metadata preservation.
These cooperating checks are not a sandbox against a hostile same-user writer.

This dependency grants no source/config mutation, linked-checkout traversal,
native publication, installer or worker authority. Clean primary observations
still do not qualify the complete doctor: scoped linked-worktree, hooks,
baseline/profile, structural documentation and memory checks remain required.
The separate required documentation capability also retains active-v2 semantics;
legacy doctor structural compatibility cannot substitute for it. Native use and
all other required migration capabilities remain separate acceptance gates.

#### Scoped primary hook and memory dependency

`_ops/portability/personal_controls.py` composes the same closed personal scope,
Git metadata and worktree dependencies. Export and verify all four exact modules
after immutable owner source acceptance. This adds read-only observations, not a
hook installer, shared skill publication, model worker or complete doctor.

```text
python3 -I -B personal_controls.py inspect
python3 -I -B personal_controls.py inspect --repository KleinPerkins/skills
```

The hook observation preserves the canonical doctor's `active`, `missing`,
`inert-hookspath` and `foreign-hookspath` distinctions. Active means the fixed
managed dispatcher marker was observed; it never proves that a hook executed.
An active registration guard is compared with the immutable accepted owner blob
bound in the module. Missing/stale guard bytes or absent owner execute bits remain
advisory. Relative, exact in-repository absolute and primary worktree-overlay
settings are supported. `/dev/null` is classified as an explicitly inert setting
without reading it. External, aliased, protected or unclassified nested-checkout
paths remain unavailable; hook bodies and chained hooks are never executed.

Memory observations use index names, no-follow presence metadata and Git's scoped
repository ignore matcher. Any tracked `agent-learnings.md` is a `VIOLATION` before
its body is read. Present untracked memory that is not ignored is `DRIFT`; unsafe
types, external ignore settings and failed ignore queries remain indeterminate.
Generated-memory bodies are never read, hashed, copied or emitted. Only tracked,
bounded owned `AGENTS.md` is checked for the original learned-section headings
(`DRIFT`) and missing memory pointer (`ADVISORY`); no control contents are emitted
or adopted as host instructions. Untracked `AGENTS.md` is not read.

Configured control pointers are checked for nested checkout boundaries before
reading their target. Bounded ancestor checks, parent identity facts, repeated
control reads and final memory/control metadata checks refuse visible later edits
without changing them. They do not provide a hostile same-user writer sandbox.
All Git probes use the disposable private metadata/index view; no source, config,
hook, journal or shared discovery mutation is authorized.

The diagnostic preserves `OK < ADVISORY < DRIFT < VIOLATION`. A proven memory
violation exits 1, unavailable evidence exits 2, and available advisory/drift
observations exit 0 as in the original doctor. Exit 0 is not full capability or
migration acceptance. Classified linked-worktree, baseline/profile, structural
documentation and complete caller/native qualification remain required, alongside
the separate active-v2 documentation capability and remaining Dev owner gates.

#### Native browser provider on the personal Codex host

The personal profile can satisfy its browser-automation requirement
(`connections/playwright`) through the host-supplied Codex browser provider.
The observed surface is `cua_repl` browser control with documented Playwright
locators and read-only DOM inspection. The installed Codex host supplies this
provider; no extra MCP registration, server daemon or copied account profile is
needed for the local synthetic workflow.

Owner acceptance of
[`native-browser-build-23880.json`](_ops/portability/evidence/native-browser-build-23880.json)
binds the provider choice to the recorded native build-23880 observation:
navigation, page inspection, labeled text entry, pointer/keyboard interaction,
rendered screenshot, console diagnostics and exact temporary-resource cleanup.
The new reproducible fixture is under
[`_ops/portability/fixtures/native-browser/`](_ops/portability/fixtures/native-browser/).
The observation used actual native browser calls, with no extra model worker,
download, account authorization or persistent configuration change.

Close only the browser-provider-selection and bounded native-functional parts of
this requirement after that exact source acceptance and destination evidence
binding. Record the provider actually used; do not assert that a legacy standalone
Playwright MCP server was installed. Browser account identities and external-site
permissions retain their normal gates. This local test qualifies no work account,
other connector, native-app control or arbitrary external workflow. Provider,
build or functional-contract changes require requalification. The approved
manifest, original journals, source pins and service ownership stay unchanged.

### 4f. Bounded imported-utility isolation

The remaining INT-008 source interface is separate from the two-skill migration above:

```text
bash capabilities/bootstrap.sh --codex-imported-skill-isolation preview  --host-root <explicit-absolute-root> --operation-dir <private-path> --host-build <build>
bash capabilities/bootstrap.sh --codex-imported-skill-isolation apply    --host-root <explicit-absolute-root> --operation-dir <private-path> --approve <preview-action-sha256>
bash capabilities/bootstrap.sh --codex-imported-skill-isolation verify   --host-root <explicit-absolute-root> --operation-dir <private-path>
bash capabilities/bootstrap.sh --codex-imported-skill-isolation rollback --host-root <explicit-absolute-root> --operation-dir <private-path> --approve <preview-action-sha256>
```

Its immutable allowlist is exactly the `SKILL.md` files under
`.agents/skills/{sdk,update-cli-config,create-subagent}`. The only writable target is that explicit
root's existing `.codex/config.toml`: the executor appends path-specific `[[skills.config]]`
`enabled = false` rows and preserves the prior config as a mode-0600 file in the private operation
directory. It refuses changed inventory hashes, malformed/unsupported TOML, folder selectors,
ancestor or same-file aliases, duplicate exact selectors, explicit conflicting overrides, changed
config preimages and rollback after any later edit. Existing exact disabled rows, every unrelated
TOML byte and field, same-name
skills elsewhere, project configuration, plugin/system roots, imported files and Cursor state remain
untouched. Apply and rollback preserve the config mode and are bound to the preview action digest;
repeated apply is a no-op. A bound interrupted stage can only be resumed or canceled through those
same apply/rollback verbs when its bytes and mode match an exact bound config image; unknown stages
refuse without deletion. Private operation storage requires positive outside-Git evidence and
refuses Git metadata, bare repositories, and unknown probe failures.

Preview creates a full private config preimage, which may include existing credentials. Before
using a live root, confirm that the active instructions permit that protected local storage. If
secret persistence is prohibited, stop before preview; obtain the specific owner disposition
without changing credentials or copying the config into review artifacts or Git.

This interface establishes source/fixture transaction behavior only. TOML parse success does not
qualify native selector semantics, discovery precedence, reload/restart behavior or effective
disablement. Those require a separately approved bounded native canary. Its preimage rechecks and
advisory file lock serialize cooperating invocations only and do not exclude another writer.
The action digest is not consequence consent, retained activation or source-ownership adoption.

---

## 5. MCP config locations + current target paths

Three independent client configs — keep them in sync when relocating a server:

| Client | Config file |
|--------|-------------|
| Cursor | `~/.cursor/mcp.json` |
| Codex  | `~/.codex/config.toml` |
| Claude | `~/.claude.json` |

Current server target paths (post-reorg):

| Server | Configured in | Target path |
|--------|---------------|-------------|
| `snow-kit` | Cursor + Codex + Claude | `~/.local/bin/snow-kit mcp --read-only` (immutable release under `~/.local/share/kp-mcp/snow-kit/`) |
| `google-kit` | Cursor + Codex + Claude | `~/dev/capabilities/mcp/.venv/bin/google-kit` |

### How to relocate an MCP server
1. **Move the code** (lossless `mv`) to its new home under `~/dev`.
2. **Repoint every config** that references the old path (`~/.cursor/mcp.json`, `~/.codex/config.toml`, `~/.claude.json`).
3. **Recreate the venv if present** — venvs hardcode absolute paths. Development uses `cd ~/dev/capabilities/mcp && uv sync`; LD-host snow-kit is never served from that checkout and instead uses `bash capabilities/mcp-bootstrap.sh repair snow-kit`.
4. **Verify**: restart the client(s) and confirm the server connects / the entrypoint resolves (`ls <target>` for a file entrypoint, or run the `bin` shim with `--help`).

---

## 6. Secret & config policy

- **Auth/config lives at home**, never inside a repo: `~/.cursor/`, `~/.codex/`, `~/.claude.json`, shell rc files, cloud CLI creds. These are user-level and never committed.
- **Never commit secrets** (tokens, API keys, cookies, session files) into any repo under `~/dev`.
- Tracked **`.npmrc`** files in repos hold **registry configuration only** (registry URLs / scopes) — no auth tokens. Auth tokens belong in `~/.npmrc` at home.

### Git identity (personal vs work)
- **Work / Affirm repos** keep the **global default** `user.email` (`laurence.duggan@affirm.com`) — do not override per-repo.
- **Personal repos** (`KleinPerkins/*`, personal repos under `~/dev/personal/`, and personal capability repos) use the KleinPerkins GitHub **noreply** email via a **LOCAL per-repo** setting — never global:
  ```
  git -C <repo> config --local user.email "49759187+KleinPerkins@users.noreply.github.com"
  ```
- **Rationale:** avoids GH007 email-privacy push rejections and keeps the `@affirm.com` work email out of personal commit history.
- **Applied so far:** `~/dev/capabilities/skills` (done). Other personal repos (e.g. under `~/dev/personal/`) can take the same LOCAL setting the same way when needed — not done yet.

---

## 7. Backup policy

- The Chunk-1 safety backup is retained at **`~/reorg-backup-20260619-2319/`** (`chmod 700`). It contains full/partial captures and a `reconcile/` dir of patches for repos that were dirty at move time, plus `CHUNK1-LOG.md`.
- Pre-move copies of the 4 global skills (resolved real content, captured before the repo move) are at **`~/reorg-backup-20260619-2319/global-skills-premove/`**.
- Treat it as **read-only insurance**. Do not delete until the reorg is fully verified and explicitly signed off (the redundant-backup purge, M8, is still HELD).

---

## 8. DEFERRED / TODO

- **✅ DONE — `card-platform-product` (cpp) operating model is LIVE & HARDENED (2026-06-23).** The
  governed repo `Affirm/card-platform-product` (working tree `~/dev/affirm/src/card-platform-product`)
  went from an **empty remote** to a fully implemented, documented, tested, and **hardened** operating
  model (build P0–P8 → independent audit → hardening A→D). Depth lives in the SOT — which has now
  **moved INTO the repo**, where it is **version-controlled + governed** (control plane), at
  **`_ops/cpp-operating-model-SOT.md`** in `Affirm/card-platform-product` (now **v4**;
  cross-linked with `_ops/POLICY.md`). The old disk path `~/dev/affirm/cpp-operating-model-SOT.md`
  is now just a **redirect stub** (gitignored breadcrumb). This is the summary. As-built:
  - **Durable on the remote:** `main` pushed (SSH remote — bypassed the then-missing `workflow` OAuth
    scope, since granted; SSH kept as the default). Branch protection: **7 required status checks** (the
    6 `cpp-policy` jobs + `cpp-tests`) + 1 code-owner review + linear history; squash-only + auto-merge +
    auto-delete; `strict=false`. **`enforce_admins=false` is deliberate** — control-plane (`_ops/`,
    `.github/`) changes land via **PR → green → `gh pr merge --admin --squash`** (no direct-push), and
    `cpp-control-plane-guard` opens an advisory issue on any direct-push bypass.
  - **Control plane (`_ops/`, LD-only):** `facts/` source-of-truth → **generated** `ownership.yml` +
    `.github/CODEOWNERS`; deterministic **`cpp-integrity-engine`** (checks **C0–C6**, verdicts
    `OK<ADVISORY<DRIFT<NEEDS_HUMAN<VIOLATION`); self-contained git hooks; closed `meta.schema.json`
    (no `visibility`). The **bot `affirm-cpp-bot`** auto-approves + squash-auto-merges eligible PRs
    (metadata-only, no PR-code checkout) with an explicit **`_ops//.github` control-plane deny**.
  - **Identity — record + honor:** each member's git identity is recorded in `_ops/facts/people.yml`
    (`git_user_name`/`git_user_email`/`email_preference: affirm|noreply`) and applied per-repo by
    `apply-git-identity.sh`; `cpp-compliance` checks each commit against that record. The optional
    `additional_emails` field is a **general capability (kept)**; the **bot's** value was **removed**
    after enabling account email-privacy, so GitHub now authors its squashes under the noreply form
    `296122475+affirm-cpp-bot@users.noreply.github.com` (== its `git_user_email`) and compliance passes.
  - **Hardened (A→D):** Actions **SHA-pinned** (`# vX.Y.Z`); quiver **kind-shelf** layout
    (`quiver/<kind>/<id>`; `/cpp-promote` lands there; `quiver/skills/quickhost-example` is canonical);
    **`CPP_BOT_TOKEN` rotation** runbook (`_ops/runbooks/`) + `bot.yml` cadence (~90d / 14d lead) + weekly
    `cpp-token-reminder`; a **daily `cpp-canary`** E2E liveness probe (eligible auto-merge heartbeat +
    control-plane deny probe + cleanup + failure issue). **6 workflows** total (the B-5 `cpp-reindex` was retired).
  - **Agent UX:** 10 `/cpp-*` skills (`_ops/skills/`) backed by `_ops/bin/` scripts; **3** pinned subagents
    (`cpp-integrity`, `cpp-pr-triage`, `cpp-sync-repair`); a `gh` PR-triage poller; anti-duplication is an
    in-memory lexical **C3** block + `/cpp-resolve` + `_ops/index/distinctions.yml` (the advisory dedup caches
    + the nightly `cpp-reindex` Action were **retired in B-5**).
  - **Team tooling — quiver now populated (2026-06-24; PRs #24–#39; SOT → v4):** `quiver/skills/` holds **7**
    skills — `affirm-brand`, `quickhost`, `feature-explainer-video`, `natprd`, `upward-comms-review`, and
    `council` (a ~21-persona cross-tool doc-review orchestrator, 9 KBs) + the canonical `quickhost-example` —
    and `team/resources/` holds **2** resources (`product-playbook`, `pm-comms`). A `cpp-data-guard` job
    (secrets / PII / oversized-data) was added to `cpp-policy`. Depth lives in the SOT (Appendix V4).
  - **Tested:** a hermetic regression + discrete suite (`_ops/tests/`, **required CI check `cpp-tests`**)
    covering schema enforcement, dedup blocking, ownership/CODEOWNERS invariants, the real auto-approve
    eligibility bytes, handoff-check, bootstrap idempotency, and commit-email compliance.
  - **Docs:** in-repo `README.md`, `CONTRIBUTING.md`, `_ops/README.md`, `_ops/POLICY.md`,
    `_ops/facts/README.md`, `.github/cpp-automation-README.md`, and — **newly relocated in** — the
    canonical conceptual SOT at **`_ops/cpp-operating-model-SOT.md`** (ratified **v3**, Appendix
    V2 + V3; cross-linked both ways with `_ops/POLICY.md`, which is its enforced subset). The
    point-in-time records stay **disk-only / NOT moved into the repo** (operator chose SOT-only):
    **`cpp-implementation-report.md`** (P0–P8), **`cpp-audit-report.md`** (audit),
    **`cpp-hardening-report.md`** (A→D + the identity reversal).
  - **Pending — onboarding ("E"):** PMs aren't onboarded yet (`_ops/facts/` owners are `TODO`
    placeholders; LD is the sole human owner). Awaiting operator inputs: PM roster + owner assignments +
    an optional 2nd `_ops/` owner (which would unblock the `enforce_admins=true` flip).
- **chaos-labs — Phases 1–3 DONE (2026-06-22); `~/chaos-labs` removed.** The product repo is collapsed → `~/dev/personal/chaos-labs` and the live scheduler is hoisted → `~/dev/personal/chaos-scheduler` (§1 + §2). The scheduler binary was **rebuilt** to honor `CHAOS_LABS_ROOT` (canonical venv `~/dev/personal/chaos-labs/.venv`; `chaos-scheduler` commit `db76ab1`), the temporary symlink bridge was retired, and the old `~/chaos-labs` shell (~6.6G cruft) was **torn down** after a verified complete backup. Post-teardown the scheduler still fires (PID unchanged) and a graph-touching health-check workflow runs cleanly against `~/dev/personal/chaos-labs/data/knowledge-graph/chaos-labs.db`.
  - **Complete pre-teardown backup (chmod 700, integrity-verified):** `~/chaos-labs-full-preteardown-backup-20260622-1038.tar.gz` (2.0G; symlinks preserved) + manifest `~/chaos-labs-preteardown-manifest-20260622-1038.txt`. (The earlier data-only `~/chaos-labs-premigration-backup-20260621-1506/` is also retained.)
  - **In-repo `scheduler/` removed** (superseded by the hoisted repo) → chaos-labs commit `afe911d` (noreply LOCAL). **Stale local branch** `vision/domain-corpus-lifecycle/2026-05-19-domain-corpus-lifecycle-2` (merge `99d8480`, no unique delta) deleted. Stray `com.chaoslabs.capture-prompt.plist.pre-migration-backup-*` removed.
  - **✅ DONE — chaos-labs pushed to its remote (2026-06-22):** the formerly-unpushed local commits — the collapse `a0c5a5f` and the scheduler-removal `afe911d` — plus the `CHAOS_LABS_ROOT`-default repoint `a3406a2` were pushed **fast-forward** to `origin/main` (`661ff64..a3406a2`, no force); `origin/main` == `main`. Loss-risk cleared.
  - **✅ RESOLVED — residual `~/chaos-labs` coupling (2026-06-22):** the active `commit-msg-enforcement` git hook defaulted `CHAOS_LABS_ROOT`→`$HOME/chaos-labs` when the env var was unset, so a `git commit` made without `CHAOS_LABS_ROOT` exported re-created a tiny `~/chaos-labs/data/session-logs/.../activations.ndjson` telemetry stub. The hook default — plus a stale `$HOME/chaos-labs/.venv` candidate in the `schema-registry-gate` pre-commit hook — was **repointed to `$HOME/dev/personal/chaos-labs`** (tracked hooks → pushed in `a3406a2`); unset-env commits now write under the canonical gitignored `data/` path, never `~/chaos-labs`. *(Inert `Path.home()/"chaos-labs"` fallbacks in a few non-commit-time utility scripts — guarded by `.exists()` or not exercised on commit — were left alone per the surgical scope.)*
  - **Still deferred:** chaos-labs **thin bootstrap** (Phase-4 remainder — pin `KleinPerkins/skills`, read workspace repos from `~/dev`); **session-plane externalization** (its planned `chaos-session-system` home was retired 2026-10; chaos-labs keeps its `/vision` scripts); **multi-repo registry repoint** (load-bearing `scripts/chaos-git.py` code change, not a yml edit). Capture-state consolidation is now resolved by the rebuild (captures write under the canonical repo).
  - **`~/.codex/memories`** — still deferred; not yet mapped into `~/dev`.
- **Global skills capability repo** — ✅ DONE (2026-06). Created `KleinPerkins/skills` (PRIVATE) at `~/dev/capabilities/skills`; the 4 globals moved in; all tool refs symlink into it (Model A, §4); `skills.code-workspace` added; `bootstrap.sh` recreates the symlinks on a new machine.
  - **✅ RESOLVED (2026-06-26) — cpp / Affirm-team mirror → the ecosystem orchestrator (§10).** The chosen **option (a)** (a vendored, self-sufficient copy of a `global/` capability into cpp kept in sync by a script — the access-asymmetry-safe path, since `KleinPerkins/skills` is private) is now implemented as `KleinPerkins/ecosystem-orchestrator`. It vendors into `cpp/quiver/<cat>/<id>` via an **LD-authored governed PR** gated on cpp's integrity engine, enforces **INV-zero-link** (no ld paths in the cpp payload), and never touches cpp's control plane. **Canonical first sync landed:** `prompt-architect` → `Affirm/card-platform-product` **PR #68** (merged, squash `9dd9bad`). See §10e–§10g.
- **`duggan-bach` remote handling** — ✅ **RETIRED (2026-10):** the source checkouts (`personal/duggan-bach`, `personal/duggan-bach-source`) were removed, `KleinPerkins/duggan-bach` (the former GitHub-Pages build) and `KleinPerkins/duggan-bach-source` were archived, and `duggan-bach.com` was taken down. The 2026-06 backup/identity-rewrite history is preserved only in those archived repos.

---

## 9. Home operating model: durability, agent-wiring & bootstrap

The master repository owns the operating-model source and shared policy. It is
prepared as public-safe source with a new GitHub identity under the separately
released replacement procedure. [_ops/POLICY.md](_ops/POLICY.md) is enforceable;
private host snapshots and predecessor recovery archives remain outside Git.

### 9a. What is version-controlled (allow-list)

`.gitignore` explicitly admits the operating manual, entrypoints, `_ops` source,
repository CI/review/App scripts/tests/docs, and the selected capability bootstrap
files. It excludes nested personal/work repositories, credentials, client config,
work proposals, machine state and recovery packages. Immutable runtime pins contain
release identifiers only. The local identity is the canonical KleinPerkins noreply
identity. The source check and data guard supplement the allow-list; ignore patterns
alone cannot prove that a tracked file is safe to publish.

### 9b. Agent discoverability (one SOT → three tools, drift-detected)
Every agent session — any tool, any cwd under `~/dev` — auto-loads the operating model:
- **Single source of truth:** `_ops/rules/agent-context.md` (tight, tool-agnostic). Edit *only* this file to change what agents are told.
- **Cursor:** `_ops/rules/dev-operating-model.mdc` (`alwaysApply: true`) is generated from the SOT and **symlinked** to `~/.cursor/rules/dev-operating-model.mdc`.
- **Codex / Claude:** a hash-stamped **managed block** (`<!-- BEGIN dev-operating-model … -->` … `<!-- END dev-operating-model -->`) is injected into `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md` (created if missing); existing user content is **never clobbered** — only the marked block is replaced in place.
- **Repo entrypoint:** the root `AGENTS.md` is auto-read by Cursor/Codex when working in `~/dev`.
- **Install / refresh (idempotent):** `bash _ops/bin/install-agent-rules.sh` (or `make install-rules`, or `bash bootstrap.sh`). The Codex/Claude blocks embed `sha256(agent-context.md)`, so staleness is detectable; `make verify` and CI fail if any surface drifts from the SOT.
- **Operating-model skills (`_ops/skills/`, the proportional home analogs of cpp's `/cpp-*`):** surfaced into the tools via symlink (`~/.cursor/skills` / `~/.claude/skills`). **`/dev-doctor`** — the read-only cross-repo health check (per-repo verdict on `OK < ADVISORY < DRIFT < VIOLATION` for identity/placement/sync; the agent-facing front end of `make doctor`); **`/dev-new-repo`** — scaffolds a **born-compliant** private `KleinPerkins/*` repo (LOCAL canonical noreply identity + the `identity-guard` hook installed at creation, so it can never drift into the `@affirm` work email). Both never touch `affirm/`; the one home skill that may is `/dev-remove-repo`, solely to remove a whole retired checkout (`_ops/POLICY.md` §7).
- **Cross-tool parity — behavioral rules + MCP (added 2026-06-24):** beyond the home context, `install-agent-rules.sh` mirrors Cursor's `alwaysApply` behavioral rules (`terse-output`, `subagent-orchestration`, `worktree-default`) into a **second** hash-stamped managed block (`<!-- BEGIN cursor-rules-mirror … -->`), and every `~/.cursor/rules/*-mcp-safety.mdc` guardrail (`Notion`/`jira`/`slack`/`snowflake`, each gated by its "apply only when using this MCP" description) into a **third** block (`<!-- BEGIN cursor-mcp-safety-mirror … -->`) — both injected into the Codex **and** Claude files in a fixed order below the home-context block and **verify-enforced** (drift fails `make verify`). Separately, `_ops/bin/install-mcp.sh` mirrors shareable MCP servers from `~/.cursor/mcp.json` — **all → Claude** (same `mcpServers` JSON schema; http/sse/stdio), **command/stdio → Codex** (`[mcp_servers.*]` TOML; remote `url` servers skipped, as Codex's client is stdio-first). The MCP mirror is **non-destructive** (adds-only; `MCP_MIRROR_FORCE=1` to overwrite a Claude entry), **backed up** (timestamped `.bak`), idempotent (`--dry-run` previews), and advisory (not in `verify`). Run via `make install-mcp`; both run automatically in `bootstrap.sh`. Mechanism detail: `_ops/POLICY.md` §3b. **Sources of truth:** home rules and MCP guardrails remain version-controlled in `_ops/rules/global/`; reusable rule capabilities live in `capabilities/skills/global/rules/<id>/`. Bootstrap prepares the skills hub first, then the installer symlinks both source sets into `~/.cursor/rules`, prunes retired managed links, and mirrors them, so a fresh clone reproduces the chain without a duplicate rule copy. The MCP **servers** are still read from machine-local `~/.cursor/mcp.json`, which has no committed SOT — the MCP mirror copies it, it does not own it. These per-tool files (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.claude.json`, `~/.codex/config.toml`) live under `~` and are never committed.

The accepted interoperability path adds an explicit bounded Codex operation:
`bash _ops/bin/install-agent-rules.sh --codex-native preview|apply|verify|rollback`.
It projects owner sources into the existing managed blocks, selects native entry
instructions and the qualified skills resolver reference, and preserves all
unmanaged bytes. The preview and exact action digest bind preimages and rollback;
applicable shared-session consequence approval remains separate. Cursor/Claude and
the legacy default bootstrap retain their current behavior. A full legacy install
preserves and verifies native Codex instructions while reconciling Cursor/Claude. See `_ops/POLICY.md` §3a and
the mutable interoperability ledger for actual delivery/activation status; this
bounded path is not INT-021 production rollout or AWA registration.

The personal Codex work-assessment successor is explicitly selected by adding
`--work-source <absolute-accepted-export>` to that bounded entrypoint. It uses
`_ops/interoperability/codex_work_rules.py` and the Dev-owned
`_ops/rules/hosts/codex-work-dispatch.md` caller, preserving the Skills-owned
assessment, policy and lifecycle semantics. It publishes only one new managed
block and does not render the mixed Dev context, worktree/AWA overlay or MCP
mirrors. The current native profile is exactly `collaboration.spawn_agent`, with
explicit model/effort, `fork_turns:none` and bounded caller task fields. Routing
does not authorize delegation or change the parent model.

The initial closed activation registry contains no bindings: preview/apply cannot
activate this route until the accepted Skills source, exact profile/build native
qualification and independent owner review are bound in a governed Dev source
update. Offline fixture tests do not create such evidence. After that binding:

```text
bash _ops/bin/install-agent-rules.sh --codex-native preview --work-source <absolute-private-export> --qualification <private-closed-observation> --host-build <build> --operation-dir <new-private-operation>
bash _ops/bin/install-agent-rules.sh --codex-native apply --operation-dir <same-operation> --approve <exact-preview-action-sha256>
bash _ops/bin/install-agent-rules.sh --codex-native verify --work-source <same-export> --qualification <same-observation> --host-build <build>
bash _ops/bin/install-agent-rules.sh --codex-native rollback --operation-dir <same-operation> --approve <same-action-sha256>
```

Preview retains private preimages and reports shared-session consequences. Apply
rechecks the exact source, implementation, qualified native host and target; a
changed source/profile/build never falls back to legacy qualification. Rollback
preserves later edits and remains available if qualification later becomes stale.
The initial interface deliberately cannot activate any build. Existing managed
legacy routing requires its own transition; a broad legacy installer refuses
before mutation when the personal work profile is selected. Fresh-session
discovery/use, accepted-source delivery and exact activation consent remain
separate gates. See `_ops/POLICY.md` §3a for the export and binding contracts.

### 9c. Bootstrap contract (new machine / refresh)
```
git clone git@github.com:KleinPerkins/dev.git ~/dev && cd ~/dev && bash bootstrap.sh
```
`bootstrap.sh` is idempotent and conservative: it prepares the skills hub, installs and mirrors agent rules, mirrors existing MCP entries, runs the no-argument noninteractive MCP bootstrap (including the pinned snow-kit runtime, without browser SSO or legacy removal), installs the remaining host tooling, then runs verification. Re-running preserves operator config and sibling client entries.

### 9d. Enforcement (local + remote)

Local guards and `make verify-ci` verify source; `make verify` additionally observes
installed host context. The lasting public-cohort delivery path is substantive
sharded GitHub Actions CI, one automatic independent review from the originating
Codex account, and approval/native squash by the qualified Chaos Scheduler App.
There is no human technical-review requirement. The old controller is abandoned;
PAC Mini Actions is planned work with no current delivery role or assumed launch date.
Its repository remains private with no CI. Retire legacy delivery scaffolding before
migration, preserving source, held WIP and historical evidence. New CI, publication
and release design belong to PAC Mini Actions development after migration.

The 13 public targets, six private/no-CI exceptions and retirement disposition are
owned by `_ops/baseline/delivery-policy.json` and `_ops/POLICY.md` §6. Inclusion is
not publication or activation. Sensitive policy/workflow changes use the same
qualified agent-review/check path. Initial seed admission and external settings
retain their exact administrative gates. See `docs/github-delivery.md`.

### 9e. Relationship to cpp
`KleinPerkins/dev` does **not** govern cpp (`affirm/src/card-platform-product`), which runs its own heavier `_ops/` model (deterministic integrity engine, bot, branch protection). This home layer only *references* cpp and points agents at it. As always, **never write under `affirm/`** from the home layer — the sanctioned exceptions are the ecosystem orchestrator's governed PR into cpp (§10) and, narrowly, whole-checkout removal of a retired clone by `/dev-remove-repo` after a preflight proves nothing is writing there (`_ops/POLICY.md` §7). cpp itself is never removed from here, and detaching it from a removed checkout stays a governed PR in cpp.

---

## 10. The ecosystem operating model (reorg-v2)

**Added 2026-06-26.** The "reorg-v2" initiative turned the ad-hoc skill/MCP sharing into a small, tested, self-managing **ecosystem operating model**: every reusable capability is *designated* (global vs local), *installed* the same way, *kept in sync* by an engine, and — for the global ones consumed by the cpp team — *vendored into cpp* through a single governed edge. This section is the 360° end-state (what / how / why / where / when). The build/decision provenance is the historical dossier at `_ops/reorg-v2/` (§10g).

### 10a. The model in one breath (WHAT / WHY)
Four "stuffs": **ld-stuff** (this home operating model), **global-stuff** (capabilities useful everywhere — the `KleinPerkins/skills` + `kp-mcp` masters), **cpp-stuff** (what the Affirm cpp team consumes), and **orchestrator-stuff** (the single wiring between them). Two invariants make it safe:
- **INV-master + consistency** — one **master** copy is canonical. On LD's machine, locally-consumed capabilities are **symlinks** into the master (no second real copy). The cpp-team payload is the one deliberate exception: it is a **REAL second copy** vendored into cpp (teammates have no access to the private masters), so the strict single-physical-copy rule (the old "INV-single-master") is **intentionally relaxed to two real copies** — reconciled by a **sync-time master↔payload CONSISTENCY VERIFY** that asserts the shared content is byte-identical (Decision A, 2026-06-26; supersedes the abandoned symlink-dedup — §10e).
- **INV-zero-link** — a **global** artifact must contain **zero** cpp references, and a **cpp** payload must contain **zero** ld references. The only place the ld↔cpp relationship is allowed to exist is the orchestrator repo. This keeps the private personal masters and the Affirm repo cleanly separable. The gate scans **ALL managed roots** (skills/global, skills/local, kp-mcp), **case-insensitively** (Decision C).

### 10b. Designation: the directory paradigm + the manifest contract (HOW)
Scope is the **containing directory**, not a flag: a capability under `…/global/` is global; under `…/local/` is local. Each capability carries a flat (dependency-free) **`meta.yml`** (schema `kp-capability/v1`) paired with an idempotent **`install.sh`**:
```
id · kind(skill|mcp|rule|tool|sub-agent|plugin) · flavor(1|2) · scope(global|local) · owner ·
install: install.sh · post_mgmt(none|…) · provenance_* (flavor-2 only)
```
- **Flavor 1** = homegrown master (e.g. `prompt-architect`); `install.sh` symlinks the master into `~/.cursor /.claude /.codex`.
- **Flavor 2** = a source-tracked pointer (clone/pull a provenance source, or govern an externally delivered runtime, then expose/activate). A **`kind: tool`** Flavor-2 shelf further declares `sync_policy`: `record-only` (a pure descriptor that installs nothing) or **`standalone-release`** (a **Global Capability Binding** that clones a **Standalone System Package** at its pin and delegates to the release's own installer — see §10i, `_ops/eco/MANIFEST-CONTRACT.md`, and `_ops/eco/STANDALONE-SYSTEM-PARADIGM.md`; `global/tools/awa` is the worked example).
Tooling: `_ops/eco/manifest.sh` (`validate|scope|plan|scaffold|scaffold-standalone-tool`), `_ops/eco/verify-manifests.sh` (schema gate over all managed roots), and the shared `_ops/eco/lib.sh`. Managed roots: `capabilities/skills/global`, `capabilities/skills/local`, `capabilities/mcp`. Local plugin governors are lock/doctor/install governed locally but are not WF1 registry enrollments.

### 10c. Install + bootstrap (HOW / WHEN)
- `capabilities/bootstrap.sh` does a **manifest-driven pass** on top of the Model-A relink for BOTH `capabilities/skills/global/` and `capabilities/skills/local/` (per-tool symlink exposure is scope-independent; only orchestrator → cpp vendoring eligibility differs). It runs each artifact's `install.sh` for Flavor-2 / `post_mgmt != none` cases; for `kind: plugin`, install/reconcile call `install.sh --apply`, doctor calls `install.sh --doctor`, and repair calls `install.sh --repair`.
- `capabilities/mcp-bootstrap.sh` keeps the development workspace reproducible and owns the LD-host snow-kit lifecycle. Snow-kit resolves the tracked tag+full-SHA pin, stages a non-editable locked install under `~/.local/share/kp-mcp/snow-kit/releases/<sha>/repo`, runs offline checks, atomically promotes `~/.local/bin/snow-kit`, and reconciles Cursor/Codex/Claude to `mcp --read-only`. `--activate` performs external-browser SSO plus live safe-read checks before promotion and only then removes legacy global `snowflake` entries. Rollback/uninstall preserve the mode-0600 local profile and Snowflake secure authentication cache.
- `.gitignore` allow-list re-includes the tracked bootstrap and immutable `mcp-pins.env`, keeping operator values, `affirm/`, `personal/`, and nested repos ignored.

### 10d. Sync, self-heal, clean-room (HOW)
- **`_ops/eco/sync.sh <repair|replace|rebuild>`** mirrors a source into a bootstrap-managed root. `repair` is additive-only; `replace` backs up **out-of-tree** then overwrites drifted entries; `rebuild` additionally **deletes** undeclared in-scope files — guarded by `--confirm` **and** a `.eco-managed` sentinel so a shared dir can never be nuked. (`make eco-sync`.)
- **`_ops/eco/self-heal.sh`** runs the verifier set (operating-model `--ci`, manifests, **zero-link across all managed roots**, master↔payload consistency); on failure it applies idempotent heals (regen `.mdc`, relink/re-surface skills) and retries up to **N=3**, then surfaces what's still red. (`make eco-selfheal`.)
- **`_ops/eco/clean-room.sh`** is the reproducibility gate: local `--no-hardlinks` clones of dev+skills into a tmpdir under an **isolated `$HOME`**, runs a Flavor-1 `install.sh`, asserts the per-tool symlink, then runs the repo-only gates — proving a fresh checkout reaches green without touching the real environment. (`make eco-cleanroom`.)

### 10e. The orchestrator — the single ld↔cpp edge (WHAT / HOW / WHERE)
A standalone **PRIVATE** repo **`KleinPerkins/ecosystem-orchestrator`** (`~/dev/personal/ecosystem-orchestrator`, born-compliant: SSH origin, LOCAL noreply identity, identity-guard hook). It is the **only** place the relationship is defined (`config/relationship.yml`) and the only sanctioned writer of the cpp edge:
- **`vendor <id>`** builds a self-sufficient, **ld-agnostic** copy of a global capability, places it under the correct cpp quiver **category** (kind→category; e.g. `skill`→`quiver/skills/<id>`, `mcp`→`quiver/mcp/<id>`), **translates** the `kp-capability/v1` meta into cpp's closed quiver `meta.schema.json`, asserts **zero-link (cpp)**, guards the control plane (only `quiver/<cat>/<id>` may be staged — never `_ops/`,`.github/`; relies on cpp's **wildcard** `/quiver/` ownership so no CODEOWNERS/ownership regen is needed), commits with cpp's recorded LD identity, and **gates on cpp's real integrity engine** (`cpp-integrity-engine check --ci`). With `--execute` it pushes + opens an **LD-authored PR** and enables **GitHub NATIVE auto-merge** (`gh pr merge --auto --squash`) — the merge then waits for **cpp's OWN required server checks + the `@affirm-cpp-bot` CODEOWNER auto-approval** (Decision B, 2026-06-26: **no human reviewer, no `--admin` bypass** on the routine path). `--admin` force-merge is **BREAK-GLASS ONLY**, behind `--break-glass-admin` / `ORCH_VENDOR_BREAKGLASS_ADMIN=1`. **Master resolution:** skills resolve under `source_skills_global` (`~/dev/capabilities/skills/global/<id>`); **`kind: mcp` capabilities resolve under `source_mcp_local`** (`~/dev/capabilities/mcp/<id>`, the kp-mcp monorepo root). **mcp descriptor mode (2026-06-26):** for `kind: mcp` masters the orchestrator vendors a SOURCE-FREE, ld-agnostic **discoverability descriptor** (a generated `README.md` + `VENDORED.md` + translated `meta.yml`) rather than the source tree — an MCP server's source carries forbidden-ld tokens (e.g. `kp-mcp` workspace deps) and its launch command lives per-operator in `~/.cursor /.codex /.claude` MCP configs anyway. *Governance verified (read-only): `/quiver/ @KleinPerkins @affirm-cpp-bot` in cpp CODEOWNERS (bot approval counts), repo `allow_auto_merge`+`allow_squash_merge` on, branch protection requires 1 CODEOWNER review + the cpp-* checks — no governance change needed.*
- **`delete <id>`** propagates a master removal the same governed way.
- **`consistency [<id>]`** is the **Decision A** compensating control (replaces the abandoned symlink-dedup). cpp keeps a **REAL vendored copy** (same bytes teammates clone); `consistency` recomputes the expected payload from the master and asserts it matches cpp's vendored copy, flagging content **drift**, an **orphan** payload file, or a **legacy armed symlink**. **Kind-aware:** for `kind: skill` (and other source-bearing kinds) it does the master↔payload **byte comparison**; for `kind: mcp` it asserts **descriptor shape** instead (required `README.md` + `VENDORED.md` + `meta.yml` present, no unexpected source files in the cpp payload). Read-only by default; on drift the sync modes resync (repair = warn/log; replace/rebuild = re-vendor). Exposed as `make eco-consistency`. *(History: the live single-master **symlink-dedup was ABANDONED 2026-06-26** — it was unsafe because routine cpp git ops write THROUGH the symlink into the global SOT, and semantically wrong because master (a self-managed skill) ≠ payload (an ld-agnostic copy). `dedup.sh` now hard-disables `--apply`/`--reassert`; only `--reverse` survives as a one-time un-arm utility nothing auto-calls.)*
- **`doctor` / `zero-link`** are the read-only health + forensic checks (`zero-link --all-roots` scans every managed root, case-insensitively — Decision C); `forbidden-cpp.txt` / `forbidden-ld.txt` are the token definitions.
- **Credential model:** the laptop is the PR author/committer (holds creds + identity). GitHub Actions are **signals/validation only** and never hold secrets.

### 10f. Triggers + self-management (WHEN)
- **`orchestrator install`** wires a Cursor **`sessionStart`** user hook (safe `~/.cursor/hooks.json` merge, backup-first, idempotent — existing hooks preserved) and a **launchd** agent (`com.kleinperkins.orchestrator`, RunAtLoad + every 6h). Both call the FAIL-OPEN `bin/session-hook.sh`: sessionStart is instant + network-free; the launchd `--periodic` run does doctor + self-heal + a **DRY-RUN** sync (it **never** auto-merges to cpp).
- **`orchestrator cpp-sync`** (renamed from `sync`, 2026-06-28) reconciles every **enrolled** id (`config/registry.yml`, state `enrolled`) into cpp (DRY-RUN by default, idempotent no-op when already on `main`; `--execute` lands PRs). Enrollment is now the registry, not `managed-items.txt` — see §10h.
- **Push-side backstop:** `KleinPerkins/skills/.github/workflows/verify-capabilities.yml` runs a self-contained verifier (manifest contract + zero-link over `global/`) on every push/PR.
- **Regression:** `_ops/eco/regression-suite.sh` (`make eco-regression`) is the full-coverage gate (manifests/flavor, zero-link all-roots, all 3 sync modes, vendor add/delete + zero-link abort, master↔payload consistency, trigger firing incl. the symlink-invocation path, self-heal, clean-room). A hermetic subset (`ECO_RS_HERMETIC_ONLY=1`) runs in CI; the full suite + clean-room run locally. `make eco-verify` runs the verifiers.

### 10g. Provenance (the dossier) + the canonical first sync
The reorg-v2 **dossier** (`_ops/reorg-v2/`: requirements → inventory → gap analysis → decisions → migration plan → execution log) is the point-in-time build record. It is **tracked** in `KleinPerkins/dev` as a **historical record**; this §10 is the living end-state SOT — when they disagree, §10 wins. The **canonical first sync** (`prompt-architect`) was vendored live: **`Affirm/card-platform-product` PR #68, merged** (squash `9dd9bad`) → `quiver/skills/prompt-architect/`. This **resolves** the §8 "cpp / Affirm-team mirror" deferral: option (a) (a vendored copy kept in sync by a script) is now implemented as the orchestrator. The **second** managed sync — **`google-kit`, the first `kind: mcp` capability** vendored as an ld-agnostic discoverability descriptor — landed as **`Affirm/card-platform-product` PR #73 (merged 2026-06-26)** → `quiver/mcp/google-kit/`, replacing an earlier hand-authored LINK stub that itself violated INV-zero-link.

### 10h. Capability-lifecycle paradigm — WF1 registration + WF2 governed cpp-sync (canonical)

**Added 2026-06-28.** This is the canonical statement of the capability lifecycle and the boundaries between the three planes. It supersedes the earlier ad-hoc surface: `config/managed-items.txt` → **`config/registry.yml`** (`schema: eco-registry/v1`, the sole enrollment SoT); `orchestrator sync` → **`orchestrator cpp-sync`**; and it adds the data-plane **manifest** + the cpp-owned **reconciler**. Two contained workflows with a hard boundary — a registration change never auto-triggers a sync.

**Boundaries & ownership (three planes, three owners; each boundary is a one-way contract):**

| Plane | Owner / writer | Source of truth | Crosses the boundary via |
| --- | --- | --- | --- |
| Global capabilities (`KleinPerkins/skills` `global/{skills,rules,sub-agents,tools}/*`, `kp-mcp` `*-kit`) | author (LD) | `meta.yml` = per-capability config **and the sole exposure SoT** (the `expose:` field); `meta.kind` must match the shelf | n/a (upstream of everything) |
| Eco orchestrator (`personal/ecosystem-orchestrator`) | LD | `registry.yml` (**sole enrollment SoT**) + the ld↔cpp relationship | governed quiver PR, auto-merge on green = the ONLY sanctioned writer of the cpp edge |
| cpp **data** plane (`quiver/*` payloads + `quiver/tooling/eco-capability-sync/eco-capability-manifest.yml`) | orchestrator (vendored copy + generated manifest) | upstream master; the cpp copy is a byte-equal projection (INV-master); the manifest is consistency-excluded data | orchestrator `vendor` / `vendor --delete` + manifest regen only |
| cpp **control** plane (`_ops/`, `.github/`, incl. the cpp-owned reconciler + bootstrap hook) | cpp (its own governance) | cpp | cpp-governed PR only — never the orchestrator |

**Compact artifact ownership matrix (live SoT vs projection vs intentional non-owner):**

| Artifact | Owner / normal writer | Role | Enforcement / non-owner boundary |
| --- | --- | --- | --- |
| Capability `meta.yml` + `install.sh` | capability repo author (LD today) | per-capability config; `meta.yml.expose` is the sole exposure SoT | schema/kind/scope checks in capability verifiers; cpp never edits upstream masters |
| `config/registry.yml` | orchestrator | sole enrollment SoT (`enrolled|excluded|demoted`) | mutated only by `enroll|exclude|demote`; registration never auto-runs WF2 |
| `.eco-registry.lock` | capability repo, generated by vendored `eco-lock.sh` | normalized metadata lock over committed `meta.yml` | local explicit checks + CI parity; not an enrollment source and not payload integrity |
| Eco-lock master + vendored copies | orchestrator master; capability repos carry vendored copies | single normalizer lineage (`templates/eco-lock/eco-lock.sh` → `.github/scripts/eco-lock.sh`) | `lockkit check|write|diff`; guards/CI invoke the vendored copy and do not fork the algorithm |
| `registration-guard` | source in `~/dev`; installed copies in eligible repos | advisory commit-time lock regeneration | self-disables without a lock+writer, always exits 0, and delegates only to `bash .github/scripts/eco-lock.sh write` |
| `enabled_kinds` | orchestrator relationship config | explicit WF2 rollout switch by kind | new kinds stay off until cpp-owned reconciler support is green and merged |
| cpp `quiver/<cat>/<id>` payloads | orchestrator via governed cpp PR | cpp data-plane projection of enrolled global capabilities | no hand-vendoring; consistency verifies source-bearing payloads, descriptor-shape verifies MCP payloads |
| cpp `eco-capability-manifest.yml` | orchestrator via governed cpp PR | atomic data-plane manifest and sole prune authority (`owned_ids`) | generated after payload sync; consistency-excluded and not manually edited |
| cpp reconciler + bootstrap hook | cpp control plane | PM-laptop install/repair/prune mechanics | cpp-governed only; orchestrator never writes `_ops/` or `.github/` |

**WF1 — registration + right-sized enforcement (in the orchestrator + capability repos):**
- `registry.yml` records minimal `{ id, state(enrolled|excluded|demoted), reason }`. Verbs `enroll | exclude | demote | status` (`bin/orchestrator.sh`) mutate it; `cpp-sync` reads it.
- **Exposure** is `meta.yml`'s `expose:` field (subset of `cursor claude codex`; absent ⇒ all three). `capabilities/skills/bootstrap.sh` links per `expose:`; `verify-skills.sh` validates it.
- **Lockkit** is the single metadata-lock normalizer lineage:
  `personal/ecosystem-orchestrator/templates/eco-lock/eco-lock.sh` is the master,
  `orchestrator lockkit check|write|diff` propagates vendored copies, and
  `make eco-lockkit-*` delegates from `~/dev`. It locks normalized `meta.yml` fields, not payload bytes.
- Orchestrator `reconcile` treats only `scope=global` lock rows as satisfying registry enrollment. Local rows, including `kind: plugin`, are valid CI inventory but can never satisfy a mistaken global enrollment with the same id.
- Enforcement is **honest about its strength**: explicit local checks + CI workflow parity are the gate of record; GitHub branch protection is unavailable for the private capability repos on the current account plan unless that changes. The pre-commit `registration-guard` = **advisory** fast-feedback (self-disables without a lock); the **orchestrator-side `reconcile`** = the **authority** (only it sees both `registry.yml` and a repo's committed lock). Passive checks (`doctor`, the launchd periodic run) are **fail-open** and surface drift + the WF2 auto-merge preconditions (gh login, cpp allow-auto-merge).

**WF2 — independent sync to cpp (governed, async auto-merge):**
- `cpp-sync` is **registry-driven**: a **preflight** first runs WF1 lockkit/reconcile checks, then gates every id on kind ∈ `enabled_kinds`; translated kind ∈ cpp's live enum and kind==shelf(category); zero-link clean; local cpp-integrity GREEN; flavor-2 `approved_digest` matching the current shared-content digest. A non-empty block set aborts before any push, so mixed approved/blocked sets cannot partially open payload PRs.
- `approve <id>` computes the current shared-content digest and pins `approved_digest` for flavor-2 supply-chain sync. `status --matrix [--json]` reports registry, lock, approval, cpp payload/manifest, open PR, journal, and next action state. `repair` refreshes only journal fields derivable from observed cpp `main`; the journal is a cache, not authority.
- After the per-id payload PRs, `cpp-sync` regenerates **one atomic** manifest PR: `quiver/tooling/eco-capability-sync/eco-capability-manifest.yml` (`eco-manifest/v1`, meta-less, consistency-excluded). It is the **sole prune authority** (`owned_ids`). `cpp-sync --execute` opens async auto-merge PRs; `last_synced_cpp_sha` is updated only after the payload is observed on cpp `main`, never merely because a PR was opened.
- Recovery stays governed: `rollback <id>` restores `quiver/<cat>/<id>` from a trusted `last_synced_cpp_sha` through a normal data-plane PR, and `quarantine <id> -- <reason>` closes in-flight orchestrator PRs, marks the id excluded, delete-propagates any landed payload, and regenerates the manifest without it.
- The cpp-owned **reconciler** (`_ops/bin/eco-capability-reconcile.sh`, authored under cpp governance) reads the manifest on PM laptops and installs/repairs/prunes native links per `expose:` using a table-driven routing contract: `skill` directory links to all tools, `mcp` record-only, `sub-agent` `<id>.md` links to all agent homes, `rule` `<id>.mdc` links to Cursor only, and `tool` record-only. It independently refuses to prune any cpp-owned shelf. Wired into `cpp-bootstrap.sh` so `/cpp-bootstrap` + `/cpp-sync` both reconcile. See cpp `_ops/runbooks/eco-capability-sync.md`.

**The 4-way state model (which check covers each seam, at what strength):**

| Seam | Artifacts | Check | Strength |
| --- | --- | --- | --- |
| author → registry | `meta.yml` → `registry.yml` | orchestrator enrollment-drift (periodic + `doctor`) | detective, fail-open |
| registry → lock | `registry.yml` → `.eco-registry.lock` | local explicit checks + CI parity workflow (branch-protected only where GitHub supports it) + pre-commit guard (advisory) + orchestrator `reconcile` (authority) | preventive / advisory / authoritative |
| registry → cpp payload | `registry.yml` → `quiver/<cat>/<id>` | `cpp-sync` preflight (zero-link + cpp-integrity + flavor-2 approval) + `consistency` (master↔payload byte-equality) | preventive + detective |
| manifest → laptop | `eco-capability-manifest.yml` → native links / record-only logs | cpp-owned reconciler (defense-in-depth: never prunes cpp-owned shelves) | preventive (cpp-side) |

`enabled_kinds` remains the explicit rollout switch in `personal/ecosystem-orchestrator/config/relationship.yml`. The cpp reconciler has native routing for `rule`, `sub-agent`, and `tool`; the orchestrator must flip those kinds on only after the cpp-governed reconciler PR is green and merged.

### 10i. Standalone System Package + Global Capability Binding (SSP + GCB)

**Added 2026-07-05.** Some capabilities outgrow a single shelf master and become **products** (a generic runtime + a frozen behavioral contract). The **Standalone-System paradigm** ships such a capability as three roles with one-way contracts — canonicalised in `_ops/eco/STANDALONE-SYSTEM-PARADIGM.md`:
- **SSP (Standalone System Package)** — the product lives in its **own repo** and installs itself from a fresh clone via its own `install.sh` (`install|--repair|--doctor|--check|--uninstall`), XDG layout, idempotent + backup-before-write, **zero-link** runtime, shipping its own frozen contract + freeze checker (behavior-only; location resolved by role). No sibling-repo dependency.
- **GCB (Global Capability Binding)** — a Flavor-2 `global/tools/<id>/` shelf (`shape: release-descriptor`, `sync_policy: standalone-release`) whose `install.sh` clones the SSP at `provenance_ref` and **delegates** to the checkout's own installer, carrying only the pinned pointer (`<id>-gcb-pointer/v1`, never the runtime bytes). WF1-enrolled like any capability; `manifest.sh` treats `standalone-release` as first-class and exempts it from the record-only "no fetch/exec" gate.
- **Host overlay** — the consuming host keeps only policy literals (`_ops/policy/*.yml`, including the tool-owned source-tracked modes file) + thin delegators to the installed SSP + a dashboard pointer, installed by an overlay installer that delegates to the GCB `--repair`. No duplicated runtime, no contract copy.

**AWA is the worked example** — canonical SSP/GCB/overlay doctrine lives in the owning repo; see
the cross-repo authority pointer at the end of this manual. §11 covers **~/dev host operations only**.

---

## 11. Agent Worktree Automation (AWA) — ~/dev host binding

**Added 2026-07-04.** AWA keeps agent work off your **primary checkout** and inside an isolated
**Safe Workspace** (a git *linked worktree*) — the concrete implementation of §9's "one writer per
working tree" rule. End-state planning: `_ops/plans/agent-worktree-automation-end-state-v3.md`.

**Canonical product authority** (SSP location, GCB binding, kernel/engine/security model, frozen
contract) is **not duplicated here** — defer to the cross-repo authority pointer at the end of this
manual.

**What ~/dev owns (host binding only):**
- **Policy literals** — `_ops/policy/worktree-policy.yml` (org include/exclude globs) and
  `_ops/policy/worktree-modes.yml` (per-repo on/off; PMs never hand-edit — use `dev-worktree.sh mode …`
  or `awa_mode_*` MCP tools).
- **Stable-path delegators** (each passes host policy to the installed runtime):
  `_ops/bin/dev-worktree.sh` (`status|ensure|list|clean|doctor|policy-check|dashboard-data|mode`;
  `clean` is bundle-or-refuse), `_ops/cursor-hooks/{worktree-guard,worktree-session}.sh`,
  `_ops/checks/awa-contract-freeze.sh`, `_ops/bin/install-dev-awa-overlay.sh`, and dashboard pointer
  `_ops/dashboards/awa-dashboard.canvas.tsx` (refresh via `make worktree-dashboard`).
- **PM-facing copy gate** — `_ops/awa/copy/operator-copy.json` checked by
  `_ops/checks/copy-honesty-check.sh` (dev-local only).
- Delegators **degrade-to-allow** when the pinned release is not installed.

### 11g. How a PM uses AWA (never edit the infrastructure directly)
A non-technical PM never edits AWA's policy, hooks, engine, dashboard, or the per-repo modes file by
hand. Agents/automation do all of that. In practice: start agent work in a Safe Workspace via the
Agents-Window Worktree dropdown (AWA adopts it); let the shell gate nudge you off the primary
checkout; watch state in the canvas (`make worktree-dashboard`); and when work is ready, use the
apply-back preview and the governed PR path. To change how AWA treats a repo, ask in plain language
(or run `dev-worktree.sh mode set <repo> on|off`) — the agent edits `worktree-modes.yml`
through the `mode` verbs / `awa_mode_*` MCP tools and commits the source-tracked diff; the file is
never hand-edited. Everything is driven through the CLI/engine and the dashboard — the operating
infrastructure itself is changed only through this repo's reviewed `_ops/` flow.

### 11h. Verify + remaining operator/live steps
Local gates (all must exit 0): `make awa-engine-verify`, `make worktree-verify`, `make verify-ci`
(repo invariants + `.mdc`↔SOT sync). Full engine/security UATs run in the owning repo's CI.
Still requiring a live surface (documented, not shipped): hook-probe empirical runs (Desktop +
cloud agent), `move_agent_to_root` relocation, MCP registration, and live apply-back push/PR.
Install/repair the host binding: `_ops/bin/install-dev-awa-overlay.sh`.

---

## 12. Uniform repo control baseline (repo-baseline)

The baseline preserves a small shared local-file floor and local identity/guard
requirements. The repository-owned CI/App policy can exceed that floor. No baseline
command may erase required review/checks, weaken protections, or restore retired
controller requirements. See [_ops/baseline/README.md](_ops/baseline/README.md).

New scaffolds preserve the sharding requirement and report pending delivery until
real coverage, same-origin review and App qualification exist. Private/no-CI
exceptions remain unenrolled. Repository names are discovery hints; settings changes
must verify immutable IDs. The frozen native-delivery ADRs remain provenance for
the first product implementations; the accepted wider cohort now owns current scope.

The future `repo-platform` capability is a bounded post-migration effort. This Dev
replacement repairs current policy and delivery prerequisites without implementing
that larger framework or restarting paused product work.

<!-- doc-warden:cross-repo-authority:awa-dev-overlay:begin -->
## Cross-repo authority pointer — awa-dev-overlay

**Canonical owner:** [`KleinPerkins/awa`](https://github.com/KleinPerkins/awa) — `docs/adr/0002-awa-dev-overlay.md`

This section is a **pointer only**. Canonical prose for this authority boundary lives in the
owning repository above. Do not duplicate governed statements here; link and defer.

**Profile:** poc3d · **Topic:** ssp-product-location,host-overlay-role,kernel-first-invariant,no-duplicated-contract,operator-copy-honesty,host-policy-literals · **Recorded:** 2026-08-06

<!-- doc-warden:cross-repo-authority:awa-dev-overlay:end -->

<!-- doc-warden:cross-repo-authority:awa-integrity:begin -->
## Cross-repo authority pointer — awa-integrity

**Canonical owner:** [`KleinPerkins/awa`](https://github.com/KleinPerkins/awa) — `docs/adr/0020-awa-integrity-surveillance-and-lifecycle.md`

This section is a **pointer only**. Canonical prose for this authority boundary lives in the
owning repository above. Do not duplicate governed statements here; link and defer.

**Profile:** awa-integrity · **Topic:** integrity-sot,integrity-invariants,runnerless-surveillance,host-trigger-wiring,safe-workspace-entry,operator-interface · **Recorded:** 2026-08-24

<!-- doc-warden:cross-repo-authority:awa-integrity:end -->
