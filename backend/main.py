
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from fastapi.responses import FileResponse
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pypdf import PdfReader
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

@app.on_event("startup")
def startup_event():
    initialize_database()

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
MAX_FILE_SIZE = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".docm",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".pptm",
    ".csv",
    ".tsv",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".eml",
    ".json",
    ".xml",
}


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
    }


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="A filename is required.",
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. Silvera currently accepts PDF, DOCX, DOCM, "
                "XLSX, XLSM, PPTX, PPTM, CSV, TSV, TXT, MD, HTML, HTM, EML, JSON, and XML."
            ),
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Files must be smaller than 10 MB.",
        )

    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid PDF.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    document_id = str(uuid4())
    filename = Path(file.filename).name

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
        "file_type": extraction.file_type,
        "pages": len(page_texts),
        "characters_extracted": len(extracted_text),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "original_extension": suffix,
        "warnings": extraction.warnings,
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

        chunk_count = index_document_pages(
            document_id=document_id,
            filename=filename,
            pages=page_texts,
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
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not save and index the document. "
                "Please try again."
            ),
        ) from exc

    return {
        "document_id": document_id,
        "filename": filename,
        "pages": len(page_texts),
        "characters_extracted": len(extracted_text),
        "preview": extracted_text[:500],
        "chunks_indexed": chunk_count,
        "message": "Document uploaded and indexed for search.",
    }


@app.get("/api/documents/search")
def search_documents(q: str):
    query = q.strip().lower()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Please enter a search query.",
        )

    if not UPLOAD_DIR.exists():
        return {"query": q, "results": [], "total_results": 0}

    results = []

    for text_path in UPLOAD_DIR.glob("*.txt"):
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

    return {
        "query": q,
        "results": results[:10],
        "total_results": len(results),
    }


@app.get("/api/documents/semantic-search")
def semantic_search(q: str, limit: int = 5):
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
        matches = search_similar_documents(query, limit=limit)

        matches = [
            match
            for match in matches
            if (
                UPLOAD_DIR / f"{match['document_id']}.txt"
            ).is_file()
        ]

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
def ask_silvera(request: AskRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Please enter a question.",
        )

    # Create a new conversation or continue an existing one.
    conversation_id = request.conversation_id

    if conversation_id:
        try:
            conversation_id = str(UUID(conversation_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid conversation ID.",
            ) from exc

        if not conversation_exists(conversation_id):
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )
    else:
        conversation_id = create_conversation(question)

    if request.data_mode:
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
        structured_query = None
        try:
            matches = search_similar_documents(
                question,
                limit=5,
            )

            # Ignore passages from documents that no longer exist.
            matches = [
                match
                for match in matches
                if (
                    UPLOAD_DIR / f"{match['document_id']}.txt"
                ).is_file()
            ]

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
def list_documents():
    if not UPLOAD_DIR.exists():
        return {"documents": []}

    documents = []

    for text_path in UPLOAD_DIR.glob("*.txt"):
        document_id = text_path.stem
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
            })

        except OSError:
            continue

    documents.sort(
        key=lambda document: document.get("uploaded_at") or "",
        reverse=True,
    )

    return {"documents": documents}


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str):
    try:
        document_id = str(UUID(document_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        ) from exc

    text_path = UPLOAD_DIR / f"{document_id}.txt"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    pages_path = UPLOAD_DIR / f"{document_id}.pages.json"

    if not text_path.is_file() and not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    try:
        metadata = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = {}

        original_extension = metadata.get("original_extension") or ".pdf"
        original_path = UPLOAD_DIR / f"{document_id}{original_extension}"

        metadata_path.unlink(missing_ok=True)
        pages_path.unlink(missing_ok=True)
        text_path.unlink(missing_ok=True)
        original_path.unlink(missing_ok=True)
        delete_document_vectors(document_id)
        delete_structured_document(document_id)

    except (OSError, sqlite3.Error):
        raise HTTPException(
            status_code=500,
            detail="Could not delete the document. Please try again.",
        )

    return {
        "document_id": document_id,
        "message": "Document and its search index deleted successfully.",
    }

@app.get("/api/documents/{document_id}/original")
def open_original_document(document_id: str):
    try:
        document_id = str(UUID(document_id))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        )

    metadata_path = UPLOAD_DIR / f"{document_id}.meta"
    if not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "Original document not found. "
                "Please upload the document again."
            ),
        )

    try:
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="Could not read document metadata.",
        )

    original_extension = metadata.get("original_extension") or ".pdf"
    original_path = UPLOAD_DIR / f"{document_id}{original_extension}"

    if not original_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Original document file is missing.",
        )

    filename = Path(metadata.get("filename", "document")).name
    extension = original_extension.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docm": "application/vnd.ms-word.document.macroEnabled.12",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".eml": "message/rfc822",
        ".json": "application/json",
        ".xml": "application/xml",
    }

    return FileResponse(
        path=original_path,
        media_type=media_types.get(extension, "application/octet-stream"),
        filename=filename,
        content_disposition_type="inline" if extension == ".pdf" else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/documents/{document_id}/pages/{page_number}")
def get_document_page(document_id: str, page_number: int):
    """Return extracted text for one indexed document page or section."""
    try:
        document_id = str(UUID(document_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        ) from exc

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

    return {
        "document_id": document_id,
        "filename": Path(metadata.get("filename", "document.pdf")).name,
        "page_number": page_number,
        "total_pages": len(page_texts),
        "text": page_texts[page_number - 1] or "",
    }


@app.get("/api/conversations")
def api_list_conversations():
    return {
        "conversations": list_conversations(),
    }


@app.get("/api/conversations/{conversation_id}")
def api_get_conversation(conversation_id: str):
    try:
        conversation_id = str(UUID(conversation_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        ) from exc

    conversation = get_conversation(conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return conversation


@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(conversation_id: str):
    try:
        conversation_id = str(UUID(conversation_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        ) from exc

    if not delete_conversation(conversation_id):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return {
        "conversation_id": conversation_id,
        "message": "Conversation deleted successfully.",
    }
