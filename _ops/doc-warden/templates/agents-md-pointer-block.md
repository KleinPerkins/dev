<!-- doc-warden:begin -->
## Documentation governance

This repo's documentation structure is governed by `doc-warden`.

| Artifact type | Location |
|---|---|
| Plans | `{{PLANS_DIR}}/` — index at `{{PLANS_DIR}}/README.md` |
| ADRs | `{{ADR_DIR}}/` — index at `{{ADR_DIR}}/README.md` |
| Runbooks | `docs/runbooks/` |
| Glossary | `docs/GLOSSARY.md` (created when genuine terminology ambiguity arises) |

**Policy:** `~/dev/_ops/doc-warden/POLICY.md`
**Engine:** `~/dev/_ops/bin/doc-warden.sh check {{REPO_SLUG}}` (read-only health check)
<!-- doc-warden:end -->
