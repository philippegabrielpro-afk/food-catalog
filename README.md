# Food Catalog API

Version 0.2.1 includes the administration interface, corrected Docker networking and daily PostgreSQL backups.

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
`POSTGRES_PASSWORD`), prepare the backup directory as described below, then run:

```bash
docker compose up -d --build
```

Both API keys must be distinct secrets of at least 32 characters in production.
Generate each one independently, for example with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

The API binds only to `127.0.0.1:8080`; expose it through a separately configured
TLS reverse proxy. PostgreSQL is on an internal Docker network.

The API also joins a separate `access` bridge for its host port publication.
The database and backup service join only `private` (`internal: true`). Do not
remove database isolation or publish port 5432 to work around a networking issue.
See the [Docker Compose networking documentation](https://docs.docker.com/compose/how-tos/networking/).

## Daily PostgreSQL backups

The `backup` service creates a backup immediately after the API/database are
healthy, then waits 86,400 seconds between completed runs. This is a daily
interval, not a fixed wall-clock schedule; restarting it starts a new backup.
It does not delete old completed dumps. A snapshot is published only after
`pg_dump` succeeds, the file is nonempty and `pg_restore --list` can read it.
The custom-format temporary file is renamed on the same filesystem, avoiding
an incomplete final `.dump`. Files are mode `600`; credentials are not passed
on command lines or intentionally printed. Failed temporary dumps are cleaned
up, existing archives and the previous success marker are left intact.

Create the host backup directory **before** starting Compose. Default settings
target `/home/ubuntu/food-catalog-backups` and the Ubuntu UID/GID `1000:1000`:

```bash
mkdir -p /home/ubuntu/food-catalog-backups
chmod 700 /home/ubuntu/food-catalog-backups
```

It must be owned by the configured backup UID/GID. Other installations can set
`FOOD_CATALOG_BACKUP_DIR`, `FOOD_CATALOG_BACKUP_UID` and
`FOOD_CATALOG_BACKUP_GID` in `.env`. Compose deliberately does not create a
missing bind directory automatically, to avoid an unexpectedly root-owned path.
The service uses a read-only root filesystem, only the backup directory is
writable, and it receives no API keys. Docker health becomes unhealthy if no
success was recorded in the last 26 hours. This is a status check, not an email
alert. Logs are size-limited; monitor health and available disk space.

Manual one-off backup, while the database is already running:

```bash
docker compose -p food-catalog --env-file .env run --rm --no-deps backup --once
```

These backups contain **only PostgreSQL catalog data**, not `.env`, deployment
keys or host configuration. Same-VPS storage is not off-site protection; plan
a separate encrypted copy and a documented, tested recovery procedure. Archive
listing is not a restoration test. See [OPERATIONS.md](OPERATIONS.md).

## Infrastructure checks

Python tests now include shell success/failure checks and portable Compose
configuration checks. Shell tests are skipped on Windows and must pass on Linux
in CI. `sh -n scripts/backup.sh` and `sh -n scripts/backup-healthcheck.sh` check
syntax on Linux. The new CI-only `scripts/verify-compose.py` uses a fresh,
randomly named project and dummy secrets in a sanitized temporary source copy.
It checks real loopback port publication, startup/data readiness, successful
backups, invalid-password failure protection, and restores one archive into
a **separate disposable database**. It checks 3,484 foods/references, one import
and the code 9125 value. Only that generated CI project's volumes are removed.
It never runs against the VPS or an existing catalog volume. Its dynamic-port
override requires Docker Compose 2.24.4+ (`!override`).

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
