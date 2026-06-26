# QueueStorm Investigator Runbook

## 1. Fast local verification

```bash
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In a second terminal:

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

Run a sample request:

```bash
curl -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id":"TKT-SMOKE-01",
    "complaint":"I paid 1200 taka for mobile recharge but it failed and my balance was deducted.",
    "language":"en",
    "transaction_history":[{
      "transaction_id":"TXN-SMOKE-01",
      "timestamp":"2026-04-14T16:00:00Z",
      "type":"payment",
      "amount":1200,
      "counterparty":"MERCHANT-MOBILE-OP",
      "status":"failed"
    }]
  }'
```

## 2. Docker build and run

```bash
docker build -t queuestorm-investigator:latest .
docker run --rm -p 8000:8000 --name queuestorm queuestorm-investigator:latest
```

Verify from the host:

```bash
curl http://127.0.0.1:8000/health
```

The API must bind to `0.0.0.0`, which the Dockerfile already configures.

## 3. DockerHub fallback

Replace `YOUR_DOCKERHUB_USERNAME`:

```bash
docker tag queuestorm-investigator:latest YOUR_DOCKERHUB_USERNAME/queuestorm-investigator:latest
docker push YOUR_DOCKERHUB_USERNAME/queuestorm-investigator:latest
```

Judge-side/runbook command:

```bash
docker pull YOUR_DOCKERHUB_USERNAME/queuestorm-investigator:latest
docker run --rm -p 8000:8000 YOUR_DOCKERHUB_USERNAME/queuestorm-investigator:latest
```

## 4. VM deployment with Docker

On a Linux VM with Docker installed:

```bash
docker pull YOUR_DOCKERHUB_USERNAME/queuestorm-investigator:latest
docker rm -f queuestorm 2>/dev/null || true
docker run -d \
  --name queuestorm \
  --restart unless-stopped \
  -p 8000:8000 \
  --env PORT=8000 \
  YOUR_DOCKERHUB_USERNAME/queuestorm-investigator:latest
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

If the VM firewall is enabled, allow the application port only as required by the hosting platform/reverse proxy. Place a TLS-enabled reverse proxy or platform HTTPS endpoint in front of the service for a public submission URL.

## 5. Public smoke test

After deployment, use the public HTTPS base URL, not localhost:

```bash
curl https://YOUR_PUBLIC_BASE_URL/health
curl -X POST https://YOUR_PUBLIC_BASE_URL/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @sample_request.json
```

## 6. Optional Gemini hint configuration

This service is fully functional without an external key. Keep this off for the most reliable judging path:

```env
ENABLE_LLM=false
```

If deliberately enabled for a hosted demo, set secrets only in the hosting platform:

```env
ENABLE_LLM=true
GEMINI_API_KEY=your_temporary_limited_key
LLM_TIMEOUT=8
```

The LLM client is non-authoritative. A missing key, timeout, invalid response, or rate limit results in no hint and does not change the response schema or rules decision.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| `404` | Use exact paths: `/health` and `/analyze-ticket`. |
| `422` | Check `ticket_id`, non-blank `complaint`, enum spelling, timestamp, and transaction fields. |
| API not reachable outside VM | Ensure Docker publishes `-p 8000:8000`, VM firewall/security group allows the port, and reverse proxy points to port 8000. |
| Docker health check fails | Inspect `docker logs queuestorm`; verify the service is bound to `0.0.0.0`. |
| LLM failure | Disable `ENABLE_LLM`; it is optional and not needed for core triage. |
| Unsafe wording concern | Run `pytest -q`; all templates pass the credential-request and unauthorized-promise tests. |
