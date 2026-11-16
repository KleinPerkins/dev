# ADR 0004: Optimize context projections without moving authority
Status: accepted — 2026-08-15

**Deciders:** Laurence Duggan
**Owning repository:** `KleinPerkins/dev`
**Related plan:** [Context Efficiency Program v1](../plans/context-efficiency-program-v1.md)

## Context

Recurring agent context is assembled from projections owned by different systems:

- Dev owns its workspace entrypoint, operating-model rule, terse-output rule, and host AWA policy/delegators.
- AWA owns SSP/operator semantics and generic hook/product behavior.
- Skills owns global capability source/exposure, bootstrap, continual-learning generation, Save-Game, and the AWA release binding.
- CPP owns CPP-local skills that its current installer projects globally; global capability payloads still flow from Skills through the orchestrator.
- Cursor, Claude, and Codex decide what an eligible client discovers or injects.

The draft Context Efficiency Program originally treated the seven static payloads as the main reduction surface. A remote-first refresh confirmed the 30% opportunity but also found that source authority and installed projection can diverge:

- active capability links and the AWA shelf pointer can resolve under a disposable workspace;
- CPP-installed Cursor, Claude, and Codex skill links can resolve under a disposable CPP worktree because the current installer projects from its invoking checkout;
- the machine can run an older AWA release than the current Skills pin;
- AWA's direct installer and Dev's overlay can both write the three policy hook rows, while Dev's clean overlay path omits two AWA product rows;
- continual-learning can correctly refuse to overwrite generated memory when any discovered source is nonempty but unparsable; and
- source-file counts do not prove what a client injects, particularly across project scope, user-home state, Cloud, Claude, and Codex.

Centralizing source, adding a context registry, or creating a new runtime would reduce neither the measured payload nor these convergence risks. It would duplicate existing authority and introduce a second state machine.

## Decision

Optimize **owner-controlled projections**, not source authority.

1. **Authority stays distributed.**
   - Dev coordinates the program, deterministic evidence, and host-policy rollout.
   - AWA, Skills, CPP, and Dev each change only their owned source/install surfaces through separately accepted plans/change artifacts classified by that repository's current convention.
   - Global capability delivery continues through the existing Skills → orchestrator → CPP lifecycle.
   - Operator-owned `~/agent-learnings.md` and workspace `agent-learnings.md` data can be classified or repaired only through a separate explicit machine-local operator authorization; no repository plan grants that authority.

2. **Eligibility repair precedes the official baseline.**
   - Skills-owned and CPP-owned Cursor/Claude/Codex links/pointers must resolve to durable approved sources through their respective owner mechanisms.
   - Continual-learning generation must be reproducible from preserved machine-local sources after the operator-owned source gate; Skills work activates only for a reproduced code defect.
   - Hook installation must converge to one explicit five-row owner matrix.
   - Installed bytes must match exact current owner refs before they enter the denominator.

3. **Dev's program manifest and ledger are evidence only.**
   - They record source refs/blobs, installed digests, deterministic sizes, client observations, approvals, and rollback points.
   - They do not enroll capabilities, select exposure, write hooks, generate memory, render rules, or decide what a client loads.
   - They contain digests/counts for private memory, never learned content.

4. **Reductions are subtractive and projection-specific.**
   - Remove duplicate prose and use precise progressive-disclosure pointers before compressing safety-critical content.
   - Reconcile and scope capability discovery through existing mechanisms before shortening descriptions.
   - Preserve ordinary-language access through existing `agent-route`; add no context-specific router.
   - Exclude MCP optimization and a duplicate Save-Game project from this version.
   - Make AWA operator-text reduction conditional on Dev/Skills failing the 30% static target.

5. **Verification has two independent layers.**
   - Deterministic evidence proves exact source/installed bytes, sizes, tests, installation, and rollback under a versioned counting contract.
   - Fresh eligible client evidence proves actual discovery/invocation and changed behavior.
   - Neither source tests nor UI token observations substitute for the other layer.

6. **Measurement rejects ambiguous input.**
   - `kp-context-measurement/v1` pins strict UTF-8, `CRLF`/`CR`→`LF`, no other Unicode normalization, Unicode-scalar character counts, a fixed Unicode 15.0 whitespace set for maximal non-whitespace words, inclusion of projected frontmatter/delimiters, and identity/version refusal rules.
   - Skill-description inventory requires valid YAML 1.2 Core-schema frontmatter and `skill-description-normalization/v1`; malformed YAML is `BLOCKED_PREREQUISITE`, never a permissive fallback count.
   - Exact totals are evidence only when bound to raw digests, projection IDs, algorithm version, and client/root class.

## Why

This boundary is the smallest design that addresses the observed failures:

- projection drift is repaired where each projection is created;
- source governance, worktree safety, private memory, and exact-digest approvals remain intact;
- Dev can prove a cross-repository outcome without becoming a runtime authority;
- clients with different scopes and hook support get honest, bounded evidence; and
- shipped systems such as Save-Game, agent-route, Skills linked-worktree resolution, and AWA v1.5.1 are reused instead of rebuilt.

The decision also creates an architectural rule for hook ownership: an embedded product may support a declared external host writer, but the live hook file has exactly one writer and the product's standalone direct mode remains the default.

## Authority boundaries

