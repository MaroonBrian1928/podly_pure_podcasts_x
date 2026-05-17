# Multi-stage build for combined frontend and backend
FROM node:18-alpine AS frontend-build

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN set -e && \
    npm run build && \
    test -d dist && \
    echo "Frontend build successful - dist directory created"

FROM rust:1-slim AS rust-tools
WORKDIR /app/rust

COPY rust/Cargo.toml rust/Cargo.lock* ./
COPY rust/src/ ./src/
RUN cargo build --release --locked

FROM python:3.14-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    ffmpeg \
    gosu \
    libjemalloc2 \
    libsqlite3-dev \
    sqlite3 && \
    apt-get remove -y python3-blinker 2>/dev/null || true && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Preload jemalloc to replace glibc's ptmalloc allocator. jemalloc has much
# better fragmentation behavior for long-running multi-threaded Python servers,
# typically cutting steady-state RSS roughly in half. Resolve the actual file
# at build time because the path varies across architectures.
RUN JEMALLOC_PATH="$(dpkg -L libjemalloc2 | grep -E 'libjemalloc\.so\.2$' | head -n1)" && \
    test -n "$JEMALLOC_PATH" && \
    printf '%s\n' "$JEMALLOC_PATH" > /etc/podly-jemalloc-path
ENV PODLY_JEMALLOC_PRELOAD=1

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
RUN rm -rf ./src/instance
COPY scripts/ ./scripts/
RUN chmod +x scripts/start_services.sh

RUN mkdir -p /app/bin
COPY --from=rust-tools /app/rust/target/release/podly_tools /app/bin/podly_tools

COPY --from=frontend-build /app/dist ./src/app/static

RUN groupadd -r appuser && \
    useradd --no-log-init -r -g appuser -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

RUN mkdir -p /app/processing /app/src/instance /app/src/instance/data /app/src/instance/data/in /app/src/instance/data/srv /app/src/instance/config /app/src/instance/db && \
    chown -R appuser:appuser /app/processing /app/src/instance

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod 755 /docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5001

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["./scripts/start_services.sh"]
