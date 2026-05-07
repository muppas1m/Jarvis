FROM python:3.12-slim

WORKDIR /app

# System deps
#  - build-essential, libpq-dev: psycopg2 / asyncpg compile + native pg client
#  - curl: healthchecks + occasional debug from inside the container
#  - git: a few Python packages (mcp, langgraph) install fine with vendored
#    wheels but git is needed when pip falls back to a sdist that uses VCS metadata
#  - zlib1g-dev: zlib-state (transitive via FlagEmbedding → ir-datasets) is a
#    C extension that links zlib at build time. Without these headers the cold
#    `pip install` fails with "Failed building wheel for zlib-state".
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        git \
        zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only the manifest first so Docker's layer cache survives source-only edits.
COPY pyproject.toml ./

# pip install -e . needs *something* to install. Until Turn 4 lands real code,
# we seed a stub `app/` package so setuptools' editable install registers a
# discoverable package. The stub gets overwritten when source COPYs in below
# (and again at runtime when docker-compose mounts the live ./backend volume).
RUN mkdir -p app && touch app/__init__.py

# Install dependencies + dev extras + register the local package as editable.
# Editable mode lets uvicorn --reload pick up host changes via the volume mount
# defined in docker-compose.yml.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# Copy the rest of the source. The COPY of `./app` (when it exists locally)
# overwrites the stub from above. Other top-level files (alembic.ini, scripts/)
# also land here.
COPY . .

EXPOSE 8000

# Default command — uvicorn with reload. The reload watcher needs PYTHONUNBUFFERED
# so logs surface immediately under `docker compose logs -f backend`.
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
