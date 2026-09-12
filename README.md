# 🛡️ AI Voice Risk Agent — Enterprise Cybersecurity Integration

Call a phone number and ask, in plain language, *"What's our current risk score?"*,
*"Any critical vulnerabilities on our vendors?"*, or *"What's our exposure to
ransomware?"* — and get answers from **live UpGuard data** and a **RAG archive
of historical findings**, served by a **GPT-4o voice agent** via Vapi.ai.

Passive Q&A is half the product: scanners POST webhooks to this service, and a
**critical** vulnerability triggers an **outbound call** that briefs the on-call
engineer.

## Architecture

```
Caller ──phone──▶ Vapi.ai ──▶ GPT-4o Realtime (speech-to-speech)
                       │  tool-call → POST /vapi/tools
                       ▼
              FastAPI tool router
                 ├─ get_risk_summary  → UpGuard API (OAuth2 → Redis cache)
                 ├─ get_vulnerabilities → UpGuard API → PostgreSQL (audit)
                 └─ query_findings    → LangChain → Pinecone (semantic RAG)

Scanner / UpGuard ──▶ POST /webhooks/vulnerability (HMAC-verified)
                        → normalize → PostgreSQL (idempotent)
                        → Redis pub/sub
                        → severity == critical → Vapi outbound call ☎️
```

Stack: **FastAPI · Vapi.ai · OpenAI GPT-4o + embeddings · UpGuard API (OAuth 2.0) ·
PostgreSQL · Redis · Pinecone · LangChain**

## Repo layout

```
main.py               FastAPI app (routers, legacy Twilio demo, JSON API)
app/
  config.py           pydantic-settings, env-driven
  db.py               async SQLAlchemy engine + session
  models.py           Alert / CallLog (JSONB raw payloads for audit)
  redis_client.py     token cache, risk cache, pub/sub
  upguard.py          OAuth2 client-credentials client + mock mode
  rag.py              LangChain + Pinecone semantic query (graceful fallback)
  vapi_tools.py       POST /vapi/tools — Vapi server-tool endpoint
  webhooks.py         POST /webhooks/vulnerability → proactive outbound call
config/
  vapi_assistant.json assistant definition (paste into Vapi dashboard)
tests/                pytest suite
```

## Run it

```bash
docker compose up -d          # api + postgres + redis
cp .env.example .env          # fill in keys (mock modes work without UpGuard/OpenAI)
pytest -v
```

### 1. Create the Vapi assistant
Dashboard → **Assistants → Import JSON** → paste `config/vapi_assistant.json`.
Set `serverUrl` to your public `https://<domain>/vapi/tools` (ngrok for dev) and
attach a phone number. Voice model: `gpt-4o-realtime-preview`.

### 2. UpGuard (OAuth 2.0)
Set `UPGUARD_CLIENT_ID` / `UPGUARD_CLIENT_SECRET`. Tokens are fetched via
client-credentials and cached in Redis (no stampedes under concurrent callers);
risk profiles cached 5 minutes. **No credentials → realistic mock data**, so the
whole agent works out of the box.

### 3. RAG over findings (Pinecone)
`python scripts/embed_findings.py --dir ./reports` (chunk → embed → upsert), then
*"what's our ransomware exposure?"* answers from your own report archive. Without
keys, a canned demo finding is returned.

### 4. Proactive alerts
Point your scanner / UpGuard webhook at `POST /webhooks/vulnerability` with header
`X-Signature-256: <hmac-sha256 of body>`. Critical severity → Vapi places an
outbound call to `ONCALL_NUMBER` and the assistant opens with the alert brief.

## Production hardening checklist
- [ ] HTTPS everywhere + secret manager (Vault / SM)
- [ ] Per-caller auth (PIN via Vapi `assistantOverrides`, or registered caller-ID allowlist)
- [ ] Rate limiting on /vapi/tools (Redis token bucket)
- [ ] Alembic migrations instead of `create_all`
- [ ] Structured logs + Sentry; PII redaction in CallLog
- [ ] Outbound-call escalation policy (retry, SMS fallback, PagerDuty bridge)

## Tests
```bash
pytest -v   # no phone line or vendor credentials required
```

## License
MIT
