# Operator Voice Toolkit — Forensic Static Audit

**Version:** v1
**Status:** Static audit complete and independently reviewed. **Not verifier-cleared** — see §8.
**Date:** 2026-07-30
**Owning repository:** `KleinPerkins/dev` (`~/dev`)
**Plan-type:** standard
**Scope:** Read-only static inspection of three vendor repositories. No execution, no installation, no vendor-repo mutation, no implementation.
**Method:** One deep static-inspection pass followed by a bounded, multi-territory review and parent evidence correction.
**Companion artifact:** `operator-voice-toolkit-build-plan-v4.md` (same directory).

---

## 0. Governance and safety confirmation

- Read `AGENTS.md`, `_ops/POLICY.md` before any inspection.
- `_ops/bin/dev-worktree.sh ensure` run at session start: umbrella repo (`~/dev`) is policy-excluded (umbrella-repo exception) — no worktree relocation required or performed. Work proceeded directly in the primary checkout, which is permitted for `~/dev` itself per policy.
- Umbrella `git status` at start: clean, no pre-existing changes. No pre-existing files at either target artifact path before this worker began writing.
- All vendor-repo work was git-metadata reads (`git log`, `git status`, `git rev-parse`, `git ls-files`, `git remote -v`) plus file reads/searches (`Read`, `Grep`, `Glob`). No `npm`/`pip` install, no build, no test execution, no script execution, no `git fetch`/`pull`, no file writes under `affirm/vendor/*`.
- Final vendor-repo verification (re-run at close of this pass, see §7): all three repos report `git status --porcelain` empty and `HEAD` unchanged from the values recorded below. This proves clean working trees relative to each committed `HEAD`; it does not attest upstream or supply-chain identity.

## 1. Repository metadata

| Repo | Branch | HEAD SHA | Dirty? | License | Primary language | Dependency manifest(s) | Apparent maturity |
|---|---|---|---|---|---|---|---|
| MYNAH | `main` | `470c63b7ca0a3a66477c3072ab8680d19cb11371` | No | MIT (`LICENSE`) | Markdown / Claude prompt-skill (no executable code) | none — no `package.json`/`requirements.txt`; delegates storage to PACK or Claude memory (`skills/mynah/SKILL.md:45-86`) | v1.0.0 is declared in `.claude-plugin/plugin.json`; no tests or CI are tracked. Tags/releases and maintainer activity were not probed. |
| write-like-me | `main` | `3878d9dbfb57a28ea414c891623b57612b6e1734` | No | MIT (`LICENSE`) | Python analysis scripts + Markdown skill/methodology | `scripts/requirements.txt` (optional `textstat`, `spacy`) | Methodologically developed (nine numbered references, verification and regeneration protocols), but no tracked version, CI, releases, or tests. Remote activity was not probed. |
| voice-analyser-mcp | `main` | `7608d4e9a6b3a4dec465e31bd6338cd1b916cf7b` | No | Apache-2.0 (`LICENSE`) | TypeScript (compiled `dist/` is untracked) | `package.json` plus lockfile; several declared NLP packages are unused in tracked `src/` | v1.4.1 package with a stdio MCP server and CLI entry (`src/index.ts:19-22,130-139`; `package.json:1-18`). No tracked tests; `.gitignore:11-14` excludes `test-*`. Published-release state was not probed. |

The configured `origin` URLs identify third-party upstreams (`Percona-Lab`, `Hiro-Inagawa`, `armigerr`); they do not prove read/write permissions. No access probe was performed. All three are reference-only vendor clones per `~/dev` policy (`affirm/vendor/*`).

## 2. Tracked-file inventory

Inventory method: `git ls-files` per repo (git-tracked files only; `.gitignore`-excluded generated/build artifacts are not tracked and are not counted below except where explicitly named). Every tracked file was either **inspected** (opened and read in full) or **catalogued** (identified, classified, and its purpose confirmed from name/extension/one targeted read, but not read line-by-line because it is binary, a lockfile, or an empty marker). Zero tracked files were skipped without classification.

### 2.1 MYNAH — 8 tracked files, 8 inspected, 0 catalogued-only, 0 excluded

| File | Class |
|---|---|
| `LICENSE` | Inspected |
| `README.md` | Inspected |
| `.claude-plugin/plugin.json` | Inspected |
| `skills/mynah/SKILL.md` | Inspected |
| `skills/mynah/references/context-guide.md` | Inspected |
| `skills/mynah/references/profile-schema.md` | Inspected |
| `skills/mynah/references/sample-collection.md` | Inspected |
| `skills/mynah/references/style-dimensions.md` | Inspected |

No source code, no tests, no config beyond the plugin manifest, no lockfiles, no binaries. 100% prompt/documentation. This is itself a material audit finding (see §3.1).

### 2.2 write-like-me — 25 tracked files, 23 inspected, 2 catalogued-only, 0 excluded

Inspected (23): `LICENSE`, `.gitignore`, `README.md`, `SKILL.md`, `references/00-universal-baseline.md` through `references/08-regeneration-and-diff.md` (9 files), `scripts/stylometry.py`, `scripts/extract_author_turns.py`, `scripts/generate_report_from_json.py`, `scripts/requirements.txt` (4 files), `templates/generated-01-generative.md`, `templates/generated-02-corrective.md`, `templates/generated-03-corpus-source.md`, `templates/generated-SKILL.md`, `templates/generated-claude-ai-skill.md`, `templates/style-profile-report.md` (6 files).

Catalogued-only (2):
- `docs/write-like-me.webp` — binary image, referenced from `README.md` as an illustrative screenshot; not machine-readable text, no functional role, excluded from line-level inspection as a binary asset.
- `voices/.gitkeep` — zero-byte marker file that keeps the empty `voices/` output directory tracked in git; the `.gitignore` excludes real contents of `voices/*`. No content to inspect.

`grep`-confirmed: zero files matching `test`/`spec` patterns anywhere in the repo. There is no test suite, tracked or gitignored-but-implied.

### 2.3 voice-analyser-mcp — 36 tracked files, 34 inspected, 2 catalogued-only, 0 excluded

Inspected (34): `LICENSE`, `.gitignore`, `README.md`, `CHANGELOG.md`, `package.json`, `tsconfig.json` (6 root/config), `src/index.ts` (1), `src/tools/collect-corpus.ts`, `src/tools/analyze-corpus.ts`, `src/tools/generate-narrative-guide-v4.ts` (3), `src/utils/crawler.ts`, `src/utils/extractor.ts`, `src/utils/cleaner.ts`, `src/utils/statistics.ts`, `src/utils/advanced-statistics.ts`, `src/utils/micro-rhythm.ts`, `src/utils/zscore.ts` (7), `src/reference/function-words.ts` (1), and all 16 files in `src/analyzers/`: `anti-mechanical.ts`, `argument-flow.ts`, `clustering.ts`, `expression-markers.ts`, `function-words.ts`, `information-density.ts`, `paragraph-transitions.ts`, `paragraph.ts`, `phrase-extraction.ts`, `punctuation.ts`, `sentence.ts`, `specificity-patterns.ts`, `vocabulary-tiers.ts`, `vocabulary.ts`, `voice-markers.ts`, `vulnerability-patterns.ts`.

