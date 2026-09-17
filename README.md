# Food Catalog API

Version 0.2.0 adds a single-admin browser interface at `/admin`.

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
- `GET /v1/admin/foods?q=&offset=0&limit=30` (paginated browser search)
- `GET /v1/admin/foods/{food_id}` (all reference versions)
- `PATCH /v1/admin/foods/{food_id}` (metadata only, full metadata payload)
- `POST /v1/admin/foods/{food_id}/references` (new immutable version)
- `POST /v1/admin/foods/{food_id}/references/{reference_id}/prefer`
- `GET /v1/admin/imports`
- `POST /v1/admin/imports/ciqual`
- `GET /v1/admin/audit?food_id={optional_food_id}&limit=50`

## Administration interface

Start the local API, then open `http://127.0.0.1:8080/admin`. Sign in using
`FOOD_CATALOG_ADMIN_API_KEY` from your own `.env`; never share it. The consumer
key cannot access administration. The admin key cannot access consumer routes.
The interface keeps its key in JavaScript memory only, clears the login field,
and loses authentication on page reload or logout. There are no authentication
cookies, persistent browser storage or third-party frontend assets.

Use HTTPS outside loopback. The login interface blocks sending a key over
non-local HTTP; this does not replace TLS configuration for direct API callers.
HTML/assets and admin responses have `no-store`, an explicit CSP, frame denial
and MIME-sniffing protection.

The browser supports paginated browsing, accent-insensitive name/alias/tag
search, generic food creation, metadata editing, reference history and default
reference selection. A new value becomes the default but does not overwrite
historical references. `Ciqual` is reserved for bundled official imports;
generic corrections must use another source, such as `manual`.

The import button reruns only the bundled extract; it does not discover new
Anses releases or accept arbitrary files. Import history stores completed
batches. Repeated requests are visible in the administration audit but do not
duplicate the source batch. Failed imports roll back and show an immediate
error, without a persistent failed batch.

Changes through admin write endpoints are recorded transactionally in
`admin_audit`, including generic before/after snapshots. Automatic startup
imports are visible in source history, not as human admin actions. The audit
starts with this version (no invented backfill). It is a shared-key technical
log, not a named-user or tamper-proof audit. Direct database changes are outside
its scope. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for the French local test guide.

Before updating an existing database: stop the API, make a verified backup,
then run `python -m alembic upgrade head`. Migration `0002_admin_audit` adds the
audit table without modifying food/reference records. Do not delete the existing
database or run `Base.metadata.create_all` as a substitute for Alembic.

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
current two static keys are suitable for one controlled integration only. The
administration UI does not change this commercial-readiness boundary. Its
technical audit does not replace per-user identity or a security assessment.
