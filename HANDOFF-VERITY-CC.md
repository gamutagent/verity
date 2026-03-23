# HANDOFF: Verity — Open Source Information Scanner

## What This Is

Verity is a new open-source project under the Gamut Intelligence GitHub org. It is a config-driven, security-hardened information scanner with three-layer AI content authenticity detection. It was designed and scaffolded in an Opus strategy session on 2026-03-22.

**Motto: "Trust, but verify." Verity handles trust. Gamut handles verify.**

Verity is the open-source Layer 1 of the Gamut Trust Stack:
- **Layer 1 (Verity, open source):** Source trust — is this content authentic?
- **Layer 2 (Gamut, product):** Claim trust — is this entity real? Registry verification, CVI scoring.
- **Layer 3 (Gamut IC Memo, product):** Synthesis trust — is the analysis faithful to evidence?

## Strategic Context

- Verity is Gamut's first public GitHub presence, designed to build developer credibility and serve as an on-ramp to Gamut's paid API.
- The Gamut integration hook is already wired as a config section (`gamut:` in config.yaml) and a stub method in scanner.py. When enabled, discovered entities are verified via Gamut MCP tools.
- LinkedIn launch posts are drafted and coordinated between Vinay and Arjun, timed to ride GTC/NemoClaw and Claude Code Channels news cycle.
- Naming is final. Do not rename. "Verity" is the project name. "Trust, but verify" is the tagline.

## What's In The Folder

```
verity/
├── config.example.yaml         # Full config reference with all sections
├── config/
│   └── source_reputation.yaml  # Tiered domain trust DB (~80 domains, 3 tiers + blocklist)
├── .env.example                # API key template
├── docker-compose.yml          # Cloud-agnostic Docker deployment
├── Dockerfile                  # Non-root, production-ready
├── requirements.txt            # Minimal: aiohttp + pyyaml core; cloud SDKs optional
├── src/
│   ├── scanner.py              # Main orchestrator (class Verity). Entry points: CLI + Cloud Function HTTP handler
│   ├── searcher.py             # Web search abstraction (Serper, Tavily, Brave)
│   ├── scorer.py               # LLM relevance scoring (Gemini, OpenAI, Anthropic, Ollama)
│   ├── authenticity.py         # 3-layer AI content detection:
│   │                           #   Layer 1: SourceReputation (YAML-driven domain tiers, zero cost)
│   │                           #   Layer 2: ContentHeuristics (7 deterministic Python checks, zero cost)
│   │                           #   Layer 3: LLMAuthenticityDetector (optional, 1 API call/article)
│   │                           #   Composite: source×0.30 + heuristic×0.35 + llm×0.35
│   │                           #   Also contains ContentFetcher for fetching article text
│   ├── notifier.py             # Slack, Telegram, generic webhook — shows relevance + authenticity badge
│   ├── store.py                # Dedup + approval state + export (Firestore / SQLite / local JSON)
│   ├── secrets_resolver.py     # Pluggable secrets: env, .env, GCP Secret Manager, AWS SM, Azure KV
│   ├── config_loader.py        # YAML loading + secrets validation via resolver
│   └── audit.py                # Append-only JSONL audit log (search, score, authenticity, approval events)
├── scripts/
│   ├── deploy.sh               # Unified entry point — auto-detects cloud or explicit gcp/aws/azure/docker
│   ├── deploy-gcp.sh           # Cloud Run + Cloud Scheduler + Secret Manager
│   ├── deploy-aws.sh           # ECS Fargate + EventBridge + Secrets Manager
│   ├── deploy-azure.sh         # Container Apps + Timer Trigger + Key Vault
│   └── crontab                 # For Docker/VPS cron-based scheduling
├── tests/                      # EMPTY — needs test suite (see Task 3)
├── docs/                       # EMPTY — architecture.md placeholder
├── SECURITY.md                 # Full threat model and security boundaries doc
├── LICENSE                     # Apache 2.0
└── .gitignore
```

