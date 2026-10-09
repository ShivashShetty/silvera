
const API_BASE_URL = "http://127.0.0.1:8000";

export interface SilveraStatus {
  name: string;
  status: string;
  message: string;
}

export async function getSilveraStatus(): Promise<SilveraStatus> {
  const response = await fetch(`${API_BASE_URL}/api/status`);

  if (!response.ok) {
    throw new Error("Could not connect to Silvera's backend.");
  }

  return response.json();
}

export interface DocumentUploadResult {
  document_id: string;
  filename: string;
  pages: number;
  characters_extracted: number;
  preview: string;
  message: string;
}

export async function uploadDocument(
  file: File
): Promise<DocumentUploadResult> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/documents/upload`, {
    method: "POST",
    body: formData,
  });

  const result = await response.json();

  if (!response.ok) {
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Could not upload the document."
    );
  }

  return result as DocumentUploadResult;
}

export interface DocumentSearchResult {
  document_id: string;
  filename: string;
  passage: string;
}

export interface DocumentSearchResponse {
  query: string;
  results: DocumentSearchResult[];
  total_results: number;
}

export async function searchDocuments(
  query: string
): Promise<DocumentSearchResponse> {
  const params = new URLSearchParams({ q: query });

  const response = await fetch(
    `${API_BASE_URL}/api/documents/search?${params.toString()}`
  );

  const result = await response.json();

  if (!response.ok) {
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Could not search documents."
    );
  }

  return result as DocumentSearchResponse;
}

export interface StoredDocument {
  document_id: string;
  filename: string;
  pages: number | null;
  characters_extracted: number;
  uploaded_at: string | null;
}

export async function getDocuments(): Promise<StoredDocument[]> {
  const response = await fetch(`${API_BASE_URL}/api/documents`);

  if (!response.ok) {
    throw new Error("Could not load documents.");
  }

  const data: { documents: StoredDocument[] } = await response.json();

  return data.documents;
}

export async function deleteDocument(
  documentId: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" }
  );

  if (!response.ok) {
    const result = await response.json().catch(() => ({}));

    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Could not delete document."
    );
  }
}
