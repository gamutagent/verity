# Verity

**Config-driven information scanner with three-layer AI content authenticity detection.**

Verity monitors topics you define, scores results for relevance using the LLM of your choice, and — before surfacing anything — runs every item through a three-layer authenticity pipeline to filter out low-credibility sources, AI-generated noise, and press release spam.

Built by [Gamut Intelligence](https://gamutagent.ai).

## Why This Exists

Most search-and-score pipelines have the same blind spot: they score *relevance* but not *authenticity*. A high-relevance score on a PR Newswire repost or an AI-generated article is noise, not signal. Verity adds a second gate before anything reaches you.

- **Three-layer authenticity scoring** — source reputation, content heuristics, and optional LLM-based detection run on every item before it surfaces
- **Scoped by design** — searches and scores. No filesystem access, no email sending, no autonomous tool chaining
- **Localhost by default** — binds to `127.0.0.1`. Never `0.0.0.0`
- **Audit everything** — every search query, relevance score, and authenticity decision is logged to an append-only audit file
- **No plugin marketplace** — your config is your config. No third-party skills, no supply chain risk

## Quickstart

```bash
# Clone and install
git clone https://github.com/gamutagent/verity.git
cd verity
pip install -r requirements.txt

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your topics, keywords, and thresholds

# Set environment variables
export SEARCH_API_KEY="your-serper-or-tavily-key"
export SCORING_API_KEY="your-gemini-or-openai-key"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Run
python src/scanner.py
```

## How It Works

```
┌─────────────┐     ┌───────────┐     ┌─────────────────────┐     ┌────────────┐
│ Web Search   │────▶│ LLM Score  │────▶│ Authenticity Check   │────▶│ Notify     │
│ (per keyword)│     │ (0.0–1.0)  │     │ (3-layer pipeline)   │     │ (Slack /   │
└─────────────┘     └───────────┘     └─────────────────────┘     │  Telegram) │
                                                                    └─────┬──────┘
                                                                          │
                                                              ┌───────────▼──────────┐
                                                              │ Human: 👍 approve /   │
                                                              │         👎 skip        │
                                                              └───────────┬──────────┘
                                                                          │
                                                                ┌─────────▼──────────┐
                                                                │ Approved items      │
                                                                │ accumulate in       │
                                                                │ JSONL / Markdown    │
                                                                └─────────────────────┘
```

1. **Search** — runs your keywords against a search API on a cron schedule
2. **Score** — each result is scored by an LLM against your topic-specific relevance prompt
3. **Authenticity check** — items that pass relevance go through three layers (see below)
4. **Deduplicate** — URL hashing prevents resurfacing items you've already seen
5. **Notify** — items that pass both gates are pushed to Slack/Telegram with scores and context
6. **Approve** — react with 👍 to keep, 👎 to discard — or let high-confidence items auto-approve
7. **Accumulate** — approved items build up in a structured file for downstream use

### Three-Layer Authenticity Pipeline

Verity's authenticity engine runs after relevance scoring. All three layers produce a composite score (0.0–1.0). Items below `authenticity.min_score` are blocked before they reach you. Auto-approval requires *both* high relevance *and* high authenticity.

| Layer | What it checks | Cost |
|-------|---------------|------|
| **Layer 1: Source Reputation** | Domain trust tier — authoritative registries and established outlets score high; press wire services and blocklisted domains score low | Zero (YAML lookup) |
| **Layer 2: Content Heuristics** | 7 deterministic checks: excessive capitalization, promotional language density, missing byline, link-to-text ratio, boilerplate patterns, duplicate-sentence ratio, AI fluency markers | Zero (pure Python) |
| **Layer 3: LLM Detection** | Optional LLM call asking: "Is this human-reported news or AI-generated/PR content?" — uses your existing scoring API key | 1 API call per item |

```yaml
authenticity:
  min_score: 0.4              # block items below this composite score
  auto_approve_min_score: 0.8 # require this for auto-approval (alongside relevance)
  use_llm_layer: false        # enable Layer 3 (costs money — disable for high-volume runs)
  source_reputation_path: "config/source_reputation.yaml"
```

Composite scoring: `source × 0.45 + heuristic × 0.55` (without LLM), or `source × 0.30 + heuristic × 0.35 + llm × 0.35` (with LLM enabled).

The source reputation database (`config/source_reputation.yaml`) ships with ~80 pre-classified domains. Add your own.

## Configuration

See [`config.example.yaml`](config.example.yaml) for the full reference. Key sections:

| Section | What it controls |
|---------|-----------------|
| `topics` | What to monitor — keywords, relevance prompts, schedules |
| `search` | Search provider (Serper, Tavily, Brave) and lookback window |
| `scoring` | LLM provider (Gemini, OpenAI, Anthropic, Ollama) and thresholds |
| `authenticity` | Three-layer authenticity gate and per-layer config |
| `notifications` | Where results go (Slack, Telegram, webhook) |
| `storage` | Where state lives (Firestore, SQLite, local JSON) |
| `security` | Bind address, rate limits, domain filtering, audit logging |

### Model-Agnostic Scoring

Use any LLM for relevance scoring:

```yaml
scoring:
  provider: "gemini"          # or: openai, anthropic, ollama
  model: "gemini-2.5-flash"   # cheap and fast for scoring
  temperature: 0.1
```

For fully local/private operation, use Ollama:

```yaml
scoring:
  provider: "ollama"
  model: "qwen3:8b"
```

### Gamut Intelligence Integration (Optional)

If you have Gamut API credentials, discovered entities are automatically verified against APAC government registries with confidence scoring:

```yaml
gamut:
  enabled: true
  api_key_env: "GAMUT_API_KEY"
  auto_verify_entities: true
  attach_confidence_score: true
```

## Deploy

Verity runs anywhere: your laptop, a VPS, or any major cloud provider.

### Option 1: Docker Compose (any host)

```bash
cp config.example.yaml config.yaml   # customize topics and thresholds
cp .env.example .env                  # fill in API keys
./deploy.sh docker                    # builds and starts containers
```

### Option 2: Cloud-Native (auto-detect)

```bash
./deploy.sh         # auto-detect: GCP, AWS, or Azure
./deploy.sh gcp     # Cloud Run + Cloud Scheduler + Secret Manager
./deploy.sh aws     # ECS Fargate + EventBridge + Secrets Manager
./deploy.sh azure   # Container Apps + Timer Trigger + Key Vault
```

| | GCP | AWS | Azure |
|---|---|---|---|
| **Container** | Cloud Run | ECS Fargate | Container Apps |
| **Scheduler** | Cloud Scheduler | EventBridge | Timer Trigger |
| **Secrets** | Secret Manager | Secrets Manager | Key Vault |
| **Storage** | Firestore | DynamoDB* | CosmosDB* |

\* DynamoDB and CosmosDB storage backends are on the roadmap. Use SQLite (mounted volume) for now.

### Option 3: Cron on a VPS

```bash
# Run competitors scan daily at 7am
0 7 * * * cd /path/to/verity && python src/scanner.py competitors

# Run tech patterns scan on Fridays
0 7 * * 5 cd /path/to/verity && python src/scanner.py tech_patterns
```

## Security Model

See [SECURITY.md](SECURITY.md) for the full security model. Key principles:

- **No ambient authority** — Verity can search the web and call an LLM. Nothing else.
- **No secrets in config** — all API keys are resolved through a pluggable secrets backend (env vars, `.env` file, GCP Secret Manager, AWS Secrets Manager, Azure Key Vault)
- **Append-only audit log** — every search, relevance score, and authenticity decision is recorded
- **Domain filtering** — block or allow-list which domains can be fetched
- **Rate limiting** — configurable per-hour caps on search and scoring calls

## Project Structure

```
verity/
├── config.example.yaml       # Full config reference (copy to config.yaml)
├── config/
│   └── source_reputation.yaml  # Domain trust tier database (~80 pre-classified domains)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── src/
│   ├── scanner.py            # Main orchestrator (Verity class) + CLI + Cloud Function entry
│   ├── authenticity.py       # Three-layer authenticity engine
│   ├── searcher.py           # Web search provider abstraction
│   ├── scorer.py             # LLM relevance scoring (Gemini/OpenAI/Anthropic/Ollama)
│   ├── notifier.py           # Slack, Telegram, webhook delivery
│   ├── store.py              # Dedup + approval state + export (Firestore/SQLite/JSON)
│   ├── secrets_resolver.py   # Pluggable secrets (env/.env/GCP/AWS/Azure)
│   ├── config_loader.py      # YAML loading + validation
│   └── audit.py              # Append-only audit logging
├── tests/                    # 22 tests covering pipeline logic and authenticity layers
├── deploy.sh                 # Unified deploy script
├── deploy-gcp.sh
├── deploy-aws.sh
├── deploy-azure.sh
├── SECURITY.md
└── LICENSE                   # Apache 2.0
```

## Contributing

PRs welcome. Please read [SECURITY.md](SECURITY.md) before contributing.

## License

Apache 2.0. See [LICENSE](LICENSE).

---

*Built by [Gamut Intelligence](https://gamutagent.ai) — AI-powered entity verification for PE/VC due diligence.*