Catalogued-only (2):
- `houtini-logo.png` — binary brand asset, no functional role.
- `package-lock.json` — generated dependency lockfile; contents are a mechanical transitive-dependency graph, not hand-authored logic. Its top-level dependency set was cross-checked against `package.json` rather than read exhaustively.

Excluded by the repo's own `.gitignore` (confirmed not tracked, and therefore correctly out of scope for this git-tracked-file audit): `node_modules/`, `dist/`, `corpus/`, `templates/`, `archive/`, `research/`, `test-*.ts`, `test-*.js`, and standard log/OS-noise patterns. The exclusion of `test-*` patterns is itself evidence about test maturity, recorded in §3.3 and the scoring rubric — not merely a build artifact.

**Dead-dependency finding:** `grep` across all of `src/` for `from 'natural'` and `from 'wink` (and the `require(...)` equivalents) returns zero matches. `natural`, `wink-nlp`, `wink-nlp-utils`, and `wink-eng-lite-web-model` are declared in `package.json` `dependencies` but are never imported anywhere in the tracked source tree. This is either dead weight from an earlier implementation phase or unused planned infrastructure; either way it is not implementation evidence for any NLP capability claimed in the README and is noted as a code-quality flag, not a functional capability.

### 2.4 Aggregate inventory

- Total tracked files across all three repos: **69** (8 + 25 + 36).
- Inspected line-by-line: **65**.
- Catalogued-only (binary/lockfile/empty-marker): **4**.
- Intentionally excluded by repo `.gitignore` (confirmed untracked, named for completeness): `node_modules/`, `dist/`, `corpus/`, `templates/` (voice-analyser-mcp's own generated-corpus templates dir, distinct from write-like-me's tracked `templates/`), `archive/`, `research/`, `test-*.{ts,js}` (voice-analyser-mcp); `voices/*` contents beyond `.gitkeep` (write-like-me).
- Zero files were skipped without a classification decision.

### 2.5 Exact evidence index for material selection claims

This index supersedes approximate line references in the initial pass. “Strongest” and “best” below mean **among these three audited repositories**, not market-wide.

| Material claim | Exact on-disk evidence |
|---|---|
| MYNAH is a prompt workflow, not an engine | LEARN and COMPOSE are instruction sequences in `skills/mynah/SKILL.md:144-201,205-254`; persistence is delegated to PACK/Claude memory at `skills/mynah/SKILL.md:45-86,180-192`. No executable source file exists in its eight tracked files (§2.1). |
| MYNAH has the strongest context taxonomy of the three | Distinct Slack contexts and traps at `skills/mynah/references/context-guide.md:9-81`; email contexts at `:85-119`; calendar at `:123-152`; comments/internal docs/public blog at `:156-223`. |
| MYNAH’s profile schema is human-readable but unenforced | Required/optional fields and a worked profile at `skills/mynah/references/profile-schema.md:8-81`; storage conventions at `:85-141`; update/compactness guidance at `:145-165`. No validator or parser exists. |
| MYNAH’s “zero personal data” statement applies only to the plugin repo | The claim and delegated profile storage appear together at `MYNAH/README.md:54-61`; PACK-backed cross-platform/versioned storage is described at `MYNAH/README.md:63-84`. |
| write-like-me performs deterministic role-based extraction | Claude sender filtering is `scripts/extract_author_turns.py:182-205`; ChatGPT role filtering is `:208-235`; Markdown marker extraction is `:104-138`. |
| write-like-me’s “AI tell” handling is brittle auto-rejection, not review flagging | Phrase list at `scripts/extract_author_turns.py:55-62`; matching turns are silently omitted at `:125-132,193-201,219-231`. The initial-pass description of “flagging for manual review” was incorrect and is withdrawn. |
| write-like-me has the broadest deterministic stylometry foundation | Tier definitions at `scripts/stylometry.py:18-30`; Markdown normalization at `:113-147`; MATTR/function words at `:197-230`; punctuation/sentence/paragraph/hedging features at `:233-354`; optional textstat/spaCy at `:366-442`; aggregation at `:445-493`. |
| write-like-me has the strongest evidence hierarchy and held-out procedure | Explicit preferences outrank inference at `references/04-rule-mining.md:7-18`; statistical/negative-space rules and uncertainty at `:26-76`; held-out generation and falsifiable checks at `references/07-verification.md:13-64`; stated preferences override measurements at `references/08-regeneration-and-diff.md:65-83`. |
| voice-analyser-mcp is the only implemented MCP surface | Three stdio tools are registered at `src/index.ts:19-128`; stdio transport is started at `:130-139`. |
| voice-analyser-mcp’s reusable statistics are real but untested | Burstiness at `src/utils/advanced-statistics.ts:8-26`, clustering at `:28-94`, entropy at `:96-122`, MATTR at `:124-157`; no tracked tests (§2.3). |
| voice-analyser-mcp computes argument-pattern confidence | The shape is declared at `src/analyzers/argument-flow.ts:8-15`; strong/weak matches feed confidence at `:199-241,246-289,293-337,341-383`; thresholds are computed at `:387-406`. |
| Detection-evasion guidance is deliberately rejected | The product framing appears at `src/analyzers/clustering.ts:1-9`; detector-oriented directives at `:184-232,235-292`; expression-marker detector risk and deliberate-fragment instructions at `src/analyzers/expression-markers.ts:1-20,88-121,263-305`. |
| The style guide is monolithic and untargeted | It loads all named analysis files at `src/tools/generate-narrative-guide-v4.ts:16-45` and emits generic “zero tolerance”/phrase-library content at `:48-180`; no query-scoped retrieval exists. |

## 3. Flow reconstruction per repo

Canonical pipeline stages used as the comparison frame: **source acquisition → operator separation → normalization → signal extraction → inference → confidence/provenance → profile schema → storage/indexing → retrieval → prompt/context assembly → generation → output validation → feedback/continual learning → correction/deletion/rollback/observability.**

### 3.1 MYNAH

