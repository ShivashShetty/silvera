
import json
import logging
import mimetypes
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from fastapi.responses import FileResponse, JSONResponse
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from services.chat_history import (
    initialize_database,
    create_conversation,
    conversation_exists,
    save_message,
    list_conversations,
    get_conversation,
    delete_conversation,
)

from services.semantic_search import (
    index_document_pages,
    search_similar_documents,
    delete_document_vectors,
)
from services.local_ai import generate_answer
from services import security
from services import structured_data_service
from services.document_extraction import SUPPORTED_EXTENSIONS
from services.document_service import parse_uploaded_file
from services.structured_data_service import (
    StructuredQueryError,
    delete_structured_document,
    get_indexed_document_ids,
    index_structured_document,
    run_structured_query,
)


app = FastAPI(
    title="Silvera API",
    description="Secure Enterprise Intelligence",
    version="0.5.0",
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
def startup_event():
    initialize_database()
    security.initialize_database()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_MB = int(os.environ.get("SILVERA_MAX_UPLOAD_MB", "100"))
if not 1 <= MAX_UPLOAD_MB <= 500:
    raise ValueError("SILVERA_MAX_UPLOAD_MB must be between 1 and 500.")
MAX_FILE_SIZE = MAX_UPLOAD_MB * 1024 * 1024
STRUCTURED_DATABASE_PATH = BASE_DIR / "data" / "structured_data.db"
ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
SESSION_COOKIE = "silvera_session"
CSRF_COOKIE = "silvera_csrf"
SESSION_COOKIE_PATH = "/api"


@app.middleware("http")
async def enforce_authentication_and_csrf(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    security.set_request_id(request_id)
    path = request.url.path
    public_paths = {
        "/",
        "/health",
        "/api/status",
        "/api/auth/setup-status",
        "/api/auth/setup",
        "/api/auth/login",
    }

    if path.startswith("/api/") and path not in public_paths and request.method != "OPTIONS":
        user = security.user_from_session(request.cookies.get(SESSION_COOKIE))
        if user is None:
            response = JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        request.state.user = user

    if path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin not in ALLOWED_ORIGINS:
            response = JSONResponse(
                {"detail": "Request origin is not allowed."},
                status_code=403,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        if path not in {"/api/auth/login", "/api/auth/setup"}:
            session_token = request.cookies.get(SESSION_COOKIE, "")
            csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
            csrf_header = request.headers.get("x-csrf-token", "")
            if (
                not csrf_cookie
                or not csrf_header
                or not hmac_compare(csrf_cookie, csrf_header)
                or not security.verify_csrf(session_token, csrf_header)
            ):
                response = JSONResponse(
                    {"detail": "CSRF validation failed."},
                    status_code=403,
                )
                response.headers["X-Request-ID"] = request_id
                return response

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


def hmac_compare(value_a: str, value_b: str) -> bool:
    import hmac

    return hmac.compare_digest(value_a, value_b)


class SetupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    role: str


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    role: str | None = None
    active: bool | None = None


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class GrantRequest(BaseModel):
    principal_type: str
    principal_id: str
    permissions: list[str]
    columns: list[str] = Field(default_factory=list)


class DocumentPolicyRequest(BaseModel):
    visibility: str | None = None
    classification: str | None = None


class DataAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    dataset_id: str = Field(min_length=1, max_length=200)
    sql: str | None = Field(default=None, max_length=10000)


class RetentionPolicyRequest(BaseModel):
    retention_days: int | None = None


class RetentionExecutionRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=500)
    action: str
    confirmed: bool


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = None
    data_mode: bool = False
    sql: str | None = Field(default=None, max_length=10000)


STRUCTURED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xlsm"}


def sync_existing_structured_documents() -> None:
    if not UPLOAD_DIR.exists():
        return
    indexed_ids = get_indexed_document_ids()
    for metadata_path in UPLOAD_DIR.glob("*.meta"):
        document_id = metadata_path.stem
        if document_id in indexed_ids:
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        extension = str(metadata.get("original_extension") or "").lower()
        if extension not in STRUCTURED_EXTENSIONS:
            continue
        original_path = UPLOAD_DIR / f"{document_id}{extension}"
        if not original_path.is_file():
            continue

        extraction = parse_uploaded_file(
            file_path=original_path,
            filename=Path(metadata.get("filename") or original_path.name).name,
            document_id=document_id,
        )
        index_structured_document(
            document_id,
            Path(metadata.get("filename") or original_path.name).name,
            extraction.tables,
        )
        indexed_ids.add(document_id)


@app.get("/")
def home():
    return {"message": "Welcome to Silvera"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/status")
def api_status():
    return {
        "name": "Silvera",
        "status": "online",
        "message": "Backend connection successful",
        "max_upload_mb": MAX_UPLOAD_MB,
    }


def _set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
) -> None:
    max_age = security.SESSION_TTL_HOURS * 60 * 60
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=security.COOKIE_SECURE,
        samesite="strict",
        path=SESSION_COOKIE_PATH,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=security.COOKIE_SECURE,
        samesite="strict",
        path=SESSION_COOKIE_PATH,
    )


def _new_authenticated_response(user: dict) -> JSONResponse:
    session_token, csrf_token, expires_at = security.create_session(user["id"])
    response = JSONResponse(
        {
            "user": user,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
        }
    )
    _set_auth_cookies(response, session_token, csrf_token)
    return response


def _current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _delete_document_files(document_id: str) -> None:
    text_path = UPLOAD_DIR / f"{document_id}.txt"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    if not text_path.is_file() and not metadata_path.is_file():
        raise FileNotFoundError("Document content was not found.")

    original_extension = ".pdf"
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            stored_extension = metadata.get("original_extension")
            if stored_extension in SUPPORTED_EXTENSIONS or stored_extension in {
                ".pdf",
                ".original",
            }:
                original_extension = stored_extension
        except (OSError, json.JSONDecodeError):
            pass

    for suffix in (
        ".meta",
        ".pages.json",
        ".txt",
        ".pdf",
        ".original",
        original_extension,
    ):
        (UPLOAD_DIR / f"{document_id}{suffix}").unlink(missing_ok=True)
    delete_document_vectors(document_id)
    delete_structured_document(document_id)


def _update_document_index_status(
    metadata_path: Path,
    *,
    status: str,
    progress: int,
    error: str | None = None,
    chunks_indexed: int | None = None,
) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["index_status"] = status
    metadata["index_progress"] = progress
    if error is not None:
        metadata["index_error"] = error
    if chunks_indexed is not None:
        metadata["chunks_indexed"] = chunks_indexed
    temporary_path = metadata_path.with_suffix(".meta.tmp")
    temporary_path.write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(metadata_path)


def _index_document_in_background(
    document_id: str,
    filename: str,
    page_texts: list[str],
    metadata_path: Path,
) -> None:
    def update_progress(completed_batches: int, total_batches: int) -> None:
        progress = (
            100
            if total_batches == 0
            else min(99, int(completed_batches * 100 / total_batches))
        )
        _update_document_index_status(
            metadata_path,
            status="processing",
            progress=progress,
        )

    try:
        chunk_count = index_document_pages(
            document_id=document_id,
            filename=filename,
            pages=page_texts,
            progress_callback=update_progress,
        )
        _update_document_index_status(
            metadata_path,
            status="ready",
            progress=100,
            chunks_indexed=chunk_count,
        )
    except Exception:
        logger.exception("Could not index uploaded document %s", document_id)
        try:
            delete_document_vectors(document_id)
        except Exception:
            logger.exception(
                "Could not remove partial search index for document %s",
                document_id,
            )
        _update_document_index_status(
            metadata_path,
            status="failed",
            progress=0,
            error="Could not create the search index. Check backend logs.",
        )
        security.audit(
            "document_index_failed",
            resource_type="document",
            resource_id=document_id,
            result="failed",
            metadata={"filename": filename},
        )


def _retrievable_document_ids(user: dict) -> list[str]:
    query_ids = set(security.document_ids_for(user, "query"))
    view_ids = set(security.document_ids_for(user, "view"))
    return sorted(query_ids & view_ids)


def _conversation_has_current_source_access(user: dict, conversation: dict) -> bool:
    for message in conversation.get("messages", []):
        for source in message.get("sources", []):
            document_id = source.get("document_id")
            if document_id and not security.can_access_document(
                user, document_id, "view"
            ):
                return False
    return True


def _require_role(user: dict, *roles: str) -> None:
    if user.get("role") not in roles:
        security.audit(
            "permission_denied",
            actor_id=user.get("id"),
            result="denied",
            metadata={"required_role": list(roles)},
        )
        raise HTTPException(status_code=403, detail="Insufficient permissions.")


@app.get("/api/auth/setup-status")
def auth_setup_status():
    return security.security_status()


@app.post("/api/auth/setup")
def initial_admin_setup(request: Request, body: SetupRequest):
    try:
        user = security.create_initial_admin(
            body.name,
            body.username,
            body.password,
            upload_dir=UPLOAD_DIR,
            structured_db_path=STRUCTURED_DATABASE_PATH,
            conversation_db_path=BASE_DIR / "data" / "chat_history.db",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _new_authenticated_response(user)


@app.post("/api/auth/login")
def auth_login(request: Request, body: LoginRequest):
    client_key = request.client.host if request.client else "unknown"
    user, error = security.login(body.username, body.password, client_key)
    if user is None:
        raise HTTPException(status_code=401, detail=error)
    return _new_authenticated_response(user)


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = _current_user(request)
    csrf_token = request.cookies.get(CSRF_COOKIE, "")
    return {"user": user, "csrf_token": csrf_token}


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    user = _current_user(request)
    security.logout(request.cookies.get(SESSION_COOKIE), user["id"])
    response = JSONResponse({"message": "Logged out."})
    response.delete_cookie(
        SESSION_COOKIE,
        path=SESSION_COOKIE_PATH,
        secure=security.COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path=SESSION_COOKIE_PATH,
        secure=security.COOKIE_SECURE,
        httponly=False,
        samesite="strict",
    )
    return response


@app.post("/api/auth/change-password")
def auth_change_password(request: Request, body: PasswordChangeRequest):
    user = _current_user(request)
    try:
        security.change_password(
            user["id"],
            body.current_password,
            body.new_password,
            request.cookies.get(SESSION_COOKIE, ""),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"message": "Password changed. Other active sessions were revoked."}


@app.get("/api/security/overview")
def security_overview(request: Request):
    _require_role(_current_user(request), "ADMIN")
    return security.overview()


@app.get("/api/security/users")
def security_list_users(request: Request, search: str = ""):
    _require_role(_current_user(request), "ADMIN")
    return {"users": security.list_users(search[:120])}


@app.post("/api/security/users", status_code=201)
def security_create_user(request: Request, body: UserCreateRequest):
    try:
        user = security.create_user(
            _current_user(request),
            body.name,
            body.username,
            body.password,
            body.role,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user": user}


@app.patch("/api/security/users/{user_id}")
def security_update_user(
    request: Request,
    user_id: str,
    body: UserUpdateRequest,
):
    try:
        user = security.update_user(
            _current_user(request),
            user_id,
            name=body.name,
            role=body.role,
            active=body.active,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user": user}


@app.post("/api/security/users/{user_id}/reset-password")
def security_reset_password(
    request: Request,
    user_id: str,
    body: PasswordResetRequest,
):
    try:
        security.reset_password(_current_user(request), user_id, body.password)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"message": "Password reset. Existing user sessions were revoked."}


@app.get("/api/security/audit")
def security_audit_log(
    request: Request,
    search: str = "",
    event_type: str = "",
    actor_id: str = "",
    resource_type: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    page_size: int = 25,
):
    user = _current_user(request)
    _require_role(user, "ADMIN", "MANAGER")
    resource_ids = None
    if user["role"] == "MANAGER":
        resource_ids = [
            document["id"] for document in security.security_documents(user)
        ]
    return security.audit_search(
        search=search,
        event_type=event_type,
        actor_id=actor_id,
        resource_type=resource_type,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
        resource_ids=resource_ids,
    )


@app.get("/api/security/governance")
def security_governance(request: Request):
    _require_role(_current_user(request), "ADMIN")
    preview = security.retention_preview()
    return {
        "classification_levels": list(security.CLASSIFICATIONS),
        "retention_days": preview["retention_days"],
        "expiring_documents": preview["affected_documents"],
    }


@app.put("/api/security/governance/retention")
def security_set_retention(
    request: Request,
    body: RetentionPolicyRequest,
):
    try:
        security.set_retention_days(
            _current_user(request),
            body.retention_days,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return security.retention_preview()


@app.post("/api/security/governance/retention/preview")
def security_retention_preview(request: Request):
    _require_role(_current_user(request), "ADMIN")
    return security.retention_preview()


@app.post("/api/security/governance/retention/execute")
def security_retention_execute(
    request: Request,
    body: RetentionExecutionRequest,
):
    user = _current_user(request)
    _require_role(user, "ADMIN")
    if not body.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Explicit administrator confirmation is required.",
        )
    if body.action not in {"archive", "delete"}:
        raise HTTPException(status_code=422, detail="Action must be archive or delete.")
    preview = security.retention_preview()
    eligible = {item["document_id"] for item in preview["affected_documents"]}
    if any(document_id not in eligible for document_id in body.document_ids):
        raise HTTPException(
            status_code=400,
            detail="All selected documents must appear in the current retention preview.",
        )
    if body.action == "archive":
        count = security.mark_archived(user, body.document_ids)
        return {"action": "archive", "affected": count}

    deleted = []
    for document_id in body.document_ids:
        _delete_document_files(document_id)
        security.remove_document_record(user, document_id)
        deleted.append(document_id)
        security.audit(
            "retention_document_deleted",
            actor_id=user["id"],
            resource_type="document",
            resource_id=document_id,
            metadata={"reason": "retention_expired"},
            request_id=request.state.request_id,
        )
    return {"action": "delete", "affected": len(deleted)}


@app.get("/api/security/documents")
def security_documents(request: Request):
    user = _current_user(request)
    _require_role(user, "ADMIN", "MANAGER")
    documents = security.security_documents(user)
    output = []
    for policy in documents:
        metadata_path = UPLOAD_DIR / f"{policy['id']}.meta"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        output.append(
            {
                **policy,
                "filename": metadata.get("filename", "Unavailable document"),
                "grants": security.document_grants(policy["id"]),
            }
        )
    return {"documents": output}


@app.patch("/api/security/documents/{document_id}")
def security_update_document_policy(
    request: Request,
    document_id: str,
    body: DocumentPolicyRequest,
):
    try:
        updated = security.set_document_policy(
            _current_user(request),
            document_id,
            visibility=body.visibility,
            classification=body.classification,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated


@app.put("/api/security/documents/{document_id}/grants")
def security_update_document_grant(
    request: Request,
    document_id: str,
    body: GrantRequest,
):
    try:
        security.set_document_grant(
            _current_user(request),
            document_id,
            body.principal_type,
            body.principal_id,
            body.permissions,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"message": "Document access grant updated."}


@app.get("/api/datasets")
def list_datasets(request: Request):
    user = _current_user(request)
    datasets = []
    for dataset_id in security.dataset_ids_for(user, "query"):
        access = security.dataset_access(user, dataset_id)
        if access is None:
            continue
        policy, permitted_columns = access
        try:
            registry = sqlite3.connect(
                f"file:{STRUCTURED_DATABASE_PATH.resolve().as_posix()}?mode=ro",
                uri=True,
                timeout=5,
            )
            registry.row_factory = sqlite3.Row
            row = registry.execute(
                """
                SELECT filename, sheet_name, row_count
                FROM structured_tables WHERE table_name=?
                """,
                (policy["table_name"],),
            ).fetchone()
            registry.close()
        except sqlite3.Error:
            row = None
        filename = row["filename"] if row else "Uploaded spreadsheet"
        sheet_name = row["sheet_name"] if row else ""
        display_sheet_name = (
            ""
            if sheet_name.strip().casefold() in {"", "table 1", "sheet1"}
            else sheet_name
        )
        datasets.append(
            {
                "id": policy["id"],
                "table_name": structured_data_service.friendly_sql_table_name(
                    filename,
                    sheet_name,
                ),
                "filename": filename,
                "sheet_name": display_sheet_name,
                "row_count": row["row_count"] if row else None,
                "columns": sorted(permitted_columns),
                "classification": policy["classification"],
                "visibility": policy["visibility"],
            }
        )
    return {"datasets": datasets}


@app.get("/api/datasets/{dataset_id}/preview")
def preview_dataset(
    request: Request,
    dataset_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    access = security.dataset_access(_current_user(request), dataset_id)
    if access is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    policy, permitted_columns = access
    try:
        preview = structured_data_service.preview_dataset_rows(
            policy["table_name"],
            permitted_columns,
            limit=limit,
            offset=offset,
        )
    except structured_data_service.UnsafeQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metadata = _read_dataset_metadata(policy["table_name"])
    row_count = metadata.get("row_count") if metadata else None
    has_more = (
        offset + len(preview["rows"]) < row_count
        if isinstance(row_count, int)
        else len(preview["rows"]) == limit
    )
    return {
        "dataset_id": dataset_id,
        "filename": metadata.get("filename") if metadata else "Uploaded spreadsheet",
        "columns": preview["columns"],
        "rows": preview["rows"],
        "offset": offset,
        "limit": limit,
        "row_count": row_count,
        "has_more": has_more,
    }


@app.patch("/api/security/datasets/{dataset_id}")
def security_update_dataset_policy(
    request: Request,
    dataset_id: str,
    body: DocumentPolicyRequest,
):
    try:
        updated = security.set_dataset_policy(
            _current_user(request),
            dataset_id,
            visibility=body.visibility,
            classification=body.classification,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated


@app.put("/api/security/datasets/{dataset_id}/grants")
def security_update_dataset_grant(
    request: Request,
    dataset_id: str,
    body: GrantRequest,
):
    try:
        security.set_dataset_grant(
            _current_user(request),
            dataset_id,
            body.principal_type,
            body.principal_id,
            body.permissions,
            body.columns,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"message": "Dataset access grant updated."}


def _read_dataset_metadata(table_name: str) -> dict | None:
    if not STRUCTURED_DATABASE_PATH.is_file():
        return None
    connection = sqlite3.connect(
        f"file:{STRUCTURED_DATABASE_PATH.resolve().as_posix()}?mode=ro",
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT filename, sheet_name, row_count
            FROM structured_tables WHERE table_name=?
            """,
            (table_name,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


@app.post("/api/data/ask")
def ask_dataset(request: Request, body: DataAskRequest):
    user = _current_user(request)
    access = security.dataset_access(user, body.dataset_id)
    if access is None:
        security.audit(
            "permission_denied",
            actor_id=user["id"],
            resource_type="dataset",
            resource_id=body.dataset_id,
            result="denied",
            metadata={"action": "query"},
            request_id=request.state.request_id,
        )
        raise HTTPException(status_code=404, detail="Dataset not found.")
    policy, permitted_columns = access
    metadata = _read_dataset_metadata(policy["table_name"])
    table_alias = (
        structured_data_service.friendly_sql_table_name(
            metadata["filename"],
            metadata.get("sheet_name", ""),
        )
        if metadata
        else policy["table_name"]
    )
    try:
        if body.sql and body.sql.strip():
            statement = body.sql.strip()
            generated = False
        else:
            statement = structured_data_service.generate_sql(
                body.question.strip(),
                table_alias,
                sorted(permitted_columns),
            )
            generated = True
        try:
            result = structured_data_service.execute_readonly_query(
                policy["table_name"],
                permitted_columns,
                statement,
                table_alias=table_alias,
            )
        except structured_data_service.UnsafeQueryError as exc:
            if not generated or not str(exc).startswith(
                "SQLite rejected the query:"
            ):
                raise
            statement = structured_data_service.generate_sql(
                body.question.strip(),
                table_alias,
                sorted(permitted_columns),
                previous_sql=statement,
                error=str(exc),
            )
            result = structured_data_service.execute_readonly_query(
                policy["table_name"],
                permitted_columns,
                statement,
                table_alias=table_alias,
            )
    except structured_data_service.UnsafeQueryError as exc:
        security.audit(
            "spreadsheet_sql",
            actor_id=user["id"],
            resource_type="dataset",
            resource_id=body.dataset_id,
            result="denied",
            metadata={"generated": bool(not body.sql)},
            request_id=request.state.request_id,
        )
        detail = {"message": str(exc)}
        if generated:
            detail["sql"] = statement
        raise HTTPException(status_code=400, detail=detail) from exc
    except TimeoutError as exc:
        security.audit(
            "spreadsheet_sql",
            actor_id=user["id"],
            resource_type="dataset",
            resource_id=body.dataset_id,
            result="timeout",
            metadata={"generated": bool(not body.sql)},
            request_id=request.state.request_id,
        )
        detail = {"message": str(exc)}
        if generated:
            detail["sql"] = statement
        raise HTTPException(status_code=408, detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="Dataset query service is unavailable.") from exc

    security.audit(
        "spreadsheet_sql",
        actor_id=user["id"],
        resource_type="dataset",
        resource_id=body.dataset_id,
        metadata={
            "generated": generated,
            "rows_returned": len(result["rows"]),
            "truncated": result["truncated"],
        },
        request_id=request.state.request_id,
    )
    return {
        "sql": statement,
        "columns": result["columns"],
        "rows": result["rows"],
        "truncated": result["truncated"],
        "sources": [metadata.get("filename") if metadata else "Uploaded spreadsheet"],
    }


@app.post("/api/documents/upload")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    user = _current_user(request)
    _require_role(user, "ADMIN", "MANAGER")
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Choose a document file to upload.",
        )
    filename = Path(file.filename).name
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf" and suffix not in SUPPORTED_EXTENSIONS:
        supported_types = ", ".join([".pdf", *sorted(SUPPORTED_EXTENSIONS)])
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported types are: {supported_types}.",
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Documents must be {MAX_UPLOAD_MB} MB or smaller.",
        )

    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid PDF.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    document_id = str(uuid4())

    try:
        extraction = parse_uploaded_file(
            file_bytes=content,
            filename=filename,
            document_id=document_id,
            metadata={"original_content_type": file.content_type},
        )
    except Exception as exc:  # pragma: no cover - defensive API handling
        raise HTTPException(
            status_code=400,
            detail="Could not read this file. Please try another document.",
        ) from exc

    extracted_text = extraction.extracted_text.strip()
    if suffix == ".pdf":
        pdf_pages = extraction.metadata.get("page_texts") or []
        page_texts = [
            (page if isinstance(page, str) else "").strip()
            for page in pdf_pages
        ]
    else:
        section_texts = [
            section.text.strip()
            for section in extraction.sections
            if section.text and section.text.strip()
        ]
        page_texts = [
            text for text in section_texts or [extracted_text] if text
        ]

    if not extracted_text and not page_texts:
        raise HTTPException(
            status_code=400,
            detail=(
                "No readable text could be extracted from this file. "
                "A different source or a scanned document may be needed."
            ),
        )

    text_path = UPLOAD_DIR / f"{document_id}.txt"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    original_path = UPLOAD_DIR / f"{document_id}{suffix}"
    pages_path = UPLOAD_DIR / f"{document_id}.pages.json"

    metadata = {
        "filename": filename,
        "original_extension": suffix,
        "pages": len(page_texts),
        "characters_extracted": len(extracted_text),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "file_type": extraction.file_type,
        "warnings": extraction.warnings,
        "index_status": "processing",
        "index_progress": 0,
    }

    try:
        original_path.write_bytes(content)
        text_path.write_text(extracted_text, encoding="utf-8")
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        pages_path.write_text(
            json.dumps(page_texts, ensure_ascii=False),
            encoding="utf-8",
        )

        security.register_document(
            document_id,
            user["id"],
            metadata["uploaded_at"],
        )
        if suffix in STRUCTURED_EXTENSIONS:
            index_structured_document(
                document_id=document_id,
                filename=filename,
                tables=extraction.tables,
            )

    except Exception as exc:
        original_path.unlink(missing_ok=True)
        text_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        pages_path.unlink(missing_ok=True)

        try:
            delete_document_vectors(document_id)
            delete_structured_document(document_id)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not save the document. Please try again."
            ),
        ) from exc

    background_tasks.add_task(
        _index_document_in_background,
        document_id,
        filename,
        page_texts,
        metadata_path,
    )
    security.audit(
        "document_uploaded",
        actor_id=user["id"],
        resource_type="document",
        resource_id=document_id,
        metadata={"filename": filename, "classification": "internal"},
        request_id=request.state.request_id,
    )

    return {
        "document_id": document_id,
        "filename": filename,
        "pages": len(page_texts),
        "characters_extracted": len(extracted_text),
        "preview": extracted_text[:500],
        "index_status": "processing",
        "index_progress": 0,
        "message": "Document uploaded. Search indexing is continuing in the background.",
    }


@app.get("/api/documents/search")
def search_documents(request: Request, q: str):
    query = q.strip().lower()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Please enter a search query.",
        )

    if not UPLOAD_DIR.exists():
        return {"query": q, "results": [], "total_results": 0}

    allowed_ids = set(_retrievable_document_ids(_current_user(request)))
    results = []

    for text_path in UPLOAD_DIR.glob("*.txt"):
        if text_path.stem not in allowed_ids:
            continue
        try:
            text = text_path.read_text(encoding="utf-8")
        except OSError:
            continue

        metadata_path = UPLOAD_DIR / f"{text_path.stem}.meta"

        try:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
            filename = metadata.get("filename", "Unknown document")
        except (OSError, json.JSONDecodeError):
            filename = "Unknown document"

        pages_path = UPLOAD_DIR / f"{text_path.stem}.pages.json"
        try:
            page_texts = json.loads(pages_path.read_text(encoding="utf-8"))
            if not isinstance(page_texts, list):
                page_texts = None
        except (OSError, json.JSONDecodeError):
            page_texts = None

        if page_texts is None:
            # Legacy uploads did not preserve page boundaries.
            searchable_pages = [(None, text)]
        else:
            searchable_pages = [
                (page_number, page_text or "")
                for page_number, page_text in enumerate(page_texts, start=1)
            ]

        for page_number, page_text in searchable_pages:
            paragraphs = [
                paragraph.strip()
                for paragraph in page_text.splitlines()
                if paragraph.strip()
            ]
            matching = [
                paragraph
                for paragraph in paragraphs
                if query in paragraph.lower()
            ]
            for passage in matching:
                results.append({
                    "document_id": text_path.stem,
                    "filename": filename,
                    "passage": passage,
                    "page_number": page_number,
                })

    security.audit(
        "document_text_search",
        actor_id=_current_user(request)["id"],
        resource_type="document",
        metadata={"result_count": len(results)},
        request_id=request.state.request_id,
    )
    return {
        "query": q,
        "results": results[:10],
        "total_results": len(results),
    }


@app.get("/api/documents/semantic-search")
def semantic_search(request: Request, q: str, limit: int = 5):
    query = q.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Please enter a search query.",
        )

    if limit < 1 or limit > 10:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 10.",
        )

    try:
        allowed_ids = _retrievable_document_ids(_current_user(request))
        matches = search_similar_documents(
            query,
            limit=limit,
            document_ids=allowed_ids,
        )

        matches = [
            match
            for match in matches
            if match.get("document_id") in set(allowed_ids)
            and (
                UPLOAD_DIR / f"{match['document_id']}.txt"
            ).is_file()
        ]
        security.audit(
            "semantic_document_search",
            actor_id=_current_user(request)["id"],
            resource_type="document",
            metadata={"result_count": len(matches)},
            request_id=request.state.request_id,
        )

        # Remove weakly related passages before sending evidence to the LLM
        # and before displaying the source panel. Keep all strong matches,
        # including matches from different documents.
        if matches:
            best_relevance = max(
                float(match.get("relevance_score", 0) or 0)
                for match in matches
            )

            # Apply relative filtering only when retrieval has a reasonably
            # strong result. This avoids over-filtering broad/low-score queries.
            if best_relevance >= 0.45:
                relevance_floor = max(0.35, best_relevance * 0.70)
                filtered_matches = [
                    match
                    for match in matches
                    if float(match.get("relevance_score", 0) or 0)
                    >= relevance_floor
                ]

                # Never discard every result; retain the best passage as fallback.
                matches = filtered_matches or matches[:1]

        return {
            "query": query,
            "results": matches,
            "total_results": len(matches),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Semantic search failed. Check that the embedding "
                "model is installed and the backend is running."
            ),
        ) from exc



@app.post("/api/ask")
def ask_silvera(request: Request, body: AskRequest):
    user = _current_user(request)
    question = body.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Please enter a question.",
        )

    # Create a new conversation or continue an existing one.
    conversation_id = body.conversation_id

    if conversation_id:
        try:
            conversation_id = str(UUID(conversation_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid conversation ID.",
            ) from exc

        if not conversation_exists(conversation_id) or not security.accessible_conversation(
            user, conversation_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )
        previous_conversation = get_conversation(conversation_id)
        if not previous_conversation or not _conversation_has_current_source_access(
            user, previous_conversation
        ):
            raise HTTPException(status_code=404, detail="Conversation not found.")
    else:
        conversation_id = create_conversation(question)
        security.register_conversation(conversation_id, user["id"])

    structured_query = None
    if request.data_mode:
        _require_role(user, "ADMIN")
        try:
            sync_existing_structured_documents()
            structured_query = run_structured_query(question, request.sql)
            answer = structured_query["answer"]
        except StructuredQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not query the uploaded spreadsheet data.",
            ) from exc
        matches = []
    else:
        try:
            allowed_ids = _retrievable_document_ids(user)
            matches = search_similar_documents(
                question,
                limit=5,
                document_ids=allowed_ids,
            )

            allowed_id_set = set(allowed_ids)
            matches = [
                match
                for match in matches
                if match.get("document_id") in allowed_id_set
                and (UPLOAD_DIR / f"{match['document_id']}.txt").is_file()
            ]

            if matches:
                best_relevance = max(
                    float(match.get("relevance_score", 0) or 0)
                    for match in matches
                )
                if best_relevance >= 0.45:
                    relevance_floor = max(0.35, best_relevance * 0.70)
                    filtered_matches = [
                        match
                        for match in matches
                        if float(match.get("relevance_score", 0) or 0)
                        >= relevance_floor
                    ]
                    matches = filtered_matches or matches[:1]

        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not retrieve relevant document passages.",
            ) from exc

        try:
            answer = generate_answer(question, matches)

        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Silvera could not generate an answer. "
                    "Make sure Ollama is running and llama3.2:3b is installed."
                ),
            ) from exc

    sources = [
        {
            "document_id": match.get("document_id"),
            "filename": match.get("filename", "Unknown document"),
            "passage": match.get("passage", ""),
            "similarity": match.get("similarity"),
            "chunk_index": match.get("chunk_index"),
            "page_number": match.get("page_number"),
        }
        for match in matches
    ]
    security.audit(
        "document_query",
        actor_id=user["id"],
        resource_type="document",
        result="success",
        metadata={"source_count": len(sources)},
        request_id=request.state.request_id,
    )

    # Save the question and answer with their source references.
    try:
        save_message(
            conversation_id=conversation_id,
            role="user",
            content=question,
        )

        save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            sources=sources,
        )

        conversation = get_conversation(conversation_id)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not save the conversation history.",
        ) from exc

    return {
        "conversation_id": conversation_id,
        "title": conversation["title"],
        "question": question,
        "answer": answer,
        "sources": sources,
        "total_sources": len(sources),
        "model": "llama3.2:3b",
        "local": True,
        "structured_query": structured_query,
    }


@app.get("/api/documents")
def list_documents(request: Request):
    if not UPLOAD_DIR.exists():
        return {"documents": []}

    user = _current_user(request)
    access = {
        row["id"]: row
        for row in security.list_accessible_documents(user, "view")
    }
    documents = []

    for text_path in UPLOAD_DIR.glob("*.txt"):
        document_id = text_path.stem
        policy = access.get(document_id)
        if policy is None:
            continue
        metadata_path = UPLOAD_DIR / f"{document_id}.meta"

        try:
            metadata_content = metadata_path.read_text(encoding="utf-8")

            try:
                metadata = json.loads(metadata_content)
            except json.JSONDecodeError:
                metadata = {"filename": metadata_content.strip()}

            try:
                character_count = len(
                    text_path.read_text(encoding="utf-8")
                )
            except OSError:
                continue

            documents.append({
                "document_id": document_id,
                "filename": metadata.get("filename") or "Unknown document",
                "file_type": metadata.get("file_type"),
                "pages": metadata.get("pages"),
                "characters_extracted": metadata.get(
                    "characters_extracted", character_count
                ),
                "uploaded_at": metadata.get("uploaded_at"),
                "index_status": metadata.get("index_status", "ready"),
                "index_progress": metadata.get("index_progress", 100),
                "index_error": metadata.get("index_error"),
                "owner_id": policy["owner_id"],
                "visibility": policy["visibility"],
                "classification": policy["classification"],
            })

        except OSError:
            continue

    documents.sort(
        key=lambda document: document.get("uploaded_at") or "",
        reverse=True,
    )

    return {"documents": documents}


@app.delete("/api/documents/{document_id}")
def delete_document(request: Request, document_id: str):
    user = _current_user(request)
    try:
        document_id = str(UUID(document_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        ) from exc

    text_path = UPLOAD_DIR / f"{document_id}.txt"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    if not text_path.is_file() and not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    if not security.can_access_document(user, document_id, "delete"):
        security.audit(
            "permission_denied",
            actor_id=user["id"],
            resource_type="document",
            resource_id=document_id,
            result="denied",
            metadata={"action": "delete"},
            request_id=request.state.request_id,
        )
        raise HTTPException(status_code=403, detail="You cannot delete this document.")

    try:
        _delete_document_files(document_id)
        security.remove_document_record(user, document_id)

    except (OSError, sqlite3.Error):
        raise HTTPException(
            status_code=500,
            detail="Could not delete the document. Please try again.",
        )
    security.audit(
        "document_deleted",
        actor_id=user["id"],
        resource_type="document",
        resource_id=document_id,
        request_id=request.state.request_id,
    )

    return {
        "document_id": document_id,
        "message": "Document and its search index deleted successfully.",
    }

@app.get("/api/documents/{document_id}/original")
def open_original_document(request: Request, document_id: str):
    try:
        document_id = str(UUID(document_id))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        )

    user = _current_user(request)
    if not security.can_access_document(user, document_id, "view"):
        security.audit(
            "permission_denied",
            actor_id=user["id"],
            resource_type="document",
            resource_id=document_id,
            result="denied",
            metadata={"action": "view_original"},
            request_id=request.state.request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found.")

    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    if not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Original document not found. Please upload the document again.",
        )

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read document metadata.",
        ) from exc

    original_path = _stored_original_path(document_id, metadata)
    if not original_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Original document file is missing.",
        )
    filename = Path(metadata.get("filename", "document")).name
    security.audit(
        "document_viewed",
        actor_id=user["id"],
        resource_type="document",
        resource_id=document_id,
        request_id=request.state.request_id,
    )
    return FileResponse(
        path=original_path,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        filename=filename,
        content_disposition_type=(
            "inline" if Path(filename).suffix.lower() == ".pdf" else "attachment"
        ),
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/documents/{document_id}/download")
def download_original_document(request: Request, document_id: str):
    try:
        document_id = str(UUID(document_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID.") from exc
    user = _current_user(request)
    if not security.can_access_document(user, document_id, "download"):
        security.audit(
            "permission_denied",
            actor_id=user["id"],
            resource_type="document",
            resource_id=document_id,
            result="denied",
            metadata={"action": "download"},
            request_id=request.state.request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found.")
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Original document not found.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Could not read document metadata.") from exc
    filename = Path(metadata.get("filename", "document")).name
    original_path = _stored_original_path(document_id, metadata)
    if not original_path.is_file():
        raise HTTPException(status_code=404, detail="Original document not found.")
    security.audit(
        "document_downloaded",
        actor_id=user["id"],
        resource_type="document",
        resource_id=document_id,
        request_id=request.state.request_id,
    )
    return FileResponse(
        path=original_path,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        filename=filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _stored_original_path(document_id: str, metadata: dict) -> Path:
    extension = metadata.get("original_extension") or ".pdf"
    if extension not in SUPPORTED_EXTENSIONS and extension != ".pdf":
        extension = ".pdf"

    original_path = UPLOAD_DIR / f"{document_id}{extension}"
    if original_path.is_file():
        return original_path
    for legacy_extension in (".original", ".pdf"):
        legacy_path = UPLOAD_DIR / f"{document_id}{legacy_extension}"
        if legacy_path.is_file():
            return legacy_path
    return original_path


@app.get("/api/documents/{document_id}/pages/{page_number}")
def get_document_page(request: Request, document_id: str, page_number: int):
    """Return extracted text for one indexed document page or section."""
    try:
        document_id = str(UUID(document_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        ) from exc

    user = _current_user(request)
    if not security.can_access_document(user, document_id, "view"):
        security.audit(
            "permission_denied",
            actor_id=user["id"],
            resource_type="document",
            resource_id=document_id,
            result="denied",
            metadata={"action": "view_page"},
            request_id=request.state.request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found.")

    if page_number < 1:
        raise HTTPException(
            status_code=400,
            detail="Page number must be 1 or greater.",
        )

    pages_path = UPLOAD_DIR / f"{document_id}.pages.json"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"

    if not pages_path.is_file() or not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Page text not found for this document.",
        )

    try:
        page_texts = json.loads(pages_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the extracted page text.",
        ) from exc

    if not isinstance(page_texts, list):
        raise HTTPException(
            status_code=500,
            detail="Stored page text has an invalid format.",
        )

    if page_number > len(page_texts):
        raise HTTPException(
            status_code=404,
            detail="Page number is outside this document.",
        )

    security.audit(
        "document_page_viewed",
        actor_id=user["id"],
        resource_type="document",
        resource_id=document_id,
        metadata={"page_number": page_number},
        request_id=request.state.request_id,
    )
    return {
        "document_id": document_id,
        "filename": Path(metadata.get("filename", "document.pdf")).name,
        "page_number": page_number,
        "total_pages": len(page_texts),
        "text": page_texts[page_number - 1] or "",
    }


@app.get("/api/conversations")
def api_list_conversations(request: Request):
    user = _current_user(request)
    conversations = security.list_user_conversations(user, list_conversations)
    safe_conversations = []
    for item in conversations:
        conversation = get_conversation(item["id"])
        if conversation and _conversation_has_current_source_access(user, conversation):
            safe_conversations.append(item)
    return {
        "conversations": safe_conversations,
    }


@app.get("/api/conversations/{conversation_id}")
def api_get_conversation(request: Request, conversation_id: str):
    try:
        conversation_id = str(UUID(conversation_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        ) from exc

    user = _current_user(request)
    if not security.accessible_conversation(user, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    conversation = get_conversation(conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    if not _conversation_has_current_source_access(user, conversation):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )
    return conversation


@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(request: Request, conversation_id: str):
    try:
        conversation_id = str(UUID(conversation_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        ) from exc

    user = _current_user(request)
    if not security.accessible_conversation(user, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if not delete_conversation(conversation_id):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )
    security.remove_conversation_mapping(user, conversation_id)

    return {
        "conversation_id": conversation_id,
        "message": "Conversation deleted successfully.",
    }
