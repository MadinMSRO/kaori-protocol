# Pattern B sidecar image for a future Cloud Run service `kaori-api`
# in GCP project msro-kaori-sandbox (asia-southeast1).
#
# Build only. This file does not deploy, create Artifact Registry, or
# touch msro-udfi-sandbox.
#
# Future image name (registry is not created in this PR):
#   asia-southeast1-docker.pkg.dev/msro-kaori-sandbox/kaori/kaori-api

FROM python:3.12-slim

WORKDIR /app

COPY packages/kaori-truth/src/kaori_truth /app/kaori_truth
COPY packages/kaori-flow/src/kaori_flow /app/kaori_flow
COPY packages/kaori-db/src/kaori_db /app/kaori_db
COPY packages/kaori-api/src/kaori_api /app/kaori_api
COPY packages/kaori-spec/schemas /app/packages/kaori-spec/schemas

RUN pip install --no-cache-dir \
        "fastapi>=0.100.0" \
        "uvicorn[standard]>=0.22.0" \
        "pydantic>=2.0.0" \
        "sqlalchemy>=2.0.0" \
        "pyyaml>=6.0" \
        "psycopg2-binary>=2.9.0" \
    && useradd --create-home --uid 10001 kaori \
    && chown -R kaori:kaori /app

ENV PYTHONPATH=/app
ENV KAORI_SCHEMA_PATH=/app/packages/kaori-spec/schemas
ENV PYTHONUNBUFFERED=1

# Runtime: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY. DATABASE_URL optional (Cloud SQL).
# Compiler reads ClaimType YAML from KAORI_SCHEMA_PATH (not a claim_types table).
# Evidence uri remains a string pointer. Three routes: compile, standing, truth.
EXPOSE 8080

USER kaori

CMD ["sh", "-c", "uvicorn kaori_api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
