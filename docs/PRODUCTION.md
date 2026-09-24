# Production deployment (your own server, your own domain)

This is the guide for running the Pune console on a machine and a domain you control: no hosting platform, portable
to any Linux host with Docker (or without it, using systemd). It builds on [SELF_HOSTING](SELF_HOSTING.md), which covers the
single-process basics; this page adds the worker, the two hostnames, HTTPS, monitoring and backups.

## What was verified, and what was not

| Claim | Status |
|---|---|
| API and worker run as hardened containers (read-only filesystem, all capabilities dropped, no-new-privileges, unprivileged user) and serve live data | **Verified** on 2026-09-24 with `docker run` using the Compose file's options |
| The API answers 401 without the key; `/ready` reports the worker | **Verified** in that run |
| `docker stop` finishes in about 5.6 s with a viewer connected (API) and 0.3 s (worker) | **Verified** (both were broken before; see the changelog) |
| The Caddyfile is valid for one name and for the www/api pair | **Verified** with `caddy validate` in the Caddy image |
| `docker compose up` itself | **Not run**: the Compose plugin is not installed on the development machine. `docker compose config` runs in CI. |
| A public domain, DNS records, certificate issuance from a public CA, the Android app over HTTPS to that domain | **Not verified.** No domain was deployed. The steps below are what it requires; treat them as a checklist to confirm, not a record of something done. |
| systemd units | **Not run** on a real host (the earlier API unit was; the worker unit is new) |

## Architecture on the host

```
Internet ── 443 ──▶ Caddy (TLS, HTTP/2) ──▶ mobilityops (API + console, :8000, internal)
                                                 │ reads
                                     ┌───────────┴────────────┐
                                     ▼                        ▼
                           data/live/state.sqlite ◀── writes ── worker (pune-worker)
                           data/processed, artifacts (read-only)
```

Only Caddy publishes ports (80 and 443). The API and worker have no published port unless you choose one.

## 1. Prepare the host

```bash
git clone https://github.com/jayraj0975/mobilityops && cd mobilityops
cp deploy/mobilityops.env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"    # paste as MOBILITYOPS_API_KEY
# in .env:  MOBILITYOPS_MODE=pune   MOBILITYOPS_UID=$(id -u)   MOBILITYOPS_GID=$(id -g)
mkdir -p data/live artifacts
```

The containers run as `MOBILITYOPS_UID:MOBILITYOPS_GID`. That user must own `data/live` (the live state is the one
place the API needs write access: a reader of a WAL database maintains its shared-memory file), so use your own ids or
`chown` the folder to the image user (10001).

Build the data once (Pune needs the network for the rain history, a few seconds of compute):

```bash
python -m venv .venv && .venv/bin/pip install -c requirements.lock .
export MOBILITYOPS_MODE=pune
.venv/bin/python -m mobilityops.cli pune-build            # rain history + zones + simulated demand, gated
.venv/bin/python -m mobilityops.cli forecast-eval         # ~2 minutes
.venv/bin/python -m mobilityops.cli forecast-train
.venv/bin/python -m mobilityops.cli anomalies
```

## 2. Domain, DNS and HTTPS

Use two names on one host, for example `www.example.org` (the console) and `api.example.org` (the Android app and
scripts). Both reach the same process; the console calls `/api` on its own origin, so **no CORS is needed** for it.

1. Create two `A` records (and `AAAA` if the host has IPv6) pointing at the server's public address.
2. Open ports 80 and 443 to the host. Caddy uses port 80 for the ACME HTTP challenge and to redirect to HTTPS.
3. In `.env`:
   ```
   MOBILITYOPS_WWW_HOST=www.example.org
   MOBILITYOPS_API_HOST=api.example.org
   MOBILITYOPS_TRUST_PROXY=1
   ```
   `TRUST_PROXY=1` makes the rate limiter use the client address Caddy reports instead of Caddy's own.
4. Start everything:
   ```bash
   docker compose --profile pune --profile tls up -d --build
   ```
5. Caddy obtains and renews certificates itself. Check with `curl -I https://api.example.org/health`.

**Why Caddy:** automatic certificates and renewal, and `flush_interval -1` keeps the event stream unbuffered. Any
reverse proxy works if it does not buffer the response and allows long-lived connections: nginx needs
`proxy_buffering off; proxy_read_timeout 1h;`.

