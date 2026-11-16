# ~/dev/capabilities/Makefile — capability bootstrap / verify / mirror entrypoints.
#
# STATUS: `bootstrap` + `verify` are ACTIVE (the skills repo URL is set below); `sync`
# remains a placeholder. Nothing runs automatically and nothing pushes to any remote.
#
# Repo scope is DECIDED: global skills live in KleinPerkins/skills; the home operating
# model lives in KleinPerkins/dev. CAP_SKILLS_REPO_URL points at the real repo; override on
# the CLI only if needed. See ~/dev/OPERATING-MANUAL.md.

# Override on the CLI, e.g.  make bootstrap CAP_SKILLS_REPO_URL=git@github.com:KleinPerkins/skills.git
CAP_SKILLS_REPO_URL ?= git@github.com:KleinPerkins/skills.git
CAP_ROOT            := $(HOME)/dev/capabilities
SKILLS_DIR         := $(CAP_ROOT)/skills

.DEFAULT_GOAL := help

.PHONY: help verify bootstrap mirror sync print-config

help: ## Show available targets
	@echo "capabilities Makefile (bootstrap/verify live; sync is a placeholder)"
	@echo "  make verify     - run verify-capabilities.sh (read-only invariant check)"
	@echo "  make bootstrap  - (idempotent) clone skills repo if missing + relink tool symlinks"
	@echo "  make mirror     - alias of 'sync'"
	@echo "  make sync       - vendor global/ skills into a consumer (e.g. cpp) [PLACEHOLDER]"
	@echo "  make print-config - show resolved variables"
	@echo ""
	@echo "  CAP_SKILLS_REPO_URL = $(CAP_SKILLS_REPO_URL)"

print-config: ## Print resolved configuration
	@echo "CAP_ROOT            = $(CAP_ROOT)"
	@echo "SKILLS_DIR          = $(SKILLS_DIR)"
	@echo "CAP_SKILLS_REPO_URL = $(CAP_SKILLS_REPO_URL)"

verify: ## Read-only: assert Claude/Codex skill entries are resolving symlinks
	@bash "$(CAP_ROOT)/verify-capabilities.sh"

bootstrap: ## Idempotent: clone skills repo if missing, then relink per-tool symlinks
	@CAP_SKILLS_REPO_URL="$(CAP_SKILLS_REPO_URL)" bash "$(CAP_ROOT)/bootstrap.sh"

mirror: sync ## Alias for sync

sync: ## PLACEHOLDER: vendor global/ skills into a consumer repo (kept in sync by copy)
	@echo "TODO(sync): vendor $(SKILLS_DIR)/global/ into the cpp skills area."
	@echo "  Approach (per OPERATING-MANUAL.md §8): a *vendored copy* of global/ into cpp,"
	@echo "  kept in sync by this target — NOT a git submodule (KleinPerkins/skills is a"
	@echo "  private personal repo, so Affirm teammates cannot fetch it)."
	@echo "  Deferred until cpp has a skills home (post sandbox->production convergence)."
	@echo "  No files copied. This is an inert scaffold."
