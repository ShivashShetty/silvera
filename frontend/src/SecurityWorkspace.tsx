import { useEffect, useMemo, useState } from "react";
import type { AuthUser } from "./services/api";
import {
  askDataset,
  createSecurityUser,
  executeRetention,
  getAuditEvents,
  getDatasets,
  getGovernance,
  getSecurityDocuments,
  getSecurityOverview,
  getSecurityUsers,
  previewRetention,
  resetSecurityPassword,
  setRetentionDays,
  updateDatasetGrant,
  updateDatasetPolicy,
  updateDocumentGrant,
  updateDocumentPolicy,
  updateSecurityUser,
  type AuditEvent,
  type SecurityDataset,
  type SecurityDocument,
  type SecurityUser,
} from "./services/securityApi";

type Section =
  | "overview"
  | "users"
  | "documents"
  | "datasets"
  | "audit"
  | "governance";

const buttonStyle: React.CSSProperties = {
  border: "1px solid rgba(133, 153, 176, 0.3)",
  borderRadius: 7,
  padding: "8px 11px",
  background: "#18232f",
  color: "#e8eaf0",
  cursor: "pointer",
};
const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "9px 10px",
  color: "#e8eaf0",
  background: "#0b1118",
  border: "1px solid rgba(133, 153, 176, 0.26)",
  borderRadius: 7,
};
const cardStyle: React.CSSProperties = {
  padding: 18,
  border: "1px solid rgba(133, 153, 176, 0.18)",
  borderRadius: 10,
  background: "rgba(16, 23, 34, 0.82)",
};

function Table({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ overflowX: "auto", ...cardStyle }}>
      <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", color: "#dce5ef" }}>
        {children}
      </table>
    </div>
  );
}

function Cell({ children, header = false }: { children: React.ReactNode; header?: boolean }) {
  const Tag = header ? "th" : "td";
  return (
    <Tag style={{
      padding: "10px 9px",
      borderBottom: "1px solid rgba(133, 153, 176, 0.13)",
      color: header ? "#91a6ad" : "#dce5ef",
      fontSize: header ? "0.78rem" : "0.86rem",
      whiteSpace: "nowrap",
      fontWeight: header ? 600 : 400,
    }}>
      {children}
    </Tag>
  );
}

