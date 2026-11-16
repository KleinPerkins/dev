# contradictory fixture

This AGENTS.md has duplicate doc-warden block markers — two BEGIN markers appear,
signalling a contradiction where two separate governance block merges have occurred.
doc-warden classifies this as CONTRADICTORY and requires operator intervention.

<!-- doc-warden:begin -->
## Documentation governance (first block)

| Artifact type | Location |
|---|---|
| Plans | `docs/plans/` |
| ADRs | `docs/adr/` |

<!-- doc-warden:end -->

Some content added later.

<!-- doc-warden:begin -->
## Documentation governance (second block — conflict)

| Artifact type | Location |
|---|---|
| Plans | `_ops/plans/` |

<!-- doc-warden:end -->
