# Ecosystem manifest contract (`meta.yml` + `install.sh`) — reorg-v2 WS-1

> The machine-readable designation surface for the global-vs-local directory paradigm (D-2/D-3/D-10).
> Bootstrap (WS-2), sync (WS-3), self-heal (WS-4), and the orchestrator (WS-6/7) all read these.

## The scope paradigm (D-2/D-3, refined 2026-06-26)

Scope is decided by **structure**, not by an unenforced per-file flag. Two paths are sanctioned:

1. **Directory paradigm (eco-owned roots).** For roots whose layout this operating model defines —
   today `capabilities/skills/{global,local}/` — scope is decided by the **containing directory**:
   - An artifact under a **`global/`** subtree is **global** (shared into cpp via the orchestrator).
   - An artifact under a sibling **`local/`** subtree is **local** (stays in its own workspace).

2. **Gated explicit flag (sibling-repo roots).** For roots whose layout we do **not** dictate because
   the repo is independently-governed (today `capabilities/mcp` = `KleinPerkins/kp-mcp`, a uv-workspace
   monorepo; same doctrine as cpp) — the artifact is flat at the repo root and `meta.yml` declares
   `scope:` explicitly. This is **not** an unenforced sticky-note: `_ops/eco/manifest.sh` hard-gates
   any such artifact to **`scope: global`** for `kind: mcp` (no `mcp/local` partition exists today),
   and the orchestrator (`vendor.sh` / `consistency.sh`) refuses any non-global master as defense in
   depth.

The operator works at the structurally-correct location; the agent infers + performs the correct
local + remote plumbing via `_ops/eco/manifest.sh plan <dir>` (no repo moves — markers inside
existing repos, D-3).

## `meta.yml` (schema `kp-capability/v1`) — FLAT keys (no nesting, dependency-free parsing)

```yaml
schema: kp-capability/v1
id: <artifact-id>            # unique within its kind
kind: skill                  # skill | mcp | rule | tool | workflow | sub-agent | asset | doc
flavor: 1                    # 1 = homegrown line-for-line | 2 = source-tracked pointer
scope: global                # global | local
                             #   - dir paradigm: MUST match the containing global/local dir
                             #   - gated-flag (kind:mcp under capabilities/mcp/): MUST be 'global'
owner: KleinPerkins
install: install.sh          # the paired install contract (executable, idempotent)
post_mgmt: none              # none | launchd | cron | systemd  (Flavor-2 scheduled jobs; DD-3)
# tool-kind only — see "Flavor-2 tools" below:
shape: descriptor-only       # snapshot | release-descriptor | descriptor-only
sync_policy: record-only     # none | record-only | standalone-release
expose: cursor claude codex  # optional exposure subset (absent ⇒ all three)
# provenance_* REQUIRED when flavor: 2 (Flavor-2 pointer), else may be empty:
provenance_source: ""        # e.g. github.com/owner/repo
provenance_ref: ""           # tag/sha/branch pinned
provenance_trust: ""         # vetted | community | …
```

## Flavor-2 tools: `record-only` vs `standalone-release` (split 2026-07-05)

A `kind: tool` shelf carries two extra flat keys, `shape` and `sync_policy`, that split Flavor-2
into two first-class shapes. The distinction is enforced by `_ops/eco/manifest.sh validate`:

| `sync_policy` | What the shelf is | What its `install.sh` may do | `manifest.sh` gate |
|---------------|-------------------|------------------------------|--------------------|
| `none` \| `record-only` | A **descriptor** that records a pin/metadata and installs **no runtime bytes** (Flavor-1 snapshots use `none`). | **Nothing executable** — no `bin/`, no `curl`/`wget`, no `PATH=`, no `chmod +x`, no `exec`. | prohibition enforced on `record-only` |
| `standalone-release` | A **Global Capability Binding (GCB)** to a **Standalone System Package (SSP)** — a self-contained product that lives in its own repo and installs itself. | **Clone the pinned release** (`provenance_source @ provenance_ref`) into a per-user checkout, then **delegate to the release's own `install.sh`**. It carries the pinned pointer, **never the runtime bytes**. | requires `install.sh` + `provenance_source`; the record-only prohibition is **not** applied (fetch + delegate is its contract) |

- `shape` describes the payload: `snapshot` carries bytes in-repo (Flavor-1); `release-descriptor`
  points at a pinned external release (the GCB shape, paired with `standalone-release`);
  `descriptor-only` records metadata alone.
- **Rule of thumb:** if the shelf installs a whole product from its own repo at a pin, it is a
  `standalone-release` GCB — see `STANDALONE-SYSTEM-PARADIGM.md`. `global/tools/awa` is the worked
  example. Scaffold one with `manifest.sh scaffold-standalone-tool <id> --source <repo> --ref <sha>`.

## `install.sh` contract

Every artifact ships an executable `install.sh` that is **idempotent** and installs the artifact
locally (Flavor 1 = symlink the master into the tool dirs; Flavor 2 = clone/pull the pointer + install
post-management; a `standalone-release` GCB clones the pinned release then hands off to the release's
OWN `install.sh`). `agent-route/install.sh` is the reference Flavor-1 implementation;
`global/tools/awa/install.sh` is the reference `standalone-release` GCB.

## Validation

`_ops/eco/verify-manifests.sh` asserts, for every artifact under a managed root: schema is
`kp-capability/v1`; `id` non-empty; `kind` ∈ {skill,mcp,rule,tool,workflow,sub-agent,asset,doc};
`flavor` ∈ {1,2}; `scope` ∈ {global,local}; the scope paradigm is enforced — under an eco-owned dir
paradigm the manifest's scope **MUST match the containing directory**, and under a sibling-repo flat
root `kind: mcp` is **hard-gated to `scope: global`**; `install.sh` present + executable; and (Flavor
2) `provenance_source` non-empty. For `kind: tool` it additionally checks `shape` ∈
{snapshot,release-descriptor,descriptor-only} and `sync_policy` ∈
{none,record-only,standalone-release}: a `record-only` tool must carry no `bin/` and no executable
install claims, while a `standalone-release` GCB is exempt (it must, conversely, carry an `install.sh`
+ `provenance_source`). Wired into `make eco-verify` and the Phase-4 regression suite.

## Managed roots (sync scope, D-12)

`capabilities/skills/global`, `capabilities/skills/local`, `capabilities/mcp`. "In-scope" for a sync =
files under a root **not** listed in an artifact manifest / allow-list.