## Current State

- All source files are complete and internally consistent.
- Naming sweep done: zero references to old name "intel-sweep" remain.
- No tests exist yet.
- `_enrich_with_gamut()` in scanner.py is a stub (logs and returns item unchanged).
- The LLM authenticity detector reuses the scorer's provider infrastructure but has a known design note: it sends its own system prompt via user message rather than having a separate call path. Acceptable for v1.
- No `__init__.py` files in src/ — needed for proper Python packaging.
- No `setup.py` or `pyproject.toml` — needed if we want `pip install verity`.

---

## Tasks For CC

### Task 1: Wire Gamut Enrichment Stub

**File:** `src/scanner.py`, method `_enrich_with_gamut(self, item: dict) -> dict`

**What it should do:**
1. Extract entity names from the item's title and snippet (simple NER or regex for capitalized multi-word sequences is fine for v1).
2. For each candidate entity, call the Gamut API endpoint (`POST {api_base}/verify`) with the entity name.
3. Attach the verification result to the item under `item["gamut_verification"]` as a list of dicts:
   ```python
   {
       "entity_name": "BlueShark Pte Ltd",
       "confidence_score": 62,
       "registry_status": "struck_off",
       "registry_source": "ACRA",
       "verified_at": "2026-03-22T..."
   }
   ```
4. If the API call fails or times out (5s), log warning and return item unchanged.
5. API base URL comes from `self.config["gamut"]["api_base"]`.
6. API key is resolved via the secrets resolver: `self.config["_secrets"].resolve(self.config["gamut"]["api_key_env"])`.

**Design constraints:**
- Async (use aiohttp, already a dependency).
- Respect rate limits — don't call for every keyword match, only for items that passed both relevance and authenticity thresholds.
- This is already the case in the current pipeline flow — the stub is called after both checks.

**Update notifier.py** to include Gamut verification badge in Slack/Telegram messages when present:
```
🟢 BlueShark Pte Ltd raises Series A
Relevance: 0.91 | Authenticity: ✅ HIGH | Gamut: 🔴 STRUCK OFF (CVI: 62)
```

### Task 2: Draft ADR-020 — Trust Scoring Protocol

**Location:** Should go in the main gamut-agent-orchestrator repo under `docs/adr/ADR-020-trust-scoring-protocol.md`, NOT in the Verity repo.

**Purpose:** Formalize the three-layer trust architecture as a generalizable framework before Verity is published. This ADR serves as timestamped inventorship evidence that the pattern was conceived as platform infrastructure, not a one-off tool.

**Content the ADR must cover:**

1. **Context:** Gamut's verification confidence score (CVI) and Verity's authenticity score share identical architectural DNA — source-attributed claims, deterministic composite scoring, weighted components, audit lineage. This ADR formalizes the pattern as a reusable protocol.

2. **Three-layer trust model:**
   - Layer 1: Source Trust (Verity) — is the information source credible? Source reputation, content authenticity, authorship signals.
   - Layer 2: Claim Trust (Gamut) — are the specific factual claims verifiable? Registry matching, cross-source validation, CVI scoring.
   - Layer 3: Synthesis Trust (IC Memo) — is the synthesized conclusion faithful to evidence? NarrativeEngine, glass-box principle, source lineage.

3. **Shared scoring protocol properties:**
   - Deterministic Python computation, no LLM in the scoring formula itself
   - Weighted composite of independent signals
   - Each signal is source-attributed with lineage
   - Configurable weights per vertical/use case (Trust Templates)
   - Append-only audit trail on every scoring decision
   - Human-in-the-loop approval gate

4. **Verity as open-source reference implementation** of Layer 1.

5. **IP note:** This ADR, combined with ADR-010 (Entity Workspace), ADR-012 (Context View Separation), and ADR-016 (Shell Architecture), establishes the trust scoring protocol as a conceived framework predating public release. Reference provisional patents 63/960,800 and 63/975,910. Flag for patent counsel review when moving to utility filing.

