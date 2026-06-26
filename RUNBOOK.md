# RUNBOOK — QueueStorm Investigator

Operational guide for judges and operators. Covers local development, Docker
deployment, Render free-tier deployment, and the Poridhi Lab deployment used
for the **bKash SUST CSE Carnival 2026** preliminary round.

---

## 0. Prerequisites

| Tool       | Tested version | Notes                                   |
|------------|---------------|------------------------------------------|
| Python     | 3.11          | Anything ≥ 3.10 should work             |
| Docker     | 24.x          | Optional — only for container deploys    |
| git        | 2.40+         |                                          |
| curl       | any           | For smoke tests                          |

Optional:
- A free Google AI Studio key (`https://aistudio.google.com/app/apikey`) for
  the LLM fallback. **Without it the service still works** — it just runs
  rules-only.

---

## 1. Local development (fastest path)

```bash
# from the repo root
cd queuestorm-investigator
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

# (optional) edit .env to paste GEMINI_API_KEY=...

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Smoke test:

```bash
curl http://127.0.0.1:8000/health
# -> {"status":"ok"}

curl -X POST http://127.0.0.1:8000/analyze-ticket \
     -H "Content-Type: application/json" \
     -d @sample_outputs/sample_case_01.json
```

Tests:

```bash
python -m pytest                # 36 passed in ~1s
```

---

## 2. Docker (local container)

```bash
docker build -t queuestorm-investigator:dev .
docker run --rm -p 8000:8000 --env-file .env queuestorm-investigator:dev
```

Image size should be **< 250 MB** (`docker images queuestorm-investigator:dev`).

Smoke test (in another terminal):

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/analyze-ticket \
     -H "Content-Type: application/json" \
     -d @sample_outputs/sample_case_01.json
```

---

## 3. Render (free web service)

The repo ships a `render.yaml` Blueprint that Render can auto-detect.

1. Push this repo to GitHub.
2. In Render: **New → Blueprint → connect the repo**.
3. Render reads `render.yaml` and provisions a `free` Docker web service named
   `queuestorm-investigator`.
4. In the dashboard, set `GEMINI_API_KEY` to your free Google AI Studio key
   (optional; service works without it).
5. Wait for the first deploy (~3 min on the free plan because of the cold
   build). Once live, Render exposes `https://queuestorm-investigator.onrender.com`.

Smoke test:

```bash
curl https://queuestorm-investigator.onrender.com/health
curl -X POST https://queuestorm-investigator.onrender.com/analyze-ticket \
     -H "Content-Type: application/json" \
     -d @sample_outputs/sample_case_01.json
```

> Free plan note: the instance spins down after 15 min idle. First request
> after idle takes ~30 s (cold start). Subsequent requests are instant.

---

## 4. Poridhi Lab (primary deployment target for the carnival)

Poridhi Lab is the deployment sandbox used during the hackathon. The image is
hosted on Docker Hub and exposed publicly through Poridhi's edge.

### 4.1 Build and push the image

```bash
# from repo root
docker build -t <your-dockerhub-username>/queuestorm-investigator:1.0.0 .
docker push <your-dockerhub-username>/queuestorm-investigator:1.0.0
```

### 4.2 Launch on Poridhi

1. Visit `https://lab.poridhi.io/` and sign in.
2. **Deploy → Container → Custom Image**.
3. Image: `docker.io/<your-dockerhub-username>/queuestorm-investigator:1.0.0`
4. Port: `8000`
5. Public exposure: **ON**
6. Environment variables (mirror `.env.example`):

   | Key             | Value              |
   |-----------------|--------------------|
   | `PORT`          | `8000`             |
   | `ENABLE_LLM`    | `true`             |
   | `GEMINI_API_KEY`| *(your free key)*  |
   | `LLM_TIMEOUT`   | `8`                |
   | `LOG_LEVEL`     | `INFO`             |

7. Deploy. Poridhi prints a public URL like
   `https://<service-id>.lab.poridhi.io`.

### 4.3 Verify

```bash
curl https://<service-id>.lab.poridhi.io/health
# -> {"status":"ok"}

curl -X POST https://<service-id>.lab.poridhi.io/analyze-ticket \
     -H "Content-Type: application/json" \
     -d @sample_outputs/sample_case_01.json
```

---

## 5. Failure modes & recovery

| Symptom                                     | Likely cause                | Fix                                  |
|---------------------------------------------|------------------------------|--------------------------------------|
| `503` on `/health` after deploy             | Image failed to start        | Check Render/Poridhi logs; confirm `PORT=8000` |
| `LLM timeout` reason code in response       | Slow Gemini API              | Increase `LLM_TIMEOUT` or set `ENABLE_LLM=false` |
| `we will refund` / `PIN` appears in output  | Safety sanitizer regression  | Run `python -m pytest tests/test_safety.py` |
| First request after idle takes 30 s         | Render free-tier cold start  | Expected; warn judges in advance     |
| `ModuleNotFoundError: app`                  | Running from wrong directory | `cd` into `queuestorm-investigator/` before uvicorn |

---

## 6. Rollback

```bash
git tag -l                    # find last green tag
git checkout <last-green-tag>
docker build -t <user>/queuestorm-investigator:<tag> .
docker push <user>/queuestorm-investigator:<tag>
# redeploy on Render / Poridhi with the previous tag
```

On Render: **Service → Manual Deploy → pick previous commit**.

---

## 7. Security checklist

- [x] Container runs as non-root (`USER app`).
- [x] No secrets baked into the image; `.env` is excluded by `.dockerignore`.
- [x] No customer PII (PIN, OTP, full card numbers) ever leaves the sanitizer.
- [x] LLM only sees structured complaint text + the LLM system prompt; the
      `customer_reply` is always template-generated locally.

---

## 8. Contact

For issues during the carnival, contact the team via the official Discord
channel pinned by the organizers.