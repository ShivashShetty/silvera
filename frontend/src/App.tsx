
import { useEffect, useRef, useState } from "react";
import {
  getSilveraStatus,
  uploadDocument,
  searchDocuments,
  getDocuments,
  deleteDocument,
  type DocumentUploadResult,
  type DocumentSearchResponse,
  type StoredDocument,
} from "./services/api";
import "./App.css";

type Page = "intelligence" | "documents";

function App() {
  const [question, setQuestion] = useState("");
  const [backendStatus, setBackendStatus] = useState("checking");
  const [activePage, setActivePage] = useState<Page>("intelligence");

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadResult, setUploadResult] =
    useState<DocumentUploadResult | null>(null);

  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResult, setSearchResult] =
    useState<DocumentSearchResponse | null>(null);

  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSilveraStatus()
      .then(() => setBackendStatus("online"))
      .catch(() => setBackendStatus("offline"));
  }, []);

  async function loadDocuments() {
    setDocumentsLoading(true);
    setDocumentsError("");

    try {
      const items = await getDocuments();
      setDocuments(items);
    } catch (error) {
      setDocumentsError(
        error instanceof Error
          ? error.message
          : "Could not load documents."
      );
    } finally {
      setDocumentsLoading(false);
    }
  }

  async function handleUpload() {
    if (!selectedFile || uploading) return;

    setUploading(true);
    setUploadError("");
    setUploadResult(null);

    try {
      const result = await uploadDocument(selectedFile);
      setUploadResult(result);
      setSelectedFile(null);

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }

      if (activePage === "documents") {
        await loadDocuments();
      }
    } catch (error) {
      setUploadError(
        error instanceof Error ? error.message : "Upload failed."
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleSearch() {
    const query = question.trim();
    if (!query || searching) return;

    setSearching(true);
    setSearchError("");
    setSearchResult(null);

    try {
      const result = await searchDocuments(query);
      setSearchResult(result);
    } catch (error) {
      setSearchError(
        error instanceof Error ? error.message : "Search failed."
      );
    } finally {
      setSearching(false);
    }
  }

  async function handleDelete(document: StoredDocument) {
    const confirmed = window.confirm(
      `Delete "${document.filename}"? Its extracted text and metadata will be removed.`
    );

    if (!confirmed || deletingId) return;

    setDeletingId(document.document_id);
    setDocumentsError("");

    try {
      await deleteDocument(document.document_id);

      setDocuments((current) =>
        current.filter(
          (item) => item.document_id !== document.document_id
        )
      );

      // Refresh current search so deleted content disappears.
      if (searchResult) {
        try {
          const updatedResults = await searchDocuments(
            searchResult.query
          );
          setSearchResult(updatedResults);
        } catch {
          setSearchResult(null);
        }
      }
    } catch (error) {
      setDocumentsError(
        error instanceof Error
          ? error.message
          : "Could not delete document."
      );
    } finally {
      setDeletingId(null);
    }
  }

  function openDocuments() {
    setActivePage("documents");
    void loadDocuments();
  }

  function resetWorkspace() {
    setQuestion("");
    setSearchResult(null);
    setSearchError("");
    setUploadResult(null);
    setUploadError("");
    setSelectedFile(null);
    setActivePage("intelligence");
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <h2 className="brand">
          silver<span>a.</span>
        </h2>
        <p className="tagline">SECURE ENTERPRISE INTELLIGENCE</p>

        <button className="new-chat" onClick={resetWorkspace}>
          + New conversation
        </button>

        <div className="nav-label">WORKSPACE</div>

        <button
          className={`nav-item ${
            activePage === "intelligence" ? "active" : ""
          }`}
          onClick={() => setActivePage("intelligence")}
        >
          ⌂ &nbsp; Intelligence
        </button>

        <button
          className={`nav-item ${
            activePage === "documents" ? "active" : ""
          }`}
          onClick={openDocuments}
        >
          ▤ &nbsp; Documents
        </button>

        <div className="nav-item">◈ &nbsp; Data sources</div>
        <div className="nav-item">◉ &nbsp; Activity logs</div>

        <div className="sidebar-bottom">
          <div
            className="status-dot"
            style={{
              background:
                backendStatus === "online"
                  ? "#8ebca7"
                  : backendStatus === "offline"
                    ? "#e58c8c"
                    : "#d8bd7a",
            }}
          />

          {backendStatus === "checking"
            ? "Checking connection..."
            : backendStatus === "online"
              ? "Backend connected"
              : "Backend offline"}

          <span className="local-badge">
            {backendStatus.toUpperCase()}
          </span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span>
            Workspace /{" "}
            {activePage === "intelligence"
              ? "Intelligence"
              : "Documents"}
          </span>

          <div className="user">
            S <span>Administrator</span>
          </div>
        </header>

        {activePage === "intelligence" && (
          <>
            <section className="hero">
              <div className="eyebrow">
                <span className="status-dot" />
                YOUR PRIVATE AI WORKSPACE
              </div>

              <h1>
                Intelligence, <span>under your control.</span>
              </h1>

              <p className="description">
                Explore your organization's knowledge and business data
                through a secure, unified intelligence platform.
              </p>

              <div className="search-box">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !searching
                    ) {
                      e.preventDefault();
                      void handleSearch();
                    }
                  }}
                  placeholder="Search your documents..."
                  rows={3}
                />

                <div className="search-footer">
                  <span>↳ Document keyword search</span>
                  <button
                    onClick={() => void handleSearch()}
                    disabled={!question.trim() || searching}
                  >
                    {searching ? "Searching..." : "Ask Silvera ↗"}
                  </button>
                </div>
              </div>

              <p className="notice">
                <span>◇</span> Silvera searches the text of your uploaded
                documents. AI-generated answers are coming next.
              </p>

              {searchError && (
                <div className="search-results" role="alert">
                  <p className="upload-error">{searchError}</p>
                </div>
              )}

              {searchResult && (
                <div className="search-results" aria-live="polite">
                  <h3>Search results</h3>
                  <p>
                    Found {searchResult.total_results} matching
                    passage(s) for "{searchResult.query}".
                  </p>

                  {searchResult.results.length === 0 ? (
                    <p>
                      No matching passages found. Try other keywords
                      or upload a document first.
                    </p>
                  ) : (
                    searchResult.results.map((result, index) => (
                      <article
                        className="search-result"
                        key={`${result.document_id}-${index}`}
                      >
                        <p>{result.passage}</p>
                        <span>Source: {result.filename}</span>
                      </article>
                    ))
                  )}
                </div>
              )}
            </section>

            <section className="features">
              <div className="section-heading">
                <span>KNOWLEDGE WORKSPACE</span>
                <span>01 — 03</span>
              </div>

              <div className="feature-grid">
                <article className="feature-card">
                  <div className="feature-icon">▤</div>
                  <h3>Knowledge intelligence</h3>
                  <p>
                    Upload PDF documents and search their extracted text.
                  </p>

                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,application/pdf"
                    hidden
                    onChange={(e) => {
                      setSelectedFile(e.target.files?.[0] ?? null);
                      setUploadError("");
                      setUploadResult(null);
                    }}
                  />

                  <button
                    className="new-chat"
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                  >
                    Choose PDF
                  </button>

                  {selectedFile && (
                    <div className="upload-details">
                      <p>Selected: {selectedFile.name}</p>
                      <p>
                        Size:{" "}
                        {(
                          selectedFile.size /
                          (1024 * 1024)
                        ).toFixed(2)}{" "}
                        MB
                      </p>
                      <button
                        className="upload-button"
                        type="button"
                        onClick={() => void handleUpload()}
                        disabled={uploading}
                      >
                        {uploading
                          ? "Uploading..."
                          : "Upload document ↑"}
                      </button>
                    </div>
                  )}

                  {uploadError && (
                    <p className="upload-error" role="alert">
                      {uploadError}
                    </p>
                  )}

                  {uploadResult && (
                    <div className="upload-success" role="status">
                      <p>✓ {uploadResult.message}</p>
                      <p>Pages: {uploadResult.pages}</p>
                      <p>
                        Characters extracted:{" "}
                        {uploadResult.characters_extracted}
                      </p>
                      <details>
                        <summary>View extracted text</summary>
                        <pre>{uploadResult.preview}</pre>
                      </details>
                    </div>
                  )}
                </article>

                <article className="feature-card">
                  <div className="feature-icon">⌘</div>
                  <h3>Data intelligence</h3>
                  <p>
                    Ask questions about business data and uncover useful
                    insights without writing SQL.
                  </p>
                  <span className="feature-status">PLANNED</span>
                </article>

                <article className="feature-card">
                  <div className="feature-icon">⬡</div>
                  <h3>Security & governance</h3>
                  <p>
                    Build toward controlled access, audit trails and
                    permission-aware AI retrieval.
                  </p>
                  <span className="feature-status">PLANNED</span>
                </article>
              </div>
            </section>
          </>
        )}

        {activePage === "documents" && (
          <section className="documents-page">
            <div className="section-heading">
              <span>YOUR DOCUMENTS</span>
              <span>{documents.length} FILE(S)</span>
            </div>

            <h1>Document library</h1>
            <p className="description">
              Manage the documents stored in your Silvera workspace.
            </p>

            <div className="documents-toolbar">
              <button
                className="new-chat"
                onClick={() => void loadDocuments()}
                disabled={documentsLoading}
              >
                {documentsLoading
                  ? "Refreshing..."
                  : "↻ Refresh documents"}
              </button>

              <button
                className="new-chat"
                onClick={() => setActivePage("intelligence")}
              >
                + Upload a document
              </button>
            </div>

            {documentsError && (
              <p className="upload-error" role="alert">
                {documentsError}
              </p>
            )}

            {documentsLoading && <p>Loading documents...</p>}

            {!documentsLoading && documents.length === 0 && (
              <div className="empty-documents">
                <div className="feature-icon">▤</div>
                <h3>No documents yet</h3>
                <p>Upload a PDF to start building your knowledge base.</p>
                <button
                  className="new-chat"
                  onClick={() => setActivePage("intelligence")}
                >
                  Go to Intelligence
                </button>
              </div>
            )}

            {!documentsLoading && documents.length > 0 && (
              <div className="document-list">
                {documents.map((document) => (
                  <article
                    className="document-row"
                    key={document.document_id}
                  >
                    <div className="document-info">
                      <div className="feature-icon">▤</div>
                      <div>
                        <h3>{document.filename}</h3>
                        <p>
                          {document.pages == null
                            ? "Page count unavailable"
                            : `${document.pages} page(s)`}
                          {" · "}
                          {document.characters_extracted.toLocaleString()}{" "}
                          characters
                        </p>
                        <p>
                          {document.uploaded_at
                            ? `Uploaded ${new Date(
                                document.uploaded_at
                              ).toLocaleString()}`
                            : "Upload date unavailable"}
                        </p>
                      </div>
                    </div>

                    <button
                      className="delete-button"
                      onClick={() => void handleDelete(document)}
                      disabled={deletingId !== null}
                    >
                      {deletingId === document.document_id
                        ? "Deleting..."
                        : "Delete"}
                    </button>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        <footer>
          <span>SILVERA © 2026</span>
          <span>PRIVATE BY DESIGN · BUILT LOCALLY</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
