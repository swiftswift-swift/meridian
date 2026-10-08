# Multi-stage: dependencies are installed once into a virtual environment that the runtime
# stage copies, so the final image carries no compiler, no pip cache and no build headers.

FROM python:3.14-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# build-essential is needed only for any package without a manylinux wheel; it stays in this
# stage and never reaches the runtime image.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied on its own so a source change does not invalidate the dependency layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=docker \
    DATA_DIR=/data

# curl is for the healthcheck below; without it HEALTHCHECK has nothing to call.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 meridian

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=meridian:meridian app ./app
COPY --chown=meridian:meridian company_db ./company_db
COPY --chown=meridian:meridian scripts ./scripts
COPY --chown=meridian:meridian web ./web
COPY --chown=meridian:meridian tests/fixtures ./tests/fixtures
COPY --chown=meridian:meridian docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /data \
    && chown meridian:meridian /data

# Non-root from here on: a container that never needs to write outside /data has no reason to
# run with the privileges to do so.
USER meridian
VOLUME ["/data"]
EXPOSE 8000

# Checks readiness rather than liveness, so an instance with an unreachable database is pulled
# out of rotation instead of serving errors.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health/ready || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
