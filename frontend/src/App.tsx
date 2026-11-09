import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Document as PdfDocument, Page as PdfPage, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
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

// Use the PDF.js worker bundled with the installed react-pdf dependency.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

type Page = "intelligence" | "documents";
function normalizeMarkdown(text: string) {
  // Ollama sometimes escapes Markdown punctuation even when it intends
  // to return Markdown. Normalize only common formatting characters.
  return text.replace(/\\([|*`_])/g, "$1");
}

function findPassageRange(pageText: string, passage: string): [number, number] | null {
  const normalizeWithPositions = (value: string) => {
    let normalized = "";
    const positions: number[] = [];
    let previousWasWhitespace = false;
    for (let index = 0; index < value.length; index += 1) {
      const character = value[index];
      if (/\s/.test(character)) {
        if (!previousWasWhitespace) {
          normalized += " ";
          positions.push(index);
        }
        previousWasWhitespace = true;
      } else {
        normalized += character.toLocaleLowerCase();
        positions.push(index);
        previousWasWhitespace = false;
      }
    }
    while (normalized.startsWith(" ")) {
      normalized = normalized.slice(1);
      positions.shift();
    }
    while (normalized.endsWith(" ")) {
      normalized = normalized.slice(0, -1);
      positions.pop();
    }
    return { normalized, positions };
  };

  const page = normalizeWithPositions(pageText);
  const target = normalizeWithPositions(passage.trim());
  if (!target.normalized) return null;
  const start = page.normalized.indexOf(target.normalized);
  if (start < 0) return null;
  const originalStart = page.positions[start];
  const originalEnd = page.positions[start + target.normalized.length - 1] + 1;
  return [originalStart, originalEnd];
}

function renderPageWithHighlight(pageText: string, passage: string): ReactNode {
  const range = findPassageRange(pageText, passage);
  if (!range) return pageText;
  return (
    <>
      {pageText.slice(0, range[0])}
      <mark
        data-source-passage-highlight="true"
        style={{
          background: "rgba(105, 190, 169, 0.28)",
          color: "#d9fff3",
          border: "1px solid rgba(105, 190, 169, 0.55)",
          borderRadius: "4px",
          padding: "1px 2px",
          boxShadow: "0 0 14px rgba(105, 190, 169, 0.12)",
        }}
      >
        {pageText.slice(range[0], range[1])}
      </mark>
      {pageText.slice(range[1])}
    </>
  );
}

function renderInlineMarkdown(
  text: string,
  keyPrefix: string,
  sources: AskSource[] = [],
  onEvidenceClick?: (source: AskSource) => void
): ReactNode {
  const normalized = normalizeMarkdown(text);
  const pattern = /(\[Evidence\s+\d+\]|\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_)/gi;
  const parts = normalized.split(pattern);

  return parts.map((part, index) => {
    if (!part) return null;
    const key = `${keyPrefix}-${index}`;

    const evidenceMatch = part.match(/^\[Evidence\s+(\d+)\]$/i);
    if (evidenceMatch) {
      const source = sources[Number(evidenceMatch[1]) - 1];
      return (
        <button
          key={key}
          type="button"
          onClick={() => source && onEvidenceClick?.(source)}
          disabled={!source || !onEvidenceClick}
          title={source ? `Open ${source.filename}` : "Source details unavailable"}
          aria-label={source ? `Open source ${source.filename}` : part}
          style={{
            display: "inline-flex",
            alignItems: "center",
            verticalAlign: "baseline",
            margin: "0 2px",
            padding: "2px 7px",
            borderRadius: "6px",
            border: "1px solid rgba(105, 190, 169, 0.28)",
            background: "rgba(105, 190, 169, 0.10)",
            color: "#9bd6c5",
            fontSize: "0.78em",
            fontWeight: 650,
            lineHeight: 1.5,
            cursor: source && onEvidenceClick ? "pointer" : "default",
          }}
        >
          {`Evidence ${evidenceMatch[1]}`}
          <span aria-hidden="true" style={{ marginLeft: "4px", fontSize: "0.9em" }}>↗</span>
        </button>
      );
    }

    if (
      (part.startsWith("**") && part.endsWith("**")) ||
      (part.startsWith("__") && part.endsWith("__"))
    ) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (
      (part.startsWith("*") && part.endsWith("*")) ||
      (part.startsWith("_") && part.endsWith("_"))
    ) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

function splitMarkdownTableRow(line: string): string[] {
  const normalized = normalizeMarkdown(line.trim());
  const withoutOuterPipes = normalized.replace(/^\|/, "").replace(/\|$/, "");
  return withoutOuterPipes.split("|").map((cell) => cell.trim());
}

function isMarkdownTableDivider(line: string): boolean {
  const cells = splitMarkdownTableRow(line);
  return (
    cells.length > 0 &&
    cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")))
  );
}

function renderAnswerContent(
  text: string,
  sources: AskSource[] = [],
  onEvidenceClick?: (source: AskSource) => void
) {
  const lines = normalizeMarkdown(text).replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const trimmed = lines[index].trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    // Render evidence references as compact citation cards instead of plain bullets.
    if (/^(?:#{1,3}\s*)?(?:references|sources)\s*:?$/i.test(trimmed)) {
      index += 1;
      const references: string[] = [];
      while (index < lines.length) {
        const referenceLine = lines[index].trim();
        if (!referenceLine) {
          if (references.length > 0) {
            index += 1;
            break;
          }
          index += 1;
          continue;
        }
        const bullet = referenceLine.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
        if (bullet) {
          references.push(bullet[1]);
          index += 1;
          continue;
        }
        // Some model responses wrap a citation onto a second line.
        if (references.length > 0 && !/^(?:#{1,3}\s|\|)/.test(referenceLine)) {
          references[references.length - 1] += ` ${referenceLine}`;
          index += 1;
          continue;
        }
        break;
      }

      blocks.push(
        <section
          className="answer-reference-list"
          key={`references-${index}`}
          style={{
            display: "grid",
            gap: "9px",
            margin: "12px 0 16px",
          }}
        >
          {references.map((reference, referenceIndex) => {
            const match = reference.match(/^\\[?Evidence\\s+(\\d+)\\]?\\s*(?:\\(PDF page\\s+\\d+\\))?\\s*:?\\s*(.*)$/i);
            const evidenceNumber = match?.[1] ?? String(referenceIndex + 1);
            const sourceIndex = Math.max(0, Number(evidenceNumber) - 1);
            const source = sources[sourceIndex] as
              | (AskSource & { page_number?: number | null })
              | undefined;
            // The page and filename come from backend source metadata, never model prose.
            const metadataFilename = source?.filename?.trim();
            const modelDescription = (match?.[2] || reference)
              .replace(/\\s*\\(PDF page\\s+\\d+\\)/gi, "")
              .trim();
            const description = metadataFilename || modelDescription || "Source document";
            const pageNumber = source?.page_number;
            return (
              <button
                type="button"
                className="answer-reference-card"
                key={`reference-${referenceIndex}`}
                onClick={() => source && onEvidenceClick?.(source)}
                disabled={!source || !onEvidenceClick}
                title={source ? `Open ${source.filename}` : "Source details unavailable"}
                style={{
                  width: "100%",
                  textAlign: "left",
                  color: "inherit",
                  cursor: source && onEvidenceClick ? "pointer" : "default",
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  padding: "11px 13px",
                  border: "1px solid rgba(126, 159, 166, 0.19)",
                  borderRadius: "10px",
                  background: "linear-gradient(110deg, rgba(19, 39, 43, 0.72), rgba(15, 22, 31, 0.92))",
                  boxShadow: "inset 3px 0 0 rgba(105, 190, 169, 0.72)",
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    display: "grid",
                    placeItems: "center",
                    flex: "0 0 34px",
                    width: "34px",
                    height: "34px",
                    borderRadius: "9px",
                    color: "#9bd6c5",
                    background: "rgba(105, 190, 169, 0.12)",
                    border: "1px solid rgba(105, 190, 169, 0.2)",
                    fontSize: "15px",
                  }}
                >
                  ▤
                </span>
                <span style={{ display: "grid", gap: "3px", minWidth: 0, flex: 1 }}>
                  <span style={{ color: "#dce6e9", fontSize: "0.88em", lineHeight: 1.45, overflowWrap: "anywhere" }}>
                    {metadataFilename || renderInlineMarkdown(description, `reference-description-${referenceIndex}`, sources, onEvidenceClick)}
                  </span>
                  <span style={{ color: "#82969e", fontSize: "0.72em", letterSpacing: "0.035em" }}>
                    EVIDENCE {evidenceNumber}
                  </span>
                </span>
                {pageNumber != null && (
                  <span
                    style={{
                      flex: "0 0 auto",
                      padding: "5px 8px",
                      borderRadius: "6px",
                      color: "#a9cfc6",
                      background: "rgba(105, 190, 169, 0.09)",
                      border: "1px solid rgba(105, 190, 169, 0.16)",
                      fontSize: "0.72em",
                      whiteSpace: "nowrap",
                    }}
                  >
                    PAGE {pageNumber}
                  </span>
                )}
              </button>
            );
          })}
        </section>
      );
      continue;
    }

    // Markdown table: a header row followed by a separator row.
    if (
      trimmed.includes("|") &&
      index + 1 < lines.length &&
      isMarkdownTableDivider(lines[index + 1])
    ) {
      const headers = splitMarkdownTableRow(lines[index]);
      index += 2;
      const rows: string[][] = [];

      while (index < lines.length && lines[index].trim().includes("|")) {
        const row = splitMarkdownTableRow(lines[index]);
        if (row.length > 0) rows.push(row);
        index += 1;
      }

      blocks.push(
        <div
          className="answer-table-wrap"
          key={`table-${index}`}
          style={{
            width: "100%",
            overflowX: "auto",
            margin: "16px 0",
            border: "1px solid rgba(133, 153, 176, 0.18)",
            borderRadius: "11px",
            background: "#0d131b",
            boxShadow: "0 8px 24px rgba(0, 0, 0, 0.14)",
          }}
        >
          <table
            className="answer-table"
            style={{
              width: "100%",
              minWidth: "520px",
              borderCollapse: "separate",
              borderSpacing: 0,
              fontSize: "0.9em",
              lineHeight: 1.55,
              textAlign: "left",
              color: "#d4dce6",
            }}
          >
            <thead>
              <tr>
                {headers.map((header, headerIndex) => (
                  <th
                    key={`head-${headerIndex}`}
                    style={{
                      padding: "12px 14px",
                      borderBottom: "1px solid rgba(133, 153, 176, 0.22)",
                      borderRight: headerIndex < headers.length - 1
                        ? "1px solid rgba(133, 153, 176, 0.14)"
                        : "none",
                      fontWeight: 650,
                      fontSize: "0.82em",
                      letterSpacing: "0.025em",
                      color: "#9eafc2",
                      background: "#18232f",
                      whiteSpace: "normal",
                    }}
                  >
                    {renderInlineMarkdown(header, `table-head-${index}-${headerIndex}`, sources, onEvidenceClick)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {headers.map((_, cellIndex) => (
                    <td
                      key={`cell-${rowIndex}-${cellIndex}`}
                      style={{
                        padding: "12px 14px",
                        borderBottom: rowIndex < rows.length - 1
                          ? "1px solid rgba(133, 153, 176, 0.13)"
                          : "none",
                        borderRight: cellIndex < headers.length - 1
                          ? "1px solid rgba(133, 153, 176, 0.11)"
                          : "none",
                        verticalAlign: "top",
                        background: rowIndex % 2 === 0 ? "#101821" : "#0d151e",
                        color: cellIndex === 0 ? "#dce7ef" : "#c3ceda",
                        fontWeight: cellIndex === 0 ? 600 : 400,
                      }}
                    >
                      {renderInlineMarkdown(
                        row[cellIndex] ?? "",
                        `table-cell-${index}-${rowIndex}-${cellIndex}`
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Headings.
    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const content = renderInlineMarkdown(heading[2], `heading-${index}`, sources, onEvidenceClick);
      blocks.push(
        level === 1 ? <h3 key={index}>{content}</h3> :
        level === 2 ? <h4 key={index}>{content}</h4> :
        <h5 key={index}>{content}</h5>
      );
      index += 1;
      continue;
    }

    // Consecutive bullet or numbered-list items.
    const listMatch = trimmed.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (listMatch) {
      const items: { marker: string; content: string }[] = [];
      while (index < lines.length) {
        const match = lines[index].trim().match(/^(?:([-*•])|(\d+[.)]))\s+(.+)$/);
        if (!match) break;
        items.push({
          marker: match[2] ?? "•",
          content: match[3],
        });
        index += 1;
      }

      const ordered = /^\d/.test(items[0]?.marker ?? "");
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag className="answer-markdown-list" key={`list-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>
              {renderInlineMarkdown(item.content, `list-${index}-${itemIndex}`, sources, onEvidenceClick)}
            </li>
          ))}
        </ListTag>
      );
      continue;
    }

    // Join wrapped plain-text lines into a single paragraph.
    const paragraphLines = [trimmed];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,3})\s+/.test(lines[index].trim()) &&
      !/^(?:[-*•]|\d+[.)])\s+/.test(lines[index].trim()) &&
      !(
        lines[index].trim().includes("|") &&
        index + 1 < lines.length &&
        isMarkdownTableDivider(lines[index + 1])
      )
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }

    blocks.push(
      <p key={`paragraph-${index}`}>
        {renderInlineMarkdown(paragraphLines.join(" "), `paragraph-${index}`, sources, onEvidenceClick)}
      </p>
    );
  }

  return blocks;
}

