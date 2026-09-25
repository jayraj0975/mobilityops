# syntax=docker/dockerfile:1
# MobilityOps: API + built UI in one small image. No data, models or secrets are baked in:
# mount ./data and ./artifacts, and pass any keys at run time.

FROM node:24-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.14-slim AS app
# LightGBM needs the OpenMP runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir -c requirements.lock .
COPY --from=web /web/dist ./apps/web/dist
COPY scripts/fetch_demo.py ./scripts/fetch_demo.py
# Optional: bake in the aggregate-only demo bundle (see docs/DEPLOYMENT.md). Without these
# build arguments the image contains no data, as above.
ARG DEMO_URL=""
ARG DEMO_SHA256=""
RUN if [ -n "$DEMO_URL" ]; then python scripts/fetch_demo.py "$DEMO_URL" "$DEMO_SHA256" /app; fi
RUN mkdir -p /app/data /app/artifacts /app/reports && chown -R app:app /app
USER app
ENV MOBILITYOPS_DATA_DIR=/app/data \
    MOBILITYOPS_MODE=sample \
    MOBILITYOPS_WEB_DIST=/app/apps/web/dist \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["python", "-m", "mobilityops.cli"]
# Secure by default: listening on 0.0.0.0 requires MOBILITYOPS_API_KEY, and the server refuses to
# start without it. To run without a key, say so explicitly and publish to localhost only:
#   docker run -p 127.0.0.1:8000:8000 -e MOBILITYOPS_ALLOW_UNAUTHENTICATED=true ...
# (a deliberately public demo sets the same variable; see render.yaml).
CMD ["serve", "--host", "0.0.0.0"]
