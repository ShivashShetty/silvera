import { API_BASE_URL, apiFetch } from "./api";

export class ApiError extends Error {
  sql?: string;
}

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail?.message === "string"
          ? detail.message
          : fallback;
    const error = new ApiError(message);
    if (typeof detail?.sql === "string") error.sql = detail.sql;
    throw error;
  }
  return body as T;
}

export interface SecurityUser {
  id: string;
  name: string;
  username: string;
  role: "ADMIN" | "MANAGER" | "EMPLOYEE" | "VIEWER";
  active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface SecurityDocument {
  id: string;
  owner_id: string;
  visibility: "private" | "shared" | "organization";
  classification: "public" | "internal" | "confidential" | "restricted";
  uploaded_at: string | null;
  archived_at: string | null;
  filename: string;
  grants: Array<{
    principal_type: "user" | "role";
    principal_id: string;
    permissions: string[];
  }>;
}

export interface SecurityDataset {
  id: string;
  table_name: string;
  filename: string;
  sheet_name: string;
  row_count: number | null;
  columns: string[];
  classification: string;
  visibility: string;
}

export interface AuditEvent {
  id: string;
  timestamp: string;
  actor_id: string | null;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  result: string;
  metadata_json: string;
  request_id: string | null;
}

export interface RetentionPreview {
  retention_days: number | null;
  affected_documents: Array<{
    document_id: string;
    classification: string;
    uploaded_at: string;
    expires_at: string;
    reason: string;
  }>;
  count: number;
}

export async function getSecurityOverview() {
  return readJson<{
    total_users: number;
    active_users: number;
    protected_documents: number;
    restricted_datasets: number;
    recent_events: AuditEvent[];
    setup_complete: boolean;
    session_ttl_hours: number;
    cookie_secure: boolean;
    csrf_protection: boolean;
    login_lockout_threshold: number;
    legacy_import_complete: boolean;
  }>(
    await apiFetch(`${API_BASE_URL}/api/security/overview`),
    "Could not load the security overview."
  );
}

export async function getSecurityUsers(search = "") {
  const params = new URLSearchParams({ search });
  return readJson<{ users: SecurityUser[] }>(
    await apiFetch(`${API_BASE_URL}/api/security/users?${params}`),
    "Could not load users."
  );
}

export async function createSecurityUser(
  name: string,
  username: string,
  password: string,
  role: SecurityUser["role"]
) {
  return readJson<{ user: SecurityUser }>(
    await apiFetch(`${API_BASE_URL}/api/security/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, username, password, role }),
    }),
    "Could not create user."
  );
}

export async function updateSecurityUser(
  id: string,
  patch: Partial<Pick<SecurityUser, "name" | "role" | "active">>
) {
  return readJson<{ user: SecurityUser }>(
    await apiFetch(`${API_BASE_URL}/api/security/users/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
    "Could not update user."
  );
}

export async function resetSecurityPassword(id: string, password: string) {
  return readJson<{ message: string }>(
    await apiFetch(`${API_BASE_URL}/api/security/users/${encodeURIComponent(id)}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }),
    "Could not reset the password."
  );
}

export async function getSecurityDocuments() {
  return readJson<{ documents: SecurityDocument[] }>(
    await apiFetch(`${API_BASE_URL}/api/security/documents`),
    "Could not load document access settings."
  );
}

export async function updateDocumentPolicy(
  id: string,
  patch: { visibility?: SecurityDocument["visibility"]; classification?: SecurityDocument["classification"] }
) {
  return readJson<SecurityDocument>(
    await apiFetch(`${API_BASE_URL}/api/security/documents/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
    "Could not update document policy."
  );
}

export async function updateDocumentGrant(
  id: string,
  grant: { principal_type: "user" | "role"; principal_id: string; permissions: string[] }
) {
  return readJson<{ message: string }>(
    await apiFetch(`${API_BASE_URL}/api/security/documents/${encodeURIComponent(id)}/grants`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(grant),
    }),
    "Could not update document access."
  );
}

export async function getDatasets() {
  return readJson<{ datasets: SecurityDataset[] }>(
    await apiFetch(`${API_BASE_URL}/api/datasets`),
    "Could not load permitted datasets."
  );
}

export async function updateDatasetPolicy(
  id: string,
  patch: { visibility?: string; classification?: string }
) {
  return readJson<Record<string, unknown>>(
    await apiFetch(`${API_BASE_URL}/api/security/datasets/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
    "Could not update dataset policy."
  );
}

export async function updateDatasetGrant(
  id: string,
  grant: { principal_type: "user" | "role"; principal_id: string; permissions: string[]; columns: string[] }
) {
  return readJson<{ message: string }>(
    await apiFetch(`${API_BASE_URL}/api/security/datasets/${encodeURIComponent(id)}/grants`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(grant),
    }),
    "Could not update dataset access."
  );
}

export async function getAuditEvents(filters: {
  search?: string;
  event_type?: string;
  actor_id?: string;
  resource_type?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return readJson<{ events: AuditEvent[]; total: number; page: number; page_size: number }>(
    await apiFetch(`${API_BASE_URL}/api/security/audit?${params}`),
    "Could not load the audit log."
  );
}

export async function getGovernance() {
  return readJson<{
    classification_levels: string[];
    retention_days: number | null;
    expiring_documents: RetentionPreview["affected_documents"];
  }>(
    await apiFetch(`${API_BASE_URL}/api/security/governance`),
    "Could not load governance settings."
  );
}

export async function setRetentionDays(retention_days: number | null) {
  return readJson<RetentionPreview>(
    await apiFetch(`${API_BASE_URL}/api/security/governance/retention`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ retention_days }),
    }),
    "Could not update the retention policy."
  );
}

export async function previewRetention() {
  return readJson<RetentionPreview>(
    await apiFetch(`${API_BASE_URL}/api/security/governance/retention/preview`, {
      method: "POST",
    }),
    "Could not preview retention."
  );
}

export async function executeRetention(
  document_ids: string[],
  action: "archive" | "delete",
  confirmed: boolean
) {
  return readJson<{ action: string; affected: number }>(
    await apiFetch(`${API_BASE_URL}/api/security/governance/retention/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids, action, confirmed }),
    }),
    "Could not execute retention."
  );
}

export interface DataQueryResult {
  sql: string;
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  sources: string[];
}

export interface DatasetPreview {
  dataset_id: string;
  filename: string;
  columns: string[];
  rows: unknown[][];
  offset: number;
  limit: number;
  row_count: number | null;
  has_more: boolean;
}

export async function getDatasetPreview(
  datasetId: string,
  offset: number,
  limit = 50
) {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  return readJson<DatasetPreview>(
    await apiFetch(
      `${API_BASE_URL}/api/datasets/${encodeURIComponent(datasetId)}/preview?${params}`
    ),
    "Could not preview this dataset."
  );
}

export async function askDataset(
  question: string,
  dataset_id: string,
  sql?: string
) {
  return readJson<DataQueryResult>(
    await apiFetch(`${API_BASE_URL}/api/data/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, dataset_id, ...(sql ? { sql } : {}) }),
    }),
    "Could not query this dataset."
  );
}
