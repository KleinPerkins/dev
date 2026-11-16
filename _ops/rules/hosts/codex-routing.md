## Model Choice

Automatically assess each bounded task before authorized Codex delegation, using
Skills' source-owned `global/rules/subagent-orchestration/codex_dispatch.py` and
`CODEX-DISPATCH.md`. The qualified Skills revision is
`bc58eb77f442307ab4f124ab5aeec3f99571cb21`; its payload SHA-256 is
`4cfb6f107e5a26dbea73c83bf35d4c918dbc73e0ba26498d2605de9ac71a5ba3`.
Resolve `KleinPerkins/skills` by Git remote. Read the pinned resolver, policy
(`codex-work-policy.json`) and caller contract from an owner-approved checkout or
byte-verified read-only Git-object export. Run `source-digest` and require the
exact digest above. Never change a primary checkout to obtain this source.

Read the rubric and closed schemas in `CODEX-DISPATCH.md`. Supply objective,
deliverable, scope, predefined acceptance checks, work class, evidence-backed
ratings, consequences, reversibility and review requirements. Run `assess`, then
`plan --input PATH` with that assessment. Use the highest applicable difficulty;
route-changing unknowns require assessment. Model family and effort are separate
explicit decisions. The Skills policy owns their mappings; callers cannot bypass
assessment by supplying a tier. Reassess at material scope changes. For parent
work use the same assessment with target `parent`; report advice without claiming
to change this chat's model.

Observe the complete current native `collaboration.spawn_agent` contract and
model/effort offers, bound to this session, host and source digest. This qualified
profile consumes `codex-work-decision/v2`; legacy native-profile evidence does not
qualify it. Evidence must be at most 15 minutes old. API catalogs and documentation
are not native offers. Use only a `ready` decision and call its exact
`dispatch.tool` with unchanged `dispatch.arguments`, including explicit `model`,
`reasoning_effort`, and `fork_turns: "none"`. Add exactly the bounded `task_name`
and `message` named by `dispatch.caller_fields`; pass no `agent_type`,
`fork_context`, evidence metadata, or record metadata. Never alias native tool
names or translate one profile's arguments into another. Unknown contracts,
stale evidence, absent models and unsupported efforts mean no dispatch. Custom
or pinned roles remain unqualified. Native delegation permissions remain binding.

Use a separate fresh-context worker for independent review, supplying the artifact
and explicit criteria. Prefer another sufficiently capable family when offered;
same-provider review is context independence, never provider diversity. Preserve
stricter repository review and authorization requirements.

Record launches, selection reasons, warnings and outcomes with `observe`. Keep
requested settings separate from acknowledged execution identity: a handle alone
leaves actual model and effort unknown. Join workers and verify task-owned resource
cleanup before using results or continuing. A confirmed prelaunch availability
rejection permits one same-pair retry after 60 seconds with fresh evidence where
required, then unavailable; never silently substitute a model, effort or task band.
A completed attempt that fails predefined checks may receive one quality escalation
only after diagnosis, verified cleanup and reassessment, following the Skills
continuation contract. Infrastructure failures, missing permissions and ambiguous
acceptance do not qualify. A second quality failure stops automatic escalation.

Explicit overrides require user authority and remain within the qualified policy.
`refresh` produces a policy proposal for review; it never adopts new models or
preferences automatically. No automatic maximum effort, interception hook or
background scheduler is introduced. Historical interfaces remain in Skills for
existing consumers; this is the active Codex assessment path.
