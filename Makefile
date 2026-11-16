# ~/dev/Makefile — entrypoints for the home operating model.
# Style mirrors capabilities/Makefile (help-first, .PHONY, self-documenting targets).

.DEFAULT_GOAL := help
.PHONY: help verify verify-ci verify-staged gen install-rules install-mcp install-hooks install-worktree-hooks install-skills bootstrap verify-capabilities worktree-verify worktree-dashboard awa-engine-verify snow-kit-host-verify dev-remove-repo-verify capability-health doctor doctor-matrix fix-hooks eco-verify eco-sync eco-selfheal eco-cleanroom eco-regression eco-consistency eco-zero-link eco-lockkit-check eco-lockkit-write eco-lockkit-diff repo-baseline-list pr-automation-test doc-warden-verify personal-portability-verify

help: ## Show available targets
	@echo "KleinPerkins/dev — home operating model"
	@echo "  make verify              - full local check (repo invariants + the 3 tool rules on this machine)"
	@echo "  make verify-ci           - repo-only check (CI-safe: no ~/.cursor ~/.codex ~/.claude)"
	@echo "  make verify-staged       - path-scoped staged checks with selection receipt"
	@echo "  make doctor              - read-only cross-repo health check of every repo under ~/dev"
	@echo "  make doctor-matrix       - run doctor AND refresh the living matrix in git-hygiene-audit.md"
	@echo "  make fix-hooks           - install the identity-guard hook across eligible KleinPerkins repos"
	@echo "  make repo-baseline-list  - list eligible/excluded repos for the uniform repo baseline (read-only)"
	@echo "  make pr-automation-test  - run PR-automation legacy + runnerless v3 contract tests"
	@echo "  make doc-warden-verify   - doc-warden subsystem regression (structure + fixture + byte-stability)"
	@echo "  make install-rules       - (re)install agent rules + mirror alwaysApply Cursor rules into Codex/Claude"
	@echo "  make install-mcp         - legacy MCP mirror; refuses suspended or registrar-owned targets"
	@echo "  make install-skills      - surface the /dev-* skills to Cursor/Codex/Claude (idempotent)"
	@echo "  make install-hooks       - install the local pre-commit gate"
	@echo "  make install-worktree-hooks - install Cursor worktree automation hooks"
	@echo "  make gen                 - regenerate the Cursor .mdc from _ops/rules/agent-context.md"
	@echo "  make bootstrap           - full new-machine / refresh flow (bash bootstrap.sh)"
	@echo "  make personal-portability-verify - isolated personal reconstruction and package tests"
	@echo "  make verify-capabilities - run the capabilities dedup invariant check"
	@echo "  make worktree-verify     - verify worktree automation policy/tooling"
	@echo "  make awa-engine-verify   - smoke-check the installed AWA engine release (software: KleinPerkins/awa)"
	@echo "  make snow-kit-host-verify - hermetic LD-host snow-kit lifecycle regression"
	@echo "  make dev-remove-repo-verify - hermetic /dev-remove-repo suite (isolated fixtures + journal replay)"
	@echo "  make worktree-dashboard  - refresh the AWA status canvas in the Cursor workspace (read-only scan)"
	@echo "  make capability-health   - PM-facing capability health + repair hints"
	@echo "  --- reorg-v2 ecosystem (eco) ---"
	@echo "  make eco-verify          - validate all artifact manifests (meta.yml) under managed roots"
	@echo "  make eco-sync            - 3-mode sync/refresh: MODE=repair|replace|rebuild (default repair)"
	@echo "  make eco-selfheal        - bounded verifier-driven self-heal retry loop (N=3)"
	@echo "  make eco-cleanroom       - clean-room fresh-clone+install regression in a tmpdir"
	@echo "  make eco-regression      - full reorg-v2 regression suite (Phase 4)"
	@echo "  make eco-consistency     - verify master<->cpp vendored-payload are in sync (Decision A control)"
	@echo "  make eco-zero-link       - INV-zero-link scan across ALL managed roots (Decision C)"
	@echo "  make eco-lockkit-check   - verify eco-lock master + consumer lock parity"
	@echo "  make eco-lockkit-write   - propagate eco-lock master to clean capability repos"
	@echo "  make eco-lockkit-diff    - show eco-lock master/consumer drift"

verify: ## Full local verification (repo + installed agent rules)
	@bash _ops/checks/verify-operating-model.sh

verify-ci: ## Exact union of the eight source CI shards (installed-host checks remain separate)
	@bash _ops/checks/verify-operating-model.sh --ci

verify-staged: ## Path-scoped staged verification with full fail-safe fallback
	@PYTHONDONTWRITEBYTECODE=1 python3 _ops/verification/path_gate.py --repo .

doctor: ## Read-only cross-repo health check (advisory; never blocks/modifies)
	@bash _ops/checks/dev-doctor.sh

doctor-matrix: ## Run doctor and refresh the living matrix in git-hygiene-audit.md
	@bash _ops/checks/dev-doctor.sh --write-matrix

fix-hooks: ## Install the identity-guard hook across eligible KleinPerkins personal/cap repos
	@bash _ops/checks/dev-doctor.sh --fix-hooks --quiet

repo-baseline-list: ## List eligible/excluded repos for the uniform repo baseline (read-only)
	@bash _ops/bin/repo-baseline.sh list

pr-automation-test: ## Run PR-automation legacy + runnerless v3 tests
	@bash _ops/baseline/profiles/pr-automation/test.sh
	@bash _ops/baseline/profiles/pr-automation/v3/test.sh