6. **Decision:** Accepted. Verity to be published under Apache 2.0 as Layer 1 reference implementation. Layers 2 and 3 remain proprietary Gamut IP.

**Format:** Follow existing ADR format in the repo (Status, Context, Decision, Consequences, Rejected Alternatives).

### Task 3: Test Suite

**Location:** `verity/tests/`

**Framework:** pytest + pytest-asyncio

**Required test files:**

1. **`tests/test_authenticity.py`** (highest priority)
   - Test `SourceReputation.score()` with tier_1, tier_2, tier_3, unknown, and blocklisted domains
   - Test subdomain resolution (blog.reuters.com → reuters.com → tier_1)
   - Test `ContentHeuristics.analyze()` with:
     - Clean human-written text (expect score > 0.8)
     - AI-generated text with heavy hedge phrases (expect score < 0.5)
     - Text with uniform sentence lengths (expect penalty signal)
     - Clickbait titles (expect penalty signal)
     - Text with good sourcing (quotes, dates, named sources — expect bonus)
   - Test `AuthenticityResult.to_dict()` and `.emoji` property
   - Test composite score calculation with and without LLM layer (weight redistribution)

2. **`tests/test_scorer.py`**
   - Test scoring prompt construction
   - Test score clamping (0.0–1.0)
   - Test JSON parse failure returns 0.0
   - Mock the LLM provider calls (don't make real API calls in tests)

3. **`tests/test_store.py`**
   - Test LocalJSONStore: save, seen, approve, discard, get_pending
   - Test SQLiteStore: same operations
   - Test deduplication (save same URL hash twice, verify seen() returns True)
   - Test approved output writes (JSONL and markdown formats)

4. **`tests/test_config.py`**
   - Test config loading with valid YAML
   - Test missing required fields raise ValueError
   - Test security warning on 0.0.0.0 bind address
   - Test secrets validation with missing env vars

5. **`tests/test_scanner.py`**
   - Integration test with mocked searcher, scorer, and store
   - Test that items below relevance threshold are not authenticity-checked (efficiency)
   - Test that items below authenticity min_score are blocked
   - Test auto-approval requires BOTH high relevance and high authenticity
   - Test Gamut enrichment is only called when config enables it

6. **`tests/conftest.py`**
   - Shared fixtures: sample config dict, sample items, mock search results
   - Temp directory fixtures for local JSON and SQLite stores

**Design rules:**
- Zero real API calls. Mock all external services.
- Each test file must be independently runnable.
- Use `tmp_path` fixture for file-based stores.
- Test the deterministic parts exhaustively. Test the LLM-dependent parts via mocking.

### Task 4: Packaging Cleanup (do after Tasks 1-3)

- Add `src/__init__.py`
- Add `pyproject.toml` with project metadata (name: verity, version: 0.1.0, license: Apache-2.0, author: Gamut Intelligence)
- Verify all imports work when running from repo root: `python -m src.scanner`
- Run a local smoke test: `python src/scanner.py --help` should not crash
- Verify `.gitignore` covers all transient files

---

## What NOT To Change

- Project name, tagline, or positioning language in README/SECURITY.md
- The three-layer authenticity scoring architecture or weight distribution
- The config.example.yaml structure (it's referenced in LinkedIn posts being drafted)
- Apache 2.0 license
- The security model (localhost binding, no plugins, audit-everything)

## Reference

- Opus session: 2026-03-22 (this handoff)
- Related ADRs: ADR-010, ADR-012, ADR-015, ADR-016, ADR-019
- Provisional patents: 63/960,800, 63/975,910
- Gamut MCP tools: gamut_verify_entity, gamut_entity_profile, gamut_landscape, gamut_conflict_check
- Competitor context: OpenClaw (open source), NemoClaw (Nvidia), Claude Code Channels (Anthropic)
- Verity GitHub target: github.com/gamut-ai/verity
