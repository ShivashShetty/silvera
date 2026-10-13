
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

export interface SemanticSearchResult {
  document_id: string;
  filename: string;
  passage: string;
  similarity: number;
  chunk_index: number;
}

export interface SemanticSearchResponse {
  query: string;
  results: SemanticSearchResult[];
  total_results: number;
}

export async function semanticSearchDocuments(
  query: string,
  limit: number = 5
): Promise<SemanticSearchResponse> {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });

  const response = await fetch(
    `${API_BASE_URL}/api/documents/semantic-search?${params.toString()}`
  );

  const result = await response.json();

  if (!response.ok) {
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Semantic search failed."
    );
  }

  return result as SemanticSearchResponse;
}


export interface AskSource {
  document_id: string;
  filename: string;
  passage: string;
  similarity: number | null;
  chunk_index: number | null;
}

export interface AskResponse {
  conversation_id: string;
  title: string;
  question: string;
  answer: string;
  sources: AskSource[];
  total_sources: number;
  model: string;
  local: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: AskSource[];
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
}

async function readApiError(response: Response, fallback: string): Promise<Error> {
  const result = await response.json().catch(() => ({}));
  return new Error(
    typeof result.detail === "string" ? result.detail : fallback
  );
}

export async function getConversations(): Promise<ConversationSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/conversations`);
  if (!response.ok) {
    throw await readApiError(response, "Could not load conversation history.");
  }
  const data: { conversations: ConversationSummary[] } = await response.json();
  return data.conversations;
}

export async function getConversation(
  conversationId: string
): Promise<ConversationDetail> {
  const response = await fetch(
    `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`
  );
  if (!response.ok) {
    throw await readApiError(response, "Could not open this conversation.");
  }
  return response.json() as Promise<ConversationDetail>;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw await readApiError(response, "Could not delete this conversation.");
  }
}

export async function askSilvera(
  question: string,
  conversationId?: string | null
): Promise<AskResponse> {
  const response = await fetch(`${API_BASE_URL}/api/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question, ...(conversationId ? { conversation_id: conversationId } : {}) }),
  });

  const result = await response.json();

  if (!response.ok) {
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Silvera could not generate an answer."
    );
  }

  return result as AskResponse;
}
export function getOriginalDocumentUrl(documentId: string): string {
  return `http://127.0.0.1:8000/api/documents/${encodeURIComponent(documentId)}/original`;
}