| Stage | What MYNAH actually does | Classification |
|---|---|---|
| Source acquisition | The skill targets 5–10 samples and delegates collection to connected tools or manual paste (`skills/mynah/SKILL.md:160-168`; `skills/mynah/references/sample-collection.md:3-64`). There is no connector, allowlist, or automated collector code in the repo. | Prompt/docs-only |
| Operator separation | Not addressed anywhere in the 4 reference files or `SKILL.md`. The instructions say to collect "your" messages but provide no mechanism to detect or strip AI-authored text, quoted/forwarded text, or third-party text if it ends up in a pasted sample (e.g., a Slack thread export containing replies from others). | **Absent** — searched all 5 markdown files (`SKILL.md` + 4 `references/*.md`, ~700 lines total) for "contamination", "third-party", "quote", "forward", "AI-generated" — no hits beyond a single unrelated mention of "AI" in the plugin description. |
| Normalization | None; raw pasted text is fed directly to the LLM performing LEARN mode. | Absent |
| Signal extraction | `skills/mynah/SKILL.md:170-178` delegates pattern extraction to the LLM using `skills/mynah/references/style-dimensions.md`; no code computes or verifies a signal. | Prompt/docs-only |
| Inference | LEARN asks the LLM to capture characteristic patterns (`skills/mynah/SKILL.md:170-197`). The only explicit “3+” threshold located is for repeated misspellings (`skills/mynah/references/style-dimensions.md:153-155`), not a general inference rule; it is still unenforced. | Prompt/docs-only |
| Confidence/provenance | The schema stores profile-level date, sample count, and language (`skills/mynah/references/profile-schema.md:8-29`) but no per-fact confidence, sample links, or operator-confirmed state. | Partial |
| Profile schema | Required/optional fields and a worked profile are concrete (`skills/mynah/references/profile-schema.md:8-81`), but the Markdown convention has no validator or type enforcement. | Implemented convention, unvalidated |
| Storage/indexing | `README.md` and `SKILL.md` state profiles are saved via "PACK" (an external, out-of-repo memory tool) or, as fallback, "Claude's built-in memory." Neither is part of this repo; both are unaudited external dependencies. There is no indexing, no search, no versioning mechanism visible in-repo. | Delegated to an external, out-of-scope system — functionally **absent** from this repo's own implementation surface |
| Retrieval | `SKILL.md` COMPOSE-mode step 1 says "load the relevant context profile" by matching a trigger phrase or inferred context ID against the 10-context taxonomy. This is a flat lookup-by-ID, not a search/rank/relevance system; there is no mechanism for partial-context blending (e.g., "email but slightly informal because it's to a friend at another company"). | Implemented (as a prompt instruction) — trivial exact-match retrieval, not indexed search |
| Prompt/context assembly | The entire loaded profile (all fields) is implied to be pulled into context wholesale; there is no token-budgeting, truncation, or relevance filtering logic anywhere in the skill. | Prompt/docs-only, and notably naive at scale (whole-profile injection has no upper bound as more contexts/profiles accumulate) |
| Generation | COMPOSE-mode steps ask the LLM to draft, then apply the profile's imperfection patterns, then "read it aloud" as a self-check. This is entirely prompt-driven; there is no separate generation-time guardrail beyond the model's own re-reading of its own output. | Prompt/docs-only |
| Output validation | `SKILL.md` COMPOSE step "Output Validation" (a short bullet list) asks the model to self-check tone/length/imperfections match the profile, and to flag if uncertain. This is a soft, self-graded check with no deterministic scan and no held-out test. | Prompt/docs-only, weak |
| Feedback/continual learning | `README.md`/`SKILL.md` describe a "Style Evolution" concept: if a new sample contradicts the stored profile, the agent should "note the shift explicitly" rather than silently overwrite. This is a sound design instinct but, again, entirely dependent on the LLM noticing and acting on it in-context; there is no code path that diffs old vs. new signals. | Prompt/docs-only |
| Correction/deletion/rollback/observability | No deletion, export, or correction mechanism beyond "ask the agent to update the profile" — which routes back through the same unaudited external memory backend. No audit log, no rollback, no inspection UI. `README.md`'s claim of "contains zero personal data" is true of *this git repository* but says nothing about the external memory store where the actual profile data lives — that store is out of MYNAH's control and out of this audit's inspectable surface. | Absent (in-repo); delegated and unverifiable (out-of-repo) |

**Bottom line for MYNAH:** it is a genuinely well-organized *prompt specification* for a voice-mimicry workflow — the context taxonomy and profile-schema design are its real contributions — but it implements zero of the fourteen pipeline stages in deterministic code. Every stage is either "ask the LLM to do this well" or "delegate to an unaudited external system." README claims of persistence, multilingual support, and "zero personal data" are aspirational/conditional on components this repository does not contain or control.

### 3.2 write-like-me

