# Migration Oracle API (control plane)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
  && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
COPY backend/alembic ./backend/alembic
COPY backend/alembic.ini ./backend/alembic.ini
# Three migrations do `from alembic_helpers import Vector`. It resolves locally
# only because alembic runs with backend/ as the working directory; without it
# in the image, `alembic upgrade head` dies at container start with
# ModuleNotFoundError before uvicorn is ever reached.
COPY backend/alembic_helpers.py ./backend/alembic_helpers.py
# Curated open-source incident corpus (16 records). `open_source_corpus.py`
# resolves this as backend/data/open_source_corpus; without it the startup seed
# fails and main.py swallows the error as a warning, leaving the memory browser
# and every retrieval demo silently empty.
COPY backend/data ./backend/data
COPY certs ./certs

WORKDIR /app/backend
# Editable install is load-bearing, not a convenience: resolve_cockroach_ca_cert()
# locates the CockroachDB CA via Path(__file__).parents[3], which only resolves to
# /app (and therefore /app/certs) while the package stays at /app/backend/app. A
# non-editable install relocates it into site-packages, the CA is not found, and
# every sslmode=verify-full connection fails.
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
