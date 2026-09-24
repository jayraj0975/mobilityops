# Self-hosting

MobilityOps runs entirely on a machine you control: the API, the web dashboard and the live stream
are one process, and the Android app talks to it directly. No hosting platform is involved.

| You want | Use |
|---|---|
| The simplest, most contained setup | [Docker Compose](#option-1-docker-compose) |
| A Linux server without Docker | [systemd](#option-2-systemd) |
| Just try it on your own computer | `make setup && make serve` (see the [README](../README.md)) |

## What you need

* A machine that stays on while you use it (a laptop, a spare PC, a small server).
* About 1 GB of disk for the image and about 1 GB for the derived data. The raw downloads for the
  full pipeline are several GB more (see [Get the data](#1-get-the-data)).
* Outbound internet only for the Live tab's public feeds (Citi Bike, National Weather Service). The
  rest works offline.

## 1. Get the data

The server reads two folders, `data/` (the gold DuckDB database and quality reports) and
`artifacts/` (the model, evaluation, anomaly events and backtest). Produce them one of two ways.

**A. Run the pipeline yourself (recommended; everything is regenerated from public sources).**

```bash
make setup                                   # virtualenv and dependencies (Python 3.12+)
export MOBILITYOPS_MODE=real
python -m mobilityops.cli ingest --start 2024-01 --end 2024-12 --services green,fhvhv   # several GB
python -m mobilityops.cli build              # quality gates; keeps the last good database on failure
python -m mobilityops.cli forecast-eval && python -m mobilityops.cli forecast-train
python -m mobilityops.cli anomalies
python -m mobilityops.cli optimize-backtest  # about an hour; skip it and the Scenarios tab says so
```

Leave out `--services green,fhvhv` to fetch yellow taxis only (about 0.6 GB). Interrupted downloads
resume: the manifest is saved after every file.

**B. Use an aggregate bundle (fast start).** A bundle holds only the derived, aggregate-only files (no
trip-level rows), with a SHA-256 to check. The bundle published on the repository's Releases page
(`demo-data-v1`) is the **earlier January to May snapshot**, which the public demo serves; it works, but it is
not the full-year data described in the README. To make a current one from your own run of option A:

```bash
python scripts/pack_demo.py --out dist/mobilityops-demo-real.tar.gz   # about 21 MB; writes a .sha256 beside it
# on the machine that will serve it, in the checkout's root:
sha256sum -c mobilityops-demo-real.tar.gz.sha256 && tar -xzf mobilityops-demo-real.tar.gz
```

To publish a bundle for others, `scripts/fetch_demo.py <https-url> <sha256> <dest>` downloads, verifies and
unpacks it. The bundle contains everything the dashboard needs, including
`artifacts/real/forecast/predictions.parquet`, which the Live tab's replay is built from.

## Option 1: Docker Compose

```bash
cp deploy/mobilityops.env.example .env
# edit .env: set MOBILITYOPS_API_KEY to a long random value, for example
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose up -d --build
curl http://127.0.0.1:8000/health            # {"status":"ok"}
```

Open <http://127.0.0.1:8000>. The dashboard asks for the API key once per browser.

* **Serve your local network:** set `MOBILITYOPS_BIND=0.0.0.0` in `.env`, then use
  `http://<this-machine's-address>:8000` from other devices. The key is mandatory; the server
  refuses to listen on a network address without one.
* **HTTPS:** set `MOBILITYOPS_DOMAIN` and `MOBILITYOPS_TRUST_PROXY=1` in `.env` and add
  `--profile tls` (`docker compose --profile tls up -d`). Caddy obtains a certificate for a public
  name, or uses its own local authority for `localhost`. The bundled `deploy/Caddyfile` turns off
  response buffering, which the live stream needs; keep that if you use another proxy.
* The container runs as an unprivileged user with a read-only filesystem, no capabilities and
  `no-new-privileges`, and mounts `data/` and `artifacts/` read-only. Update with
  `git pull && docker compose up -d --build`.

## Option 2: systemd

```bash
sudo useradd --system --home /opt/mobilityops --shell /usr/sbin/nologin mobilityops
sudo git clone https://github.com/jayraj0975/mobilityops /opt/mobilityops
cd /opt/mobilityops && sudo python3 -m venv .venv && sudo .venv/bin/pip install -c requirements.lock .
cd apps/web && npm ci && npm run build && cd ../..       # the dashboard; skip for an API-only server
# put data/ and artifacts/ in /opt/mobilityops (step 1), then:
sudo mkdir -p /etc/mobilityops
sudo cp deploy/mobilityops.env.example /etc/mobilityops/mobilityops.env   # edit; set MOBILITYOPS_API_KEY
sudo chmod 640 /etc/mobilityops/mobilityops.env && sudo chown root:mobilityops /etc/mobilityops/mobilityops.env
sudo cp deploy/mobilityops.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mobilityops
journalctl -u mobilityops -f
```

The unit runs the service unprivileged with the install directory read-only.

## Connect the Android app

Build or download the APK ([apps/android](../apps/android/README.md)), install it, and open
**Settings**:

* On the Android **emulator** the host computer is `http://10.0.2.2:8000`.
* On a **phone**, use the server machine's address on your network, for example
  `http://192.168.1.20:8000` (the phone and the server must be on the same network; check the
  server's firewall allows the port), then the API key. **Save and test connection** shows what it
  reached.
* The app allows plain `http://` because a home server rarely has a certificate. Anything that
  leaves your local network should use the HTTPS profile above, and then an `https://` address.

## What "real time" means here

| On the Live tab | Is | Source |
|---|---|---|
| **REPLAY** | A replay of held-out days, one hour every few seconds, on a clock shared by every viewer. Forecasts were made before those days; actual pickups are shown against them. **Not live taxi data**: the TLC publishes trips monthly. | `artifacts/<mode>/forecast/predictions.parquet` |
| **LIVE** | Citi Bike station availability and the current Central Park weather, with the publisher's own timestamp. If a source stops answering, the last good reading stays on screen and says it is not current. | public GBFS feed, api.weather.gov |

The feeds are fetched only while someone has the Live tab (or the app) open, once a minute.
`MOBILITYOPS_LIVE_FEEDS=false` switches them off; `MOBILITYOPS_LIVE_SECONDS_PER_HOUR` changes the
replay speed; `MOBILITYOPS_LIVE_MAX_STREAMS` caps concurrent viewers (default 32; further ones get a
429 that says so).

## Security: what is and is not covered

* Every API request needs the key when one is set; a wrong or missing key is a 401. Comparison is
  constant-time. The dashboard keeps the key in the browser's local storage, the app in private app
  preferences.
* Rate limits, a request body cap, security headers and single-flight caching are on by default (see
  [SECURITY](SECURITY.md)). The event stream is capped by concurrent viewers.
* **Not covered:** user accounts (there is one shared key), audit logging, protection against a
  distributed flood. Plain HTTP on a network is readable by anyone on it: use the HTTPS profile if that
  matters.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Live tab says "Connection lost: reconnecting" and never recovers | A proxy is buffering the stream. Turn buffering off (`flush_interval -1` in Caddy, `proxy_buffering off` in nginx). |
| "This server needs an API key" | The key entered does not match `MOBILITYOPS_API_KEY`. |
| "32 live streams are already open" | The stream cap was reached; wait or raise `MOBILITYOPS_LIVE_MAX_STREAMS`. |
| Replay says "not available yet" | No held-out forecasts: run `forecast-eval`. |
| Citi Bike says "not answering" | The feed is down or the machine has no outbound access; the message shows the error. |
| Server exits at start-up about "network address" | Listening beyond localhost needs `MOBILITYOPS_API_KEY`. |
