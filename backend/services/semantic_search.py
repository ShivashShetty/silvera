from pathlib import Path
import re

import chromadb
from sentence_transformers import SentenceTransformer


# Keep the existing database location and collection to preserve indexed data.
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
_collection = _client.get_or_create_collection(
    name="silvera_documents",
    metadata={"hnsw:space": "cosine"},
)
_model = None

# Common words contribute little to keyword matching. Keep this deliberately
# small so technical terms, IDs, dates, and names are not discarded.
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


def split_into_chunks(text: str, chunk_size: int = 700, overlap: int = 100):
    """Split extracted document text into overlapping chunks."""
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


def index_document(document_id: str, filename: str, text: str):
    """Create embeddings and store a document's text chunks."""
    chunks = split_into_chunks(text)
    # Delete old chunks even if the replacement document is now empty.
    _collection.delete(where={"document_id": document_id})
    if not chunks:
        return 0

    embeddings = get_model().encode(chunks, normalize_embeddings=True).tolist()
    ids = [f"{document_id}_{index}" for index in range(len(chunks))]
    metadatas = [
        {
            "document_id": document_id,
            "filename": filename,
            "chunk_index": index,
        }
        for index in range(len(chunks))
    ]
    _collection.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
    return len(chunks)


def _query_terms(query: str) -> list[str]:
    """Extract useful terms while retaining IDs, numbers, and technical tokens."""
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._/#-]*", query.lower())
    return list(dict.fromkeys(token for token in tokens if token not in _STOP_WORDS and len(token) > 1))


def search_similar_documents(query: str, limit: int = 5):
    """Hybrid retrieval: merge vector similarity with keyword coverage.

    The returned keys preserve the API contract used by main.py and the UI.
    `similarity` remains the cosine similarity; extra scoring fields are additive.
    """
    query = query.strip()
    if not query or limit <= 0:
        return []

    total = _collection.count()
    if total == 0:
        return []

    terms = _query_terms(query)
    candidates: dict[str, dict] = {}

    # Semantic retrieval retrieves more than the final limit so the keyword
    # ranking can reorder results and recover exact-term matches.
    model = get_model()
    query_embedding = model.encode([query], normalize_embeddings=True).tolist()
    semantic_results = _collection.query(
        query_embeddings=query_embedding,
        n_results=min(max(limit * 4, 20), total),
        include=["documents", "metadatas", "distances"],
    )
    semantic_docs = semantic_results.get("documents", [[]])[0]
    semantic_metas = semantic_results.get("metadatas", [[]])[0]
    semantic_distances = semantic_results.get("distances", [[]])[0]
    semantic_ids = semantic_results.get("ids", [[]])[0]

    for chunk_id, passage, metadata, distance in zip(
        semantic_ids, semantic_docs, semantic_metas, semantic_distances
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
            "lexical_score": 0.0,
        }

    # Scan indexed text chunks for exact terms that embeddings can overlook.
    # Chroma returns all stored chunks here; this is simple and dependable for
    # Silvera's current local-document scale, without adding another service.
    all_chunks = _collection.get(include=["documents", "metadatas"])
    all_ids = all_chunks.get("ids", [])
    all_docs = all_chunks.get("documents", [])
    all_metas = all_chunks.get("metadatas", [])

    for chunk_id, passage, metadata in zip(all_ids, all_docs, all_metas):
        if not passage or not metadata:
            continue
        passage_lower = passage.lower()
        matched_terms = sum(1 for term in terms if term in passage_lower)
        lexical_score = matched_terms / len(terms) if terms else 0.0

        if chunk_id not in candidates and lexical_score > 0:
            candidates[chunk_id] = {
                "document_id": metadata.get("document_id", ""),
                "filename": metadata.get("filename", "Unknown document"),
                "passage": passage,
                "similarity": 0.0,
                "chunk_index": metadata.get("chunk_index", 0),
                "lexical_score": 0.0,
            }
        if chunk_id in candidates:
            candidates[chunk_id]["lexical_score"] = round(lexical_score, 4)

    ranked = []
    for item in candidates.values():
        # Semantic meaning gets the larger weight, while exact term overlap can
        # meaningfully boost or recover matches. Lexical-only hits remain useful.
        item["relevance_score"] = round(
            0.65 * item["similarity"] + 0.35 * item["lexical_score"], 4
        )
        ranked.append(item)

    ranked.sort(key=lambda item: item["relevance_score"], reverse=True)
    return ranked[:limit]


def delete_document_vectors(document_id: str):
    """Remove all indexed chunks belonging to a document."""
    _collection.delete(where={"document_id": document_id})


def get_indexed_chunk_count():
    """Return the total number of indexed chunks."""
    return _collection.count()
