import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  getSilveraStatus,
  uploadDocument,
  askSilvera,
  getDocuments,
  deleteDocument,
  getOriginalDocumentUrl,
  getConversations,
  getConversation,
  deleteConversation,
  type ConversationSummary,
  type ConversationMessage,
  type DocumentUploadResult,
  type AskResponse,
  type AskSource,
  type StoredDocument,
} from "./services/api";
import "./App.css";
type Page = "intelligence" | "documents";
function formatAnswerLine(line: string, index: number) {
  const trimmed = line.trim();
  if (!trimmed) {
    return <div className="answer-spacer" key={index} />;
  }
  const bullet = trimmed.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
  if (bullet) {
    return (
      <div className="answer-list-item" key={index}>
        <span className="answer-bullet">
          {trimmed.match(/^\d+[.)]/)?.[0] ?? "•"}
        </span>
        <span>{bullet[1]}</span>
      </div>
    );
  }
  return <p key={index}>{trimmed}</p>;
}
/* --------------------------------------------------
   Animated answer
   The completion callback stops the three dots.
\-------------------------------------------------- */
function AnimatedAnswer({
  content,
  animate,
  onTypingComplete,
}: {
  content: string;
  animate: boolean;
  onTypingComplete: () => void;
}) {
  const [visibleLength, setVisibleLength] = useState(
    animate ? 0 : content.length
  );
  useEffect(() => {
    if (!animate) {
      setVisibleLength(content.length);
      return;
    }
    let currentLength = 0;
    let lastTime = 0;
    let frameId = 0;
    let cancelled = false;
    setVisibleLength(0);
    if (content.length === 0) {
      onTypingComplete();
      return;
    }
    const revealText = (time: number) => {
      if (cancelled) return;
      if (time - lastTime >= 18) {
        currentLength = Math.min(
          currentLength + Math.max(1, Math.ceil(content.length / 250)),
          content.length
        );
        setVisibleLength(currentLength);
        lastTime = time;
        if (currentLength >= content.length) {
          onTypingComplete();
          return;
        }
      }
      frameId = requestAnimationFrame(revealText);
    };
    frameId = requestAnimationFrame(revealText);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frameId);
    };
  }, [content, animate, onTypingComplete]);
  const visibleText = content.slice(0, visibleLength);
  return (
    <div className={`answer-content ${animate ? "answer-animated" : ""}`}>
      {visibleText.split("\n").map((line, index) =>
        formatAnswerLine(line, index)
      )}
    </div>
  );
}
function App() {
  const [question, setQuestion] = useState("");
  const [conversationMessages, setConversationMessages] =
    useState<ConversationMessage[]>([]);
  const [backendStatus, setBackendStatus] = useState("checking");
  const [activePage, setActivePage] = useState<Page>("intelligence");
  const [conversations, setConversations] =
    useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] =
    useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [openingConversationId, setOpeningConversationId] =
    useState<string | null>(null);
  const [deletingConversationId, setDeletingConversationId] =
    useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadResult, setUploadResult] =
    useState<DocumentUploadResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResult, setSearchResult] =
    useState<AskResponse | null>(null);
  const [typingMessageId, setTypingMessageId] =
    useState<string | null>(null);
  const [selectedSource, setSelectedSource] =
    useState<AskSource | null>(null);
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const conversationPanelRef = useRef<HTMLDivElement>(null);
  const pendingPromptRef = useRef<string | null>(null);
  // Stable callback: the animation effect won't restart on each render.
  const handleTypingComplete = useCallback(() => {
    setTypingMessageId(null);
  }, []);
  useEffect(() => {
    void loadConversationHistory();
  }, []);
  useEffect(() => {
    getSilveraStatus()
      .then(() => setBackendStatus("online"))
      .catch(() => setBackendStatus("offline"));
  }, []);
  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedSource(null);
      }
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, []);
  // Scroll only the conversation panel to the latest submitted prompt.
  useLayoutEffect(() => {
    if (!pendingPromptRef.current) return;
    const panel = conversationPanelRef.current;
    if (!panel) return;
    const userMessages = panel.querySelectorAll<HTMLElement>(
      '[data-role="user"]'
    );
    const latestMessage = userMessages[userMessages.length - 1];
    if (!latestMessage) return;
    const panelRect = panel.getBoundingClientRect();
    const messageRect = latestMessage.getBoundingClientRect();
    // Start the submitted question near the top, leaving room for the
    // response-following effect to move it up to the top edge.
    const targetTop =
      panel.scrollTop + messageRect.top - panelRect.top - 90;
    panel.scrollTo({
      top: Math.max(0, targetTop),
      behavior: "smooth",
    });
    pendingPromptRef.current = null;
  }, [conversationMessages]);
  // Follow Silvera's growing answer while keeping the submitted question visible.
  // Scrolling stops once that question reaches the top of the conversation panel.
  useLayoutEffect(() => {
    if (!typingMessageId) return;
    const panel = conversationPanelRef.current;
    if (!panel) return;
    const articles = Array.from(
      panel.querySelectorAll<HTMLElement>(".chat-message")
    );
    const assistantIndex = articles.findIndex(
      (article) => article.dataset.messageId === String(typingMessageId)
    );
    if (assistantIndex < 0) return;
    const assistantMessage = articles[assistantIndex];
    const assistantContent = assistantMessage.querySelector<HTMLElement>(
      ".chat-assistant-content"
    );
    if (!assistantContent) return;
    // Find the most recent user message before this assistant response.
    const promptMessage = articles
      .slice(0, assistantIndex)
      .reverse()
      .find((article) => article.dataset.role === "user");
    if (!promptMessage) return;
    let frameId = 0;
    const followAnswer = () => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(() => {
        const panelRect = panel.getBoundingClientRect();
        const promptRect = promptMessage.getBoundingClientRect();
        const assistantRect = assistantMessage.getBoundingClientRect();
        const topInset = 20;
        const bottomInset = 16;
        const distanceBeforePromptHitsTop =
          promptRect.top - (panelRect.top + topInset);
        // Preserve the question: never scroll it above the panel's top inset.
        if (distanceBeforePromptHitsTop <= 0) return;
        const visibleBottom = panelRect.top + panel.clientHeight - bottomInset;
        const answerOverflow = assistantRect.bottom - visibleBottom;
        if (answerOverflow <= 0) return;
        const scrollBy = Math.min(
          answerOverflow,
          distanceBeforePromptHitsTop
        );
        if (scrollBy > 0) {
          // Avoid competing smooth-scroll animations during character reveal.
          panel.scrollTop += scrollBy;
        }
      });
    };
    const observer = new ResizeObserver(followAnswer);
    observer.observe(assistantContent);
    observer.observe(assistantMessage);
    followAnswer();
    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
    };
  }, [typingMessageId, conversationMessages]);
  async function loadConversationHistory() {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setConversations(await getConversations());
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Could not load conversation history."
      );
    } finally {
      setHistoryLoading(false);
    }
  }
  async function openConversation(conversationId: string) {
    if (openingConversationId) return;
    setOpeningConversationId(conversationId);
    setHistoryError("");
    pendingPromptRef.current = null;
    setTypingMessageId(null);
    try {
      const conversation = await getConversation(conversationId);
      setActiveConversationId(conversation.id);
      setActivePage("intelligence");
      setQuestion("");
      setSearchError("");
      setSearchResult(null);
      setConversationMessages(conversation.messages ?? []);
      setSelectedSource(null);
      requestAnimationFrame(() => {
        if (conversationPanelRef.current) {
          conversationPanelRef.current.scrollTop = 0;
        }
      });
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Could not open this conversation."
      );
    } finally {
      setOpeningConversationId(null);
    }
  }
  async function handleDeleteConversation(
    conversation: ConversationSummary
  ) {
    const confirmed = window.confirm(
      `Delete conversation "${conversation.title}"?`
    );
    if (!confirmed || deletingConversationId) return;
    setDeletingConversationId(conversation.id);
    setHistoryError("");
    try {
      await deleteConversation(conversation.id);
      setConversations((current) =>
        current.filter((item) => item.id !== conversation.id)
      );
      if (activeConversationId === conversation.id) {
        resetWorkspace();
      }
    } catch (error) {
      setHistoryError(
        error instanceof Error
          ? error.message
          : "Could not delete this conversation."
      );
    } finally {
      setDeletingConversationId(null);
    }
  }
  async function loadDocuments() {
    setDocumentsLoading(true);
    setDocumentsError("");
    try {
      setDocuments(await getDocuments());
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
    setSelectedSource(null);
    setSearchResult(null);
    setTypingMessageId(null);
    setQuestion("");
    pendingPromptRef.current = query;
    const temporaryMessage = {
      id: `pending-${Date.now()}`,
      role: "user",
      content: query,
      sources: [],
      created_at: new Date().toISOString(),
    } as ConversationMessage;
    setConversationMessages((current) => [
      ...current,
      temporaryMessage,
    ]);
    try {
      const result = await askSilvera(query, activeConversationId);
      setActiveConversationId(result.conversation_id);
      const conversation = await getConversation(
        result.conversation_id
      );
      const messages = conversation.messages ?? [];
      setConversationMessages(messages);
      const newestAssistantMessage = [...messages]
        .reverse()
        .find((message) => message.role === "assistant");
      setTypingMessageId(
        newestAssistantMessage
          ? String(newestAssistantMessage.id)
          : null
      );
      setSearchResult(result);
      await loadConversationHistory();
    } catch (error) {
      setTypingMessageId(null);
      setConversationMessages((current) =>
        current.filter(
          (message) => !String(message.id).startsWith("pending-")
        )
      );
      setSearchError(
        error instanceof Error
          ? error.message
          : "Silvera could not generate an answer."
      );
    } finally {
      setSearching(false);
    }
  }
  async function handleDelete(document: StoredDocument) {
    const confirmed = window.confirm(
      `Delete "${document.filename}"? Its extracted text, metadata, original PDF, and search index will be removed from Silvera.`
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
      if (
        searchResult?.sources.some(
          (source) => source.document_id === document.document_id
        )
      ) {
        setSearchResult(null);
        setSearchError(
          "A source document was deleted. Ask your question again to generate a new answer."
        );
      }
      if (
        selectedSource?.document_id === document.document_id
      ) {
        setSelectedSource(null);
      }
      await loadDocuments();
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
  function resetWorkspace() {
    pendingPromptRef.current = null;
    setTypingMessageId(null);
    setActiveConversationId(null);
    setConversationMessages([]);
    setQuestion("");
    setSearchResult(null);
    setSearchError("");
    setUploadResult(null);
    setUploadError("");
    setSelectedFile(null);
    setSelectedSource(null);
    setActivePage("intelligence");
  }
  function openDocuments() {
    setActivePage("documents");
    void loadDocuments();
  }
  function openOriginalDocument() {
    if (!selectedSource) return;
    const url = getOriginalDocumentUrl(
      selectedSource.document_id
    );
    window.open(url, "_blank", "noopener,noreferrer");
  }
  return (
    <div className="app">
      <aside className="sidebar">
        <h2 className="brand">
          silver<span>a.</span>
        </h2>
        <p className="tagline">
          SECURE ENTERPRISE INTELLIGENCE
        </p>
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
        <div className="history-heading">
          <span>RECENT CONVERSATIONS</span>
          <button
            type="button"
            className="history-refresh"
            onClick={() => void loadConversationHistory()}
            disabled={historyLoading}
            aria-label="Refresh conversation history"
            title="Refresh history"
          >
            ↻
          </button>
        </div>
        <div className="conversation-list">
          {historyLoading && conversations.length === 0 ? (
            <p className="history-empty">Loading history...</p>
          ) : conversations.length === 0 ? (
            <p className="history-empty">
              Your conversations will appear here.
            </p>
          ) : (
            conversations.map((conversation) => (
              <div
                className={`conversation-item ${
                  activeConversationId === conversation.id
                    ? "active"
                    : ""
                }`}
                key={conversation.id}
              >
                <button
                  type="button"
                  className="conversation-open"
                  onClick={() =>
                    void openConversation(conversation.id)
                  }
                  disabled={openingConversationId !== null}
                  title={conversation.title}
                >
                  <span className="conversation-title">
                    {conversation.title}
                  </span>
                  <span className="conversation-meta">
                    {conversation.message_count} messages
                  </span>
                </button>
                <button
                  type="button"
                  className="conversation-delete"
                  onClick={() =>
                    void handleDeleteConversation(conversation)
                  }
                  disabled={deletingConversationId !== null}
                  aria-label={`Delete conversation: ${conversation.title}`}
                  title="Delete conversation"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
        {historyError && (
          <p className="history-error" role="alert">
            {historyError}
          </p>
        )}
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
                  onChange={(event) =>
                    setQuestion(event.target.value)
                  }
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey &&
                      !searching
                    ) {
                      event.preventDefault();
                      void handleSearch();
                    }
                  }}
                  placeholder="Ask a question about your documents..."
                  rows={3}
                  maxLength={1000}
                  aria-label="Ask Silvera a question"
                />
                <div className="search-footer">
                  <span>↳ AI-powered document Q&amp;A</span>
                  <button
                    onClick={() => void handleSearch()}
                    disabled={!question.trim() || searching}
                  >
                    {searching ? "Thinking..." : "Ask Silvera ↗"}
                  </button>
                </div>
              </div>
              <p className="notice">
                <span>◇</span> Answers grounded in your documents,
                powered by your local AI model.
              </p>
              {searchError && (
                <div className="search-results" role="alert">
                  <p className="upload-error">{searchError}</p>
                </div>
              )}
              {searching && (
                <div
                  className="search-results loading-answer"
                  role="status"
                >
                  <span className="loading-orb" />
                  <p>Searching your knowledge base...</p>
                  <span>Silvera is preparing your answer</span>
                </div>
              )}
              {conversationMessages.length > 0 && (
                <div
                  className="conversation-panel"
                  ref={conversationPanelRef}
                  aria-label="Conversation messages"
                  style={{
                    maxHeight: "65vh",
                    overflowY: "auto",
                    overflowX: "hidden",
                    overscrollBehavior: "contain",
                    scrollBehavior: "smooth",
                    scrollPaddingTop: "20px",
                  }}
                >
                  <div
                    className="conversation-thread"
                    aria-live="polite"
                  >
                    {conversationMessages.map((message) => {
                      const isTyping =
                        message.role === "assistant" &&
                        String(message.id) === typingMessageId;
                      return (
                        <article
                          key={message.id}
                          data-role={message.role}
                          data-message-id={String(message.id)}
                          className={`chat-message ${
                            message.role === "user"
                              ? "user-message"
                              : "assistant-message"
                          }`}
                        >
                          {message.role === "user" ? (
                            <>
                              <div className="chat-message-label">
                                YOU
                              </div>
                              <div className="chat-user-bubble">
                                {message.content}
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="chat-message-label silvera-label">
                                <span className="model-dot" />
                                SILVERA
                                {isTyping && (
                                  <span
                                    className="typing-dots"
                                    aria-label="Silvera is typing"
                                    role="status"
                                  >
                                    <span />
                                    <span />
                                    <span />
                                  </span>
                                )}
                              </div>
                              <div className="chat-assistant-content">
                                <AnimatedAnswer
                                  key={String(message.id)}
                                  content={message.content}
                                  animate={isTyping}
                                  onTypingComplete={
                                    handleTypingComplete
                                  }
                                />
                                <div className="answer-bottom">
                                  <span>
                                    <span className="privacy-symbol">
                                      ◇
                                    </span>
                                    Generated locally
                                  </span>
                                  <span>
                                    {(message.sources ?? []).length}{" "}
                                    source passage
                                    {(message.sources ?? []).length === 1
                                      ? ""
                                      : "s"}
                                  </span>
                                </div>
                              </div>
                              {(message.sources ?? []).length > 0 && (
                                <div className="sources-section chat-sources-section">
                                  <div className="sources-heading">
                                    <div>
                                      <h4>Sources</h4>
                                      <p>
                                        Evidence retrieved from your
                                        documents
                                      </p>
                                    </div>
                                    <span className="source-count">
                                      {message.sources.length}
                                    </span>
                                  </div>
                                  <div className="source-chips">
                                    {message.sources.map(
                                      (source, index) => (
                                        <button
                                          className="source-chip"
                                          key={`${message.id}-${source.document_id}-${source.chunk_index}-${index}`}
                                          onClick={() =>
                                            setSelectedSource(source)
                                          }
                                          title={`View source: ${source.filename}`}
                                          aria-label={`View source ${source.filename}`}
                                        >
                                          <span className="source-file-icon">
                                            ▤
                                          </span>
                                          <span className="source-chip-text">
                                            <span className="source-chip-label">
                                              {source.filename}
                                            </span>
                                            <span className="source-chip-meta">
                                              {source.similarity != null
                                                ? `${(
                                                    source.similarity * 100
                                                  ).toFixed(1)}% match`
                                                : "Source passage"}
                                            </span>
                                          </span>
                                          <span className="source-open-icon">
                                            ↗
                                          </span>
                                        </button>
                                      )
                                    )}
                                  </div>
                                </div>
                              )}
                            </>
                          )}
                        </article>
                      );
                    })}
                  </div>
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
                    Upload PDF documents and ask questions about their
                    extracted text.
                  </p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,application/pdf"
                    hidden
                    onChange={(event) => {
                      setSelectedFile(
                        event.target.files?.[0] ?? null
                      );
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
                        {(selectedFile.size / (1024 * 1024)).toFixed(2)}{" "}
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
                  <h3>Security &amp; governance</h3>
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
                <p>
                  Upload a PDF to start building your knowledge base.
                </p>
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
      {selectedSource && (
        <div
          className="source-modal-backdrop"
          onClick={() => setSelectedSource(null)}
          role="presentation"
        >
          <section
            className="source-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-modal-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="source-modal-header">
              <div className="source-modal-title-icon">▤</div>
              <div className="source-modal-heading">
                <span className="answer-kicker">
                  SOURCE DOCUMENT
                </span>
                <h3 id="source-modal-title">Retrieved passage</h3>
              </div>
            </div>
            <div className="source-modal-file">
              <div className="source-modal-file-info">
                <span className="source-modal-filename">
                  {selectedSource.filename}
                </span>
                <span className="source-modal-subtitle">
                  Retrieved from your local knowledge base
                </span>
              </div>
            </div>
            {selectedSource.similarity != null && (
              <div className="source-relevance">
                <span>Semantic similarity</span>
                <span>
                  {(selectedSource.similarity * 100).toFixed(1)}%
                </span>
              </div>
            )}
            <div className="source-modal-body">
              <span className="answer-kicker">PASSAGE CONTENT</span>
              <p className="passage-content">
                {selectedSource.passage}
              </p>
            </div>
            <div className="source-modal-footer">
              <span>◇ Stored and processed locally</span>
              <div className="source-modal-actions">
                <button
                  className="source-open-original"
                  onClick={openOriginalDocument}
                  type="button"
                >
                  Open original ↗
                </button>
                <button
                  className="source-done-button"
                  onClick={() => setSelectedSource(null)}
                  type="button"
                >
                  Done
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
export default App;
