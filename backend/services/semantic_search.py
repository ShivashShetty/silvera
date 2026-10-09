
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer


# Store the vector database inside the backend folder.
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"

# Lightweight multilingual-capable embedding model.
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
_collection = _client.get_or_create_collection(
    name="silvera_documents",
    metadata={"hnsw:space": "cosine"},
)

_model = None


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
    """Create embeddings and store the document's text chunks."""
    chunks = split_into_chunks(text)

    if not chunks:
        return 0

    model = get_model()
    embeddings = model.encode(chunks, normalize_embeddings=True).tolist()

    ids = [
        f"{document_id}_{index}"
        for index in range(len(chunks))
    ]

    metadatas = [
        {
            "document_id": document_id,
            "filename": filename,
            "chunk_index": index,
        }
        for index in range(len(chunks))
    ]

    # Make indexing the same document again replace its old chunks.
    _collection.delete(where={"document_id": document_id})

    _collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)


def search_similar_documents(query: str, limit: int = 5):
    """Retrieve the most relevant document chunks for a query."""
    query = query.strip()

    if not query:
        return []

    if _collection.count() == 0:
        return []

    model = get_model()
    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
    ).tolist()

    results = _collection.query(
        query_embeddings=query_embedding,
        n_results=min(limit, _collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    matches = []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for passage, metadata, distance in zip(
        documents, metadatas, distances
    ):
        matches.append(
            {
                "document_id": metadata["document_id"],
                "filename": metadata["filename"],
                "passage": passage,
                "similarity": round(1 - distance, 4),
                "chunk_index": metadata["chunk_index"],
            }
        )

    return matches


def delete_document_vectors(document_id: str):
    """Remove all indexed chunks belonging to a document."""
    _collection.delete(where={"document_id": document_id})


def get_indexed_chunk_count():
    """Return the total number of indexed chunks."""
    return _collection.count()
