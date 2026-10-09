
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader

app = FastAPI(
    title="Silvera API",
    description="Secure Enterprise Intelligence",
    version="0.3.0",
)

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

UPLOAD_DIR = Path("uploads")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


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
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file.",
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF must be smaller than 10 MB.",
        )

    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid PDF.",
        )

    try:
        reader = PdfReader(io.BytesIO(content), strict=True)

        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="Password-protected PDFs are not supported yet.",
            )

        extracted_text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read this PDF. Please try another file.",
        )

    if not extracted_text:
        raise HTTPException(
            status_code=400,
            detail="No readable text found. Scanned PDFs are not supported yet.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid4())
    filename = Path(file.filename).name

    text_path = UPLOAD_DIR / f"{document_id}.txt"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"

    metadata = {
        "filename": filename,
        "pages": len(reader.pages),
        "characters_extracted": len(extracted_text),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    text_path.write_text(extracted_text, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "document_id": document_id,
        "filename": filename,
        "pages": len(reader.pages),
        "characters_extracted": len(extracted_text),
        "preview": extracted_text[:500],
        "message": "PDF uploaded and text extracted successfully.",
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
            metadata_content = metadata_path.read_text(encoding="utf-8")
            try:
                metadata = json.loads(metadata_content)
                filename = metadata.get("filename", "Unknown document")
            except json.JSONDecodeError:
                # Support older metadata files containing only a filename.
                filename = metadata_content.strip() or "Unknown document"
        except OSError:
            filename = "Unknown document"

        paragraphs = [
            paragraph.strip()
            for paragraph in text.splitlines()
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
            })

    return {
        "query": q,
        "results": results[:10],
        "total_results": len(results),
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
                # Support older metadata files containing only a filename.
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
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid document ID.",
        )

    text_path = UPLOAD_DIR / f"{document_id}.txt"
    metadata_path = UPLOAD_DIR / f"{document_id}.meta"

    if not text_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    try:
        # Remove metadata first. If that fails, the document remains searchable.
        metadata_path.unlink(missing_ok=True)
        text_path.unlink()
    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Could not delete the document. Please try again.",
        )

    return {
        "document_id": document_id,
        "message": "Document deleted successfully.",
    }
