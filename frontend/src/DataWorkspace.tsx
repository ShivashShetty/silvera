import { useEffect, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { oneDark } from "@codemirror/theme-one-dark";
import {
  ApiError,
  askDataset,
  getDatasetPreview,
  getDatasets,
  type DataQueryResult,
  type DatasetPreview,
  type SecurityDataset,
} from "./services/securityApi";

export default function DataWorkspace() {
  const previewPageSize = 50;
  const [datasets, setDatasets] = useState<SecurityDataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [previewOffset, setPreviewOffset] = useState(0);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [question, setQuestion] = useState("");
  const [sqlDraft, setSqlDraft] = useState("");
  const [result, setResult] = useState<DataQueryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    void getDatasets()
      .then(({ datasets: items }) => {
        if (!active) return;
        setDatasets(items);
        setDatasetId(items[0]?.id ?? "");
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load datasets.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!datasetId) return;
    let active = true;
    void getDatasetPreview(datasetId, previewOffset, previewPageSize)
      .then((nextPreview) => {
        if (active) setPreview(nextPreview);
      })
      .catch((previewLoadError: unknown) => {
        if (active) {
          setPreviewError(
            previewLoadError instanceof Error
              ? previewLoadError.message
              : "Could not preview this dataset."
          );
          setPreview(null);
        }
      })
      .finally(() => {
        if (active) setPreviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [datasetId, previewOffset]);

  async function runQuery(sql?: string) {
    setRunning(true);
    setError("");
    setMessage("");
    try {
      const next = await askDataset(question, datasetId, sql);
      setResult(next);
      setSqlDraft(next.sql);
      setMessage("Query completed.");
    } catch (queryError) {
      if (queryError instanceof ApiError && queryError.sql) {
        setSqlDraft(queryError.sql);
      }
      setError(queryError instanceof Error ? queryError.message : "The query failed.");
    } finally {
      setRunning(false);
    }
  }

  const selectedDataset = datasets.find((dataset) => dataset.id === datasetId);
  return (
    <section className="data-page">
      <div className="section-heading">
        <span>DATA INTELLIGENCE</span>
        <span>{datasets.length} AUTHORIZED DATASET(S)</span>
      </div>
      <h1>Ask your spreadsheet data</h1>
      <p className="description">
        Silvera generates a read-only SQL query using only the schema you are authorized to access. Review or edit it before running.
      </p>
      {loading && <p role="status">Loading your authorized datasets...</p>}
      {!loading && datasets.length === 0 && (
        <div className="empty-documents">
          <div className="feature-icon">⌘</div>
          <h3>No accessible datasets</h3>
          <p>Ask an administrator to grant access to a spreadsheet dataset.</p>
        </div>
      )}
      {!loading && datasets.length > 0 && (
        <div className="data-query-card">
          <label>
            Dataset
            <select value={datasetId} onChange={(event) => {
              setDatasetId(event.target.value);
              setPreviewOffset(0);
              setPreview(null);
              setPreviewLoading(true);
              setPreviewError("");
              setResult(null);
              setSqlDraft("");
            }}>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.filename}{dataset.sheet_name ? ` · ${dataset.sheet_name}` : ""}
                </option>
              ))}
            </select>
          </label>
          {selectedDataset && (
            <p className="security-muted">
              {selectedDataset.row_count ?? "Unknown"} rows · {selectedDataset.columns.length} permitted column(s): {selectedDataset.columns.join(", ")}
            </p>
          )}
          <section className="data-preview" aria-label="Dataset preview">
            <div className="data-sql-heading">
              <strong>CSV preview</strong>
              <span>
                {preview?.row_count == null
                  ? `Showing up to ${previewPageSize} rows`
                  : `${preview.row_count.toLocaleString()} total rows`}
              </span>
            </div>
            {previewLoading && <p className="security-muted" role="status">Loading preview…</p>}
            {previewError && <p className="security-message error" role="alert">{previewError}</p>}
            {!previewLoading && preview && (
              <>
                {preview.rows.length === 0 ? (
                  <p className="security-muted">This dataset has no rows to preview.</p>
                ) : (
                  <div className="data-preview-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          {preview.columns.map((column, index) => (
                            <th key={`${column}-${index}`}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.rows.map((row, rowIndex) => (
                          <tr key={preview.offset + rowIndex}>
                            {row.map((value, columnIndex) => (
                              <td key={`${preview.offset + rowIndex}-${columnIndex}`}>
                                {String(value ?? "")}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="data-preview-controls">
                  <span className="security-muted">
                    Rows {preview.rows.length ? preview.offset + 1 : 0}–
                    {preview.offset + preview.rows.length}
                    {preview.row_count != null
                      ? ` of ${preview.row_count.toLocaleString()}`
                      : ""}
                  </span>
                  <div className="security-actions">
                    <button
                      type="button"
                      className="new-chat"
                      disabled={previewOffset === 0 || previewLoading}
                      onClick={() => {
                        setPreviewOffset(Math.max(0, previewOffset - previewPageSize));
                        setPreview(null);
                        setPreviewLoading(true);
                      }}
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      className="new-chat"
                      disabled={!preview.has_more || previewLoading}
                      onClick={() => {
                        setPreviewOffset(previewOffset + previewPageSize);
                        setPreview(null);
                        setPreviewLoading(true);
                      }}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            )}
          </section>
          <label>
            Ask a question
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              maxLength={1000}
              placeholder="For example: show total sales by region"
            />
          </label>
          <div className="security-actions">
            <button type="button" className="new-chat" disabled={!question.trim() || running} onClick={() => void runQuery()}>
              {running ? "Generating..." : "Generate & run"}
            </button>
          </div>
          {sqlDraft && (
            <div className="data-sql-editor">
              <div className="data-sql-heading">
                <strong>Generated SQL</strong>
                <span>Read-only · 5-second timeout · 100-row cap</span>
              </div>
              <CodeMirror
                aria-label="Editable SQL query"
                value={sqlDraft}
                onChange={setSqlDraft}
                extensions={[sql()]}
                theme={oneDark}
                height={`${Math.min(16, Math.max(5, sqlDraft.split("\n").length + 1)) * 23 + 16}px`}
                basicSetup={{ foldGutter: false }}
              />
              <button type="button" className="new-chat" disabled={!sqlDraft.trim() || running} onClick={() => void runQuery(sqlDraft)}>
                {running ? "Running..." : "Run edited SQL"}
              </button>
            </div>
          )}
          {error && <p className="security-message error" role="alert">{error}</p>}
          {message && <p className="security-message success" role="status">{message}</p>}
          {result && (
            <section className="data-results" aria-label="SQL results">
              <div className="data-sql-heading">
                <strong>Results</strong>
                <span>Source: {result.sources.join(", ")}{result.truncated ? " · Results capped at 100" : ""}</span>
              </div>
              {result.columns.length === 0 ? <p>The query returned no result columns.</p> : result.rows.length === 0 ? <p>No rows matched the query.</p> : (
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead><tr>{result.columns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead>
                    <tbody>{result.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>{row.map((value, index) => <td key={`${rowIndex}-${index}`}>{String(value ?? "")}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
              <p className="security-muted">{result.rows.length} row(s) returned.</p>
            </section>
          )}
        </div>
      )}
    </section>
  );
}
