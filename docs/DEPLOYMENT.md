# Deployment

The public demo is one container: the FastAPI service and the built React interface, serving the
real-data snapshot. It runs on Render's free plan. Nothing is stored server side; the API is
read-only.

## What is deployed

| Piece | Where it comes from |
|---|---|
| Code | this repository, `main`, built from the `Dockerfile` |
| Data | the aggregate-only bundle attached to the GitHub release `demo-data-v2` (all of 2024, all three services; `demo-data-v1` is the earlier January to May snapshot and is left in place), downloaded at build time and checked against a pinned SHA-256 (`scripts/fetch_demo.py`) |
| Settings | environment variables in [`render.yaml`](../render.yaml): real mode, per-client rate limits, trusted-proxy depth 3 (measured, see below), one model thread, `MALLOC_ARENA_MAX=2` |

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
  a cold start (measured at about 34 seconds on 2026-09-24). The wait happens before the page
  loads, so the app cannot show anything during it; once the page is up, any request slower than
  four seconds shows an explanation instead of a bare "Loading". A scheduled request every ten
  minutes from an uptime monitor would keep the service awake, at the cost of keeping the free instance
  running continuously; this project does not do that.
* 512 MB of memory (536,870,900 bytes reported as the limit). Measured on the live service with
  Render's metrics after the full-year redeploy, while exercising it with scenario solves, analyst questions,
  a next-day forecast and live streams: **350 to 379 MB, about 70% of the limit**. On the earlier five-month data
  the same kind of exercise showed 224 to 267 MB; the full year, the service tables and the live hub cost about
  110 MB more, so the headroom is now roughly 150 MB. A local rehearsal of the same image under a 512 MB cap
  peaked at 370 MB with six concurrent streams. The scenario solver is capped at 2 concurrent solves, the Live tab
  at 8 concurrent viewers (`MOBILITYOPS_LIVE_MAX_STREAMS`), and the heavy endpoints have their own, lower rate
  limit. A scenario request took 11 to 17 seconds on the free CPU when measured (about 1.5 s on a 12-core
  machine); the live stream kept ticking every 2 seconds while a solve ran. The first stream request after a
  redeploy or a cold start can be slow to deliver its first events.
* The URL is `https://mobilityops.onrender.com`. Health: `/health`, readiness: `/ready`.

## Client addresses behind Render

Rate limits count by client address, taken from `X-Forwarded-For` counted from the right
(`MOBILITYOPS_TRUST_PROXY` = number of proxies in front). On Render the chain the app receives is
`<whatever the client sent>, <client>, <Cloudflare edge>, <Render load balancer>`, so the depth is 3.
This was measured, not assumed: with depth 1 the logged address was an internal 10.x load balancer,
with depth 2 a rotating Cloudflare address, and with depth 3 the address of the machine making the
request, unchanged by forged `X-Forwarded-For` prefixes. A first attempt that trusted the leftmost
entry let a forged header dodge the limit on the live site; that is fixed and covered by tests
(`tests/unit/test_limits.py`). If the hosting provider changes its proxy chain, re-measure.
