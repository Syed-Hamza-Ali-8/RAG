#!/bin/sh
# Container start: apply migrations, seed the demo corpus on first start only, then serve.
set -eu
# Fail fast, before migrations or seeding, if the model ID in .env is not in the provider's live roster.
python scripts/resolve_models.py --check
python scripts/migrate.py
python scripts/seed_corpus.py --if-empty
exec uvicorn gateway.main:app --host 0.0.0.0 --port 8000
