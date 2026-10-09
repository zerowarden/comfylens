# syntax=docker/dockerfile:1

# The frontend is built here and copied into the runtime image; the host needs no Node.js.
FROM node:24-slim AS frontend
# pnpm comes from the packageManager field in frontend/package.json via Corepack.
RUN corepack enable
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# Vite writes to ../src/comfylens/web (see frontend/vite.config.ts).
RUN pnpm run build

# Publishes comfylens.local over mDNS through the host's Avahi daemon over DBus.
# Built only through docker-compose.yml (`target: mdns`); keep it before runtime so a
# plain `docker build .` still produces the application image.
FROM debian:trixie-slim AS mdns
RUN apt-get update \
    && apt-get install -y --no-install-recommends avahi-utils dbus \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["avahi-publish", "--address", "--no-reverse", "comfylens.local", "127.0.0.1"]

# The application: Python, the frontend build and the dependencies from uv.lock.
FROM python:3.14-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY --from=frontend /app/src/comfylens/web ./src/comfylens/web
RUN uv sync --frozen --no-dev
EXPOSE 8765
ENTRYPOINT ["comfylens"]
# The image default serves a directory mounted at /library; docker-compose mounts the host
# library at its own path and passes that path as the argument instead.
CMD ["serve", "/library", "--host", "0.0.0.0", "--watch", "--no-open"]
