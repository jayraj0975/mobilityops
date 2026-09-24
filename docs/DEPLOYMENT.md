# Deployment

The public demo is one container: the FastAPI service and the built React interface, serving the
real-data snapshot. It runs on Render's free plan. Nothing is stored server side; the API is
read-only.

## What is deployed

| Piece | Where it comes from |
|---|---|
| Code | this repository, `main`, built from the `Dockerfile` |
| Data | the aggregate-only bundle attached to the GitHub release `demo-data-v1`, downloaded at build time and checked against a pinned SHA-256 (`scripts/fetch_demo.py`) |
| Settings | environment variables in [`render.yaml`](../render.yaml): real mode, per-client rate limits, trusted-proxy client IPs, one model thread, `MALLOC_ARENA_MAX=2` |

The bundle holds pickups per zone per hour, the zone dimension, daily weather, quality results and
the generated model artifacts. It holds no trip-level rows and no secrets. Sources and licences:
[DATA_SOURCES.md](DATA_SOURCES.md).

## Rebuild the bundle

```bash
# regenerate the real-mode artifacts first (commands in docs/EVALUATION.md)
python scripts/pack_demo.py # writes dist/mobilityops-demo-real.tar.gz and its .sha256
gh release create demo-data-v2 dist/mobilityops-demo-real.tar.gz --title "Demo data bundle v2"
```

Then update `DEMO_URL` and `DEMO_SHA256` on the service. A wrong checksum fails the build instead of
serving unknown data.

## Run the same image locally

```bash
docker build -t mobilityops-demo \
  --build-arg DEMO_URL=<release asset url> --build-arg DEMO_SHA256=<sha256> .
docker run --rm -p 127.0.0.1:8000:8000 -e MOBILITYOPS_MODE=real mobilityops-demo
```

## Known properties of the free plan

* The service sleeps after about 15 minutes without traffic; the first request afterwards waits for
  a cold start (tens of seconds).
* 512 MB of memory. Measured peak resident memory on the real snapshot after exercising the
  forecast, analyst and scenario endpoints was about 410 MB, so it fits with little headroom. The
  scenario solver is capped at 2 concurrent solves and the heavy endpoints have their own, lower
  rate limit. If the process is killed for memory, upgrade the plan; nothing else needs changing.
* The URL is `https://mobilityops.onrender.com`. Health: `/health`, readiness: `/ready`.