/* --------------------------------------------------
   Animated answer
   The completion callback stops the three dots.
\-------------------------------------------------- */
function AnimatedAnswer({
  content,
  sources,
  onEvidenceClick,
  animate,
  onTypingComplete,
}: {
  content: string;
  sources: AskSource[];
  onEvidenceClick: (source: AskSource) => void;
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
      {renderAnswerContent(visibleText, sources, onEvidenceClick)}
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
  const [sourcePageCount, setSourcePageCount] = useState<number | null>(null);
  const [sourcePageText, setSourcePageText] = useState("");
  const [sourcePageLoading, setSourcePageLoading] = useState(false);
  const [sourcePageError, setSourcePageError] = useState("");
  const [pdfPageCount, setPdfPageCount] = useState<number | null>(null);
  const [pdfLoading, setPdfLoading] = useState(true);
  const [pdfError, setPdfError] = useState("");
  const pdfViewerRef = useRef<HTMLDivElement>(null);
  const sourceHighlightRef = useRef<HTMLDivElement>(null);
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
  useEffect(() => {
    if (!selectedSource) {
      setSourcePageCount(null);
      return;
    }
    let cancelled = false;
    getDocuments()
      .then((items) => {
        if (cancelled) return;
        const document = items.find(
          (item) => item.document_id === selectedSource.document_id
        );
        setSourcePageCount(
          typeof document?.pages === "number" ? document.pages : null
        );
      })
      .catch(() => {
        if (!cancelled) setSourcePageCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSource?.document_id]);
  useEffect(() => {
    setPdfLoading(Boolean(selectedSource));
    setPdfError("");
    setPdfPageCount(null);
    if (!selectedSource) {
      setSourcePageText("");
      setSourcePageError("");
      return;
    }

    const pageNumber =
      (selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1;
    const controller = new AbortController();
    setSourcePageLoading(true);
    setSourcePageError("");
    setSourcePageText("");

    fetch(
      `http://127.0.0.1:8000/api/documents/${encodeURIComponent(selectedSource.document_id)}/pages/${pageNumber}`,
      { signal: controller.signal }
    )
      .then(async (response) => {
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(
            typeof result.detail === "string"
              ? result.detail
              : "Could not load the extracted page text."
          );
        }
        return result as { text?: string };
      })
      .then((result) => setSourcePageText(result.text ?? ""))
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setSourcePageError(
          error instanceof Error ? error.message : "Could not load the extracted page text."
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourcePageLoading(false);
      });

    return () => controller.abort();
  }, [selectedSource?.document_id, (selectedSource as (AskSource & { page_number?: number | null }) | null)?.page_number]);

  useEffect(() => {
    if (!sourcePageText) return;
    const timer = window.setTimeout(() => {
      const highlightedPassage = sourceHighlightRef.current?.querySelector<HTMLElement>(
        '[data-source-passage-highlight="true"]'
      );
      highlightedPassage?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [sourcePageText, selectedSource?.passage]);

  // Draw highlight rectangles from the real PDF text geometry. CSS Custom
  // Highlight can misalign across PDF.js transformed spans, so use Range rects.
  useEffect(() => {
    const viewer = pdfViewerRef.current;
    if (!viewer || !selectedSource?.passage || pdfLoading) return;

    let overlayElements: HTMLDivElement[] = [];
    const timer = window.setTimeout(() => {
      const pageElement = viewer.querySelector<HTMLElement>(".react-pdf__Page");
      const textLayer = viewer.querySelector<HTMLElement>(".react-pdf__Page__textContent");
      if (!pageElement || !textLayer) return;

      const walker = document.createTreeWalker(textLayer, NodeFilter.SHOW_TEXT);
      const positions: Array<{ node: Text; offset: number }> = [];
      let normalizedPage = "";
      let previousWasWhitespace = true;
      let current: Node | null;

      while ((current = walker.nextNode())) {
        const node = current as Text;
        for (let offset = 0; offset < node.data.length; offset += 1) {
          const character = node.data[offset];
          if (/\s/.test(character)) {
            if (!previousWasWhitespace) {
              normalizedPage += " ";
              positions.push({ node, offset });
            }
            previousWasWhitespace = true;
          } else {
            normalizedPage += character.toLocaleLowerCase();
            positions.push({ node, offset });
            previousWasWhitespace = false;
          }
        }
      }

      const normalized = (value: string) =>
        value.toLocaleLowerCase().replace(/\s+/g, " ").trim();
      normalizedPage = normalized(normalizedPage);
      while (positions.length && /\s/.test(positions[0].node.data[positions[0].offset])) positions.shift();
      while (positions.length && /\s/.test(positions[positions.length - 1].node.data[positions[positions.length - 1].offset])) positions.pop();

      const passage = selectedSource.passage;
      const candidates = passage
        .split(/(?<=[.!?])\s+|\n+/)
        .map(normalized)
        .filter((part) => part.length >= 28)
        .sort((a, b) => b.length - a.length);

      let matchedText = "";
      let matchAt = -1;
      for (const candidate of candidates) {
        const index = normalizedPage.indexOf(candidate);
        if (index >= 0) {
          matchedText = candidate;
          matchAt = index;
          break;
        }
      }

      // If extraction punctuation/spacing differs, use a long distinctive
      // sequence of words rather than highlighting a short generic phrase.
      if (matchAt < 0) {
        const words = normalized(passage).split(" ").filter(Boolean);
        for (let size = Math.min(18, words.length); size >= 7 && matchAt < 0; size -= 1) {
          for (let offset = 0; offset <= words.length - size; offset += 1) {
            const candidate = words.slice(offset, offset + size).join(" ");
            if (candidate.length < 35) continue;
            const found = normalizedPage.indexOf(candidate);
            if (found >= 0) {
              matchedText = candidate;
              matchAt = found;
              break;
            }
          }
        }
      }

      if (matchAt < 0 || !matchedText) return;
      const startPosition = positions[matchAt];
      const endPosition = positions[matchAt + matchedText.length - 1];
      if (!startPosition || !endPosition) return;

      const range = document.createRange();
      range.setStart(startPosition.node, startPosition.offset);
      range.setEnd(endPosition.node, endPosition.offset + 1);
      const pageRect = pageElement.getBoundingClientRect();
      const rects = Array.from(range.getClientRects()).filter(
        (rect) => rect.width > 0 && rect.height > 0
      );

      // One overlay per rendered text line. Coordinates are relative to the
      // PDF page itself, so the marks remain aligned at any scroll position.
      for (const rect of rects) {
        const overlay = document.createElement("div");
        overlay.setAttribute("data-silvera-pdf-highlight", "true");
        Object.assign(overlay.style, {
          position: "absolute",
          left: `${rect.left - pageRect.left}px`,
          top: `${rect.top - pageRect.top}px`,
          width: `${rect.width}px`,
          height: `${rect.height}px`,
          background: "rgba(105, 190, 169, 0.38)",
          borderBottom: "2px solid rgba(65, 160, 137, 0.95)",
          borderRadius: "2px",
          pointerEvents: "none",
          zIndex: "8",
          boxSizing: "border-box",
        });
        pageElement.appendChild(overlay);
        overlayElements.push(overlay);
      }

      const firstRect = rects[0];
      if (firstRect) {
        viewer.scrollTo({
          top: viewer.scrollTop + firstRect.top - viewer.getBoundingClientRect().top - 90,
          behavior: "smooth",
        });
      }
    }, 450);

    return () => {
      window.clearTimeout(timer);
      overlayElements.forEach((element) => element.remove());
    };
  }, [
    selectedSource?.document_id,
    (selectedSource as (AskSource & { page_number?: number | null }) | null)?.page_number,
    selectedSource?.passage,
    pdfLoading,
  ]);

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
                                  sources={message.sources ?? []}
                                  onEvidenceClick={setSelectedSource}
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
                                              {(source as AskSource & { page_number?: number | null }).page_number != null
                                                ? `Page ${(source as AskSource & { page_number?: number | null }).page_number} · `
                                                : ""}
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
        <div className="source-modal-backdrop" onClick={() => setSelectedSource(null)} role="presentation">
          <section
            className="source-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-modal-title"
            onClick={(event) => event.stopPropagation()}
            style={{ width: "min(1120px, calc(100vw - 40px))", maxWidth: "1120px", maxHeight: "90vh", display: "flex", flexDirection: "column", overflow: "hidden" }}
          >
            <div className="source-modal-header">
              <div className="source-modal-title-icon">▤</div>
              <div className="source-modal-heading">
                <span className="answer-kicker">SOURCE DOCUMENT</span>
                <h3 id="source-modal-title">Retrieved passage</h3>
              </div>
              <button type="button" className="source-done-button" onClick={() => setSelectedSource(null)} aria-label="Close source viewer" style={{ marginLeft: "auto" }}>✕</button>
            </div>

            <div className="source-modal-file">
              <div className="source-modal-file-info">
                <span className="source-modal-filename">{selectedSource.filename}</span>
                <span className="source-modal-subtitle">
                  PDF page {(selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1}
                  {" · "}Retrieved from your local knowledge base
                </span>
              </div>
            </div>

            <style>{`
              .silvera-pdf-document { display: flex; justify-content: center; min-width: 0; }
              .silvera-pdf-document .react-pdf__Page { position: relative; margin: 0 auto 18px; background: #fff; box-shadow: 0 8px 28px rgba(0,0,0,.32); }
              .silvera-pdf-document .react-pdf__Page__canvas { display: block; max-width: 100%; }
              .silvera-pdf-document .react-pdf__Page__textContent { user-select: text; }
              .silvera-pdf-document .react-pdf__Page__textContent span { cursor: text; }
              @media (max-width: 760px) {
                .source-modal > div[style*="grid-template-columns"] { grid-template-columns: minmax(0,1fr) !important; overflow-y: auto !important; }
                .source-modal .silvera-pdf-viewer { min-height: 360px !important; }
              }
            `}</style>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(250px, 0.8fr) minmax(0, 1.7fr)", gap: "14px", minHeight: 0, flex: 1, padding: "14px 18px", overflow: "hidden" }}>
              <aside style={{ minWidth: 0, overflowY: "auto", border: "1px solid rgba(105, 190, 169, 0.22)", borderRadius: "10px", background: "rgba(105, 190, 169, 0.055)", padding: "16px" }}>
                <span className="answer-kicker">RETRIEVED PASSAGE</span>
                <p className="passage-content" style={{ whiteSpace: "pre-wrap", lineHeight: 1.75, overflowWrap: "anywhere", marginTop: "12px" }}>
                  {selectedSource.passage}
                </p>
                {selectedSource.similarity != null && (
                  <div className="source-relevance">
                    <span>Semantic similarity</span>
                    <span>{(selectedSource.similarity * 100).toFixed(1)}%</span>
                  </div>
                )}
                <p style={{ color: "#91a6ad", fontSize: "0.78em", marginTop: "14px" }}>
                  Exact text passage retrieved for this answer. Inspect the PDF alongside it for original context.
                </p>
              </aside>

              <div style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: "420px", border: "1px solid rgba(133, 153, 176, 0.18)", borderRadius: "10px", overflow: "hidden", background: "#0b1118" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", padding: "9px 12px", borderBottom: "1px solid rgba(133, 153, 176, 0.16)", color: "#cbd6df", fontSize: "0.82em" }}>
                  <span>ORIGINAL PDF DOCUMENT</span>
                  <div style={{ display: "flex", alignItems: "center", gap: "9px" }}>
                    <button
                      type="button"
                      className="source-done-button"
                      disabled={((selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1) <= 1}
                      onClick={() => {
                        const currentPage = (selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1;
                        setSelectedSource({ ...selectedSource, page_number: Math.max(1, currentPage - 1) } as AskSource);
                      }}
                    >←</button>
                    <span>
                      Page {(selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1}
                      {sourcePageCount || pdfPageCount ? ` of ${sourcePageCount ?? pdfPageCount}` : ""}
                    </span>
                    <button
                      type="button"
                      className="source-done-button"
                      disabled={(sourcePageCount ?? pdfPageCount) != null && ((selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1) >= (sourcePageCount ?? pdfPageCount ?? 1)}
                      onClick={() => {
                        const currentPage = (selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1;
                        setSelectedSource({ ...selectedSource, page_number: sourcePageCount ? Math.min(sourcePageCount, currentPage + 1) : currentPage + 1 } as AskSource);
                      }}
                    >→</button>
                  </div>
                </div>
                <div
                  ref={pdfViewerRef}
                  className="silvera-pdf-viewer"
                  style={{ flex: 1, minHeight: "420px", overflow: "auto", padding: "18px", background: "#202833" }}
                >
                  {pdfLoading && (
                    <p style={{ color: "#b8c5d2", textAlign: "center", padding: "24px" }}>
                      Loading original PDF...
                    </p>
                  )}
                  {pdfError && (
                    <p role="alert" style={{ color: "#e58c8c", padding: "18px" }}>
                      {pdfError}
                    </p>
                  )}
                  <PdfDocument
                    key={selectedSource.document_id}
                    file={getOriginalDocumentUrl(selectedSource.document_id)}
                    onLoadSuccess={({ numPages }) => {
                      setPdfPageCount(numPages);
                      setPdfLoading(false);
                      setPdfError("");
                    }}
                    onLoadError={(error) => {
                      setPdfLoading(false);
                      setPdfError(error instanceof Error ? error.message : "Could not render this PDF.");
                    }}
                    loading={null}
                    error={null}
                    className="silvera-pdf-document"
                  >
                    <PdfPage
                      key={`${selectedSource.document_id}-${(selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1}`}
                      pageNumber={(selectedSource as AskSource & { page_number?: number | null }).page_number ?? 1}
                      renderTextLayer
                      renderAnnotationLayer
                      onRenderSuccess={() => setPdfLoading(false)}
                      width={Math.max(280, Math.min(760, (typeof window !== "undefined" ? window.innerWidth : 1200) * 0.52))}
                    />
                  </PdfDocument>
                </div>
              </div>
            </div>

            <div className="source-modal-footer">
              <span>◇ Stored and processed locally</span>
              <div className="source-modal-actions">
                <button className="source-open-original" onClick={openOriginalDocument} type="button">Open original ↗</button>
                <button className="source-done-button" onClick={() => setSelectedSource(null)} type="button">Done</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
export default App;
