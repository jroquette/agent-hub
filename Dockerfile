# The agent-hub control plane (`hub web`: API and web app) as a container (ADR 0022).
# Build with `make up` or `docker compose build`. Base images are pinned by digest; to bump one,
# read the new digest with `docker buildx imagetools inspect <image>:<tag>` and change it here.
ARG NODE_IMAGE=node:22-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
ARG PYTHON_IMAGE=python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
# uv: the same release as CI (.github/workflows/ci.yml), installed from PyPI with its wheels'
# hashes (x86_64 and aarch64), so a build needs only the Python and npm registries.
ARG UV_REQUIREMENT="uv==0.12.19 \
    --hash=sha256:a63d18a0aa38ee9f21a5406afbbaeb41303bcd954be9d6b7c1b95ac275e53958 \
    --hash=sha256:b466eb0f74645883df52446d54474905e8515d75fdf0b313bf099dedc3237896 \
    --hash=sha256:a36d92c137098fdb9dce27261c5fa8ef5519ba82dcd15d70864c4676d889738d"

# The web app, built from its lockfile exactly as `make web-build` builds it. A build behind a
# TLS-intercepting proxy passes its CA as the optional `build_ca` secret (never stored in a layer).
FROM ${NODE_IMAGE} AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json apps/web/.npmrc ./
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build -- --outDir /web_dist --emptyOutDir

# The Python packages, installed (not editable) from uv.lock into /opt/venv, without dev tools.
FROM ${PYTHON_IMAGE} AS build
ARG UV_REQUIREMENT
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    echo "$UV_REQUIREMENT" > /tmp/uv-requirements.txt \
    && pip install --no-cache-dir --root-user-action=ignore --require-hashes \
       -r /tmp/uv-requirements.txt
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.14 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY packages/ packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --locked --no-dev --no-editable --package agent-hub
# The image serves the app its own web stage built, not the committed copy (equal; tested).
RUN rm -rf /opt/venv/lib/python3.14/site-packages/agent_hub/api/web_dist
COPY --from=web /web_dist /opt/venv/lib/python3.14/site-packages/agent_hub/api/web_dist

FROM ${PYTHON_IMAGE} AS runtime
# git lets Health list a registered hub's files as `hub doctor` does. INSTALL_GIT=0 leaves it out
# (where Debian's mirrors cannot be reached); Health then reports the hubs' listing as a problem.
ARG INSTALL_GIT=1
RUN if [ "$INSTALL_GIT" = 1 ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends git \
      && rm -rf /var/lib/apt/lists/* \
      # The hubs are mounted read-only and owned by the host user, not by uid 10001.
      && git config --system safe.directory '*'; \
    fi
RUN groupadd --system --gid 10001 agent-hub \
    && useradd --system --uid 10001 --gid 10001 --home-dir /data --no-create-home \
       --shell /usr/sbin/nologin agent-hub \
    && install -d -o 10001 -g 10001 -m 0700 /data
COPY --from=build /opt/venv /opt/venv
# AGENT_HUB_IN_CONTAINER=1 is what lets `hub web` bind 0.0.0.0 inside the container; the host
# sees the port only where Compose publishes it, on 127.0.0.1.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/data \
    XDG_CONFIG_HOME=/data/config \
    AGENT_HUB_IN_CONTAINER=1 \
    AGENT_HUB_DB=/data/agent-hub.db
VOLUME ["/data"]
USER 10001:10001
WORKDIR /data
EXPOSE 7420
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import http.client as h; c = h.HTTPConnection('127.0.0.1', 7420, timeout=4); c.request('GET', '/api/v1/collector/status'); raise SystemExit(c.getresponse().status != 200)"]
ENTRYPOINT ["hub", "web", "--host", "0.0.0.0", "--port", "7420"]
LABEL org.opencontainers.image.title="agent-hub" \
      org.opencontainers.image.description="The agent-hub control plane: hub web (API and web app)" \
      org.opencontainers.image.source="https://github.com/jroquette/agent-hub" \
      org.opencontainers.image.base.name="docker.io/library/python:3.14-slim"
