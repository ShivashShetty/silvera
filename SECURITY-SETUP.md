# Security & Governance Setup

This guide covers the current local-development implementation. It is not
production-hardening guidance or a security certification.

## Run locally

From the repository root, install the backend and frontend dependencies:

```powershell
Set-Location .\backend
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

Set-Location ..\frontend
npm install
```

Run the API and frontend in separate PowerShell windows:

```powershell
Set-Location .\backend
.\venv\Scripts\python.exe -m uvicorn main:app --reload
```

```powershell
Set-Location .\frontend
npm run dev
```

Open `http://localhost:5173`. The API allows browser origins on
`localhost:5173` and `127.0.0.1:5173`; other origins are rejected by the
current configuration.

## First administrator setup and existing data

On first startup, Silvera creates `backend/data/security.db`. Use the
first-run setup screen to create the initial administrator. During this
one-time setup, existing documents, conversations, and registered
structured datasets are imported into the security database and assigned
private/restricted defaults under that administrator.

The importer reads the existing upload metadata and application databases;
it does not migrate, rewrite, or delete the existing ChromaDB,
conversation-history, or structured-data databases. No backup is created
automatically. Keep your normal backups before changing or upgrading the
application.

After setup, administrators can create users, change roles, configure
resource policies and grants, inspect audit events, and manage retention.
New documents and datasets are private by default. Search and RAG access
checks are enforced before retrieved passage text is sent to the local
answer model. Dataset query grants can limit the visible columns.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `SILVERA_SECURITY_DB` | `backend/data/security.db` | Path to the separate security database |
| `SILVERA_STRUCTURED_DATABASE` | `backend/data/structured_data.db` | Path to the structured-data SQLite database |
| `SILVERA_MAX_UPLOAD_MB` | `100` | Per-file upload limit in MiB; allowed range is 1–500 |
| `SILVERA_SESSION_TTL_HOURS` | `12` | Session lifetime, clamped to 1 hour through 30 days |
| `SILVERA_COOKIE_SECURE` | `false` | Set to `true` when serving over HTTPS to mark auth cookies Secure |

Set variables in the process environment before starting the API. Use
HTTPS and `SILVERA_COOKIE_SECURE=true` for a deployment behind a properly
configured TLS endpoint. Do not expose the development server directly to
the public internet.

The upload limit defaults to 100 MiB per file. For example, set
`$env:SILVERA_MAX_UPLOAD_MB = "200"` in the API's PowerShell window before
starting Uvicorn to allow files up to 200 MiB. The limit is also returned
by `/api/status` so the Documents page displays the configured value.

## Current safeguards and limitations

- Passwords are bcrypt-hashed. Passwords must be at least 12 characters
  and at most 72 UTF-8 bytes.
- Login is temporarily locked after five failed attempts for the
  username/client-address pair.
- Authentication uses opaque server-side sessions, HttpOnly session
  cookies, CSRF-token validation, and an allowed-origin check for
  state-changing API requests.
- Roles are `ADMIN`, `MANAGER`, `EMPLOYEE`, and `VIEWER`. Administrative
  and resource permissions are enforced by the API, not just the UI.
- SQL execution is read-only and restricted to the permitted dataset and
  columns. It accepts a single `SELECT`/`WITH` statement, has a five-second
  execution limit, returns at most 100 rows, and limits response data to
  1 MB. NL-to-SQL generation requires the local Ollama service.
- Retention preview is non-destructive. Archive hides selected documents;
  permanent deletion requires administrator confirmation and removes
  stored document files, search vectors, and the security record.
- Supported local document types include PDF, DOCX/DOCM, XLSX/XLSM,
  PPTX/PPTM, CSV/TSV, TXT/MD, HTML, EML, JSON, and XML. Legacy `.doc`,
  `.xls`, and `.ppt` files and scanned-PDF OCR are not supported.
- Extracted text is capped at 50 million characters per document, and
  Office files are checked for oversized expanded archives. ChromaDB
  embeddings are generated in batches after upload, so the upload response
  does not wait for the full indexing job. The Documents page reports
  indexing progress and any indexing failure. Larger uploads can still
  take time and need adequate disk, memory, and CPU resources.
- SQL-specific spreadsheet table registration/ingestion is not
  implemented in this checked-out source. SQL can use only datasets
  already registered in the configured structured-data database.
- The origin allowlist is currently fixed to the two local development
  origins. Production deployment needs an intentional origin and proxy
  configuration.
- The application has not been independently penetration-tested or
  reviewed for production deployment. Plan backups, monitoring,
  infrastructure-level rate limiting, HTTPS, dependency review, and
  operational recovery before using sensitive or shared production data.

## Verification

Run the backend tests and production frontend build from the repository
root:

```powershell
Set-Location .\backend
.\venv\Scripts\python.exe -m unittest discover -s tests -v

Set-Location ..\frontend
npm run build
```

## Manual security checklist

1. Verify that an unauthenticated API request is rejected.
2. Create the initial administrator and confirm that setup cannot be
   repeated.
3. Create a non-admin user and confirm that admin-only endpoints reject
   that user.
4. Grant document view/query access and confirm that search and RAG only
   return passages for authorized documents.
5. Grant access to selected dataset columns and confirm that querying
   other columns fails without revealing their names.
6. Revoke a grant and confirm that subsequent document and dataset
   requests no longer succeed.
7. Preview retention and confirm that it changes no stored data. Test
   archive and permanent deletion only with disposable data and an
   explicit administrator confirmation.
