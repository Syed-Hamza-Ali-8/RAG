# Gateway app image: the API, dashboard, migrations, seeder and demo corpus. No secrets: configuration comes from
# the environment (docker compose passes .env), and .dockerignore keeps .env out of the build context.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies first (cached layer), exactly as locked; no dev tools in the image.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY gateway ./gateway
COPY migrations ./migrations
COPY scripts ./scripts
COPY corpus ./corpus
COPY eval/baselines ./eval/baselines
# Mode set here, not inherited: git on NTFS (core.filemode=false) and Windows checkouts drop the exec bit.
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh
RUN uv sync --frozen --no-dev

# Unprivileged user; the embedding-weights cache is a volume this user owns.
RUN useradd --create-home --uid 10001 gateway && mkdir -p /cache/fastembed && chown -R gateway /cache /app
USER gateway

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
