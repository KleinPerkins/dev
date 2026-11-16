# Context Efficiency D-01 - Capability-discovery inventory

**Version:** v1
**Status:** ACCEPTED
**Date:** 2026-08-20
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Owner:** Laurence Duggan
**Plan-type:** standard
**Parent authority:** [`context-efficiency-program-v2.md`](context-efficiency-program-v2.md) Release 1.1 / D-01
**Prerequisite evidence:** E-01/E-02/E-03 must be verified merged on owner `main` branches at implementation start, including the E-03 `skill-description-inventory.py` normalization implementation in `SKILLS_ROOT`; E-09 denominator frozen on Dev `main`; accepted S-04 Release 1 evidence plan must be resolved from protected Dev `origin/main`, and its canonical artifact path used to set `RELEASE1_EVIDENCE_PATH`.

This plan is ACCEPTED; its Dev-owned Release 1.1 capability-discovery inventory is implemented, merged ([PR #289](https://github.com/KleinPerkins/dev/pull/289)), and `PASS`-evidenced in `_ops/evidence/context-efficiency/capability-discovery-inventory-v1.json`.

**Changelog**
- v1 (2026-08-20) - Establish the narrow D-01 plan for inventorying the actual installed and client-discovered capability catalog before D-02/D-03 reductions.

## 1. Goal

Inventory the actual capability-discovery surface by client and root so Release 1.1 can reduce only the descriptions that are truly exposed and owner-authorized.

Success means D-01 produces one content-safe evidence artifact that lists every observed capability row with a stable ID, client, root/scope, owner source repository, exposure class, installed path and digest, normalized description character/word counts, and reduction eligibility. Source-file counts alone are not sufficient.

## 2. Exact Scope

Authorized later D-01 implementation output:

| Artifact | Purpose |
|---|---|
| `_ops/evidence/context-efficiency/capability-discovery-inventory-v1.json` | Content-safe inventory evidence consumed by D-02, D-03, and D-04. |

Authorized read-only discovery roots:

| Client | Required? | Root / scope | Classification requirement |
|---|---|---|---|
| Cursor | Required | `~/.cursor/rules/*.mdc` | Distinguish always-applied full rule injection from requestable rule description exposure and installed-only files. |
| Cursor | Conditional injected | Home `~/AGENTS.md` when present in the live always-applied session context | Root scope `cursor-home-agents-context`; full-context home/user injection; inventory as `cursor-home-full-context` / `ineligible-full-context-rule` with owner `KleinPerkins/skills` per protected E-09 `generated-home-agents` attribution, not a description-reduction target. |
| Cursor | Optional conditional | Dev checkout `.cursor/rules/*.mdc` when present | Workspace-scoped rule discovery; distinguish full injection, requestable description exposure, and installed-only files. |
| Cursor | Conditional injected | Dev checkout `AGENTS.md` when present in the live always-applied session context | Root scope `dev-workspace-agents-context`; full-context workspace injection; inventory as `cursor-workspace-full-context` / `ineligible-full-context-rule`, not a description-reduction target. Defer targets named by `AGENTS.md` are not separate injected rows unless they also appear as explicit catalog entries. |
| Cursor | Required | `~/.cursor/skills/*/SKILL.md` | User-installed skill descriptors. |
| Cursor | Optional conditional | `~/.cursor/skills-cursor/*/SKILL.md` | Cursor-owned built-in skill descriptors. |
| Cursor | Optional conditional | `~/.cursor/plugins/**/skills/*/SKILL.md` | Plugin-cached skill descriptors; include plugin owner/version path components in the root scope. |
| Cursor | Optional conditional | Global `~/.cursor/hooks.json` and `~/.cursor/hooks/*` | Runtime hook configuration; inventory as `cursor-global-runtime-config` / ineligible runtime config when present; when absent, emit one absent optional root summary row. |
| Cursor | Required | Dev checkout `.cursor/hooks.json` and `.cursor/hooks/*` | Runtime hook configuration; inventory as ineligible runtime config, not a description-reduction target. |
| Claude | Required if Claude scoped | `~/.claude/skills/*/SKILL.md` | User-installed skill descriptors. |
| Claude | Optional if Claude scoped | `~/.claude/plugins/**/skills/*/SKILL.md` | Plugin-cached skill descriptors; include plugin owner/version path components in the root scope. |
| Codex | Required if Codex scoped | `~/.codex/skills/*/SKILL.md` and `~/.codex/skills/.system/*/SKILL.md` | User-installed and system skill descriptors. |

Required roots are conditional on `client_scope`: Cursor requires `~/.cursor/rules`, `~/.cursor/skills`, home `~/AGENTS.md` when injected, Dev checkout `AGENTS.md` when injected, global Cursor hooks when present, and the Dev checkout `.cursor/hooks` surface; Claude requires `~/.claude/skills`; Codex requires `~/.codex/skills`. Optional roots are plugin cache roots, `~/.cursor/skills-cursor`, and the Dev checkout `.cursor/rules` conditional root for included clients only. Every required and optional root for each included client is represented in `roots[]`; when a file root is absent, record `exists: false`, `installed_count: 0`, and `installed_only_count: 0`, while `exposed_count` is the number of canonical catalog entries assigned to that root scope and may be nonzero for injection-only discovery. When an optional plugin cache parent exists, inventory each matching plugin skill root; when it is absent, emit one absent optional parent-root summary row. An unreadable existing required root stops. Missing discovery catalog for any included client stops even when that client's installed root is absent, because injection-only rows can exist without installed files.

`client_scope` is authoritative. Default D-01 scope is Cursor, because Cursor has a distinguishable injected session catalog in the current Dev evidence path. Adding Claude or Codex requires a new explicit operator scope decision that names a concrete client discovery catalog source; installed root scans alone are not enough. A narrower or expanded operator-approved scope removes non-scoped client roots from `roots[]`, forbids non-scoped rows in `rows[]`, omits non-scoped clients from `totals.by_client`, and makes only included-client catalogs mandatory.

Out of scope:

- Editing any installed client file, owner repository, hook, rule, skill, plugin cache, generated memory, or client setting.
- Editing E-09 evidence, Release 1 evidence, or `context-efficiency-program-v2.md`.
- Reducing, rewriting, moving, deduplicating, or changing exposure for any capability.
- Creating a registry, ledger, daemon, service, installer channel, dependency, analytics store, or long-lived crawler.
- Treating a source repository count as proof of client exposure.

Authorized later D-01 evidence PR paths are limited to:

- `_ops/context-measurement/capability_discovery_inventory.py`
- `_ops/context-measurement/test_capability_discovery_inventory.py`
- `_ops/checks/doc-warden-verify.sh` (only to add the new D-01 context-measurement test to the existing sandbox allowlist)
- `_ops/evidence/context-efficiency/capability-discovery-inventory-v1.json`

This plan PR itself may edit only this plan file and `_ops/plans/README.md`.

## 3. Inventory Schema

The evidence artifact must be canonical JSON using the existing context-measurement conventions for strict UTF-8 input, SHA-256 digests, ASCII-safe IDs, sorted rows, `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=True) + "\n"`, no source content, and no raw description text. Skill description extraction and `description_chars` use the E-03 `skill-description-normalization/v1` contract so D-01 inventory matches the D-02/D-03 character budget gates. Requestable-rule descriptions use `cursor-rule-description-normalization/v1`: parse `.mdc` frontmatter with the D-01 bounded rule reader, require a string `description` for description sizing, then apply the same normalized-string character counting used by E-03. `description_words` is supplemental telemetry computed from the same normalized string with the pinned context-measurement word counter; it is not a D-02/D-03 budget gate.

Top-level shape:

| Field | Requirement |
|---|---|
| `schema` | Fixed string `capability-discovery-inventory/v1`. |
| `status` | `PASS` only when every row has a known owner, valid exposure classification, and the client catalog completeness proof passes. |
| `captured_at_utc` | UTC timestamp for the inventory run. |
| `repository` | Fixed string `KleinPerkins/dev`. |
| `dev_commit` / `dev_tree` | Exact Dev implementation commit and tree that produced the evidence. |
| `client_scope` | Sorted client list included in this evidence; default D-01 scope is exactly `["cursor"]`. Expanding scope to Claude or Codex requires a new explicit operator scope decision before implementation; `rows[]`, `roots[]`, and `totals.by_client` may mention only scoped clients. |
| `environment_class` | Fixed environment label, for example `macos-local-client-installed-catalog`. |
| `method` | Fixed string `capability-discovery-inventory-method/v1`. |
| `catalog_completeness` | Content-safe proof that each included client's discovery catalog was complete enough to classify installed-only versus exposed rows. |
| `roots` | Sorted summary of every required and optional filesystem root in §2 for clients in `client_scope`, plus every synthetic catalog-only root needed by `client-injected-no-installed-file` rows. |
| `rows` | Sorted capability rows. |
| `totals` | Counts by `client`, `owner_source_repo`, `exposure_class`, and `eligibility`. |

Each `roots[]` entry must contain exactly:

| Field | Requirement |
|---|---|
| `root_id` | Stable unique ID: `client/root-scope`. |
| `client` | One of `cursor`, `claude`, or `codex`. |
| `root_scope` | Same root-scope vocabulary used by rows. |
| `root_path` | Absolute root path, or `null` for a client-injected-only catalog source. |
| `required` | Boolean: `true` for unconditional required roots and conditional-injected roots observed in the captured catalog; `false` for optional roots and conditional-injected roots not observed in the captured catalog. |
| `exists` | Boolean filesystem existence result for file roots. |
| `discovery_source_class` | One of `cursor-session-context`, `claude-skill-catalog`, `codex-skill-catalog`, `filesystem-runtime-config`, `absent-required-root`, or `absent-optional-root`. Filesystem presence alone is never a discovery source for description exposure. |
| `discovery_source_sha256` | SHA-256 of the content-free discovery catalog used for that root, or `null` for absent roots and filesystem runtime config. |
| `installed_count` | Number of installed file rows under the root. |
| `exposed_count` | Number of rows observed in client discovery/injection. |
| `installed_only_count` | Number of installed rows not observed in client discovery/injection. |
| `classification_rule` | Fixed rule ID describing how exposure was determined for that root. |

For `installed_path: null` discovery entries, `root_scope` is synthetic and derived before `capability_id`: `client-injected/<catalog_kind>` plus plugin/source identifier when the catalog provides one. The corresponding `roots[]` entry still uses the exact root schema above: `root_path: null`, `required: false`, `exists: false`, `discovery_source_class` from the catalog source, `discovery_source_sha256` from canonical bytes filtered to that synthetic scope, `installed_count: 0`, `exposed_count` equal to the number of catalog-only entries in that synthetic scope, `installed_only_count: 0`, and `classification_rule: "client-injected-catalog/v1"`.

Accepted `classification_rule` values:

| Rule ID | Applies to |
|---|---|
| `cursor-rules-session-catalog/v1` | Cursor rule roots matched against captured always-applied and requestable rule catalogs. |
| `cursor-home-full-context/v1` | Cursor home `~/AGENTS.md` context matched against the captured home full-context catalog entry. |
| `cursor-workspace-full-context/v1` | Cursor workspace `AGENTS.md` context matched against the captured workspace full-context catalog entry. |
| `cursor-skills-agent-catalog/v1` | Cursor skill and plugin-skill roots matched against captured `agent_skills` metadata. |
| `claude-skills-client-catalog/v1` | Claude skill and plugin-skill roots matched against the captured Claude skill catalog. |
| `codex-skills-client-catalog/v1` | Codex user and system skill roots matched against the captured Codex skill catalog. |
| `cursor-global-runtime-config/v1` | Global Cursor hook/config roots recorded as runtime config. |
| `dev-workspace-runtime-config/v1` | Dev workspace hook/config roots recorded as runtime config. |
| `client-injected-catalog/v1` | Synthetic catalog-only roots with no installed file path. |
| `absent-root/v1` | Required or optional file roots recorded with `exists: false`, zero installed counts, and `exposed_count` from any catalog-only entries assigned to that root scope. |

`catalog_completeness` must contain one entry per client in `client_scope`. Each entry contains exactly `client`, `complete` (`true` for `PASS`), `source_sections`, `canonical_entries`, `emitted_rows`, `dropped_entries` (must be `0` for `PASS`), and `canonical_catalog_sha256_by_root`. `source_sections` is a sorted list of objects with exactly `section`, `source_sha256`, `source_entry_count`, and `canonical_entry_count`. `canonical_catalog_sha256_by_root` is an object from `root_id` to canonical catalog SHA-256. `canonical_entries` must equal the sum of `canonical_entry_count`; `emitted_rows` must equal the number of `rows[]` entries for that client; and `dropped_entries` must be `0`. A `PASS` artifact must reject any `rows[]` client, `roots[]` client, `catalog_completeness` client, or `totals.by_client` key outside `client_scope`. No raw source text is stored.

`totals` must contain exactly `by_client`, `by_owner_source_repo`, `by_exposure_class`, and `by_eligibility`; each value is an object from enum string to nonnegative integer. Totals are computed from `rows[]` only.

Each `rows[]` entry must contain exactly:

| Field | Requirement |
|---|---|
| `capability_id` | Stable unique ID: `client/root-scope/name`, with plugin owner/version included when applicable. |
| `client` | One of `cursor`, `claude`, or `codex`. |
| `root_scope` | Stable root class, not just a filesystem parent; examples: `cursor-user-skills`, `cursor-plugin/cursor-public/figma/7f6562...`, `claude-user-skills`, `codex-system-skills`, `dev-workspace-cursor-hooks`. |
| `owner_source_repo` | One of the accepted owner sources below. Unknown owner is a stop, not an `unknown` row in a `PASS` artifact. |
| `exposure_class` | One of the exposure classes below. |
| `installed_path` | Absolute installed path for file-backed rows; `null` only for a client-injected row whose bytes are not available as an installed file. |
| `installed_sha256` | SHA-256 of resolved target file bytes; `null` only when `installed_path` is `null`. For symlinks, `installed_kind` records `symlink` and the digest covers the resolved target content, not the symlink node. |
| `installed_kind` | One of `regular-file`, `symlink`, or `injection-only`. |
| `description_chars` | Character count from the sizing precedence in §4: complete catalog description first, then the installed skill/rule fallback when allowed; forced to `0` for the zero-count exposure classes named in §4 step 12. |
| `description_words` | Word count from the same normalized string used for `description_chars`; `0` when `description_chars` is `0`. |
| `eligibility` | One of the eligibility classes below. |

Accepted `owner_source_repo` values:

| Owner | Rows |
|---|---|
| `KleinPerkins/skills` | Reusable global/local Skills projections and Skills-owned install surfaces. |
| `Affirm/card-platform-product` | CPP-owned skills or descriptors, even when projected through a shared client root. |
| `KleinPerkins/awa` | AWA-owned finish/runtime capability text. |
| `KleinPerkins/dev` | Dev host-overlay rules, workspace `AGENTS.md` context, and Dev-owned hook configuration. |
| `cursor-client` | Cursor-owned built-in skills or plugin runtime descriptors. |
| `anthropic-plugin` | Claude plugin-cache descriptors not owned by the program. |
| `openai-codex` | Codex system skills. |
| `third-party-plugin` | Other plugin descriptors with owner/version present in the installed path. |
| `foreign-preserved-install` | Preserved personal, foreign, or otherwise out-of-program installs in a shared client root. |

Accepted `exposure_class` values:

| Exposure | Meaning |
|---|---|
| `cursor-rule-always-applied` | Cursor injects the full rule text automatically. |
| `cursor-rule-requestable` | Cursor exposes a rule description and loads full text only on intent. |
| `cursor-home-full-context` | Cursor injects home `~/AGENTS.md` context as full context. |
| `cursor-workspace-full-context` | Cursor injects Dev workspace `AGENTS.md` context as full context. |
| `cursor-skill-description` | Cursor exposes an installed skill descriptor. |
| `cursor-plugin-skill-description` | Cursor exposes a plugin-cached skill descriptor. |
| `cursor-global-runtime-config` | Cursor sees global hook/config bytes, but not as a reduction target. |
| `cursor-workspace-runtime-config` | Cursor sees workspace hook/config bytes, but not as a reduction target. |
| `claude-skill-description` | Claude exposes an installed skill descriptor. |
| `claude-plugin-skill-description` | Claude exposes a plugin-cached skill descriptor. |
| `codex-skill-description` | Codex exposes an installed skill descriptor. |
| `codex-system-skill-description` | Codex exposes a system skill descriptor. |
| `installed-not-client-exposed` | File exists in an inspected root, but the current client discovery surface does not expose it. |
| `client-injected-no-installed-file` | Client exposes a descriptor or instruction that cannot be tied to an installed file path. |

Accepted `eligibility` values:

| Eligibility | Meaning |
|---|---|
| `eligible-skills-d02` | Skills-owned description row that D-02 may later plan to reduce. |
| `eligible-cpp-d03` | CPP-owned description row that D-03 may later plan to reduce or scope. |
| `eligible-dev-host-only` | Dev-owned row; no D-02/D-03 owner action may edit it. |
| `eligible-awa-host-only` | AWA-owned row; no D-02/D-03 owner action may edit it. |
| `ineligible-client-owned` | Cursor, Claude, Codex, or plugin-owned row outside this program. |
| `ineligible-full-context-rule` | Always-applied full rule/context row, already governed by static-context owner work rather than D-02/D-03 description budgets. |
| `ineligible-runtime-config` | Hook/config/runtime row, not description-reduction surface. |
| `ineligible-no-description` | Installed row with no exposed description. |
| `ineligible-not-client-exposed` | Installed file that is not observed in client injection/discovery. |
| `ineligible-injection-only` | Client-injected row that has no installed file path/digest and cannot be edited by owner source. |

Eligibility is resolved in this precedence order:

1. `installed-not-client-exposed` exposure always maps to `ineligible-not-client-exposed`.
2. Runtime hook/config exposure always maps to `ineligible-runtime-config`.
3. `client-injected-no-installed-file` exposure always maps to `ineligible-injection-only`.
4. `cursor-rule-always-applied`, `cursor-home-full-context`, and `cursor-workspace-full-context` exposure always map to `ineligible-full-context-rule`.
5. Rows with no exposed description always map to `ineligible-no-description`. Malformed frontmatter or non-string description values stop before row emission.
6. Client, system, third-party plugin, and foreign preserved owners map to `ineligible-client-owned`.
7. Remaining rows use the owner/exposure matrix below.

| Condition | Eligibility |
|---|---|
| `owner_source_repo == "KleinPerkins/skills"` and `exposure_class` is one of `cursor-skill-description`, `cursor-plugin-skill-description`, `claude-skill-description`, `claude-plugin-skill-description`, `codex-skill-description`, `codex-system-skill-description`, or `cursor-rule-requestable` | `eligible-skills-d02` |
| `owner_source_repo == "Affirm/card-platform-product"` and `exposure_class` is one of `cursor-skill-description`, `cursor-plugin-skill-description`, `claude-skill-description`, `claude-plugin-skill-description`, `codex-skill-description`, `codex-system-skill-description`, or `cursor-rule-requestable` | `eligible-cpp-d03` |
| `owner_source_repo == "KleinPerkins/dev"` and `exposure_class` is one of `cursor-skill-description`, `cursor-plugin-skill-description`, `claude-skill-description`, `claude-plugin-skill-description`, `codex-skill-description`, `codex-system-skill-description`, or `cursor-rule-requestable` | `eligible-dev-host-only` |
| `owner_source_repo == "KleinPerkins/awa"` and `exposure_class` is one of `cursor-skill-description`, `cursor-plugin-skill-description`, `claude-skill-description`, `claude-plugin-skill-description`, `codex-skill-description`, `codex-system-skill-description`, or `cursor-rule-requestable` | `eligible-awa-host-only` |
| Client, system, third-party plugin, or foreign preserved rows | `ineligible-client-owned` |
| Any runtime hook/config row | `ineligible-runtime-config` |
| Any always-applied full rule/context row, including `cursor-workspace-full-context` | `ineligible-full-context-rule` |
| Any row with no exposed description | `ineligible-no-description` |
| Any injection-only row without installed bytes | `ineligible-injection-only` |
| Any installed-only row not observed in client discovery | `ineligible-not-client-exposed` |

## 4. Implementation Plan

1. Run `_ops/bin/dev-worktree.sh ensure` from the Dev checkout and follow any printed `move_agent_to_root` instruction before producing or promoting evidence. Then start from a fresh Dev branch at current `origin/main`, prove the origin is `KleinPerkins/dev`, recheck that E-01/E-02/E-03 owner prerequisites are merged on their owner `main` branches, and recheck that E-09 and Release 1 evidence files exist unchanged on the branch.
2. Require `DEV_ROOT`, `SKILLS_ROOT`, `CPP_ROOT`, and `AWA_ROOT` inputs for owner attribution. `DEV_ROOT` must be the canonical top level of the evidence-producing Dev worktree, and `dev_commit`/`dev_tree` in the artifact must be read from that same checkout. Dev workspace `.cursor` roots are resolved only under `DEV_ROOT`. If Cursor is in `client_scope`, the inventory-running Cursor session workspace root must equal `DEV_ROOT` before catalog capture; stop on mismatch. Each provided owner root must be a clean local checkout whose normalized `origin` owner/repo matches `KleinPerkins/dev`, `KleinPerkins/skills`, `Affirm/card-platform-product`, or `KleinPerkins/awa` after accepting standard SSH and HTTPS GitHub remote URL forms; each `HEAD` must be the commit or a descendant of the owner `main` commit that satisfied its prerequisite, or current owner `main` for conditional AWA attribution. Stop on any mismatch.
3. Capture the client-discovery catalogs named below and reduce them to the content-safe canonical catalog shape before scanning installed files.
4. Build a read-only root manifest skeleton from §2 with client, root scope, root path, existence, required flag, and preliminary classification rule. Do not finalize `exposed_count`, `installed_only_count`, synthetic roots, or per-root catalog hashes until catalog-to-file matching completes.
5. Emit candidate rows from the canonical discovery catalogs first. Catalog entries with no path match become `client-injected-no-installed-file` rows with `installed_path: null`, `installed_sha256: null`, and `installed_kind: "injection-only"`. Installed files with no catalog match become `installed-not-client-exposed` rows only after the adapter proves the captured catalog is complete for that client/root; without completeness proof, stop. Matched catalog/file pairs become the corresponding description exposure rows. Then finalize `roots[]` counts, synthetic root rows, and `discovery_source_sha256` values from the emitted rows.
6. Resolve preliminary `owner_source_repo` and `installed_kind` for every installed path using the owner attribution procedure below before applying program-owned parser stops.
7. Bind the E-03 parser and normalizer from `SKILLS_ROOT/scripts/skill-description-inventory.py`. Verify that `SKILLS_ROOT` contains the accepted E-03 implementation. Use E-03 `parse_frontmatter` for `SKILL.md` extraction so D-01 follows `skills-yaml12-core-profile/v1`; invoke E-03 `normalize_description` only after that parser returns a string `description`. For exposed rows, a complete catalog-provided normalized description count takes precedence over installed frontmatter. If E-03 reports only the missing-description condition, retain the row as `ineligible-no-description` when the matched catalog also lacks a complete exposed description; non-string descriptions and malformed YAML/frontmatter stop the run.
8. Extract `.mdc` frontmatter with a bounded Cursor-rule frontmatter reader that accepts the rule keys needed for current installed files, including `description`, `alwaysApply`, and `globs`. `alwaysApply` is corroborating metadata only; the captured Cursor session catalog is the exposure source for `cursor-rule-always-applied` and `cursor-rule-requestable`. Requestable-rule description sizes come from the complete captured catalog description; when the captured catalog proves exposure but only has a truncated description, fall back to the matched installed `.mdc` `description` using the D-01 rule normalization/counting convention. Malformed rule YAML/frontmatter stops the run.
9. Hook/config files are retained as `ineligible-runtime-config`; installed-only rows are retained as `ineligible-not-client-exposed`; exposed rows with no description are retained as `ineligible-no-description`. Do not invent description text. Malformed YAML, duplicate names within one root scope, duplicate declared names across inspected roots without a path-qualified catalog match, invalid UTF-8, or unparseable frontmatter stops the run.
10. Distinguish installed files from client injection/discovery using the client-discovery procedure below. A row is reduction-eligible only when the installed file is observed in the client discovery surface for that client/root. Installed-only rows remain in the artifact as `ineligible-not-client-exposed`.
11. Attribute injection-only rows to an owner source using the deterministic procedure below. Unknown owner stops the run.
12. Compute installed SHA-256 for every file-backed row. Compute normalized description characters and words from complete catalog descriptions first; otherwise use installed skill descriptors with E-03 or installed requestable-rule `.mdc` descriptions with D-01 rule normalization after the bounded reader has extracted a string description. Catalog counts are allowed only when the catalog source proves it contains the complete normalized description, not a truncated snippet. For `installed-not-client-exposed`, `cursor-rule-always-applied`, `cursor-home-full-context`, `cursor-workspace-full-context`, runtime config, injection-only rows with only truncated descriptions, and catalog rows with no exposed description, both description counts are `0`. Do not store raw description text or source content.
13. Write a candidate artifact outside the checkout with `umask 077`; validate exact keys, enums, sorted rows, owner coverage, digest formats, canonical bytes, totals, and `PASS` catalog-completeness proof; then copy the validated artifact into `_ops/evidence/context-efficiency/capability-discovery-inventory-v1.json`.
14. Run the verification gates in §6, open a draft PR, run Bugbot, fix applicable findings within that PR's approved scope, and stop for owner acceptance. Do not mark ready, merge, or arm auto-merge.

Client-discovery procedure:

| Client/root | Discovery evidence |
|---|---|
| Cursor rules | Use installed `.mdc` frontmatter plus the current Cursor session context envelope. Full-injection exposure requires an always-applied rule catalog entry; requestable exposure requires the requestable-rule catalog. If either required Cursor rule catalog is unavailable, stop. Merge both rule catalogs into one canonical Cursor-rules catalog before hashing by emitting entries with `catalog_kind` set to `cursor-rule-always-applied` or `cursor-rule-requestable`. When catalogs are available, absent path/name matches are `installed-not-client-exposed`. |
| Cursor AGENTS full context | Parse the captured `always_applied_workspace_rules` source section for explicit home and Dev workspace `AGENTS.md` entries. Map home `~/AGENTS.md` to `catalog_kind` / `exposure_class` `cursor-home-full-context` and root scope `cursor-home-agents-context`; map `DEV_ROOT/AGENTS.md` to `cursor-workspace-full-context` and root scope `dev-workspace-agents-context`. Defer targets mentioned inside those files are not separate rows unless the captured catalog has explicit entries for them. |
| Cursor skills and plugin skills | Match installed `SKILL.md` entries against the current Cursor `agent_skills` catalog by installed path first when the catalog provides a path; name-only matching is allowed only when the declared name is unique across all inspected Cursor skill roots. If the catalog is unavailable or the same declared name appears in multiple inspected roots without a path-qualified catalog match, stop rather than assuming installed files are exposed. |
| Claude skills and plugin skills | Include only if an explicit scope decision names a concrete Claude client discovery catalog source that is separate from raw installed-root enumeration. Installed root scans may verify installed paths and digests, but they cannot prove exposure on their own. If no such catalog source is available, stop or keep Claude out of `client_scope`. |
| Codex skills | Include only if an explicit scope decision names a concrete Codex client discovery catalog source that is separate from raw installed-root enumeration. Installed root scans may verify installed paths and digests, but they cannot prove exposure on their own. If no such catalog source is available, stop or keep Codex out of `client_scope`. |
| Dev workspace hooks/config | Installed runtime config is observable from the Dev checkout and always ineligible; it does not require a description catalog. |

Every discovery catalog is reduced to a content-safe canonical shape before hashing: sorted entries with exactly `client`, `catalog_kind`, `capability_id`, `root_scope`, `declared_name`, `installed_path` or `null`, `exposure_class`, `description_sha256` or `null`, `description_chars`, and `description_words`. `capability_id` is `client/root-scope/name`; plugin owner/version is part of `root_scope`; `exposure_class` is mapped from `catalog_kind` using the accepted enum table in §3. The canonical catalog bytes use the same JSON convention as the artifact and feed `roots[].discovery_source_sha256`; raw descriptions and source text are not stored. Cursor rule roots use the merged Cursor-rules catalog hash; Cursor skill and plugin-skill roots use the `agent_skills` canonical catalog hash filtered to that root scope. Cursor exposure requires a captured session catalog. Claude and Codex exposure requires a concrete client catalog source named by the operator scope decision, never installed-root enumeration alone. If an included client cannot provide its named discovery source, stop or narrow `client_scope` through a new explicit operator scope decision.

Catalog capture is a D-01 implementation input, not inferred by the filesystem scanner. Capture it on the same machine immediately before inventory:

| Client | Capture method |
|---|---|
| Cursor | Verify the inventory-running Cursor session workspace root equals `DEV_ROOT`; then run the D-01 implementation's Cursor capture adapter against `CURSOR_SESSION_CONTEXT_SOURCE`, a raw same-session context capture stored outside the checkout with `umask 077`. The adapter parses that source, emits an internal `cursor-session-catalog/v1`, and validates `schema`, `client: "cursor"`, `workspace_root: DEV_ROOT`, `captured_at_utc`, `source_sections`, and `entries[]`; `source_sections` must name each live context section, its source digest, and its entry count, and the adapter must prove every source entry produced exactly one canonical entry or an explicit stop. Each entry must include `catalog_kind` equal to the final exposure enum (`cursor-rule-always-applied`, `cursor-rule-requestable`, `cursor-home-full-context`, `cursor-workspace-full-context`, `cursor-skill-description`, or `cursor-plugin-skill-description`), rule/skill/workspace name, path or source group, `root-scope`, `capability_id`, `exposure_class`, `description_sha256` or `null`, `description_chars`, and `description_words`. Cursor skill snippets are exposure evidence only; if the catalog description is truncated, set catalog description hash/counts to `null`/`0` and compute final row description sizes from the matched installed `SKILL.md` with E-03. If the source file, workspace-root proof, completeness proof, or both path and source group for an entry are unavailable, stop; do not derive the catalog from persisted transcripts, filesystem scans, or model prose. |
| Claude | No default capture. Include only after an explicit operator scope decision names a structured Claude discovery catalog source and mapping to the canonical fields above. |
| Codex | No default capture. Include only after an explicit operator scope decision names a structured Codex discovery catalog source and mapping to the canonical fields above. |

`cursor-session-catalog/v1` uses the same canonical JSON convention as the evidence artifact. It is derived from `CURSOR_SESSION_CONTEXT_SOURCE` and is not committed. Its top-level object contains exactly `schema`, `client`, `workspace_root`, `captured_at_utc`, `source_sections`, and `entries`. `schema` is fixed to `cursor-session-catalog/v1`; `client` is fixed to `cursor`; `source_sections` has the same shape as `catalog_completeness.source_sections`; `entries[]` has the canonical discovery-catalog fields named above. The adapter rejects any extra top-level keys, unsorted entries, malformed digests, raw source text, or non-ASCII IDs.

Record the capture command or adapter command, client name, client root, metadata/export identifier when applicable, capture timestamp, and canonical catalog SHA-256 in `roots[]` or the PR body. If an included client cannot provide its named discovery source without raw source content, stop or narrow `client_scope` through a new explicit operator scope decision.

The compliant Cursor producer is a capture-only pre-step in the same Cursor session: before inventory row emission, the agent writes `CURSOR_SESSION_CONTEXT_SOURCE` outside the checkout with `umask 077`. That source file has exactly `schema: "cursor-session-context-source/v1"`, `workspace_root`, `captured_at_utc`, and `sections[]`; each section has `section`, `source_text`, and `source_sha256`, where `source_sha256` is the SHA-256 of `source_text`. `sections[]` may contain only the catalog-bearing sections needed for this plan (`always_applied_workspace_rules`, `agent_requestable_workspace_rules`, and `agent_skills`) and may not dump unrelated conversation or private session text. The raw source file is never committed, and the checked-in evidence stores only derived counts and digests. If validation cannot prove the source came from the same session/root, stop.

The evidence artifact must record the discovery source class in `roots[]`. A `PASS` artifact may not infer exposure from owner repository counts, arbitrary filesystem presence, or installed-root scans without a separate client discovery catalog.

Owner attribution procedure:

| Procedure | Result |
|---|---|
| Resolve the installed path with `lstat` plus final target realpath; record both the installed path digest and whether the installed file is a symlink or regular file. | Distinguishes installed projection from source ownership without reading unrelated repository content. |
| If the resolved target is under the Skills checkout or a Skills-owned projection root, classify as `KleinPerkins/skills`. | Skills-owned rows feed D-02 when description-exposed. |
| If the resolved target is under the CPP checkout or a CPP-owned projection root, classify as `Affirm/card-platform-product`. | CPP-owned rows feed D-03 when description-exposed. |
| If the resolved target is under the AWA checkout or AWA installed runtime/projection root, classify as `KleinPerkins/awa`. | AWA rows are inventoried but not D-02/D-03 edit targets. |
| If the resolved target is under `DEV_ROOT`, classify as `KleinPerkins/dev`. | Dev-owned projections installed into shared client roots remain Dev-owned. |
| If the installed path is `DEV_ROOT/AGENTS.md`, classify as `KleinPerkins/dev`. | Dev workspace context is inventoried but not a D-02/D-03 edit target. |
| If the installed path is inside the Dev checkout `.cursor/` runtime surface or Dev-owned rule source, classify as `KleinPerkins/dev`. | Dev host-overlay rows are not owner-repo reduction targets. |
| If the installed path is the home `~/AGENTS.md` context projection, classify as `KleinPerkins/skills` per protected E-09 `generated-home-agents` attribution. | Home/user context is inventoried but not edited by D-01. |
| If the installed path is global `~/.cursor/hooks.json` or under global `~/.cursor/hooks`, classify as `KleinPerkins/dev` only when the resolved target or managed-hook marker proves Dev ownership; otherwise classify as `foreign-preserved-install`. | Global Cursor hook wiring is Dev-owned only when the realpath/content marker proves it. |
| If the path is under `~/.cursor/skills-cursor`, classify as `cursor-client`; if under `~/.codex/skills/.system` and the resolved target did not already prove a program owner above, classify as `openai-codex`. | Client/system rows are ineligible unless realpath proves program ownership first. |
| For plugin cache paths, parse publisher, plugin name, and version from the cache path. Program-owned classification is allowed only if the resolved target or plugin metadata proves Skills/CPP/AWA ownership; otherwise use `cursor-client`, `anthropic-plugin`, or `third-party-plugin` as applicable. | Plugin rows remain owner-attributed without prefix guessing. |
| For shared client-root installs whose resolved target is outside the four owner roots and outside client/system/plugin roots, classify as `foreign-preserved-install`. | Preserved foreign installs are inventoried but never D-02/D-03 targets. |
| For `client-injected-no-installed-file` rows, classify from the canonical catalog's `capability_id`, root-scope, declared name, and catalog source. If those fields prove a plugin/system/client root, use `cursor-client`, `anthropic-plugin`, `openai-codex`, or `third-party-plugin` as applicable; if they prove a program-owned projected root, use that program owner; if they do not prove one accepted owner, stop. | Injection-only rows remain ineligible and never become owner-repo edit targets. |
| Never classify by skill name prefix alone. | Prevents CPP/Skills confusion in shared client roots. |

## 5. Operator Gate

Plan merge is the acceptance gate for this D-01 inventory plan. It authorizes only the later D-01 evidence implementation described here; it does not authorize D-02, D-03, D-04, any description reduction, or any owner-repository mutation.

No exact-digest operator gate is required for this plan. During D-01 implementation, stop and ask for a new exact scope decision if an inventory candidate would include generated memory or private operator content beyond the authorized content-safe home `~/AGENTS.md` and Dev workspace `AGENTS.md` full-context rows, an unlisted root, an unknown owner, raw home/private content, or a client-injected row that cannot be tied to installed bytes or explicitly classified as injection-only.

## 6. Verification

Required local commands for this plan PR and the later D-01 evidence PR:

```bash
_ops/bin/doc-warden.sh check .
bash _ops/checks/doc-warden-verify.sh --sandbox
git diff --check
git diff --name-status origin/main...HEAD
```

Additional required checks for the later evidence PR:

```bash
: "${D01_CANDIDATE:?set to an absolute temp path outside the checkout}"
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/capability_discovery_inventory.py capture \
  --dev-root "$DEV_ROOT" \
  --skills-root "$SKILLS_ROOT" \
  --cpp-root "$CPP_ROOT" \
  --awa-root "$AWA_ROOT" \
  --cursor-session-source "$CURSOR_SESSION_CONTEXT_SOURCE" \
  --out "$D01_CANDIDATE"
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/capability_discovery_inventory.py validate \
  "$D01_CANDIDATE"
cp "$D01_CANDIDATE" _ops/evidence/context-efficiency/capability-discovery-inventory-v1.json
PYTHONDONTWRITEBYTECODE=1 python3 _ops/context-measurement/capability_discovery_inventory.py validate \
  _ops/evidence/context-efficiency/capability-discovery-inventory-v1.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover _ops/context-measurement -p 'test_capability_discovery_inventory.py'
: "${RELEASE1_EVIDENCE_PATH:?set to the current accepted Release 1 evidence path}"
git ls-tree --exit-code origin/main -- "$RELEASE1_EVIDENCE_PATH"
test -f "$RELEASE1_EVIDENCE_PATH"
git diff --exit-code origin/main...HEAD -- \
  _ops/evidence/context-efficiency/e09-input-v2.json \
  _ops/evidence/context-efficiency/e09-receipt-v2.json \
  _ops/evidence/context-efficiency/static-context-manifest-v1.json \
  "$RELEASE1_EVIDENCE_PATH"
```

The `validate` command must reject any `PASS` artifact whose catalog completeness proof is missing, partial, or inconsistent with `roots[]`, `rows[]`, totals, or the zero-count exposure rules in §4 step 12.

The `capture` command exits `0` only after writing canonical JSON that also passes the same validation rules. Any unknown owner, missing catalog, incomplete proof, malformed YAML/frontmatter, workspace-root mismatch, or unlisted root exits nonzero without updating the checked-in artifact.

D-01 implementation must reverify the current accepted Release 1 evidence authority before setting `RELEASE1_EVIDENCE_PATH`; stop on any ambiguity.

The plan PR must change only this file and `_ops/plans/README.md`. The evidence PR must not run the static manifest validator or remeasure E-09 unless a successor accepted plan explicitly requires it.

## 7. Rollback

Before this plan is accepted, close the draft PR and delete the branch.

Before the D-01 evidence PR is accepted, close the draft PR and discard the candidate artifact. After evidence merge, revert the one evidence PR through normal Dev governance and classify D-01 incomplete. Do not edit the evidence artifact in place after downstream consumption; create a successor version under a new accepted plan.

## 8. Stop Conditions

Stop if:

- E-09 denominator evidence or Release 1 evidence is missing, edited, or not on Dev `main`;
- any inspected `SKILL.md` or `.mdc` frontmatter is malformed;
- any row cannot be assigned to an accepted owner source;
- installed files cannot be distinguished from client injection/discovery;
- a required root implies generated memory, private content, or another unlisted data class;
- owner attribution would require editing Skills, CPP, AWA, plugin, or client files;
- the inventory requires a new registry, daemon, installer path, dependency, analytics store, or long-lived crawler; or
- D-01 evidence cannot remain content-safe without raw descriptions or source text.
