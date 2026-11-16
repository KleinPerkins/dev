# Sample agentic-execution plan — fixture

**Version:** v1
**Status:** ACCEPTED — 2026-08-09
**Date:** 2026-08-09
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** agentic-execution

**Goal:** Prove an agentic-execution plan carrying the full task-block shape classifies CONFORMANT.

## 5. Work items

### Task 1: sample component

**Files:**
- Create: `src/sample.py`
- Test: `tests/test_sample.py`

**Interfaces:**
- Consumes: none
- Produces: `add(a: int, b: int) -> int`

- [ ] **Step 1 — Write the failing test**

```python
def test_add():
    assert add(2, 3) == 5
```

- [ ] **Step 2 — Run the test, verify it FAILS**

Run: `pytest tests/test_sample.py::test_add -v`
Expected: FAIL — NameError: name 'add' is not defined

- [ ] **Step 3 — Write the minimal implementation**

```python
def add(a, b):
    return a + b
```

- [ ] **Step 4 — Run the test, verify it PASSES**

Run: `pytest tests/test_sample.py::test_add -v`
Expected: PASS

- [ ] **Step 5 — Commit**

```bash
git add src/sample.py tests/test_sample.py
git commit -m "feat: add sample add()"
```
