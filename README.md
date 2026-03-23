# Intel Sweep

**Competitive intelligence scanning that doesn't compromise your security.**

Intel Sweep is a config-driven, security-hardened competitive intelligence scanner. It monitors topics you care about, scores results for relevance using the LLM of your choice, and surfaces actionable items to your existing channels — Slack, Telegram, or any webhook.

Built by [Gamut Intelligence](https://gamutagent.ai).

## Why This Exists

AI agents that "do everything" are exciting. They're also [attack surface nightmares](https://www.bitdefender.com/en-us/blog/labs/bitdefender-discovers-135-000-exposed-openclaw-instances). Intel Sweep takes one pattern that actually works — scheduled search → LLM scoring → human-in-the-loop approval — and does it with security defaults you'd actually deploy at a company.

- **Scoped by design**: it searches and scores. That's it. No filesystem access, no email sending, no autonomous tool chaining.
- **Localhost by default**: binds to `127.0.0.1`. Never `0.0.0.0`.
- **No plugin marketplace**: your config is your config. No third-party skills, no supply chain risk.
- **Audit everything**: every search query and scoring decision is logged to an append-only audit file.

## Quickstart

```bash
# Clone and install
git clone https://github.com/gamut-ai/intel-sweep.git
cd intel-sweep
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
┌─────────────┐     ┌──────────┐     ┌────────────┐     ┌──────────┐
│ Web Search   │────▶│ LLM Score │────▶│ Deduplicate │────▶│ Notify   │
│ (per keyword)│     │ (0.0-1.0) │     │ (URL hash)  │     │ (Slack/  │
└─────────────┘     └──────────┘     └────────────┘     │ Telegram)│
                                                         └────┬─────┘
                                                              │
                                          ┌───────────────────▼──────┐
                                          │ Human: 👍 approve / 👎 skip │
                                          └───────────────────┬──────┘
                                                              │
                                                    ┌─────────▼────────┐
                                                    │ Approved items   │
                                                    │ accumulate in    │
                                                    │ JSONL / Markdown │
                                                    └──────────────────┘
```

1. **Search**: runs your keywords against a search API on a cron schedule
2. **Score**: each result is scored by an LLM against your topic-specific relevance prompt
3. **Deduplicate**: URL hashing prevents resurfacing items you've already seen
4. **Notify**: items above threshold are pushed to Slack/Telegram with score and context
5. **Approve**: react with 👍 to keep, 👎 to discard — or let high-confidence items auto-approve
6. **Accumulate**: approved items build up in a structured file for downstream use

## Configuration

See [`config.example.yaml`](config.example.yaml) for the full reference. Key sections:

| Section | What it controls |
|---------|-----------------|
| `topics` | What to monitor — keywords, relevance prompts, schedules |
| `search` | Search provider (Serper, Tavily, Brave) and lookback window |
| `scoring` | LLM provider (Gemini, OpenAI, Anthropic, Ollama) and thresholds |
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

Intel Sweep runs anywhere: your laptop, a VPS, or any major cloud provider.

### Option 1: Docker Compose (any host)

The simplest path. Works on any machine with Docker.

```bash
cp config.example.yaml config.yaml   # customize topics and thresholds
cp .env.example .env                  # fill in API keys
./scripts/deploy.sh docker            # builds and starts containers
```

### Option 2: Cloud-Native (auto-detect)

The deploy script auto-detects your cloud environment and sets up the right
container service, scheduler, and secrets manager:

```bash
./scripts/deploy.sh         # auto-detect: GCP, AWS, or Azure
./scripts/deploy.sh gcp     # explicit: Cloud Run + Cloud Scheduler + Secret Manager
./scripts/deploy.sh aws     # explicit: ECS Fargate + EventBridge + Secrets Manager
./scripts/deploy.sh azure   # explicit: Container Apps + Timer Trigger + Key Vault
```

| | GCP | AWS | Azure |
|---|---|---|---|
| **Container** | Cloud Run | ECS Fargate | Container Apps |
| **Scheduler** | Cloud Scheduler | EventBridge | Timer Trigger |
| **Secrets** | Secret Manager | Secrets Manager | Key Vault |
| **Storage** | Firestore | DynamoDB* | CosmosDB* |

\* DynamoDB and CosmosDB storage backends are on the roadmap. Use SQLite (mounted volume) for now.

### Option 3: Cron on a VPS

For personal use, a $5/mo VPS works fine:

```bash
# Edit crontab
crontab -e

# Run competitors scan daily at 7am
0 7 * * * cd /path/to/intel-sweep && python src/scanner.py competitors

# Run tech patterns scan on Fridays
0 7 * * 5 cd /path/to/intel-sweep && python src/scanner.py tech_patterns
```

## Security Model

See [SECURITY.md](SECURITY.md) for the full security model. Key principles:

- **No ambient authority**: the scanner can search the web and call an LLM. Nothing else.
- **No secrets in config**: all API keys are resolved through a pluggable secrets backend (env vars, `.env` file, GCP Secret Manager, AWS Secrets Manager, Azure Key Vault).
- **Append-only audit log**: every action is recorded for review.
- **Domain filtering**: block or allow-list which domains can be fetched.
- **Rate limiting**: configurable per-hour caps on search and scoring calls.
- **No plugin marketplace**: your config is your config. No supply chain risk.

## Project Structure

```
intel-sweep/
├── config.example.yaml       # Full config reference (copy to config.yaml)
├── .env.example              # API keys template (copy to .env)
├── docker-compose.yml        # Run anywhere with Docker
├── Dockerfile
├── requirements.txt
├── src/
│   ├── scanner.py            # Main orchestrator + entry points
│   ├── searcher.py           # Web search provider abstraction
│   ├── scorer.py             # LLM relevance scoring (Gemini/OpenAI/Anthropic/Ollama)
│   ├── notifier.py           # Slack, Telegram, webhook delivery
│   ├── store.py              # Dedup + approval state + export (Firestore/SQLite/JSON)
│   ├── secrets_resolver.py   # Pluggable secrets (env/.env/GCP/AWS/Azure)
│   ├── config_loader.py      # YAML loading + secrets validation
│   └── audit.py              # Append-only audit logging
├── scripts/
│   ├── deploy.sh             # Unified deploy (auto-detects cloud)
│   ├── deploy-gcp.sh         # Cloud Run + Cloud Scheduler
│   ├── deploy-aws.sh         # ECS Fargate + EventBridge
│   ├── deploy-azure.sh       # Container Apps + Timer Trigger
│   └── crontab               # Schedule for Docker/VPS deployment
├── tests/
├── docs/
│   └── architecture.md
├── SECURITY.md
└── LICENSE                   # Apache 2.0
```

## Contributing

PRs welcome. Please read [SECURITY.md](SECURITY.md) before contributing — we take the security model seriously.

## License

Apache 2.0. See [LICENSE](LICENSE).

---

*Built by [Gamut Intelligence](https://gamutagent.ai) — AI-powered entity verification for PE/VC due diligence.*
