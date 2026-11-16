# Work-item task block — template

<!--
  Per-work-item task block for an AGENTIC-EXECUTION plan (a plan whose header declares
  `**Plan-type:** agentic-execution`). Copy ONE block per work item into the plan's
  `## 5. Work items` section, replacing every {{PLACEHOLDER}} and every `TODO: author` slot.

  Contract: each block must be executable by a zero-context implementer subagent that can see
  ONLY this block. Name exact files, declare the cross-task interface (so neighboring tasks can
  wire to it without reading each other), and give bite-sized checkbox steps with literal code
  and commands — the same discipline as the superpowers `writing-plans` skill, wrapped in the
  doc-warden plan/ADR governance envelope.

  Enforcement (POLICY.md §10 rule 10): doc-warden asserts, STRUCTURALLY and presence-only, that an
  agentic-execution plan carries across its Work items at least one `**Files:**` block, at least
  one `**Interfaces:**` block, and at least one checkbox step (`- [ ]`). The engine NEVER authors
  or validates the code/tests/prose inside a block — a rendered skeleton still holding
  `TODO: author` markers classifies `NEEDS_AUTHORING` until a human/agent fills it; a filled plan
  that is missing the shape classifies `DRIFTED`.
-->

### Task {{N}}: {{COMPONENT_NAME}}

**Files:**
- Create: `{{exact/path/to/new_file.ext}}`
- Modify: `{{exact/path/to/existing_file.ext}}:{{start_line}}-{{end_line}}`
- Test: `{{exact/path/to/test_file.ext}}`

**Interfaces:**
- Consumes: <!-- TODO: author — exact signatures/types this task uses from earlier tasks (names + types) -->
- Produces: <!-- TODO: author — exact names, params, and return types later tasks depend on. A task's
  implementer sees ONLY this block, so this line is how neighboring tasks learn the names/types to wire to. -->

- [ ] **Step 1 — Write the failing test**

```{{lang}}
# TODO: author — the actual failing test (real code, no placeholder)
```

- [ ] **Step 2 — Run the test, verify it FAILS**

Run: `{{exact test command}}`
Expected: FAIL — {{exact expected failure, e.g. "NameError: function 'foo' is not defined"}}

- [ ] **Step 3 — Write the minimal implementation**

```{{lang}}
# TODO: author — the actual minimal implementation (real code)
```

- [ ] **Step 4 — Run the test, verify it PASSES**

Run: `{{exact test command}}`
Expected: PASS

- [ ] **Step 5 — Commit**

```bash
git add {{exact paths}}
git commit -m "{{type: concise message}}"
```

**Definition of done:** <!-- TODO: author — the concrete, checkable end-state for this task -->

<!--
  No-placeholder rule — these are PLAN FAILURES; never ship them inside a filled task block:
  - "TBD" / "implement later" / "fill in details"
  - "add appropriate error handling" / "add validation" / "handle edge cases"
  - "write tests for the above" without the actual test code
  - "similar to Task N" (repeat the code — tasks may be read out of order)
  - a code step with no code block
  - references to types/functions/methods that no task defines
-->