doc-warden-verify: ## doc-warden subsystem regression (structure + fixture classifications + byte-stability)
	@bash _ops/checks/doc-warden-verify.sh

install-skills: ## Surface the /dev-* skills to Cursor/Codex/Claude (idempotent)
	@bash _ops/bin/install-skills.sh

gen: ## Regenerate the Cursor .mdc from the agent-context SOT
	@bash _ops/bin/install-agent-rules.sh --gen-only

install-rules: ## Install/refresh the agent rules for Cursor/Codex/Claude (idempotent)
	@bash _ops/bin/install-agent-rules.sh

install-mcp: ## Legacy MCP mirror; refuses suspended or registrar-owned targets
	@bash _ops/bin/install-mcp.sh

install-hooks: ## Install the local pre-commit hook
	@bash _ops/bin/install-hooks.sh

install-worktree-hooks: ## Install Cursor worktree automation hooks (idempotent)
	@bash _ops/bin/install-worktree-hooks.sh

bootstrap: ## Run the full new-machine / refresh flow
	@bash bootstrap.sh

personal-portability-verify: ## Isolated personal profile, reconstruction and package tests
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s _ops/portability -p 'test_*.py'

verify-capabilities: ## Run the capabilities (skills dedup) invariant check
	@bash capabilities/verify-capabilities.sh

worktree-verify: ## Verify worktree automation policy/tooling
	@bash _ops/checks/worktree-verify.sh

awa-engine-verify: ## Smoke-check the installed AWA engine release (software home: KleinPerkins/awa)
	@bash _ops/checks/awa-engine-smoke.sh

snow-kit-host-verify: ## Hermetic LD-host snow-kit lifecycle regression
	@bash _ops/tests/snow-kit-host-bootstrap.sh

dev-remove-repo-verify: ## Hermetic /dev-remove-repo suite (isolated fixtures + journal replay; no live repository touched)
	@bash _ops/tests/dev-remove-repo.sh

worktree-dashboard: ## Refresh the AWA status canvas in the Cursor workspace (read-only repo scan; agent/automation-driven)
	@bash _ops/bin/install-awa-dashboard.sh

capability-health: ## PM-facing capability health + repair hints
	@echo "== Capability health =="
	@echo "1) Local surfacing"; bash capabilities/verify-capabilities.sh
	@echo "2) Lockkit parity"; $(MAKE) --no-print-directory eco-lockkit-check
	@echo "3) Registry/lock reconcile"; personal/ecosystem-orchestrator/bin/orchestrator.sh reconcile
	@echo "4) Status matrix"; ORCH_STATUS_SKIP_GH=1 personal/ecosystem-orchestrator/bin/orchestrator.sh status --matrix
	@echo "Repair: run 'make eco-lockkit-write' after meta.yml edits, then rerun 'make capability-health'."

eco-verify: ## Validate all artifact manifests (meta.yml) under the managed roots
	@bash _ops/eco/verify-manifests.sh

eco-sync: ## 3-mode sync/refresh (MODE=repair|replace|rebuild, default repair)
	@bash _ops/eco/sync.sh "$${MODE:-repair}" $${ECO_SYNC_ARGS:-}

eco-selfheal: ## Bounded verifier-driven self-heal retry loop (N=3)
	@bash _ops/eco/self-heal.sh

eco-cleanroom: ## Clean-room fresh-clone+install regression in a tmpdir
	@bash _ops/eco/clean-room.sh

eco-regression: ## Full reorg-v2 regression suite (Phase 4)
	@bash _ops/eco/regression-suite.sh

eco-consistency: ## Verify master<->cpp vendored-payload content is in sync (Decision A compensating control)
	@ORCH=personal/ecosystem-orchestrator/bin/orchestrator.sh; \
	if [ -x "$$ORCH" ]; then bash "$$ORCH" consistency $${ECO_CONSISTENCY_ARGS:-}; \
	else echo "(skip) ecosystem-orchestrator not present at $$ORCH"; fi

eco-zero-link: ## INV-zero-link scan across ALL managed roots (Decision C; absent roots skipped)
	@bash _ops/eco/verify-zero-link.sh --all-roots

eco-lockkit-check: ## Verify eco-lock master + consumer lock parity (orchestrator lockkit)
	@ORCH=personal/ecosystem-orchestrator/bin/orchestrator.sh; \
	if [ -x "$$ORCH" ]; then bash "$$ORCH" lockkit check $${ECO_LOCKKIT_ARGS:-}; \
	else echo "(skip) ecosystem-orchestrator not present at $$ORCH"; fi

eco-lockkit-write: ## Propagate eco-lock master to clean capability repos (no commits)
	@ORCH=personal/ecosystem-orchestrator/bin/orchestrator.sh; \
	if [ -x "$$ORCH" ]; then bash "$$ORCH" lockkit write $${ECO_LOCKKIT_ARGS:-}; \
	else echo "(skip) ecosystem-orchestrator not present at $$ORCH"; fi

eco-lockkit-diff: ## Show eco-lock master/consumer drift
	@ORCH=personal/ecosystem-orchestrator/bin/orchestrator.sh; \
	if [ -x "$$ORCH" ]; then bash "$$ORCH" lockkit diff $${ECO_LOCKKIT_ARGS:-}; \
	else echo "(skip) ecosystem-orchestrator not present at $$ORCH"; fi
