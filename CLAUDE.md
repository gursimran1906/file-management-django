# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Django 5.1 internal practice-management system for a UK law firm. It tracks **matters** (cases) end-to-end: client/AML onboarding, risk assessment, time/finance ledgers, invoices, estate accounts and completion statements, correspondence, court bundles, and staff HR (attendance/holidays). It also ingests email (Microsoft Graph) and meeting notes (Granola) automatically against matters.

The central entity is `WIP` (a "matter"), identified by its `file_number`. Most URLs are namespaced under `<str:file_number>/...` and most code paths fan out from a matter.

## Commands

```bash
# Run the dev server (uses settings auto DB detection — see below)
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Tests (Django TestCase; files live in backend/tests/ named tests_*.py,
# which match Django's default test*.py discovery pattern)
python manage.py test                                   # all
python manage.py test backend                           # one app
python manage.py test backend.tests.tests_completion_statement            # one module
python manage.py test backend.tests.tests_estate_account.SomeTestCase.test_x  # one test

# Crontab registration (django-crontab — jobs are defined in settings.CRONJOBS)
python manage.py crontab add        # register with system cron
python manage.py crontab show

# Seed/demo data (custom management commands)
python manage.py seed_completion_statement_demo_data
python manage.py seed_pricing_test_data
python manage.py seed_bundle_large_test_data

# Production server
gunicorn filemanagementDjango.wsgi:application --bind 0.0.0.0:8000 --workers 3 --config gunicorn_config.py
```

**Frontend CSS:** Tailwind v3 + Flowbite. Source is `static/src/input.css`, compiled output is the committed `static/src/output.css` (loaded in `templates/base.html`). After editing templates/styles, rebuild with `npx tailwindcss -i static/src/input.css -o static/src/output.css` (add `--watch` while developing). `django-compressor` (`COMPRESS_ENABLED=True`) handles asset bundling at serve time.

**PDF generation** uses WeasyPrint, which needs native libraries (Cairo/Pango). On macOS install via Homebrew; the Dockerfile installs the apt equivalents plus `qpdf` (used by the bundle builder via PyPDF2/pikepdf/reportlab).

## Configuration & environment

- Secrets load from a gitignored `.env` (checked at both `filemanagementDjango/.env` and project root). `settings.require_env('NAME')` raises if a required secret (`SECRET_KEY`, `DB_USER_PASS`) is missing — there are no hardcoded fallbacks.
- **Database auto-detection** (`settings.py`): defaults to PostgreSQL, but if Postgres isn't reachable on the configured `DB_HOST:DB_PORT` (or `psycopg2` import fails), it transparently falls back to the local `db.sqlite3`. So local dev "just works" without Postgres, but be aware which backend you're actually on.
- `USE_SHAREPOINT` env toggles file storage: when true, `STORAGES['default']` is `backend.storage.sharepoint.SharePointStorage` (Microsoft Graph against four document libraries); otherwise local `FileSystemStorage` in `media/`.
- Key env vars: `DEBUG`, `ALLOWED_HOSTS`, `DB_*`, `SHAREPOINT_*`, `GRANOLA_API_KEY`, `ONBOARDING_PORTAL_*`, `ONBOARDING_SEND_INVITE_EMAILS` (invite emails are off unless true; always off under `manage.py test`).

## Architecture

**Project package:** `filemanagementDjango/` (settings, root `urls.py`, wsgi/asgi). Root URLconf includes `users`, `frontend`, and `backend` urls in that order, plus `/admin`.

**Apps:**
- **`backend`** — the domain core. Almost everything lives here. `models.py` (~50 models, ~2000 lines) and `views.py` (~13k lines) are the giants; the rest is split by domain (see below).
- **`frontend`** — top-level pages, navigation, and `templatetags`. Thin compared to backend.
- **`users`** — `CustomUser` (the `AUTH_USER_MODEL`; `username` is a 3-character staff code) plus HR models (`Rate`, `AttendanceRecord`, `HolidayRecord`, `SicknessRecord`).
- **`email_sorting`** — Microsoft Graph email ingestion (`utils.py`), run on a cron schedule, matching emails to matters and storing them via `backend.utils.insert_data`.

**Domain modules within `backend/` (paired `*.py` logic + `*_views.py` HTTP layer where applicable):**
- `estate_account.py` / `estate_account_views.py` — probate estate accounts (line overrides, manual entries, distributions, signers).
- `completion_statement.py` / `completion_statement_views.py` — conveyancing completion statements (apportionments, mortgage redemptions, scheduled payments, proceeds distribution).
- `finance_display.py`, `money_split.py`, `pmt_slip_service.py` — ledgers, invoices, credit notes, payment slips (pink/blue/green slips), VAT.
- `onboarding_portal.py` / `onboarding_views.py` — client onboarding; talks to an external FastAPI portal when `ONBOARDING_PORTAL_BASE_URL` is set, otherwise a built-in mock.
- `pdf/bundle_builder.py` — assembles court bundles (sections, documents, page ordering) into PDFs.
- `sharepoint/` (`client.py`, `paths.py`, `sharing.py`, `bundle_cache.py`) and `storage/sharepoint.py` — Microsoft Graph / SharePoint document storage and anonymous share links.
- `granola/` — ingests external meeting/attendance notes; converts markdown → Quill, syncs on a cron.

**Cross-cutting conventions:**
- **Auth-by-default:** `LoginRequiredMiddleware` is enabled, so every view requires login. Opt a view out explicitly with `@login_not_required`.
- **Brute-force protection:** `django-axes` locks out by **username only** (not IP — the whole office shares one NAT IP). `AxesMiddleware` must stay last; `AxesStandaloneBackend` must stay first in `AUTHENTICATION_BACKENDS`.
- **Audit trail:** mutations are recorded in the `Modifications` model via helpers in `backend/audit.py` (`log_created`, `build_form_field_changes`, etc.) and `backend.utils.create_modification`. Use these rather than writing audit rows by hand. `backend/audit_display.py` renders them.
- **Multi-client matters:** a `WIP` has a primary `client1` plus `additional_clients` (M2M). Use the `WIP.all_clients` / `all_client_names` / `all_client_emails` properties whenever you need the full client list — don't read `client1` alone for displays, correspondence, invoicing, or AML.
- **Rich text** uses `django_quill` (Quill editor); content is stored as Quill JSON, not raw HTML.
- **`backend.context_processors.matter_nav`** injects matter navigation into every template.

## Deployment notes

Containerized (`Dockerfile` + `docker-compose.yml`), served by Gunicorn behind a proxy. `entrypoint.sh` runs migrations, registers the crontab, and starts `cron` + the app. The container runs as root specifically because it manages the root crontab via `django-crontab` (noted as deferred hardening). See `PRODUCTION_CHECKLIST.md` for the full deploy checklist.