export default function SecurityWorkspace({
  user,
}: {
  user: AuthUser;
}) {
  const admin = user.role === "ADMIN";
  const sections: Array<[Section, string]> = admin
    ? [
        ["overview", "Overview"],
        ["users", "Users & roles"],
        ["documents", "Document access"],
        ["datasets", "Dataset access"],
        ["audit", "Audit logs"],
        ["governance", "Data governance"],
      ]
    : [["documents", "Document access"], ["audit", "My activity"]];
  const [section, setSection] = useState<Section>(sections[0][0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof getSecurityOverview>> | null>(null);
  const [users, setUsers] = useState<SecurityUser[]>([]);
  const [documents, setDocuments] = useState<SecurityDocument[]>([]);
  const [datasets, setDatasets] = useState<SecurityDataset[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [governance, setGovernance] = useState<Awaited<ReturnType<typeof getGovernance>> | null>(null);
  const [userSearch, setUserSearch] = useState("");
  const [auditSearch, setAuditSearch] = useState("");
  const [auditEventType, setAuditEventType] = useState("");
  const [auditActor, setAuditActor] = useState("");
  const [auditResource, setAuditResource] = useState("");
  const [auditStart, setAuditStart] = useState("");
  const [auditEnd, setAuditEnd] = useState("");
  const [auditPage, setAuditPage] = useState(1);
  const [newName, setNewName] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<SecurityUser["role"]>("EMPLOYEE");
  const [retentionDaysInput, setRetentionDaysInput] = useState("");
  const [grantResource, setGrantResource] = useState("");
  const [grantPrincipalType, setGrantPrincipalType] = useState<"user" | "role">("user");
  const [grantPrincipalId, setGrantPrincipalId] = useState("");
  const [grantPermissions, setGrantPermissions] = useState("view,query,download");
  const [datasetGrantPermissions, setDatasetGrantPermissions] = useState("query");
  const [grantColumns, setGrantColumns] = useState("");
  const [queryDatasetId, setQueryDatasetId] = useState("");
  const [queryQuestion, setQueryQuestion] = useState("");
  const [querySql, setQuerySql] = useState("");
  const [queryResult, setQueryResult] = useState<Awaited<ReturnType<typeof askDataset>> | null>(null);

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === queryDatasetId) ?? null,
    [datasets, queryDatasetId]
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setSuccess("");
    const load = async () => {
      try {
        if (section === "overview" && admin) {
          const result = await getSecurityOverview();
          if (active) setOverview(result);
        } else if (section === "users" && admin) {
          const result = await getSecurityUsers(userSearch);
          if (active) setUsers(result.users);
        } else if (section === "documents") {
          const [result, userResult] = await Promise.all([
            getSecurityDocuments(),
            admin ? getSecurityUsers() : Promise.resolve({ users: [] as SecurityUser[] }),
          ]);
          if (active) {
            setDocuments(result.documents);
            setUsers(userResult.users);
          }
        } else if (section === "datasets" && admin) {
          const [result, userResult] = await Promise.all([
            getDatasets(),
            getSecurityUsers(),
          ]);
          if (active) {
            setDatasets(result.datasets);
            setUsers(userResult.users);
            if (!queryDatasetId && result.datasets[0]) {
              setQueryDatasetId(result.datasets[0].id);
            }
          }
        } else if (section === "audit" && (admin || user.role === "MANAGER")) {
          const result = await getAuditEvents({
            search: auditSearch,
            event_type: auditEventType,
            actor_id: auditActor,
            resource_type: auditResource,
            start_date: auditStart,
            end_date: auditEnd,
            page: auditPage,
          });
          if (active) {
            setEvents(result.events);
            setAuditTotal(result.total);
          }
        } else if (section === "governance" && admin) {
          const result = await getGovernance();
          if (active) {
            setGovernance(result);
            setRetentionDaysInput(result.retention_days == null ? "" : String(result.retention_days));
          }
        }
      } catch (loadError) {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load this section.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [section, admin, userSearch, auditSearch, auditEventType, auditActor, auditResource, auditStart, auditEnd, auditPage, queryDatasetId]);

  async function runAction(action: () => Promise<void>) {
    setError("");
    setSuccess("");
    try {
      await action();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Action failed.");
    }
  }

  async function submitUser(event: React.FormEvent) {
    event.preventDefault();
    await runAction(async () => {
      await createSecurityUser(newName, newUsername, newPassword, newRole);
      setNewName("");
      setNewUsername("");
      setNewPassword("");
      setSuccess("User created.");
      setUsers((await getSecurityUsers(userSearch)).users);
    });
  }

  async function submitGrant(event: React.FormEvent) {
    event.preventDefault();
    const permissions = grantPermissions.split(",").map((item) => item.trim()).filter(Boolean);
    await runAction(async () => {
      if (section === "documents") {
        await updateDocumentGrant(grantResource, {
          principal_type: grantPrincipalType,
          principal_id: grantPrincipalId,
          permissions,
        });
        setDocuments((await getSecurityDocuments()).documents);
      } else {
        const dataset = datasets.find((item) => item.id === grantResource);
        if (!dataset) throw new Error("Select a dataset first.");
        await updateDatasetGrant(grantResource, {
          principal_type: grantPrincipalType,
          principal_id: grantPrincipalId,
          permissions: datasetGrantPermissions.split(",").map((item) => item.trim()).filter(Boolean),
          columns: grantColumns.trim()
            ? grantColumns.split(",").map((item) => item.trim()).filter(Boolean)
            : [],
        });
      }
      setSuccess("Access grant saved.");
    });
  }

  async function runDataQuery(sql?: string) {
    if (!selectedDataset) {
      setError("Choose an accessible dataset.");
      return;
    }
    await runAction(async () => {
      const result = await askDataset(queryQuestion, selectedDataset.id, sql);
      setQueryResult(result);
      setQuerySql(result.sql);
      setSuccess("Query completed.");
    });
  }

  async function saveRetention() {
    await runAction(async () => {
      const days = retentionDaysInput.trim() ? Number(retentionDaysInput) : null;
      if (days !== null && (!Number.isInteger(days) || days < 1)) {
        throw new Error("Enter a whole number of retention days, or leave blank for no expiry.");
      }
      const result = await setRetentionDays(days);
      setGovernance((current) => current ? {
        ...current,
        retention_days: result.retention_days,
        expiring_documents: result.affected_documents,
      } : current);
      setSuccess("Retention policy saved. Existing documents were not automatically deleted.");
    });
  }

  async function runRetention(action: "archive" | "delete") {
    if (!governance?.expiring_documents.length) return;
    const ids = governance.expiring_documents.map((item) => item.document_id);
    const accepted = window.confirm(
      `${action === "delete" ? "Permanently delete" : "Archive"} ${ids.length} expired document(s)? This action will be recorded.`
    );
    if (!accepted) return;
    await runAction(async () => {
      await executeRetention(ids, action, true);
      setGovernance(await getGovernance());
      setSuccess(`${ids.length} document(s) ${action === "delete" ? "deleted" : "archived"}.`);
    });
  }

  async function updateUser(userId: string, patch: Partial<Pick<SecurityUser, "role" | "active">>) {
    await runAction(async () => {
      const result = await updateSecurityUser(userId, patch);
      setUsers((current) => current.map((item) => item.id === userId ? result.user : item));
      setSuccess("User updated.");
    });
  }

  async function handleResetPassword(userId: string) {
    const password = window.prompt("Enter a new password (at least 12 characters).");
    if (password === null) return;
    await runAction(async () => {
      await resetSecurityPassword(userId, password);
      setSuccess("Password reset; existing sessions were revoked.");
    });
  }

  async function handleEditName(item: SecurityUser) {
    const name = window.prompt("Update the user's display name.", item.name);
    if (name === null || !name.trim()) return;
    await runAction(async () => {
      const result = await updateSecurityUser(item.id, { name: name.trim() });
      setUsers((current) => current.map((userItem) => userItem.id === item.id ? result.user : userItem));
      setSuccess("User profile updated.");
    });
  }

  async function saveDocumentPolicy(document: SecurityDocument, key: "classification" | "visibility", value: string) {
    await runAction(async () => {
      const updated = await updateDocumentPolicy(document.id, { [key]: value });
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, ...updated } : item));
      setSuccess("Document policy saved.");
    });
  }

  async function saveDatasetPolicy(dataset: SecurityDataset, key: "classification" | "visibility", value: string) {
    await runAction(async () => {
      await updateDatasetPolicy(dataset.id, { [key]: value });
      setDatasets((current) => current.map((item) => item.id === dataset.id ? { ...item, [key]: value } : item));
      setSuccess("Dataset policy saved.");
    });
  }

  return (
    <section className="security-page">
      <div className="section-heading">
        <span>SECURITY &amp; GOVERNANCE</span>
        <span>{user.role}</span>
      </div>
      <h1>Security workspace</h1>
      <p className="description">
        Manage identity, resource access, audit history and retention policies.
      </p>
      <div className="security-tabs" role="tablist" aria-label="Security workspace sections">
        {sections.map(([key, label]) => (
          <button
            type="button"
            role="tab"
            aria-selected={section === key}
            className={section === key ? "active" : ""}
            key={key}
            onClick={() => setSection(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {error && <p className="security-message error" role="alert">{error}</p>}
      {success && <p className="security-message success" role="status">{success}</p>}
      {loading && <p role="status">Loading security data...</p>}

      {!loading && section === "overview" && overview && (
        <div className="security-content">
          <div className="security-metrics">
            {[
              ["Total users", overview.total_users],
              ["Active users", overview.active_users],
              ["Protected documents", overview.protected_documents],
              ["Restricted datasets", overview.restricted_datasets],
            ].map(([label, value]) => (
              <article style={cardStyle} key={label}>
                <span className="security-muted">{label}</span>
                <strong className="security-metric">{value}</strong>
              </article>
            ))}
          </div>
          <p className="security-muted">
            Security configuration: {overview.csrf_protection ? "CSRF protection enabled" : "CSRF protection disabled"} · secure cookies {overview.cookie_secure ? "enabled" : "disabled for local HTTP"} · lockout after {overview.login_lockout_threshold} failed attempts · sessions expire after {overview.session_ttl_hours} hours.
            {" "}Legacy resources imported privately for the administrator: {overview.legacy_import_complete ? "yes" : "no"}.
          </p>
          <h2>Recent security events</h2>
          <Table>
            <thead><tr><Cell header>Time</Cell><Cell header>Event</Cell><Cell header>Actor</Cell><Cell header>Result</Cell></tr></thead>
            <tbody>{overview.recent_events.map((event) => (
              <tr key={event.id}>
                <Cell>{new Date(event.timestamp).toLocaleString()}</Cell>
                <Cell>{event.event_type}</Cell>
                <Cell>{event.actor_id ?? "System/unknown"}</Cell>
                <Cell>{event.result}</Cell>
              </tr>
            ))}</tbody>
          </Table>
        </div>
      )}

      {!loading && section === "users" && admin && (
        <div className="security-content">
          <form className="security-form" onSubmit={(event) => void submitUser(event)}>
            <h2>Create a user</h2>
            <div className="security-form-grid">
              <input aria-label="Name" placeholder="Full name" value={newName} onChange={(event) => setNewName(event.target.value)} style={inputStyle} required />
              <input aria-label="Email username" type="email" placeholder="Email / username" value={newUsername} onChange={(event) => setNewUsername(event.target.value)} style={inputStyle} required />
              <input aria-label="Initial password" type="password" minLength={12} placeholder="Temporary password (12+ characters)" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} style={inputStyle} required />
              <select aria-label="Role" value={newRole} onChange={(event) => setNewRole(event.target.value as SecurityUser["role"])} style={inputStyle}>
                {["MANAGER", "EMPLOYEE", "VIEWER", "ADMIN"].map((role) => <option key={role}>{role}</option>)}
              </select>
            </div>
            <button type="submit" style={buttonStyle}>Create user</button>
          </form>
          <input aria-label="Search users" placeholder="Search name or email" value={userSearch} onChange={(event) => setUserSearch(event.target.value)} style={{ ...inputStyle, maxWidth: 420, margin: "16px 0" }} />
          {users.length === 0 ? <p className="security-muted">No users match this search.</p> : (
            <Table>
              <thead><tr><Cell header>Name</Cell><Cell header>Email</Cell><Cell header>Role</Cell><Cell header>Status</Cell><Cell header>Last login</Cell><Cell header>Actions</Cell></tr></thead>
              <tbody>{users.map((item) => (
                <tr key={item.id}>
                  <Cell>{item.name}</Cell>
                  <Cell>{item.username}</Cell>
                  <Cell>
                    <select aria-label={`Role for ${item.username}`} value={item.role} onChange={(event) => void updateUser(item.id, { role: event.target.value as SecurityUser["role"] })} style={inputStyle}>
                      {["ADMIN", "MANAGER", "EMPLOYEE", "VIEWER"].map((role) => <option key={role}>{role}</option>)}
                    </select>
                  </Cell>
                  <Cell>{item.active ? "Active" : "Disabled"}</Cell>
                  <Cell>{item.last_login_at ? new Date(item.last_login_at).toLocaleString() : "Never"}</Cell>
                  <Cell>
                    <div className="security-actions">
                      <button type="button" style={buttonStyle} onClick={() => void handleEditName(item)}>Edit name</button>
                      <button type="button" style={buttonStyle} onClick={() => void updateUser(item.id, { active: !item.active })}>{item.active ? "Disable" : "Reactivate"}</button>
                      <button type="button" style={buttonStyle} onClick={() => void handleResetPassword(item.id)}>Reset password</button>
                    </div>
                  </Cell>
                </tr>
              ))}</tbody>
            </Table>
          )}
        </div>
      )}

      {!loading && section === "documents" && (
        <div className="security-content">
          {documents.length === 0 ? <p className="security-muted">No documents are available for access management.</p> : (
            <div className="security-resource-list">
              {documents.map((document) => (
                <article style={cardStyle} key={document.id}>
                  <div className="security-resource-heading">
                    <div><h3>{document.filename}</h3><span className="security-muted">Owner {document.owner_id} · {document.id}</span></div>
                    <span>{document.archived_at ? "Archived" : "Protected"}</span>
                  </div>
                  <div className="security-policy-row">
                    <label>Classification
                      <select value={document.classification} onChange={(event) => void saveDocumentPolicy(document, "classification", event.target.value)} style={inputStyle}>
                        {["public", "internal", "confidential", "restricted"].map((value) => <option key={value}>{value}</option>)}
                      </select>
                    </label>
                    <label>Visibility
                      <select value={document.visibility} onChange={(event) => void saveDocumentPolicy(document, "visibility", event.target.value)} style={inputStyle}>
                        {["private", "shared", "organization"].map((value) => <option key={value}>{value}</option>)}
                      </select>
                    </label>
                  </div>
                  <p className="security-muted">
                    Grants: {document.grants.length ? document.grants.map((grant) => `${grant.principal_type}:${grant.principal_id} (${grant.permissions.join(", ")})`).join("; ") : "none"}
                  </p>
                  <div className="security-grant-form">
                    <select aria-label="Grant principal type" value={grantPrincipalType} onChange={(event) => setGrantPrincipalType(event.target.value as "user" | "role")} style={inputStyle}>
                      <option value="user">User ID</option><option value="role">Role</option>
                    </select>
                    {grantPrincipalType === "role" ? (
                      <select aria-label="Grant role" value={grantPrincipalId} onChange={(event) => setGrantPrincipalId(event.target.value)} style={inputStyle}>
                        <option value="">Select role</option>{["MANAGER", "EMPLOYEE", "VIEWER"].map((role) => <option key={role}>{role}</option>)}
                      </select>
                    ) : users.length ? (
                      <select aria-label="Grant user" value={grantPrincipalId} onChange={(event) => setGrantPrincipalId(event.target.value)} style={inputStyle}>
                        <option value="">Select user</option>{users.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.username})</option>)}
                      </select>
                    ) : (
                      <input aria-label="Grant user ID" value={grantPrincipalId} onChange={(event) => setGrantPrincipalId(event.target.value)} placeholder="User ID" style={inputStyle} />
                    )}
                    <input aria-label="Permissions" value={grantPermissions} onChange={(event) => setGrantPermissions(event.target.value)} placeholder="view,query,download,manage,delete" style={inputStyle} />
                    <button type="button" style={buttonStyle} onClick={() => {
                      setGrantResource(document.id);
                      void runAction(async () => {
                        await updateDocumentGrant(document.id, {
                          principal_type: grantPrincipalType,
                          principal_id: grantPrincipalId,
                          permissions: grantPermissions.split(",").map((item) => item.trim()).filter(Boolean),
                        });
                        setDocuments((await getSecurityDocuments()).documents);
                        setSuccess("Document access grant saved.");
                      });
                    }}>Save grant</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}

      {!loading && section === "datasets" && admin && (
        <div className="security-content">
          <h2>Dataset access</h2>
          {datasets.length === 0 ? <p className="security-muted">No spreadsheet datasets are registered. Existing structured data is preserved; datasets are imported during initial administrator setup.</p> : (
            <>
              <div className="security-resource-list">
                {datasets.map((dataset) => (
                  <article style={cardStyle} key={dataset.id}>
                    <div className="security-resource-heading"><div><h3>{dataset.filename}{dataset.sheet_name ? ` · ${dataset.sheet_name}` : ""}</h3><span className="security-muted">{dataset.table_name} · {dataset.row_count ?? "?"} rows</span></div></div>
                    <div className="security-policy-row">
                      <label>Classification
                        <select value={dataset.classification} onChange={(event) => void saveDatasetPolicy(dataset, "classification", event.target.value)} style={inputStyle}>{["public", "internal", "confidential", "restricted"].map((value) => <option key={value}>{value}</option>)}</select>
                      </label>
                      <label>Visibility
                        <select value={dataset.visibility} onChange={(event) => void saveDatasetPolicy(dataset, "visibility", event.target.value)} style={inputStyle}>{["private", "shared", "organization"].map((value) => <option key={value}>{value}</option>)}</select>
                      </label>
                    </div>
                    <p className="security-muted">Available columns: {dataset.columns.join(", ")}</p>
                  </article>
                ))}
              </div>
              <form className="security-form" onSubmit={(event) => void submitGrant(event)}>
                <h3>Grant dataset access</h3>
                <div className="security-form-grid">
                  <select aria-label="Dataset for grant" value={grantResource} onChange={(event) => setGrantResource(event.target.value)} style={inputStyle}>
                    <option value="">Select dataset</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.filename}{dataset.sheet_name ? ` · ${dataset.sheet_name}` : ""}</option>)}
                  </select>
                  <select aria-label="Dataset grant type" value={grantPrincipalType} onChange={(event) => setGrantPrincipalType(event.target.value as "user" | "role")} style={inputStyle}><option value="user">User ID</option><option value="role">Role</option></select>
                  {grantPrincipalType === "role" ? <select aria-label="Dataset grant role" value={grantPrincipalId} onChange={(event) => setGrantPrincipalId(event.target.value)} style={inputStyle}><option value="">Select role</option>{["MANAGER", "EMPLOYEE", "VIEWER"].map((role) => <option key={role}>{role}</option>)}</select> : <select aria-label="Dataset grant user" value={grantPrincipalId} onChange={(event) => setGrantPrincipalId(event.target.value)} style={inputStyle}><option value="">Select user</option>{users.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.username})</option>)}</select>}
                  <input aria-label="Approved columns" value={grantColumns} onChange={(event) => setGrantColumns(event.target.value)} placeholder="Approved columns (comma-separated; blank = none)" style={inputStyle} />
                  <input aria-label="Dataset permissions" value={datasetGrantPermissions} onChange={(event) => setDatasetGrantPermissions(event.target.value)} placeholder="query" style={inputStyle} />
                </div>
                <button type="submit" style={buttonStyle}>Save query grant</button>
              </form>
              <section className="security-form">
                <h3>Spreadsheet SQL</h3>
                <p className="security-muted">Only the schema granted to your account is sent to the local model. Queries execute read-only with table/column authorization, a five-second timeout and a 100-row cap.</p>
                <label>Dataset<select value={queryDatasetId} onChange={(event) => setQueryDatasetId(event.target.value)} style={inputStyle}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.filename}{dataset.sheet_name ? ` · ${dataset.sheet_name}` : ""}</option>)}</select></label>
                <label>Question<textarea value={queryQuestion} onChange={(event) => setQueryQuestion(event.target.value)} rows={2} style={inputStyle} /></label>
                <button type="button" style={buttonStyle} disabled={!queryQuestion.trim()} onClick={() => void runDataQuery()}>Generate &amp; run SQL</button>
                {(querySql || queryResult) && (
                  <>
                    <label>Editable SQL<textarea aria-label="Editable SQL query" value={querySql} onChange={(event) => setQuerySql(event.target.value)} rows={7} spellCheck={false} style={{ ...inputStyle, fontFamily: "Consolas, 'Courier New', monospace" }} /></label>
                    <button type="button" style={buttonStyle} disabled={!querySql.trim()} onClick={() => void runDataQuery(querySql)}>Run edited SQL</button>
                  </>
                )}
                {queryResult && (
                  <div style={{ overflowX: "auto", marginTop: 16 }}>
                    <Table>
                      <thead><tr>{queryResult.columns.map((column) => <Cell header key={column}>{column}</Cell>)}</tr></thead>
                      <tbody>{queryResult.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((value, index) => <Cell key={`${rowIndex}-${index}`}>{String(value ?? "")}</Cell>)}</tr>)}</tbody>
                    </Table>
                    <p className="security-muted">{queryResult.rows.length} rows {queryResult.truncated ? "(capped at 100)" : ""} · {queryResult.sources.join(", ")}</p>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}

      {!loading && section === "audit" && (admin || user.role === "MANAGER") && (
        <div className="security-content">
          <div className="security-audit-filters">
            <input aria-label="Search events" placeholder="Search events and resources" value={auditSearch} onChange={(event) => { setAuditPage(1); setAuditSearch(event.target.value); }} style={inputStyle} />
            <input aria-label="Filter event type" placeholder="Event type" value={auditEventType} onChange={(event) => { setAuditPage(1); setAuditEventType(event.target.value); }} style={inputStyle} />
            <input aria-label="Filter actor" placeholder="Actor user ID" value={auditActor} onChange={(event) => { setAuditPage(1); setAuditActor(event.target.value); }} style={inputStyle} />
            <input aria-label="Filter resource" placeholder="Resource type" value={auditResource} onChange={(event) => { setAuditPage(1); setAuditResource(event.target.value); }} style={inputStyle} />
            <input aria-label="Start date" type="date" value={auditStart} onChange={(event) => { setAuditPage(1); setAuditStart(event.target.value); }} style={inputStyle} />
            <input aria-label="End date" type="date" value={auditEnd} onChange={(event) => { setAuditPage(1); setAuditEnd(event.target.value); }} style={inputStyle} />
          </div>
          {events.length === 0 ? <p className="security-muted">No audit events match the filters.</p> : (
            <Table>
              <thead><tr><Cell header>Timestamp</Cell><Cell header>Actor</Cell><Cell header>Event</Cell><Cell header>Resource</Cell><Cell header>Result</Cell><Cell header>Request ID</Cell></tr></thead>
              <tbody>{events.map((event) => <tr key={event.id}>
                <Cell>{new Date(event.timestamp).toLocaleString()}</Cell><Cell>{event.actor_id ?? "System"}</Cell><Cell>{event.event_type}</Cell><Cell>{event.resource_type ?? "—"} {event.resource_id ?? ""}</Cell><Cell>{event.result}</Cell><Cell>{event.request_id ?? "—"}</Cell>
              </tr>)}</tbody>
            </Table>
          )}
          <div className="security-actions" style={{ marginTop: 12 }}>
            <span className="security-muted">{auditTotal} events</span>
            <button type="button" style={buttonStyle} disabled={auditPage <= 1} onClick={() => setAuditPage((page) => page - 1)}>Previous</button>
            <span>Page {auditPage}</span>
            <button type="button" style={buttonStyle} disabled={auditPage * 25 >= auditTotal} onClick={() => setAuditPage((page) => page + 1)}>Next</button>
          </div>
        </div>
      )}

      {!loading && section === "governance" && admin && (
        <div className="security-content">
          <section className="security-form">
            <h2>Retention policy</h2>
            <p className="security-muted">Setting a period computes expirations for preview only. Existing documents are never deleted automatically.</p>
            <div className="security-actions">
              <label>Retention period in days (blank means no expiry)
                <input type="number" min={1} max={36500} value={retentionDaysInput} onChange={(event) => setRetentionDaysInput(event.target.value)} style={inputStyle} />
              </label>
              <button type="button" style={buttonStyle} onClick={() => void saveRetention()}>Save policy</button>
              <button type="button" style={buttonStyle} onClick={() => void runAction(async () => { const result = await previewRetention(); setGovernance((current) => current ? { ...current, ...result } : current); })}>Preview affected documents</button>
            </div>
          </section>
          <h2>Document classification</h2>
          <p className="security-muted">Classification labels organize governance metadata; they do not themselves grant access.</p>
          <p>{governance?.classification_levels.join(" · ")}</p>
          <h2>Expired documents requiring administrator action</h2>
          {governance?.expiring_documents.length ? (
            <>
              <Table>
                <thead><tr><Cell header>Document ID</Cell><Cell header>Classification</Cell><Cell header>Expires</Cell><Cell header>Reason</Cell></tr></thead>
                <tbody>{governance.expiring_documents.map((item) => <tr key={item.document_id}><Cell>{item.document_id}</Cell><Cell>{item.classification}</Cell><Cell>{new Date(item.expires_at).toLocaleDateString()}</Cell><Cell>{item.reason}</Cell></tr>)}</tbody>
              </Table>
              <div className="security-actions">
                <button type="button" style={buttonStyle} onClick={() => void runRetention("archive")}>Confirm and archive all</button>
                <button type="button" className="delete-button" onClick={() => void runRetention("delete")}>Confirm and permanently delete all</button>
              </div>
            </>
          ) : <p className="security-muted">No documents are currently past the configured retention period.</p>}
        </div>
      )}
    </section>
  );
}
