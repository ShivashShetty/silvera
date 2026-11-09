
const apiHost =
  typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "localhost"
    : "127.0.0.1";
export const API_BASE_URL = `http://${apiHost}:8000`;
let csrfToken = "";

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(url, { ...init, headers, credentials: "include" });
  if (
    response.status === 401 &&
    !url.includes("/api/auth/login") &&
    typeof window !== "undefined"
  ) {
    window.dispatchEvent(new Event("silvera:unauthorized"));
  }
  return response;
}

export interface AuthUser {
  id: string;
  name: string;
  username: string;
  role: "ADMIN" | "MANAGER" | "EMPLOYEE" | "VIEWER";
  active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthState {
  user: AuthUser;
  csrf_token: string;
  expires_at?: string;
}

export interface SetupStatus {
  setup_required: boolean;
  session_ttl_hours: number;
  cookie_secure: boolean;
}

export async function getAuthSetupStatus(): Promise<SetupStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/setup-status`);
  if (!response.ok) throw await readApiError(response, "Could not check setup status.");
  return response.json() as Promise<SetupStatus>;
}

export async function createInitialAdmin(
  name: string,
  username: string,
  password: string
): Promise<AuthState> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, username, password }),
  });
  if (!response.ok) throw await readApiError(response, "Could not create the administrator.");
  const state = (await response.json()) as AuthState;
  setCsrfToken(state.csrf_token);
  return state;
}

export async function login(
  username: string,
  password: string
): Promise<AuthState> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw await readApiError(response, "Could not sign in.");
  const state = (await response.json()) as AuthState;
  setCsrfToken(state.csrf_token);
  return state;
}

export async function getCurrentUser(): Promise<AuthState> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/me`);
  if (!response.ok) throw await readApiError(response, "Your session has expired.");
  const state = (await response.json()) as AuthState;
  setCsrfToken(state.csrf_token);
  return state;
}

export async function logout(): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/logout`, { method: "POST" });
  if (!response.ok) throw await readApiError(response, "Could not sign out.");
  setCsrfToken("");
}

export async function changePassword(
  current_password: string,
  new_password: string
): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/auth/change-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password, new_password }),
  });
  if (!response.ok) throw await readApiError(response, "Could not change your password.");
}

export interface SilveraStatus {
  name: string;
  status: string;
  message: string;
  max_upload_mb: number;
}

export async function getSilveraStatus(): Promise<SilveraStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/status`);

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
  index_status: "processing" | "ready" | "failed";
  index_progress: number;
  message: string;
}

export async function uploadDocument(
  file: File
): Promise<DocumentUploadResult> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await apiFetch(`${API_BASE_URL}/api/documents/upload`, {
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

export async function uploadDocuments(
  files: File[]
): Promise<DocumentUploadResult[]> {
  if (files.length === 0) {
    return [];
  }

  const results: DocumentUploadResult[] = [];
  for (const file of files) {
    results.push(await uploadDocument(file));
  }
  return results;
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

  const response = await apiFetch(
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
  index_status: "processing" | "ready" | "failed";
  index_progress: number;
  index_error: string | null;
}

export interface DocumentPage {
  document_id: string;
  filename: string;
  page_number: number;
  total_pages: number;
  text: string;
}

export async function getDocumentPage(
  documentId: string,
  pageNumber: number
): Promise<DocumentPage> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/pages/${pageNumber}`
  );
  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Could not load document text."
    );
  }
  return result as DocumentPage;
}

export async function getDocuments(): Promise<StoredDocument[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/documents`);

  if (!response.ok) {
    throw new Error("Could not load documents.");
  }

  const data: { documents: StoredDocument[] } = await response.json();

  return data.documents;
}

export async function deleteDocument(
  documentId: string
): Promise<void> {
  const response = await apiFetch(
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

  const response = await apiFetch(
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
  structured_query?: StructuredQueryResult | null;
}

export interface StructuredQueryResult {
  sql: string;
  columns: string[];
  rows: Array<Array<string | number | null>>;
  truncated: boolean;
  sources: string[];
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
  const response = await apiFetch(`${API_BASE_URL}/api/conversations`);
  if (!response.ok) {
    throw await readApiError(response, "Could not load conversation history.");
  }
  const data: { conversations: ConversationSummary[] } = await response.json();
  return data.conversations;
}

export async function getConversation(
  conversationId: string
): Promise<ConversationDetail> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`
  );
  if (!response.ok) {
    throw await readApiError(response, "Could not open this conversation.");
  }
  return response.json() as Promise<ConversationDetail>;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw await readApiError(response, "Could not delete this conversation.");
  }
}

export async function askSilvera(
  question: string,
  conversationId?: string | null,
  dataMode = false,
  sql?: string
): Promise<AskResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      question,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(dataMode ? { data_mode: true } : {}),
      ...(sql !== undefined ? { sql } : {}),
    }),
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
  return `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/original`;
}

export function getDocumentDownloadUrl(documentId: string): string {
  return `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/download`;
}