| Stage | What write-like-me actually does | Classification |
|---|---|---|
| Source acquisition | `references/01-corpus-discovery.md` (methodology for manually locating a >5,000-word corpus of the author's own writing) plus `references/02-author-filtering.md` describing use of `scripts/extract_author_turns.py` against exported Claude.ai/ChatGPT conversation JSON or Markdown. No live connector; the operator must export data themselves and point the skill at a folder. | Implemented+untested (the extraction script is real, executable code — but zero automated tests exist to prove its correctness against fixtures) |
| Operator separation | The script filters Claude `sender=="human"` and ChatGPT `author.role=="user"` (`scripts/extract_author_turns.py:182-235`) and supports Markdown author markers (`:104-138`). Its hard-coded “AI tell” phrases (`:55-62`) silently drop matching turns (`:125-132,193-201,219-231`) rather than quarantine or flag them; that sub-mechanic is brittle and must not be reused as-is. | Role filtering: implemented+untested. AI-tell handling: weak, replace. |
| Normalization | `scripts/stylometry.py`'s markdown-stripping and corpus-loading functions (code fences, headers, links, frontmatter removed before analysis) plus `extract_author_turns.py`'s cleaning steps (strip code blocks, image tags, HTML) constitute real normalization code. | Implemented+untested |
| Signal extraction | `scripts/stylometry.py` is a substantial, stdlib-only Tier-1 feature extractor: sentence-length distribution, function-word frequency (with a defined function-word list), punctuation rates (with explicit em-dash tracking — directly feeding the anti-AI baseline), hedging/booster density, pronoun rates, distinctive content words (frequency-based, not z-score-based — a design difference from voice-analyser-mcp, see matrix), MATTR lexical diversity, paragraph structure, sentence-initial word patterns, structural markers. Optional Tier 2 (`textstat` for readability) and Tier 3 (`spaCy` for POS rhythm, dependency depth, passive-voice detection) are cleanly separated as *optional* dependencies with graceful degradation implied by `scripts/requirements.txt` framing them as extras. | Implemented+untested for Tier 1 (stdlib path exercised by design); Tier 2/3 are implemented but **conditionally present** — their correctness cannot be verified without executing code with optional deps installed, which this audit does not do; classified partial for the optional tiers specifically |
| Inference | `references/04-rule-mining.md` (methodology, not code) defines three tiers of evidence for deriving a "rule": existing rule files (highest confidence — i.e., previously operator-confirmed statements), extreme statistics (quantified thresholds: e.g., a feature at 0 occurrences, or >5x a stated baseline), and negative space (absent sentence shapes). This is the most rigorous inference methodology of the three repos because it names explicit statistical thresholds and ranks evidence sources by confidence — but the actual comparison baseline ("general English") is qualitative/reference-table-based (citing Mosteller & Wallace-style priors in prose), not a shipped, computed baseline dataset in this repo. | Partial — methodology is real and well-specified; the "baseline" side of the extreme-statistics test is not itself data present in the repository, which the repo's own `references/03-methodology.md` limitations section discloses |
| Confidence/provenance | Explicit preferences outrank inferred rules (`references/04-rule-mining.md:7-18`), and stated preferences override measured features on conflict (`references/08-regeneration-and-diff.md:75-83`). This is the strongest provenance-priority design among the three, but it is not schema-enforced. | Methodology only; partial |
| Profile schema | Output is five Markdown files per voice: `01-generative.md` (exemplars + quantitative targets), `02-corrective.md` (hard bans/soft checks + mechanical scan table), `03-corpus-source.md` (provenance: exact corpus description, size, date), `claude-ai-skill.md` (self-contained export for Claude.ai, which lacks Claude Code's skill mechanism), and a dated `_STYLE-PROFILE-<DATE>.md` summary — defined precisely by the six `templates/generated-*.md` files (real templates, not just described in prose). | Implemented (templates are concrete, inspected) — but schema is Markdown-with-conventions, not machine-validated structured data; no JSON Schema, no parser that enforces required fields exist |
| Storage/indexing | Output lands in the gitignored `voices/<voice-name>/` directory as flat files. No index, no search, no database. `references/08-regeneration-and-diff.md` describes snapshotting the previous version's folder before regenerating (manual "cp the old folder" workflow, not automated). | Implemented (folder convention) but no indexing/search; versioning is a manual-copy convention, not automated |
| Retrieval | None — a single voice's five files are the entire retrievable unit; there is no cross-voice search, no relevance ranking, no partial-context assembly. Multiple "voices" (registers) are supported as entirely separate folders selected by the operator, not retrieved by the system. | Absent (by design — this is a single-profile-at-a-time tool, not a retrieval system) |
| Prompt/context assembly | `write` mode (per `SKILL.md`, mode-detection section) loads a selected voice's generative + corrective files wholesale into context for the write task. No token budgeting, no trimming for the target output's channel/length. | Implemented (whole-file load), not token-aware |
| Generation | Write mode drafts using loaded exemplars/rules, explicitly layering the universal anti-AI baseline (`references/00-universal-baseline.md`, hard bans always active regardless of voice) under the voice-specific rules. | Prompt-driven generation, implemented as instructions, not code — the actual text generation is the calling LLM, same as MYNAH and the narrative-guide half of voice-analyser-mcp |
| Output validation | `references/07-verification.md` is the single strongest validation protocol in the corpus: it defines a held-out-sample test (generate from a prompt never seen during analysis), then runs falsifiable, quantified checks (em-dash count target, semicolon count target, mean sentence length within a stated range, hedging density within a stated range) and an explicit iterate-if-fail loop. This is genuinely deterministic and falsifiable in spirit, though the *checks themselves* would need to be executed by counting characters/words in the generated text — the protocol describes what to count and against what thresholds, but does not ship as a runnable script (it's a procedure for the agent to execute manually via reasoning + counting, not a `verify.py`). | Partial — rigorous methodology, well short of "implemented+tested" because there is no automated checker in the repo; the agent is instructed to do the counting itself, which is not deterministic across runs |
| Feedback/continual learning | `references/08-regeneration-and-diff.md` describes an update workflow: re-run analysis on an expanded corpus, diff old vs. new profile, present the diff to the author, and let stated preferences override new measurements on conflict. This is a real, well-thought-out procedure. | Prompt/docs-only (procedure, not automated) |
| Correction/deletion/rollback/observability | Deletion = delete the `voices/<name>/` folder (filesystem-native, always available, zero special mechanism needed — arguably a strength via simplicity). Rollback = the manual pre-regeneration snapshot convention from stage above. No logs, no diagnostics, no automated recovery. | Implemented (trivially, via filesystem) for deletion; partial/manual for rollback; absent for diagnostics/observability |

**Bottom line for write-like-me:** the strongest repo for the "profile curation" and "voice inference accuracy" pillars specifically because it has real, inspectable, deterministic extraction code (`stylometry.py`, `extract_author_turns.py`) grounded in cited academic methodology, a genuine confidence/provenance hierarchy (measured vs. stated), and the only rigorous verification protocol of the three. Its principal gap is that none of this is packaged as a running, persistent, multi-profile system — it is a single-shot, per-invocation, per-voice Claude Code skill with zero automated tests and zero server/database/scheduler component.

### 3.3 voice-analyser-mcp

| Stage | What voice-analyser-mcp actually does | Classification |
|---|---|---|
| Source acquisition | `src/tools/collect-corpus.ts` + `src/utils/crawler.ts` implement **real, executable, active web-crawling** of a site's XML sitemap/RSS/Atom feed: fetch sitemap → optional regex URL filter → limit article count → fetch each URL's HTML with a declared user-agent and rate-limiting delay. This is the only one of the three repos with genuinely automated source acquisition — but it acquires **public, already-published content**, not private operator conversations/artifacts, and has no allowlist/consent gate beyond "you supply the sitemap URL." | **Implemented+untested** (real code, zero tests) — and structurally misaligned with the mission's "approved operator-authored conversations/artifacts" requirement, since it is built for scraping a public blog/site, not observing an operator's private writing surfaces |
| Operator separation | **Not found anywhere in the tracked source.** `src/utils/cleaner.ts`'s `validateCorpusQuality`/`getCleaningStats` check for HTML/markup artifacts and general "cleanliness," not authorship. README explicitly states the tool "works best with single-author content" and that "mixed authorship weakens statistical signals" — i.e., the repo's own documentation *acknowledges* the contamination problem exists but ships no filter, diarization, or detection logic to address it. Searched all 16 analyzers, `tools/*.ts`, `utils/*.ts` for "author", "human", "contaminat" — matches are limited to README prose and a couple of docstring comments about "the writer," none of which gate or filter content by authorship. | **Absent** |
| Normalization | `src/utils/extractor.ts` (Cheerio-based HTML→Markdown via Turndown, with a defined removal list for `<script>`/`<nav>`/`<footer>`/etc.) and `src/utils/cleaner.ts` (`cleanArticleContent`: strips base64 images, bare URLs, HTML tags, shortcodes, code blocks; normalizes whitespace; `isValidWord` token filter). Real, substantial, well-factored normalization code. | Implemented+untested |
| Signal extraction | The deepest and most creative feature set of the three repos: 16 analyzer modules covering vocabulary tiers, punctuation, sentence/paragraph structure, function words (with hardcoded general-English reference means/SDs in `src/reference/function-words.ts`), z-score-based distinctive-word detection (`src/utils/zscore.ts`), burstiness/clustering/entropy (`src/utils/advanced-statistics.ts` — genuinely sophisticated: coefficient-of-variation-based burstiness, consecutive-similar-value clustering, Shannon-entropy diversity), "micro-rhythm" detection (`src/utils/micro-rhythm.ts` — mid-thought pivots, dash interruptions, parentheticals, self-correction, sentence fragments), argument-flow pattern matching with a genuine confidence score (`src/analyzers/argument-flow.ts`), specificity/possessive-vs-generic reference analysis (`src/analyzers/specificity-patterns.ts`), and vulnerability/admission-pattern detection (`src/analyzers/vulnerability-patterns.ts`). All are real, deterministic, regex/statistics-based TypeScript — not prompt instructions. | **Implemented+untested** across the board — every analyzer is real code with zero tracked tests validating its regex/statistical correctness against known fixtures |
| Inference | Each analyzer's `interpretXxx()`/`generateGuidance()` functions convert raw counts/ratios into qualitative interpretation strings (e.g., "High specificity — strong personal ownership") using hardcoded ratio thresholds (e.g., `>0.4`, `>0.25`, `>0.15` bands in `specificity-patterns.ts`; `>0.8`, `>0.5`, `>0.3`, `>0.1` bands in `vulnerability-patterns.ts`). These thresholds are not derived from a cited study or computed baseline in-repo — they read as engineering judgment calls, weaker grounding than write-like-me's cited-methodology approach. | Implemented+untested; inference thresholds are **undocumented heuristics**, not evidenced against an external baseline |
| Confidence/provenance | `src/analyzers/argument-flow.ts:199-241,246-289,293-337,341-406` computes a strong-match ratio and maps it to a confidence band. It is the clearest implemented confidence mechanic among the three, but it is isolated and untested; no system-wide provenance exists. | Partial |
| Profile schema | `src/tools/analyze-corpus.ts` writes one JSON file per analyzer to an `analysis/` subdirectory (ad hoc per-analyzer TypeScript interfaces, not a single unified schema) plus summary Markdown. There is no single canonical "profile" object; the 16 JSON files are the closest thing to a schema, and they are heterogeneous by construction (each analyzer defines its own interface). | Implemented (as 16 independent shapes), not unified — a real gap relative to the "standardized... profile" requirement in the mission |
| Storage/indexing | Flat files on disk under a corpus directory (`<corpus>/analysis/*.json`, `<corpus>/*.md`). No database, no index, no search. Each `generate_style_guide` run reads the JSON files fresh and overwrites the guide — no history retained. | Implemented (flat-file), no indexing, no versioning |
| Retrieval | None — `generate-narrative-guide-v4.ts` loads *all* analyzer JSON files unconditionally to build one guide; there is no query, no relevance filter, no channel/audience-specific subset selection. | Absent |
| Prompt/context assembly | The generated style guide *is* the context-assembly artifact — an "example-first" Markdown document meant to be loaded wholesale into a downstream writing conversation. No token budgeting is visible; guide length scales with corpus richness and number of extracted patterns/phrases, uncapped. | Implemented (single monolithic document), not token-aware |
| Generation | Out of scope for this MCP server — it produces a *style guide*, not generated prose. Actual voice-matched writing is left entirely to whatever downstream LLM conversation loads the guide. This is an honest scope boundary (unlike MYNAH, which claims to both learn and compose) but means voice-analyser-mcp only covers roughly half of the mission's pillar C ("reliable application") — style-guide production, not generation or validation of generated output. | Implemented (guide generation) for the artifact; **absent** for actual downstream-generation and its validation |
| Output validation | The generated guide includes a "validation checklist" section (a static list of rules the *human or downstream model* should self-check against) — this is advisory content embedded in the artifact, not an automated validator run by this tool against any actual generated text. There is no round-trip: nothing in this repo ever checks a piece of writing against the guide it produced. | Prompt/docs-only (the checklist is instructions for a human/LLM, not executed code) |
| Feedback/continual learning | Not found. No mechanism to record whether a generated style guide's rules were accurate, useful, or corrected after the fact; no diff between guide versions across corpus updates. | Absent |
| Correction/deletion/rollback/observability | Deletion = delete the corpus directory (filesystem-native). No structured export/inspection beyond reading the raw JSON files directly. No logs, no diagnostics, no recovery path if a crawl partially fails (though `collect-corpus.ts` does report a cleaning-summary and per-article success/failure count, which is a *reporting* feature, not a recovery one). | Implemented (trivial, filesystem-based) for deletion; absent for rollback/diagnostics/recovery |

**Bottom line for voice-analyser-mcp:** the only repo with a real, running MCP server and the richest, most creative deterministic feature-extraction codebase of the three — genuinely strong on rhetorical/structural signal richness (argument-flow, micro-rhythms, burstiness/clustering, specificity, vulnerability). Its two disqualifying structural mismatches with the mission are (1) source acquisition is built for public web content, not private approved operator artifacts, with **zero operator/AI or single-vs-multi-author contamination filtering**, and (2) a meaningful fraction of its analyzer guidance (see §4, harmful/misleading findings) is explicitly framed as *AI-detection evasion* rather than *authentic voice fidelity*, which is a different and more ethically fraught product goal than the one this mission specifies.

## 4. Component ratings

Rating scale is relative to the three audited repos: **strongest-of-three** (retain/adapt), **strong** (retain, harden), **useful** (redesign), **weak** (replace), **harmful/misleading** (exclude).

### 4.1 Strongest among the three (retain or adapt)

| Component | Repo | Why | Reuse decision |
|---|---|---|---|
| Role-metadata operator-turn extraction | `scripts/extract_author_turns.py` (write-like-me) | Only deterministic Claude/ChatGPT role filtering among the three (`:182-235`). Its AI-tell phrase auto-drop is explicitly excluded. | **Adapt** role/sender parsing; replace phrase auto-drop with provenance-preserving quarantine and review. |
| Measured-vs-stated precedence rule | `references/08-regeneration-and-diff.md` (write-like-me) | The single clearest, most defensible provenance-priority design found: operator-declared preferences outrank code-measured statistics on conflict, and both are retained (not silently merged). Directly matches the mission's "operator-confirmed"/"operator-corrected" state requirement. | **Behavioral reimplementation** — the concept (not the prose) becomes a first-class rule in the target profile-state machine. |
| Held-out verification protocol | `references/07-verification.md` (write-like-me) | Genuinely falsifiable: names concrete, countable target metrics (em-dash count, semicolon count, mean sentence length band, hedging density band) and an explicit fail→iterate loop, applied to text the analysis never saw. | **Behavioral reimplementation** — as an automated checker, since the source repo only specifies the procedure, not a script. |
| Context taxonomy (10 communication contexts) | `skills/mynah/references/context-guide.md` + `style-dimensions.md` (MYNAH) | Practical, exhaustive, well-disambiguated (explicit "watch for" pitfalls per context) — the best channel/audience segmentation scheme found, even though MYNAH never enforces it in code. | **Adapt** — reuse the taxonomy and its disambiguation heuristics as the target system's channel/context schema; re-author as structured data, not prose. |
| Burstiness / clustering / entropy statistics | `src/utils/advanced-statistics.ts` (voice-analyser-mcp) | Real, statically plausible pure functions (`:8-122`) for descriptive variation. Runtime correctness is unverified because no tests were run or tracked. | **Behaviorally port and test** under Apache-2.0 attribution; discard detector-evasion interpretation. |
| Argument-flow confidence scoring | `src/analyzers/argument-flow.ts` (voice-analyser-mcp) | The only per-claim confidence mechanism in any of the three repos that is actually computed from match-strength ratios rather than asserted. | **Adapt** — generalize the confidence-scoring pattern (strong-match-ratio → confidence band) and apply it across every signal type in the target system, closing the "isolated, not system-wide" gap noted in §3.3. |

### 4.2 Strong (retain, harden)

| Component | Repo | Why | Gap to harden |
|---|---|---|---|
| `stylometry.py` Tier-1 feature extractor | write-like-me | Broad, stdlib-only, cited-methodology feature set (sentence length, function words, punctuation, hedging, pronouns, MATTR, paragraph/sentence-initial structure). | Zero tests; needs fixtures + unit tests before reuse; Tier 2/3 optional-dependency paths unverified by this audit. |
| Micro-rhythm detector | `src/utils/micro-rhythm.ts` (voice-analyser-mcp) | Computes descriptive patterns such as mid-thought pivots, dash interruptions, parentheticals, self-correction, and fragments. | Needs tests and the "detection risk"/evasion framing stripped (see §4.4); retain only operator-grounded descriptive signals. |
| Function-word z-score analysis | `src/utils/zscore.ts` + `src/reference/function-words.ts` (voice-analyser-mcp) | Uses a standard z-score shape to flag word usage relative to a reference distribution. | Runtime correctness is untested, and the hardcoded reference means/SDs are uncited; both implementation and baseline need validation before reuse. |
| Profile schema convention (Markdown, required+optional fields) | `skills/mynah/references/profile-schema.md` (MYNAH) | Clear, human-inspectable, complete worked example. | Needs to become a machine-validated structured schema (JSON Schema or typed store) — currently unenforced prose convention. |

### 4.3 Useful (redesign before reuse)

| Component | Repo | Why useful but not as-is |
|---|---|---|
| Sitemap/RSS corpus collector | `src/tools/collect-corpus.ts` + `crawler.ts` (voice-analyser-mcp) | The crawling/rate-limiting/HTML-extraction mechanics are solid engineering, but the *source model* (public sitemap) is wrong for this mission. Reusable only as one allowlisted collector type among several (e.g., "operator's own public blog," explicitly consented) — never as the primary or default collector for private operator conversations. |
| Rule-mining tiering (files > extreme stats > negative space) | `references/04-rule-mining.md` (write-like-me) | Good evidence-ranking idea, but expressed only as prose methodology for an LLM to follow by hand; needs to become an actual scored/weighted algorithm operating over stored signal records, not a manual reading exercise. |
| Style-guide "example-first" generator | `src/tools/generate-narrative-guide-v4.ts` (voice-analyser-mcp) | Genuinely good instinct (show, don't just tell) but married to a monolithic, uncapped, non-token-budgeted single document with no retrieval — needs to become a token-budgeted, query-able context-assembly step, not a static file. |

### 4.4 Weak (replace)

| Component | Repo | Why weak |
|---|---|---|
| "Imperfection preservation" (deliberate typo/informality replication) | MYNAH `README.md`, `skills/mynah/SKILL.md` | Sound in principle (real voices have quirks) but shipped with zero contamination gating and zero context-appropriateness check beyond the LLM's own judgment — risk of reproducing an embarrassing or context-inappropriate quirk (e.g., a casual abbreviation) in a formal-audience draft if context classification is even slightly wrong, with no deterministic guard. Replace with a signal that is scored, contextually scoped, and gated by explicit context-match confidence rather than blanket "always reproduce." |
| Whole-profile, uncapped context injection | MYNAH `SKILL.md` COMPOSE mode; voice-analyser-mcp's monolithic guide | Neither has any token budget or relevance filter; both simply load everything. This does not scale and directly contradicts the mission's "retrieve only relevant profile context" requirement and the "token efficiency" optimization target. Replace with token-budgeted, relevance-ranked retrieval. |
| Hardcoded, uncited inference thresholds | Every `interpretXxx()` function across voice-analyser-mcp's 16 analyzers (e.g., ratio bands in `specificity-patterns.ts`, `vulnerability-patterns.ts`) | Plausible-looking but unevidenced cutoffs (why is `0.4` "high specificity" and not `0.35`?). Useful as a *starting point* for signal computation, but the qualitative-label mapping needs to be replaced with either a cited baseline or an explicitly-labeled-as-heuristic confidence band, not presented as settled fact. |

### 4.5 Harmful/misleading (exclude)

| Component | Repo | Why harmful/misleading | Evidence |
|---|---|---|---|
| AI-detection-evasion framing of style guidance | `src/analyzers/clustering.ts`, `src/analyzers/expression-markers.ts`, and the "detection risk" language repeated across several analyzers/guide sections (voice-analyser-mcp) | The mission asks for writing that is genuinely, durably in the operator's authentic voice. Several analyzers instead frame their guidance explicitly as adversarial anti-AI-detector tooling — e.g., instructing the reader to "ADD deliberate fragments" and vary sentence length specifically because uniform length is what "AI" tends to produce, with guidance keyed to a "detection risk" label rather than "does this match how the operator actually writes." This conflates two different goals (authentic voice replication vs. evading AI-content detectors) and could push generated output toward performing quirks the operator does not actually have, purely to look more "human" to a detector. That is a form of manufactured inauthenticity — the opposite of the mission's intent. | `clustering.ts` guidance text keyed on burstiness/uniformity explicitly discusses avoiding "AI-like uniformity"; `expression-markers.ts` docstring explicitly contrasts "human typical rates" against "AI usage" and issues directives like "AI rarely uses fragments. ADD deliberate fragments" — a directive to inject a pattern *because* AI avoids it, not because the operator's real corpus shows the pattern at that rate for that specific piece. |
| Unverifiable marketing claims embedded as changelog fact | `CHANGELOG.md` (voice-analyser-mcp) — e.g., stated ROI/efficiency-gain and "first-pass acceptance rate" figures | Per the mission's own instruction ("README claims are not implementation evidence"), a changelog asserting specific business-outcome numbers with no methodology, no linked study, and no reproducible measurement in this repository is not evidence of anything and should not inform scoring or be carried into the target system's marketing/positioning without independent verification. | Reviewed in full; no supporting methodology, dataset, or computation exists anywhere in the tracked source for these figures. |
| "Zero personal data" claim as a privacy guarantee | MYNAH `README.md` | Technically true of *this git repository's contents*, but presented in a way that could be read as a broader privacy guarantee about the overall system. The actual operator data lives entirely in an external, unaudited memory backend (PACK or Claude's built-in memory) that this repo neither controls nor documents the retention/deletion/access-control behavior of. Carrying this claim forward into the target system's documentation without the caveat would be misleading. | `README.md`'s privacy section; cross-checked against the complete absence of any in-repo storage code (§3.1). |

## 5. Cross-repo component matrix

Legend: **T** = implemented+tested, **U** = implemented+untested, **P** = partial, **D** = prompt/docs-only, **A** = aspirational, **–** = absent (not found; search scope = full tracked source of each repo, patterns noted per row where non-obvious).

| Component area | MYNAH | write-like-me | voice-analyser-mcp |
|---|---|---|---|
| Transcript/artifact ingestion | D (manual paste, no connector) | U (`extract_author_turns.py` parses Claude/ChatGPT export JSON + Markdown) | U (`collect-corpus.ts`/`crawler.ts`; public web only, not artifact ingestion in the private-conversation sense) |
| Operator-turn extraction | D (asked, not verified) | **U (strongest of these three; see §4.1)** | – (searched "author"/"human"/"turn" across all analyzer/tool/util files; no per-turn diarization exists) |
| AI/quoted-text contamination prevention | – (searched all 5 md files; no mechanism) | P (role filtering is useful; hard-coded AI-tell matches are silently discarded, not quarantined; quoted/forwarded text remains unresolved) | – (README acknowledges mixed-author risk; no filter found) |
| Stylometric features | D (taxonomy only, no computation) | U (`stylometry.py` Tier 1-3) | U (16 analyzers; the deepest feature set of the three) |
| Qualitative rule mining | D (LLM pattern extraction; only repeated misspellings get a documented 3+ heuristic) | P (`04-rule-mining.md` tiered methodology; not automated) | P (`interpretXxx()` heuristic bands per analyzer; undocumented thresholds) |
| Context/channel segmentation | D (10-context taxonomy; best design, not enforced) | P (register = whole separate voice folders, coarse-grained) | – (single corpus = single style guide; no channel dimension modeled) |
| Schema/taxonomy/indexing | D (Markdown convention, unenforced) | U (5-file-per-voice convention; templates are concrete) | U (16 heterogeneous per-analyzer JSON shapes; no unifying schema) |
| Provenance/confidence | P ("Samples used"/date only) | P (measured-vs-stated hierarchy; not schema-enforced) | P (one analyzer has real confidence scoring; not system-wide) |
| Conflict resolution/temporal decay/drift | D ("note the shift," no mechanism) | D (diff-on-regeneration procedure, manual) | – (guides are overwritten wholesale; no diff, no decay) |
| User correction | D (ask the agent; routes to opaque external memory) | U (edit/delete Markdown files directly — trivial but real) | U (edit/delete JSON/MD files directly — trivial but real) |
| Retrieval/context assembly | D (flat exact-context-ID lookup, whole-profile injection) | – (single voice loaded wholesale; no retrieval concept) | – (single guide loaded wholesale; no retrieval concept) |
| Prompt generation/output rendering | D | D (write-mode drafting instructions) | – (this repo stops at guide generation; does not render output itself) |
| Post-generation audit/held-out evaluation | D (self-check bullet list) | **P (`07-verification.md`; strongest methodology among these three, not automated — see §4.1)** | D (static "validation checklist" embedded in guide; not executed by this tool) |
| MCP/skill/hook/CLI/scheduler integration | Claude plugin/skill only | Claude Code skill only | **Real MCP server (3 tools), plus a `bin` CLI entry — the only true MCP integration of the three** |
| Privacy/sensitive-data/deletion/rollback | A (claims "zero personal data" in-repo; no in-repo mechanism; delegates to unaudited external store) | P (filesystem deletion works; no allowlist/consent/retention controls) | – (no allowlist/consent/retention controls; crawls public data so lower sensitivity, but caches indefinitely with no documented retention policy) |
| Logs/diagnostics/recovery | – | – | P (`collect-corpus.ts` reports per-article success/failure counts — reporting, not recovery) |
| Tests/docs/packaging | Docs: strong. Tests: – . Packaging: Claude plugin manifest present. | Docs: strong (9 numbered references, including verification). Tests: –. Packaging: skill convention plus optional-dependency requirements. | Docs: strong. Tests: – (`.gitignore:11-14` excludes `test-*`). Packaging: real `package.json`/`bin`/MCP registration — most production-shaped of the three. |

### 5.1 Weighted score rationale and anchors

Scores are comparative weighted points against the mission, not a market rating or implementation pass/fail result. A component can earn points for useful design or untested code; **none is production-adoptable as a whole** because every repo lacks tracked tests and each misses at least one core pillar. No numeric score is mapped to the T/U/P/D/A implementation labels; they answer different questions.

| Dimension (max) | MYNAH | write-like-me | voice-analyser-mcp |
|---|---|---|---|
| Passive acquisition / source coverage (15) | **3** — connector instructions only (`skills/mynah/references/sample-collection.md:3-64`) | **5** — real export parsing, operator-triggered (`scripts/extract_author_turns.py:104-179,182-277`) | **6** — automated but public-web-only collection (`src/tools/collect-corpus.ts:34-155`) |
| Voice inference sophistication (15) | **3** — rich LLM-applied taxonomy, no computation (`skills/mynah/SKILL.md:170-197`) | **9** — broad deterministic stylometry (`scripts/stylometry.py:197-493`) plus evidence-tier methodology (`references/04-rule-mining.md:7-76`) | **7** — broad deterministic analyzers and confidence code (`src/utils/advanced-statistics.ts:8-157`; `src/analyzers/argument-flow.ts:199-406`) reduced for uncited thresholds and evasion framing |
| Curation/schema/provenance (15) | **5** — clear schema, weak provenance, no validation (`skills/mynah/references/profile-schema.md:8-50,145-165`) | **8** — explicit-vs-measured hierarchy and concrete output templates (`references/04-rule-mining.md:7-18`; `references/08-regeneration-and-diff.md:65-83`) | **5** — heterogeneous analyzer JSON, isolated confidence only (§3.3) |
| Retrieval/context efficiency (10) | **4** — context IDs and compactness target, exact lookup only (`skills/mynah/references/profile-schema.md:156-165`; `skills/mynah/SKILL.md:232-248`) | **3** — selected voice files loaded as a unit; no ranking (§3.2) | **2** — all analysis files feed one guide (`src/tools/generate-narrative-guide-v4.ts:16-45`) |
| Application/generation/evaluation (15) | **1** — prompt generation plus self-check, no falsifiable evaluator (`skills/mynah/SKILL.md:205-254`) | **6** — generation procedure plus held-out checks (`references/07-verification.md:13-64`) | **1** — produces a guide but neither prose nor round-trip validation (`src/index.ts:91-128`) |
| Privacy/security/sensitive-data lifecycle (10) | **2** — data delegated out of repo (`MYNAH/README.md:54-84`) | **3** — local flat files but no policy controls (§3.2) | **3** — public-source bias lowers default sensitivity, but path/network/retention controls are absent (§3.3) |
| Resilience/recovery/observability (5) | **0** — absent | **1** — manual snapshots (`references/08-regeneration-and-diff.md:17-32`) | **2** — per-article errors and cleaning summary (`src/tools/collect-corpus.ts:54-155`), no recovery |
| Performance/token efficiency (5) | **1** — compact profile guidance only (`skills/mynah/references/profile-schema.md:156-165`) | **1** — no runtime/context budgets | **1** — uncapped guide and sequential crawl (`src/tools/collect-corpus.ts:59-100`) |
| Operator experience/friction (5) | **3** — strongest context/compose UX of the three (`skills/mynah/references/context-guide.md:9-223`; `skills/mynah/SKILL.md:218-248`) | **2** — export-and-folder workflow | **3** — concise three-tool MCP surface (`src/index.ts:24-128`) |
| Maturity/maintainability (5) | **1** — prompt-only, no tests/CI | **3** — modular scripts/docs, no tests/CI | **3** — typed packaging and modular source, no tests and dead dependencies (§2.3) |
| **Total /100** | **23** | **41** | **33** |

## 6. Licensing and attribution

| Repo | License | Obligations | Reuse decision (per component; see §4) |
|---|---|---|---|
| MYNAH | MIT | Retain copyright/license notice if copying substantial text; no copyleft, no attribution-in-output requirement beyond standard notice retention. | No components rated for direct **copy**; context-taxonomy content is rated for **adapt** (re-authored as structured data, not verbatim copy) — MIT permits this freely; retain a source-attribution note in the target repo's own licensing/NOTICE material as good practice, not a legal requirement given no verbatim copying is planned. |
| write-like-me | MIT | Same as above. | `extract_author_turns.py` logic and the measured-vs-stated/verification-protocol concepts are rated **adapt** / **behavioral reimplementation** respectively — MIT permits direct copy too, but behavioral reimplementation is chosen deliberately (see Decision Log in the build plan) to avoid carrying forward the zero-test-coverage liability wholesale. |
| voice-analyser-mcp | Apache-2.0 | Retain copyright/license/NOTICE; state changes if redistributing modified files; Apache-2.0 includes an explicit patent grant/termination clause (standard, low practical risk here since no patents are asserted in-repo). | `advanced-statistics.ts` pure statistical functions are rated **copy/adapt** — Apache-2.0 permits this with attribution retained. The AI-detection-evasion-framed guidance text is explicitly rated **reject** (see §4.5) and will not be carried forward in any form, license permissions notwithstanding — this is a product-fit and ethics decision, not a licensing one. |

No GPL/AGPL/copyleft exposure was found in the three tracked license files. CLA/contribution requirements were not probed because this plan reimplements or attributes under the published licenses rather than contributing upstream.

## 7. Vendor-repo integrity verification

Re-verified at the close of this audit pass (immediately before writing this section):

```
MYNAH:               git status --porcelain -> empty; HEAD == 470c63b7ca0a3a66477c3072ab8680d19cb11371
write-like-me:        git status --porcelain -> empty; HEAD == 3878d9dbfb57a28ea414c891623b57612b6e1734
voice-analyser-mcp:   git status --porcelain -> empty; HEAD == 7608d4e9a6b3a4dec465e31bd6338cd1b916cf7b
```

All three unchanged from the values recorded in §1. No commits, no staged/unstaged changes, no untracked files introduced by this audit. No dependency installation, build, execution, or network fetch was performed against any vendor repo during this pass.

## 8. Independent review findings and limits

Five independent territories reviewed the audit/plan pair: architecture, data lifecycle, privacy, security, and evidence coherence. The audit-specific findings were corrected here:

- scoped working-tree integrity to committed `HEAD`, not upstream identity;
- removed unprobed write-access/release/activity inferences;
- replaced approximate citations supporting material selection/scoring claims with §2.5 exact source lines;
- corrected the initial misreading of write-like-me’s AI-tell behavior (silent auto-drop, not review flagging);
- bounded all comparative superlatives to the three audited repos;
- added §5.1 cell-level score rationale and removed any invented numeric-to-T/U/P/D/A threshold.

Review protocol status:

- The deterministic gate required a verifier because open P1 findings touched D03, D04, D05, D06, and D12.
- Dispatches reached the absolute ceiling of nine: one probe, five reviewers, and three correction retries.
- The swarm contract permits only one retry; the run therefore exceeded its retry allowance. No further dispatch, verifier, or second pass is permitted.
- **Formal shipping clearance: `not_evaluated`.** The independent first-pass findings are useful evidence, but this run is not represented as protocol-compliant swarm clearance.
- Dedicated testing/performance and governance reviewers were not dispatched; those dimensions remain parent-authored plan requirements rather than independently cleared territories.

---

*End of forensic audit. See `operator-voice-toolkit-build-plan-v4.md` for the scoring rubric, target architecture, evaluation design, milestone plan, and pre-swarm self-assessment.*
