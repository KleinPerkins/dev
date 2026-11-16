# Sample agentic plan with shape outside Work items — fixture

**Version:** v1
**Status:** ACCEPTED — 2026-08-09
**Date:** 2026-08-09
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** agentic-execution

**Goal:** Prove the shape gate is scoped to §5 — task-block tokens in another section do NOT satisfy it.

## 5. Work items

- Prose only in §5: no exact-file block, no interface block, and no checkbox steps here. Per
  POLICY.md §10 rule 10 the shape must be INSIDE this section, so this plan must classify DRIFTED.

## Appendix: illustrative task block (NOT in Work items)

**Files:**
- Create: `src/x.py`

**Interfaces:**
- Produces: `x() -> int`

- [ ] a checkbox step that lives in the appendix, not in §5
