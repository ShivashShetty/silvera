import unittest
from unittest.mock import patch

from services import semantic_search


class _FakeCollection:
    def __init__(self):
        self.added_batches = []

    def delete(self, **kwargs):
        pass

    def add(self, **kwargs):
        self.added_batches.append(kwargs)


class _FakeModel:
    def __init__(self):
        self.batch_sizes = []

    def encode(self, texts, normalize_embeddings):
        self.batch_sizes.append(len(texts))
        return _FakeEmbeddings([[0.0, 1.0] for _ in texts])


class _FakeEmbeddings(list):
    def tolist(self):
        return list(self)


class SemanticIndexingTests(unittest.TestCase):
    def test_large_document_chunks_are_embedded_in_bounded_batches(self):
        collection = _FakeCollection()
        model = _FakeModel()
        progress = []
        with (
            patch.object(semantic_search, "_collection", collection),
            patch.object(semantic_search, "get_model", return_value=model),
            patch.object(semantic_search, "INDEX_BATCH_SIZE", 2),
        ):
            indexed = semantic_search.index_document_pages(
                "document-id",
                "large.csv",
                ["x" * 3200],
                progress_callback=lambda completed, total: progress.append(
                    (completed, total)
                ),
            )

        self.assertEqual(indexed, 6)
        self.assertEqual(model.batch_sizes, [2, 2, 2])
        self.assertEqual(progress, [(0, 3), (1, 3), (2, 3), (3, 3)])
        self.assertEqual(
            [chunk_id for batch in collection.added_batches for chunk_id in batch["ids"]],
            [f"document-id_{index}" for index in range(indexed)],
        )
        self.assertTrue(
            all(
                metadata["page_number"] == 1
                for batch in collection.added_batches
                for metadata in batch["metadatas"]
            )
        )


if __name__ == "__main__":
    unittest.main()
