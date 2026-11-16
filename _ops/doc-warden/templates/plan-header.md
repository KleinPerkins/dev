# {{TITLE}} — {{SUBTITLE}}

**Version:** v1
**Status:** DRAFT — {{DATE}}. <!-- TODO: author — update status to ACCEPTED once operator-approved -->
**Date:** {{DATE}}
**Owning repository:** `{{REPO_SLUG}}` (`{{REPO_PATH}}`)
**Plan-type:** standard <!-- TODO: author — `standard` for a design/execution plan; `agentic-execution` if this plan is run task-by-task by an implementer subagent (then §5 MUST follow templates/plan-task-block.md; see the note below) -->
**Review provenance:** <!-- TODO: author — describe co-design gates, swarm reviews, operator approvals -->

**Goal:** <!-- TODO: author — one sentence: what this plan builds or changes -->
**Architecture:** <!-- TODO: author — 2–3 sentences on the approach -->
**Tech stack:** <!-- TODO: author — key technologies/tools this plan touches -->

<!-- Agentic-execution plans only (Plan-type: agentic-execution): this plan is executed task-by-task
     by a zero-context implementer subagent. Per POLICY.md §10 rule 10, EVERY work item in §5 MUST
     follow templates/plan-task-block.md — a **Files:** block, an **Interfaces:** block, and checkbox
     (`- [ ]`) steps with literal code and commands. Keep Plan-type: standard for an ordinary
     design/execution plan; the extra shape is then not required. -->

> **For agentic workers (agentic-execution plans only):** REQUIRED SUB-SKILL — use
> `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Each
> work item's steps use checkbox (`- [ ]`) syntax for progress tracking.

---

## Global Constraints

<!-- TODO: author — project-wide requirements that implicitly apply to EVERY work item: version
     floors, dependency limits, naming/copy rules, platform requirements — one line each, exact
     values copied verbatim from the spec. Every task's requirements implicitly include this section. -->

## 1. Purpose

<!-- TODO: author — one paragraph: what problem this plan solves and why it matters -->

## 2. Scope and non-goals

<!-- TODO: author — bullet list: what is in scope, what is explicitly out of scope -->

## 3. Background and context

<!-- TODO: author — verified live-state facts relevant to this plan; cite sources per §11 provenance model -->

## 4. Approach

<!-- TODO: author — architecture/approach at the level of detail needed for implementation -->

## 5. Work items

<!-- TODO: author — decomposed work items.
     • standard plan: each item states objective, scope, prerequisites, steps, and DoD.
     • agentic-execution plan (Plan-type: agentic-execution): EACH item MUST follow
       templates/plan-task-block.md — a **Files:** block, an **Interfaces:** (Consumes/Produces)
       block, and bite-sized checkbox (`- [ ]`) steps with literal code and exact commands, no
       placeholders. POLICY.md §10 rule 10 enforces this shape structurally. -->

## 6. Acceptance criteria

<!-- TODO: author — concrete, checkable criteria for declaring this plan complete -->

## 7. Rollback

<!-- TODO: author — how to reverse each major mutation if needed -->
