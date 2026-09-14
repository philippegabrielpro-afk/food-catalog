# Food Catalog API

Standalone generic food-reference service extracted from Diablotin. It provides
food search, autocomplete metadata and versioned nutritional provenance.

It must never receive patient identity, medical context, glucose data, insulin
data, meal history, audio or personalized nutritional corrections. See
`ARCHITECTURE.md`.

## API

Consumer endpoints require `X-API-Key`:

- `GET /v1/foods/search?q=riz%20basmati&limit=8`
- `GET /v1/foods/{food_id}`
- `GET /v1/references/{source}/{external_code}`
- `GET /v1/references/{source}/{external_code}?source_version={version}`

Administration endpoints require the distinct admin key:

- `POST /v1/admin/foods`
- `PUT /v1/admin/foods/{food_id}`
- `POST /v1/admin/imports/ciqual`

OpenAPI documentation is available at `/docs`. Liveness is public at `/health`;
database readiness and the loaded food count are available at `/ready`.

## Local development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8080
```

The default development configuration uses SQLite. Replace the keys in `.env`
before any shared deployment. Docker Compose forces production validation even
though `.env.example` remains convenient for local SQLite development.

## Docker

Create `.env` from `.env.example`, replace all three example secrets (including
`POSTGRES_PASSWORD`), then run:

```bash
docker compose up -d --build
```

Both API keys must be distinct secrets of at least 32 characters in production.
Generate each one independently, for example with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

The API binds only to `127.0.0.1:8080`; expose it through a separately configured
TLS reverse proxy. PostgreSQL is on an internal Docker network.

## Example

```bash
curl -H 'X-API-Key: dev-consumer-key' \
  'http://127.0.0.1:8080/v1/foods/search?q=riz%20basmati'
```

The response includes the selected reference and its `carbs_per_100g`. The
calling application performs any quantity calculation locally. Food Catalog
does not receive the quantity eaten or a meal event.

## Data source

The bundled Ciqual extract contains 3,484 food records and is imported
idempotently. Attribution and licence information are in `NOTICE.md`.
An import is rejected if the same published source version is presented with a
different file hash. Nutrition references are immutable: changing a value
requires a new `source_version`, preserving the audit trail.

## Scope of this increment

This is an API-first pilot foundation, not a finished public SaaS. Before selling
access, add per-client hashed credentials, revocation, quotas, rate limiting,
audit logs, monitoring, backups and contractual/security documentation. The
current two static keys are suitable for one controlled integration only.