### Hosting the console on a different origin (optional)

Only if you serve the built console from somewhere else (a static host, another domain): set
`MOBILITYOPS_CORS_ORIGINS=https://console.example.org` (an explicit list, never `*`; the server refuses a wildcard),
and the console would need its API base changed; the shipped console assumes the same origin. The supported shape is
the one above.

### The Android app

In the app's Settings enter `https://api.example.org` and the API key. Plain `http://` is allowed for a home network
and should not be used across the internet. Whether the app works against a real public HTTPS domain was **not** verified.

## 3. Without Docker (systemd)

```bash
sudo useradd --system --home /opt/mobilityops --shell /usr/sbin/nologin mobilityops
sudo git clone https://github.com/jayraj0975/mobilityops /opt/mobilityops
cd /opt/mobilityops && sudo python3 -m venv .venv && sudo .venv/bin/pip install -c requirements.lock .
cd apps/web && npm ci && npm run build && cd ../..
sudo mkdir -p /etc/mobilityops data/live && sudo chown mobilityops data/live
sudo cp deploy/mobilityops.env.example /etc/mobilityops/mobilityops.env       # edit: key, MODE=pune
sudo cp deploy/mobilityops.service deploy/mobilityops-worker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mobilityops mobilityops-worker
```

Put Caddy or nginx in front as above. Both units restart on failure and stop within 15 s.

## 4. Health and monitoring

| Probe | What it says | Alert when |
|---|---|---|
| `GET /health` | The process is up (unauthenticated, cheap) | non-200 |
| `GET /ready` | `ready`, or `degraded` with which component is missing; in Pune mode the components that matter are `database`, `forecast_model` and `live_worker` | `status` is not `ready` for 3 minutes |
| `GET /api/v1/state/quality` (needs the key) | Per-source freshness, failed polls, database checks | any source STALE or OFFLINE that should be enabled |
| `GET /api/v1/state/stream/status` | Open viewers, dropped events | viewers at the cap |
| `GET /api/v1/ops/metrics` | Request counts and latency by route | error rate |

Uptime tools that only check status codes should poll `/health` for liveness and parse `/ready` for readiness.
The worker container has its own healthcheck (a fresh heartbeat within 90 s). Logs are JSON, one line per request, with a
`request_id` that is also returned in the `X-Request-ID` header, so one request can be followed from the client to the log.

## 5. Updates, backups, and what to expect

* **Update:** `git pull && docker compose --profile pune --profile tls up -d --build`. The worker and API restart in seconds; the
  console reconnects by itself and shows a "Reconnecting" notice meanwhile.
* **Daily:** run `pune-build` (cron) to move the analytical history forward. Between builds the worker simulates the
  gap and still forecasts today, but `/state/quality` reports how many days behind the database is.
* **Backup:** the live state is disposable (the worker rebuilds it in one cycle). What is worth keeping is `data/raw/pune`
  (the cached rain history with its provenance) and, if you customise anything, `.env`. Everything else regenerates.
* **Free-tier limits:** Open-Meteo's free tier is for non-commercial use with attribution, at most 600 calls a minute
  and fewer than 10,000 a day. The worker makes about 220 requests a day (weather 96, air quality 24, rain 96); the
  weather and air-quality requests carry nine locations each, and Open-Meteo counts each location as a call, so that
  is roughly 1,200 calls a day. If you use this commercially you need their paid plan.

## 6. Shared cloud addresses and free weather APIs

Free weather APIs limit by client address. On Render's free plan the egress address is shared, and Open-Meteo's forecast host
answered HTTP 429 to the worker from the first request (observed on 2026-09-24; the same code worked from a home connection).
The worker records the failure, backs off, invents nothing and shows the source OFFLINE; a second provider (MET Norway) keeps
"weather now" available. On a host with its own address this should not happen; if it does, use Open-Meteo's paid plan
(a key is needed by the adapter, which does not yet read one) or accept the second provider alone.

## 7. What this does not give you

One shared API key, no user accounts, no audit log, no protection against a distributed flood, a single machine with
no failover, and plain SQLite that does not scale out (ADR-018). It is a sound base for a personal or small-team
deployment, and not a description of a hardened multi-tenant service. See [SECURITY](SECURITY.md).