| Authority | May change | Must not change through this program |
|---|---|---|
| Dev | Program docs/evidence, Dev rule sources, host hook reconciliation | AWA product semantics, global capability masters, CPP-local skill bodies |
| AWA | Generic external-writer contract, hook/product scripts, releases | Dev host policy literals or final host reconciliation |
| Skills | Bootstrap/source trust, global descriptions/exposure, continual-learning generator/runtime, AWA pin | CPP-local descriptions, direct CPP payloads, or operator-owned learned-data repair |
| CPP | CPP-local descriptions/scope and its governed installer | Skills-owned global payload bytes outside orchestrated flow |
| Operator / machine-local gate | Learned-data sources, private retained repair evidence, and source-action authorization | Skills code or repository planning authority |
| Client products | Discovery/injection behavior as an external constraint | Repository authority or program evidence semantics |

Repository-owner authorization is never inferred from this ADR. Every implementation change requires a separately accepted plan/change artifact under that owner's current classification and governed PR path.

## Sequencing

The architectural dependency order is:

```text
accepted ADR + program plan
  -> owner-classified plans/change artifacts
  -> durable Skills + CPP projections
  -> valid YAML description inputs + versioned normalization
  -> operator-authorized memory-source eligibility
  -> AWA external-writer release
  -> Skills exact release pin
  -> Dev atomic five-row hook reconciliation
  -> official deterministic baseline
  -> owner-local static reductions
  -> scope-first capability-discovery reductions
  -> projection-specific fresh-client closure
```

The AWA → Skills → Dev hook sequence is serial. Removing an existing writer before its replacement is live is forbidden. Independent Skills/CPP projection repair, description-input eligibility, and the operator-gated memory eligibility step may proceed in parallel, but all must pass before the official baseline.
Dev may take ownership only when the installed AWA runtime advertises the external-writer contract and its checkout, runtime, pointer, and approved release digest agree. Reconciliation keys the five logical hook roles—not command-path spelling—so direct and delegated variants cannot coexist, and it preserves unrelated hooks.

## Alternatives rejected

### Central context registry/runtime

Rejected because it would duplicate rule, capability, hook, and memory authorities; create a new operational dependency; and not reduce the recurring content by itself.

### Keep the historical baseline before repairing eligibility

Rejected because matching bytes on one machine do not prove a durable source or reproducible generated output. It would freeze an unrepeatable denominator.

### Let AWA and Dev both reconcile hooks

Rejected because independent idempotence is not joint idempotence. Current evidence shows duplicate policy rows and a clean-path risk to product rows.

### Move all hook ownership into AWA

Rejected because Dev must inject host policy and owns the live host overlay, while AWA must remain standalone outside Dev. A declared external-writer mode preserves both boundaries.

### Scope or disable capabilities from a central list

Rejected because Skills/CPP already own exposure and installation, and `agent-route` already handles destination routing. A second list would drift.

### Optimize MCP and re-prove Save-Game in the same program

Rejected because no current owner dependency requires MCP reduction and Save-Game is unchanged. Both add work without being necessary for the static target or discovery projection.

### Use only source tests or only client token observations

Rejected because source tests cannot prove client injection, while client UI observations are neither deterministic nor cross-client.

## Consequences

### Positive

- Source authority and existing governance remain unchanged.
- The official 30% denominator becomes reproducible and content-safe.
- Skills and CPP installed projections must both be durable before evidence freezes.
- Machine-local learned-data authority is explicit rather than inferred from Skills generator ownership.
- Hook ownership gains an explicit producer/consumer contract and rollback order.
- Program scope shrinks by removing unowned MCP and duplicate Save-Game work.
- CPP's real global discovery projection is included without centralizing CPP.
- Client claims become exact about root, scope, event, and local-versus-Cloud state.

### Costs

- At least four owner repositories need independently reviewed, owner-classified plan/change artifacts.
- Baseline freeze waits for eligibility work, so the first visible size reduction lands later.
- Fresh client proof is required after reconciliation and cannot be fully automated from source tests.
- CPP project scoping may fail and require description-only reduction.

### Risks and mitigations

- **Evidence ledger becomes de facto authority:** keep it non-executable, exclude enrollment/exposure fields that drive behavior, and verify owner refs directly.
- **Cross-repository partial rollout:** enforce the serial AWA → Skills → Dev gate and retain the complete prior hook owner until replacement is proven.
- **Private memory leakage:** record only digests/counts and keep restore artifacts private.
- **Repository plan mutates operator data:** require a separate path-specific operator GO; activate Skills work only after a reproduced code defect.
- **Progressive disclosure hides required safety:** maintain a protected invariant map plus ordinary-language routing tests.
- **External client behavior changes:** classify evidence by projection and supersede this ADR if the boundary no longer holds.

## Rollback and supersession

This ADR is draft and authorizes no implementation. Closing or reverting its documentation PR changes no runtime state.

After acceptance:

- owner changes roll back to the last approved source/release and reconcile through existing installers;
- hook rollback establishes and proves the complete prior five-row owner before retiring the failed writer;
- memory rollback restores preserved private sources only under operator authorization and regenerates, never hand-edits, output;
- capability scope/description rollback follows the same Skills/orchestrator/CPP path used to deploy it; and
- the evidence manifest/ledger may be regenerated or retired because it has no runtime authority.

If a future design moves source authority, introduces a context runtime/registry, changes the owner split, or replaces the two-layer evidence contract, create a superseding ADR and a versioned successor plan. Accepted ADR-0004 and plan v1 remain byte-immutable historical records.
