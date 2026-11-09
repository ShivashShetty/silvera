from pathlib import Path
import re
from collections.abc import Callable

import chromadb
from sentence_transformers import SentenceTransformer


# Keep the existing database location, collection name, and embedding model.
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
INDEX_BATCH_SIZE = 128

_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
_collection = _client.get_or_create_collection(
    name="silvera_documents",
    metadata={"hnsw:space": "cosine"},
)

_model = None

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "how", "i", "in", "into", "is", "it", "its", "may", "me",
    "my", "of", "on", "or", "our", "please", "should", "tell", "than",
    "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "to", "was", "we", "were", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your",
}


def get_model():
    """Load the embedding model only when it is first needed."""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def split_into_chunks(
    text: str,
    chunk_size: int = 700,
    overlap: int = 100,
):
    """Split extracted text into overlapping chunks."""
    text = " ".join(text.split())
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap

    return chunks


def _store_document_chunks(
    document_id: str,
    filename: str,
    chunk_records: list[tuple[str, int | None]],
    progress_callback: Callable[[int, int], None] | None = None,
):
    """Embed and store chunk text with optional original PDF page metadata."""
    _collection.delete(where={"document_id": document_id})

    if not chunk_records:
        if progress_callback:
            progress_callback(0, 0)
        return 0

    model = get_model()
    total_batches = (len(chunk_records) + INDEX_BATCH_SIZE - 1) // INDEX_BATCH_SIZE
    if progress_callback:
        progress_callback(0, total_batches)
    for start in range(0, len(chunk_records), INDEX_BATCH_SIZE):
        batch = chunk_records[start : start + INDEX_BATCH_SIZE]
        chunk_texts = [record[0] for record in batch]
        embeddings = model.encode(
            chunk_texts,
            normalize_embeddings=True,
        ).tolist()
        metadatas = []
        for index, (_, page_number) in enumerate(batch, start=start):
            metadata = {
                "document_id": document_id,
                "filename": filename,
                "chunk_index": index,
            }
            if page_number is not None:
                metadata["page_number"] = int(page_number)
            metadatas.append(metadata)

        _collection.add(
            ids=[
                f"{document_id}_{index}"
                for index in range(start, start + len(batch))
            ],
            documents=chunk_texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        if progress_callback:
            completed_batches = (start // INDEX_BATCH_SIZE) + 1
            progress_callback(completed_batches, total_batches)

    return len(chunk_records)


def index_document(document_id: str, filename: str, text: str):
    """
    Backward-compatible indexing for callers that only have merged text.
    Page numbers are intentionally not assigned because page boundaries
    cannot be recovered from a single merged text string.
    """
    chunks = split_into_chunks(text)
    chunk_records = [(chunk, None) for chunk in chunks]
    return _store_document_chunks(document_id, filename, chunk_records)


def index_document_pages(
    document_id: str,
    filename: str,
    pages: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
):
    """
    Index PDF text page by page, preserving 1-based original PDF page numbers.
    Empty pages are retained in the page sequence but do not create chunks.
    """
    chunk_records = []

    for page_number, page_text in enumerate(pages, start=1):
        for chunk in split_into_chunks(page_text or ""):
            chunk_records.append((chunk, page_number))

    return _store_document_chunks(
        document_id,
        filename,
        chunk_records,
        progress_callback,
    )


def _query_terms(query: str) -> list[str]:
    """Extract useful terms while retaining IDs, numbers, and technical tokens."""
    tokens = re.findall(
        r"[a-zA-Z0-9][a-zA-Z0-9._/#-]*",
        query.lower(),
    )
    return list(
        dict.fromkeys(
            token
            for token in tokens
            if token not in _STOP_WORDS and len(token) > 1
        )
    )


def _passages_overlap(text_a: str, text_b: str) -> bool:
    """Detect strongly overlapping passages."""
    words_a = set(re.findall(r"\w+", text_a.lower()))
    words_b = set(re.findall(r"\w+", text_b.lower()))

    if not words_a or not words_b:
        return False

    overlap = len(words_a & words_b)
    similarity = overlap / min(len(words_a), len(words_b))
    return similarity >= 0.85


def search_similar_documents(
    query: str,
    limit: int = 5,
    document_ids: list[str] | None = None,
):
    """
    Hybrid retrieval using semantic similarity and keyword matching.
    Results preserve the existing API fields and add page_number when known.
    """
    query = query.strip()
    if not query or limit <= 0:
        return []

    if document_ids is not None and not document_ids:
        return []
    where = (
        {"document_id": {"$in": document_ids}}
        if document_ids is not None
        else None
    )
    total = _collection.count(where=where) if where else _collection.count()
    if total == 0:
        return []

    terms = _query_terms(query)
    candidates = {}

    # Semantic retrieval.
    model = get_model()
    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
    ).tolist()

    query_options = {
        "query_embeddings": query_embedding,
        "n_results": min(max(limit * 4, 20), total),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_options["where"] = where
    semantic_results = _collection.query(
        **query_options,
    )

    semantic_docs = semantic_results.get("documents", [[]])[0]
    semantic_metas = semantic_results.get("metadatas", [[]])[0]
    semantic_distances = semantic_results.get("distances", [[]])[0]
    semantic_ids = semantic_results.get("ids", [[]])[0]

    for chunk_id, passage, metadata, distance in zip(
        semantic_ids,
        semantic_docs,
        semantic_metas,
        semantic_distances,
    ):
        if not passage or not metadata:
            continue

        similarity = max(0.0, min(1.0, 1.0 - float(distance)))
        candidates[chunk_id] = {
            "document_id": metadata.get("document_id", ""),
            "filename": metadata.get("filename", "Unknown document"),
            "passage": passage,
            "similarity": round(similarity, 4),
            "chunk_index": metadata.get("chunk_index", 0),
            "page_number": metadata.get("page_number"),
            "lexical_score": 0.0,
        }

    # Keyword retrieval scans stored chunks to recover exact-term matches.
    get_options = {"include": ["documents", "metadatas"]}
    if where:
        get_options["where"] = where
    all_chunks = _collection.get(**get_options)

    all_ids = all_chunks.get("ids", [])
    all_docs = all_chunks.get("documents", [])
    all_metas = all_chunks.get("metadatas", [])

    for chunk_id, passage, metadata in zip(
        all_ids,
        all_docs,
        all_metas,
    ):
        if not passage or not metadata:
            continue

        passage_lower = passage.lower()
        matched_terms = sum(
            1 for term in terms if term in passage_lower
        )
        lexical_score = (
            matched_terms / len(terms)
            if terms
            else 0.0
        )

        if chunk_id not in candidates and lexical_score > 0:
            candidates[chunk_id] = {
                "document_id": metadata.get("document_id", ""),
                "filename": metadata.get("filename", "Unknown document"),
                "passage": passage,
                "similarity": 0.0,
                "chunk_index": metadata.get("chunk_index", 0),
                "page_number": metadata.get("page_number"),
                "lexical_score": 0.0,
            }

        if chunk_id in candidates:
            candidates[chunk_id]["lexical_score"] = round(
                lexical_score,
                4,
            )

    # Relevance scoring.
    ranked = []
    for item in candidates.values():
        item["relevance_score"] = round(
            0.65 * item["similarity"]
            + 0.35 * item["lexical_score"],
            4,
        )
        ranked.append(item)

    ranked.sort(
        key=lambda item: item["relevance_score"],
        reverse=True,
    )

    # Diversity and duplicate filtering.
    selected = []
    deferred = []
    document_counts = {}

    for item in ranked:
        document_id = item["document_id"]

        duplicate = any(
            existing["document_id"] == document_id
            and _passages_overlap(
                existing["passage"],
                item["passage"],
            )
            for existing in selected
        )

        if duplicate:
            continue

        if document_counts.get(document_id, 0) >= 2:
            deferred.append(item)
            continue

        selected.append(item)
        document_counts[document_id] = (
            document_counts.get(document_id, 0) + 1
        )

        if len(selected) >= limit:
            return selected

    for item in deferred:
        duplicate = any(
            existing["document_id"] == item["document_id"]
            and _passages_overlap(
                existing["passage"],
                item["passage"],
            )
            for existing in selected
        )

        if not duplicate:
            selected.append(item)

        if len(selected) >= limit:
            break

    return selected


def delete_document_vectors(document_id: str):
    """Remove all indexed chunks belonging to a document."""
    _collection.delete(where={"document_id": document_id})


def get_indexed_chunk_count():
    """Return the total number of indexed chunks."""
    return _collection.count()
