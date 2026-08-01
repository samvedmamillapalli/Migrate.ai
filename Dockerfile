# Migration Oracle API (control plane)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
  && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
COPY backend/alembic ./backend/alembic
COPY backend/alembic.ini ./backend/alembic.ini
COPY certs ./certs

WORKDIR /app/backend
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
