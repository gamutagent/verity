# Security Model

Intel Sweep is designed with security as a first-class constraint, not an afterthought.
This document describes the threat model, security boundaries, and hardening measures.

## Threat Model

Intel Sweep processes untrusted web content through an LLM. The primary threats are:

1. **Prompt injection via search results**: malicious content in web pages could attempt
   to manipulate the scoring LLM into producing unintended behavior.
2. **Data exfiltration**: a compromised or malicious component could attempt to send
   sensitive data (API keys, scored results, topic lists) to an external endpoint.
3. **Credential exposure**: API keys stored insecurely or logged inadvertently.
4. **Unauthorized access**: if the scanner is network-accessible, unauthorized parties
   could trigger scans or read results.

## Security Boundaries

### What Intel Sweep CAN Do
- Send HTTP requests to configured search APIs
- Send HTTP requests to configured LLM APIs
- Read and write to configured storage backends (Firestore, local files, SQLite)
- Send notifications to configured webhook URLs

### What Intel Sweep CANNOT Do
- Access your filesystem beyond its data directory
- Execute arbitrary code from search results
- Install plugins or skills from external sources
- Send data to any endpoint not explicitly configured
- Access email, calendar, messaging apps, or any other services

This is the fundamental security difference from agent frameworks with broad permissions.

## Hardening Measures

### 1. Localhost Binding
The scanner binds to `127.0.0.1` by default. The config loader emits a warning if
`0.0.0.0` is configured. There is no reason for Intel Sweep to accept inbound connections
from the network in normal operation.

### 2. No Secrets in Config
All API keys and tokens are resolved from environment variables. The config file contains
only the _names_ of environment variables, never their values. This means:
- Config files can be committed to version control safely
- Secrets are managed through your platform's secrets manager (GCP Secret Manager,
  AWS Secrets Manager, Vault, etc.)
- Rotation doesn't require config file changes

### 3. Prompt Injection Mitigation
The scoring prompt is structured to minimize injection risk:
- The LLM is instructed to return ONLY a JSON object with `score` and `reason`
- Input content (titles, snippets) is truncated to 1,000 characters
- The system prompt does not grant the LLM any tool-use or action capabilities
- Scoring results are parsed as JSON; non-JSON responses are discarded with score 0.0

This does not make prompt injection impossible, but limits the blast radius to
inaccurate scoring — not data exfiltration or code execution.

### 4. Domain Filtering
Configure `block_domains` and `allow_domains` in the security section:
- `block_domains`: URLs from these domains are never fetched or scored
- `allow_domains`: if non-empty, ONLY URLs from these domains are processed

### 5. Rate Limiting
Configurable per-hour caps on search and scoring API calls prevent:
- Runaway costs from misconfigured schedules
- Accidental DoS of upstream APIs
- Budget exhaustion attacks if the scheduler is somehow triggered externally

### 6. Audit Logging
Every search query and scoring decision is logged to an append-only JSONL file:
```json
{"event": "search", "query": "Harmonic.ai", "result_count": 5, "timestamp": "2026-03-21T..."}
{"event": "score", "url": "https://...", "score": 0.82, "timestamp": "2026-03-21T..."}
{"event": "approval", "item_id": "a1b2c3d4", "action": "approved", "timestamp": "2026-03-21T..."}
```

### 7. No Plugin/Skill Marketplace
Intel Sweep has no plugin system. Your config defines your behavior. This eliminates
the entire class of supply-chain attacks that affect agent frameworks with community
skill registries.

## GCP Deployment Security

When deploying to Google Cloud:
- API keys are stored in **Secret Manager**, not environment variables on the service
- Cloud Run services are configured with **no ingress** (invoked only by Cloud Scheduler)
- Cloud Scheduler uses a **dedicated service account** with minimal IAM roles
- The container runs as a **non-root user**

See `scripts/deploy-gcp.sh` for the full deployment configuration.

## Responsible Disclosure

If you discover a security vulnerability, please email security@gamutagent.ai.
Do not open a public issue.
