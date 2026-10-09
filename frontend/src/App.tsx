import { useEffect, useState } from "react";
import { getSilveraStatus } from "./services/api";
import "./App.css";

function App() {
  const [question, setQuestion] = useState("");
  const [backendStatus, setBackendStatus] = useState("checking");

useEffect(() => {
  getSilveraStatus()
    .then(() => setBackendStatus("online"))
    .catch(() => setBackendStatus("offline"));
}, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <h2 className="brand">silver<span>a.</span></h2>
        <p className="tagline">SECURE ENTERPRISE INTELLIGENCE</p>

        <button className="new-chat">+ New conversation</button>

        <div className="nav-label">WORKSPACE</div>
        <div className="nav-item active">⌂ &nbsp; Intelligence</div>
        <div className="nav-item">▤ &nbsp; Documents</div>
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
          <span>Workspace / Intelligence</span>
          <div className="user">S <span>Administrator</span></div>
        </header>

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
              placeholder="Ask Silvera about your data..."
              rows={3}
            />
            <div className="search-footer">
              <span>↳ Documents · Data · Intelligence</span>
              <button
                onClick={() =>
                  alert("Silvera's AI backend is coming next!")
                }
                disabled={!question.trim()}
              >
                Ask Silvera ↗
              </button>
            </div>
          </div>

          <p className="notice">
            <span>◇</span> Your workspace is being set up. AI responses
            will be enabled after connecting the backend.
          </p>
        </section>

        <section className="features">
          <div className="section-heading">
            <span>PLATFORM CAPABILITIES</span>
            <span>01 — 03</span>
          </div>

          <div className="feature-grid">
            <article className="feature-card">
              <div className="feature-icon">▤</div>
              <h3>Knowledge intelligence</h3>
              <p>
                Search internal documents and get answers grounded in
                your organization's knowledge.
              </p>
              <span className="feature-status">COMING NEXT</span>
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

        <footer>
          <span>SILVERA © 2026</span>
          <span>PRIVATE BY DESIGN · BUILT LOCALLY</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
