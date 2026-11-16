# ADR 0002: Reconciliation doctrine — shared contract over shared runtime
Status: accepted — 2026-08-05

## Decision

`doc-warden`'s reconciliation engine shares a **doctrine and contract** with `server-guard` and cpp's integrity engine — classifications, lifecycle concepts, receipt requirements, collision behavior, conformance expectations, documented in `_ops/doc-warden/POLICY.md` as a model plus fixtures. It does **not** share a runtime, library, or executable with either.

## Why

The choice was framed as: recommend a shared executable/library (Option B) only if evidence proves, among other things, that all real consumers can use the same runtime without a cross-language bridge. Verified, live evidence closes that question before it opens:

- `repo-baseline`/`baseline-lib.sh` — bash.
- cpp's deterministic integrity engine (`_ops/ci/cpp/{core,engine,schema}.py`) — Python.
- `server-guard` — confirmed mixed shell, Swift, and Python (`git ls-files` extension breakdown).

Three independent, already-existing, already-working implementations of the same canonical/observed-state → diff → severity-ladder classification → gated-execution shape, in three-plus languages, is not a hypothetical cross-language bridge risk — it is the ecosystem's present reality. Option B's own precondition is falsified by the evidence, not merely disfavored on simplicity grounds. Building a shared runtime now would mean either rewriting at least two working, independently-owned systems into a common language, or building and maintaining a cross-language bridge — both are net-additive complexity with no second real consumer yet asking for it.

## Consequences

The shared contract lives as documentation + conformance fixtures in `_ops/doc-warden/POLICY.md`, not as a package, service, or plugin framework. Each domain (docs, server config, cpp facts-graph) keeps its own implementation appropriate to its own data and runtime. If a future fourth domain emerges needing the same doctrine, it gets its own thin adapter against the same documented contract — it does not trigger a runtime-unification project unless a future decision reopens Option B with genuinely different evidence (e.g., two consumers newly converge on one language with no bridge needed).
