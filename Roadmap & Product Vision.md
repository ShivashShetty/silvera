# Silvera --- Product Vision, Capabilities & Development Roadmap

**Product identity:** Secure Enterprise Intelligence\
**Tagline:** Secure intelligence for enterprise data.\
**Project type:** Enterprise AI platform · Agentic RAG ·
Natural-language analytics · Data engineering · LLMOps\
**Status:** Active prototype / local development\
**Repository:** https://github.com/ShivashShetty/silvera

> **Vision:** Build a self-hostable enterprise intelligence platform
> that lets people ask questions across company documents and structured
> business data in natural language, receive evidence-backed answers,
> explore results, and understand how the system reached its
> conclusions.

This document consolidates the original planning document with the
current Silvera implementation. It is the living product roadmap:
features are classified as **Implemented**, **In progress / verify**,
**Planned**, or **Future / optional** so that the vision is ambitious
without confusing planned functionality with working code.

------------------------------------------------------------------------

## 1. Executive summary

Organizations spread information across PDFs, spreadsheets, databases,
reports, internal knowledge bases, tickets, and APIs. Finding an answer
often requires an employee to know where the data lives, understand its
structure, and manually combine information from multiple systems.

Silvera aims to provide one secure interface for that work. A user
should be able to ask:

-   "What is our refund policy?"
-   "What was total revenue in this financial year?"
-   "Which customers generated the most revenue last quarter?"
-   "Show monthly revenue and compare it with the previous year."
-   "Why did revenue fall in Q3?"
-   "What does our policy say about refunds, and do the sales records
    show an increase in refund requests?"
-   "Generate a report and show me the evidence behind each conclusion."

Silvera will route each question to the appropriate capability: document
retrieval, structured-data querying, analytics, or a coordinated
workflow across several of them. It should explain results, cite the
evidence or data used, enforce permissions, and record enough
operational detail to make failures diagnosable.

**The goal is not simply to build a chatbot. The goal is to build an
end-to-end enterprise AI system.**

## 2. Product principles

1.  **Evidence over confidence:** Answers should be grounded in
    retrieved passages or actual query results. The system should say
    when available evidence is insufficient.
2.  **Security by design:** Authorization must be enforced before
    sensitive data reaches an LLM, not merely described in a prompt.
3.  **Local-first development:** Begin with local and open-source
    components where practical, given the current development hardware.
    Cloud and hosted model providers can be optional later.
4.  **Human-verifiable results:** Show sources, SQL, filters,
    calculation assumptions, and timestamps where useful.
5.  **Safe automation:** Generated SQL and agent tool calls must be
    validated and constrained. Read-only database access is the initial
    default.
6.  **Modular architecture:** Keep document intelligence, database
    intelligence, orchestration, security, evaluation, and UI loosely
    coupled.
7.  **Measure quality:** Evaluate retrieval, answer grounding,
    correctness, latency, reliability, and resource usage rather than
    assuming a model is good.
8.  **Incremental delivery:** Build and test a usable vertical slice at
    each phase; avoid adding infrastructure before the product needs it.
9.  **Honest status:** A feature is not complete until it has
    implementation and tests. Example metrics in mockups are not real
    performance claims.

## 3. Current implementation snapshot

This section describes the implementation recorded during the current
project work. Verify each item against the current repository before
treating it as a release guarantee.

### Implemented foundation

-   React + Vite + TypeScript frontend.
-   Python + FastAPI backend.
-   Local PDF upload with a 10 MB limit.
-   PDF text extraction using `pypdf`.
-   Text and metadata storage in the backend upload directory.
-   Semantic indexing using ChromaDB and
    `sentence-transformers/all-MiniLM-L6-v2`.
-   Local answer generation using Ollama with `llama3.2:3b`.
-   Keyword search and semantic search endpoints.
-   Document listing and deletion endpoints.
-   A question-answer endpoint that retrieves chunks and returns an
    answer with source passages.
-   A UI for the Intelligence and Documents areas,
    uploading/listing/deleting documents, displaying answers and opening
    a source modal.
-   An endpoint that serves Silvera's stored original PDF copy in the
    browser.
-   Local development and API testing through the Vite development
    server and FastAPI docs.

### Current local setup

-   Project root: `D:\Projects\silvera`
-   Backend: `D:\Projects\silvera\backend`
-   Frontend: `D:\Projects\silvera\frontend`
-   Frontend: `npm run dev` (typically `http://localhost:5173`)
-   Backend: activate `backend\.venv`, then run
    `uvicorn main:app --reload` (typically `http://127.0.0.1:8000`)
-   Ollama model: `llama3.2:3b`
-   Vector store: ChromaDB
-   Embeddings: `sentence-transformers/all-MiniLM-L6-v2`

### Known boundaries of the current prototype

-   The current ingestion flow is PDF-focused; DOCX, CSV, and Excel
    ingestion are planned, not assumed implemented.
-   Natural-language-to-SQL, database connectors, multi-agent
    orchestration, multi-user authentication, RBAC, audit dashboards,
    and cloud deployment are roadmap items unless subsequently
    implemented.
-   Semantic retrieval and local answers need systematic quality tests
    before claiming enterprise reliability.
-   The current local UI and API are a development prototype, not yet a
    hardened production service.

## 4. Product capability map

### 4.1 Knowledge Intelligence --- document question answering

**Purpose:** Answer questions from internal documents and show the
supporting passages.

Planned end-to-end flow:

1.  Upload and validate a file.
2.  Parse text and retain document/page metadata.
3.  Clean text and split it into meaningful chunks.
4.  Generate embeddings and index chunks.
5.  Retrieve relevant passages for a question.
6.  Optionally combine semantic and keyword search and rerank
    candidates.
7.  Generate an answer using retrieved evidence.
8.  Display citations, document names, and page references where
    available.
9.  Abstain or ask a clarifying question when evidence is insufficient.

**Initial file support:** PDF.\
**Planned expansion:** DOCX, TXT, CSV, XLSX, and eventually other
approved enterprise sources.

**Capabilities to build:** - Hybrid keyword + vector search. - Metadata
filtering by document, department, date, and access level. - Reranking
to improve relevance. - Page-level citations and passage previews. -
Document versioning, re-indexing, deduplication, and processing
status. - Better extraction for tables and scanned PDFs (OCR as a later
optional component). - Source-aware conversation follow-ups. -
User-visible explanation when a document cannot be parsed or has not
been indexed.

### 4.2 Data Intelligence --- natural language to SQL

**Purpose:** Let users ask business questions in plain English and
receive query-backed results without needing to write SQL themselves.

Example:

> "What was our total revenue for this financial year?"

Expected workflow:

1.  Identify the intended metric, period, and any ambiguity.
2.  Resolve business definitions such as gross versus net revenue,
    refunds, tax, currency, and fiscal-year boundaries.
3.  Inspect the permitted database schema and relevant table/column
    descriptions.
4.  Generate a SQL query for the selected database dialect.
5.  Validate the query and enforce user/table/column permissions.
6.  Execute using a restricted read-only database account, timeouts, and
    result limits.
7.  Validate and format the result.
8.  Explain the answer and show the SQL, assumptions, and data source.
9.  Offer relevant follow-up analysis or a chart when useful.

Example SQL (illustrative schema only):

``` sql
SELECT SUM(amount) AS total_revenue
FROM sales
WHERE sale_date >= :financial_year_start
  AND sale_date < :next_financial_year_start;
```

The actual table, column names, currency, and financial-year dates must
come from the connected schema and user/organization configuration.
Silvera must not invent these details.

**Planned capabilities:** - SQLite connector first for lightweight local
development. - Schema discovery and safe schema summaries. - PostgreSQL
connector after the initial SQL workflow is reliable. - SQL generation
for supported dialects. - Query preview and "show SQL" view. - Read-only
query validation and execution. - Table/column allowlists and permission
checks. - Parameterized values where supported. - Query timeout, row
cap, and resource limits. - Clear handling of invalid SQL, ambiguous
requests, missing data, and empty results. - Saved queries and query
history (optional early extension). - SQL correctness test set with
expected results.

**Initial safety policy:** Permit only approved read-only queries. Block
data modification and schema modification statements such as `INSERT`,
`UPDATE`, `DELETE`, `DROP`, `ALTER`, and `TRUNCATE`. Do not rely only on
checking the first SQL keyword; use a parser/allowlist where practical,
enforce a read-only database account, and apply permissions at the
database layer.

### 4.3 Natural-language analytics and visualization

After SQL execution, Silvera should choose a useful presentation based
on the result and question:

-   KPI cards for totals and single metrics.
-   Tables for detailed rows.
-   Bar charts for category comparisons.
-   Line charts for time series.
-   Pie/donut charts only when they communicate proportions clearly.
-   Period-over-period comparisons.
-   Breakdown by permitted dimensions such as product, region, or
    customer.
-   Plain-language explanations of trends and notable differences.

Every visualization must be based on returned data, not values invented
by the model. Show the period, units, filters, and relevant assumptions.
Avoid suggesting causation from correlation alone.

### 4.4 Cross-source intelligence

**Purpose:** Combine documents and structured data for questions that
cannot be answered well by either source alone.

Example:

> "Why did revenue fall in Q3, and what do the business reports say
> about it?"

Possible workflow: 1. SQL agent retrieves and validates revenue figures.
2. RAG agent retrieves relevant business reports and documentation. 3.
Analytics component compares periods and identifies supported changes.
4. Orchestrator combines findings while keeping their evidence separate.
5. Final answer labels measured facts, document statements, and
hypotheses distinctly, with citations and query details.

This is a major differentiator but should come after the document and
SQL paths are independently reliable.

### 4.5 Specialized agents and orchestration

Planned agents: - **RAG agent:** document-based questions and
citations. - **SQL agent:** schema-aware SQL generation, validation, and
execution. - **Analytics agent:** calculations, comparisons, and result
interpretation. - **Research agent:** gathers evidence from multiple
permitted sources. - **Report agent:** produces structured summaries and
reports. - **Security/policy layer:** evaluates tool permissions and
request constraints. Prefer deterministic authorization controls over
relying on an LLM "security agent" alone.

The orchestrator classifies or routes each request to the appropriate
capability. Start with a simple, inspectable routing function; introduce
more complex agent planning only when real workflows require it. Record
the chosen route and tools used.

### 4.6 Reports and exports

Planned: - Generate a structured business report from approved document
and database evidence. - Include executive summary, findings,
methodology/assumptions, charts/tables, and source references. - Export
to PDF/CSV and later DOCX or XLSX where useful. - Distinguish facts,
interpretations, and recommendations. - Provide a preview before export
and never silently omit limitations.

### 4.7 Data ingestion and engineering

Planned ingestion pipeline:

`Source → Ingest → Validate → Parse/Transform → Quality checks → Store/index → Monitor`

Potential source types: - PDFs and office documents. - CSV and Excel. -
SQLite and PostgreSQL. - Internal APIs and knowledge bases after
connector security is designed. - Additional databases and enterprise
services as future plugins/connectors.

Planned capabilities: - Schema validation and schema-change detection. -
Missing-value, duplicate, invalid-type, and outlier checks. - Data
profiling and quality reports. - Metadata catalog and source lineage. -
Incremental ingestion and scheduled refresh. - Retry handling and clear
pipeline status. - Deduplication and idempotent reprocessing.

Apache Airflow and dbt are possible later additions, not requirements
for the first working version. Begin with lightweight Python jobs and
add orchestration tools only when ingestion complexity justifies them.

## 5. Security, privacy, and governance

Security is a core product requirement, not a final polish phase.

### Authentication and authorization

-   User registration/login for a multi-user deployment.
-   Secure password hashing and session/token lifecycle.
-   Role-based access control (RBAC).
-   Initial roles may include Admin, Manager, Analyst, and Employee, but
    roles must be configurable to the deployment.
-   Enforce permissions for documents, database connections, tables,
    columns, and operations.
-   Apply document permissions before retrieved text is passed to the
    LLM.
-   Prevent a user from changing request parameters to access another
    user's resources.

### SQL and tool safety

-   Read-only database accounts by default.
-   SQL parser/validation, approved schema/table allowlists, timeouts,
    row limits, and query-cost controls.
-   Parameterized user values where possible.
-   Restrict agent tools to explicitly authorized operations.
-   Do not expose database credentials or secrets to the model or
    browser.
-   Keep tool execution separate from natural-language generation.

### Prompt injection and data leakage

-   Treat retrieved documents and database content as untrusted data,
    not system instructions.
-   Separate instructions from retrieved content.
-   Restrict tools independently of prompts.
-   Validate inputs and outputs where appropriate.
-   Test attempts to extract secrets, bypass permissions, or execute
    unsafe actions.
-   Do not assume a prompt-injection classifier alone can guarantee
    protection.

### Auditability

-   Record who performed an action, when, which source or tool was used,
    and whether it succeeded.
-   Avoid storing unnecessary sensitive data in logs.
-   Define retention and deletion policies.
-   Make deletion behavior explicit for original files, extracted text,
    chunks, embeddings, and derived records.

### Deployment security

-   Environment-based secrets, secure configuration, HTTPS in deployed
    environments, dependency updates, backups, and least-privilege
    service accounts.
-   Rate limits and request-size limits.
-   Security tests before external access or multi-user deployment.

## 6. Evaluation, reliability, and observability

Silvera must measure its quality instead of relying on impressive demos.

### Retrieval evaluation

-   Precision@K and Recall@K.
-   Mean Reciprocal Rank (MRR).
-   Relevance of retrieved context.
-   Correct document/page retrieval.

### Answer evaluation

-   Correctness against known answers.
-   Faithfulness/groundedness against retrieved evidence.
-   Citation correctness.
-   Answer relevance.
-   Abstention quality when evidence is missing.
-   Hallucination and unsupported-claim rate.

### Text-to-SQL evaluation

-   SQL syntax validity.
-   Execution success rate.
-   Result correctness against test cases.
-   Schema-linking accuracy.
-   Correct date and filter interpretation.
-   Safety rejection rate for prohibited queries.
-   Handling of ambiguous business definitions.

### System observability

Track real measured values such as: - Request latency and error rate. -
Retrieval latency and number of retrieved chunks. - Model and prompt
version. - Query route and tool outcomes. - SQL execution time and row
count. - Resource use on local hardware. - Hosted-model token/cost usage
if such providers are enabled.

Build a small evaluation dataset first. Metrics displayed in dashboards
must be computed from actual runs; any illustrative figures must be
clearly labelled as examples.

## 7. Conversation and user experience

Planned experience: - A unified natural-language workspace. - Separate
or clearly identifiable Knowledge and Data workflows. - Conversation
history and follow-up questions. - Visible citations and a way to
inspect original documents. - Generated SQL preview and query result
table. - Chart/table switching when appropriate. - Clear processing,
empty, error, and permission-denied states. - Document indexing and
ingestion status. - Search and filtering for documents and past
conversations. - Accessible keyboard navigation and responsive
layouts. - Consistent Silvera navy, silver, and slate visual palette.

Future UI possibilities: - Saved workspaces and reusable prompts. -
User-configurable dashboards. - Scheduled reports. - Collaborative
sharing with explicit permissions. - Admin console for users, sources,
policies, evaluations, and audit events.

## 8. Architecture and technology direction

### Current foundation

-   Frontend: React, TypeScript, Vite.
-   Backend: Python, FastAPI, Pydantic.
-   Local LLM runtime: Ollama (`llama3.2:3b` currently).
-   Embeddings: Sentence Transformers (`all-MiniLM-L6-v2`).
-   Vector storage: ChromaDB.
-   PDF extraction: `pypdf`.

### Candidate technologies (introduce only when needed)

-   Structured database: SQLite first, then PostgreSQL.
-   SQL layer: SQLAlchemy and/or a dedicated SQL parser/validator.
-   Visualization: a React chart library such as Recharts.
-   Testing: pytest and frontend/component tests; Playwright for
    end-to-end UI tests.
-   CI: GitHub Actions.
-   Packaging: Docker and Docker Compose when the local workflow is
    stable.
-   Data workflows: Pandas/Polars, with dbt or Airflow later if
    justified.
-   Observability: structured logs first; metrics/traces dashboards
    later.
-   Additional model providers: optional provider abstraction, with
    local Ollama as the initial path.

Avoid introducing PostgreSQL, Redis, Airflow, Prometheus, Grafana, or a
large agent framework simply to make the architecture look
enterprise-grade. Each dependency should solve a concrete need and
remain compatible with the available hardware.

### Logical architecture

``` text
                         Silvera Web UI
                              |
                         FastAPI API
                              |
                     Request / Policy Layer
                              |
                         Orchestrator
                  ____________|____________
                 |            |            |
             RAG Path      SQL Path    Other Tools
                 |            |            |
           Document Index  SQL Validator  Approved APIs
                 |            |            |
             Vector DB    Read-only DB     |
                 |            |            |
                 +------------+------------+
                              |
                     Evidence / Results
                              |
                  Answer + Sources + Metrics
```

## 9. Proposed data model

The final schema should evolve from actual workflows. Candidate entities
include:

-   `users`, `roles`, `user_roles`
-   `documents`, `document_versions`, `document_chunks`
-   `data_sources`, `database_connections`, `schema_metadata`
-   `conversations`, `messages`
-   `queries`, `query_runs`, `query_results_metadata`
-   `agent_runs`, `tool_runs`
-   `evaluation_cases`, `evaluation_runs`
-   `audit_logs`
-   `reports`, `scheduled_jobs` (later)

Do not store embeddings or large query result payloads in relational
tables by default if the vector store or file storage is more
appropriate. Never store raw credentials in ordinary records or logs.

## 10. Roadmap and acceptance criteria

The order below is a dependency-based roadmap, not a promise of fixed
calendar dates. Complete a phase when its acceptance criteria pass.

### Phase 0 --- Stabilize the prototype

**Goal:** Make the existing local document flow dependable.

Work: - Verify upload, extraction, indexing, list, search, ask, source
modal, original PDF, and deletion. - Check cleanup of PDF, extracted
text, metadata, and vectors on deletion or failed uploads. - Improve API
error messages and frontend loading/error states. - Add backend tests
for main endpoints. - Document setup and troubleshooting.

**Done when:** A fresh local setup can upload a test PDF, retrieve
relevant content, answer a supported question, show sources, open the
stored original, and delete all Silvera-managed artifacts without
errors.

### Phase 1 --- Reliable Knowledge Intelligence

**Goal:** Improve retrieval and answer trustworthiness.

Work: - Build a representative question/answer test set. - Test
questions that are answerable, unanswerable, ambiguous, and
multi-document. - Add hybrid search (keyword + vector) and evaluate
whether it improves results. - Improve chunking and preserve
page/document metadata. - Add reranking only if tests demonstrate a
benefit. - Enforce evidence-grounded answers and useful abstention. -
Improve citation display and source inspection.

**Done when:** Retrieval and answer quality are measured against a
baseline, regressions are caught by tests, and the system does not
confidently invent answers when evidence is missing.

### Phase 2 --- Data Intelligence MVP (Text-to-SQL)

**Goal:** Answer structured business questions safely.

Work: - Use a small, clearly documented sample sales database in
SQLite. - Create tables with realistic but fictional customers, orders,
products, dates, amounts, and refunds. - Discover schema and provide
only relevant metadata to the model. - Clarify financial-year dates and
business definitions. - Generate SQL, validate it, and execute with a
read-only connection. - Apply query timeout/row limits and return
structured results. - Display answer, table, SQL preview, and
assumptions. - Add positive, negative, ambiguous, and prohibited-query
tests.

**Done when:** Supported natural-language questions produce correct
results on the test database, SQL is inspectable, prohibited operations
are blocked, and invalid/ambiguous requests fail safely.

### Phase 3 --- Natural-language analytics

**Goal:** Turn query results into useful business insights.

Work: - Render KPI cards and data tables. - Add charts for time series
and category comparisons. - Support period comparisons and relevant
breakdowns. - Explain calculations, units, filters, and date ranges. -
Keep all displayed numbers tied to query results.

**Done when:** A set of analytics test questions produces correct
tables/charts with reproducible numbers and clear assumptions.

### Phase 4 --- Conversation and workflow continuity

**Goal:** Make follow-up questions practical.

Work: - Store conversation history. - Resolve references such as
"compare that with last year". - Preserve the active data source and
relevant filters. - Allow users to inspect previous answers, sources,
and generated SQL. - Avoid carrying forward assumptions when a new
question changes the context.

**Done when:** Follow-up scenarios pass tests without confusing metrics,
periods, sources, or permissions.

### Phase 5 --- Cross-source intelligence and reporting

**Goal:** Combine document evidence with database facts.

Work: - Introduce a simple orchestrator with transparent routing. -
Combine SQL results and RAG passages for explicitly cross-source
questions. - Separate measured facts, document claims, and model
interpretation. - Generate structured reports with citations and query
details. - Add export after report correctness is verified.

**Done when:** End-to-end scenarios can answer a cross-source question
and trace each major claim to a source passage or executed query.

### Phase 6 --- Security foundation

**Goal:** Make access controls enforceable before multi-user or
sensitive deployment.

Work: - Define a threat model and security boundaries. - Add
authentication when multi-user operation is introduced. - Implement RBAC
and source-level authorization. - Enforce document permissions before
retrieval and SQL permissions before execution. - Add prompt-injection
and data-leakage tests. - Implement audit events, secret management,
request limits, and deletion/retention rules.

**Done when:** Automated tests demonstrate that unauthorized users
cannot retrieve protected content, execute disallowed queries, or access
another user's resources.

### Phase 7 --- Evaluation and observability

**Goal:** Measure quality and diagnose failures.

Work: - Add retrieval, answer, citation, SQL-correctness, and safety
evaluation suites. - Record latency, failures, selected route, and
relevant resource metrics. - Version prompts and model configuration. -
Build a basic system-health view from real metrics. - Add regression
testing to development workflow.

**Done when:** A repeatable evaluation run produces a report, and the
team can trace a failed answer to retrieval, generation, SQL,
permission, or UI behavior.

### Phase 8 --- Ingestion and data engineering

**Goal:** Expand beyond PDF and manual uploads.

Work: - Add TXT and DOCX parsing, then CSV/XLSX ingestion. - Add
schema/data-quality checks for structured files. - Add deduplication,
versioning, re-indexing, and incremental refresh. - Introduce connector
interfaces and source metadata. - Add scheduled jobs only when there is
a real refresh requirement.

**Done when:** Each supported format has automated ingestion tests,
visible status, failure recovery, and documented limitations.

### Phase 9 --- Packaging, CI/CD, and deployment

**Goal:** Make setup reproducible and deployment safer.

Work: - Add CI checks for backend and frontend. - Add environment-based
configuration and secret handling. - Containerize stable components
where useful. - Document local installation, backups, upgrades, and
recovery. - Add HTTPS and production deployment configuration before
external access. - Test resource use and concurrent requests.

**Done when:** A clean environment can reproduce the documented
deployment and automated checks pass. Production claims require a
separate security and performance review.

## 11. Future expansion --- ideas, not MVP commitments

Silvera can grow into a broader enterprise platform. These are candidate
capabilities to prioritize based on user need, complexity, privacy, and
measurable value.

### Connectors and enterprise integration

-   Additional relational databases and warehouses.
-   Internal REST APIs and knowledge bases.
-   Business tools, ticketing systems, and document repositories.
-   Pluggable connectors with scoped credentials and health status.

### Advanced analytics

-   Metric definitions / semantic layer so "revenue" has a governed
    meaning.
-   Forecasting and anomaly detection, with uncertainty and evaluation.
-   Root-cause investigation workflows that propose hypotheses and test
    them against data.
-   Scheduled reports and threshold-based alerts.
-   Governed reusable datasets and metric catalogs.

### Enterprise knowledge management

-   OCR for scanned documents.
-   Version-aware policy comparison.
-   Document change summaries.
-   Knowledge freshness indicators and stale-source warnings.
-   Source ownership, retention labels, and approval workflows.

### Governance and administration

-   Microsoft Entra ID / SSO or OAuth where required.
-   Configurable roles and policies.
-   Audit search and export.
-   PII detection/redaction where appropriate.
-   Data retention, deletion, and legal-hold policies designed for the
    deployment's needs.
-   Admin controls for models, sources, and query policies.

### LLMOps and platform operations

-   Optional provider gateway for local and hosted models.
-   Prompt/model versioning and controlled rollout.
-   Cost and latency budgets for hosted providers.
-   Caching where safe and correct.
-   Model fallback behavior and health checks.
-   Evaluation-driven regression gates.

### Enterprise deployment options

-   Self-hosted single-user deployment.
-   Self-hosted multi-user deployment.
-   Containerized on-premises deployment.
-   Optional cloud deployment.
-   Tenant isolation if multi-tenant SaaS becomes an actual requirement.

### Other exploratory ideas

-   Natural-language generation of SQL views or dashboards only with
    explicit approval and a safe review workflow.
-   A controlled agent/tool marketplace.
-   Workflow automation with approval gates.
-   Collaboration and shared analysis workspaces.
-   Plugin/connector SDK.

These are exploratory. Do not implement them all by default. The product
should remain coherent, secure, maintainable, and feasible to develop
incrementally.

## 12. Testing strategy

Every major capability needs tests at multiple levels:

-   **Unit tests:** parsers, chunking, query routing, SQL policy
    validation, data formatting.
-   **Integration tests:** upload → index → retrieve → answer; question
    → SQL → execute → result.
-   **End-to-end tests:** main user journeys in the browser.
-   **AI quality tests:** fixed questions and expected evidence/results.
-   **Security tests:** unauthorized access, malicious document
    instructions, unsafe SQL, resource abuse.
-   **Performance tests:** latency and memory on the target machine,
    then concurrency on deployment hardware.
-   **Regression tests:** rerun after changing prompts, models,
    chunking, retrieval, or SQL logic.

Use fictional/synthetic business data for demonstrations. Do not put
real confidential enterprise data in a demo dataset or public
repository.

## 13. Definition of done for Silvera

A feature is considered complete only when: - It works through the UI
and API. - Input validation and error handling are present. -
Authorization and safety rules are enforced where relevant. - Tests
cover normal, edge, and failure cases. - Its limitations are
documented. - Metrics are real and reproducible. - It fits the modular
architecture and does not break existing flows.

The overall platform should not be called production-ready solely
because it runs locally or produces plausible answers.

## 14. Immediate next actions

Recommended next sequence:

1.  Verify the current prototype from a clean start.
2.  Add regression tests for document upload, search, answer generation,
    source viewing, and deletion.
3.  Build a small evaluation set for document questions and measure the
    current RAG baseline.
4.  Create a fictional SQLite sales database with documented schema and
    business definitions.
5.  Implement the first safe Text-to-SQL vertical slice: question →
    schema context → SQL generation → validation → read-only execution →
    result table and explanation.
6.  Add query visibility and test cases before expanding to charts and
    more databases.

**Immediate priority:** Validate the current RAG flow, then build the
SQLite Text-to-SQL MVP. Do not start with a large multi-agent framework
or a stack of infrastructure services.

## 15. Glossary

-   **RAG:** Retrieval-Augmented Generation; retrieves relevant evidence
    before generating an answer.
-   **Embedding:** Numeric representation of text used for semantic
    similarity search.
-   **Vector database:** Stores embeddings and metadata for similarity
    retrieval.
-   **Text-to-SQL:** Converts a natural-language question into a
    database query.
-   **Agent:** A component that uses a defined set of tools to complete
    a task.
-   **Orchestrator:** Routes a request to one or more capabilities and
    coordinates the workflow.
-   **RBAC:** Role-Based Access Control.
-   **LLMOps:** Practices for operating, evaluating, monitoring, and
    updating LLM applications.
-   **Data lineage:** Information about where data came from and how it
    was transformed.
-   **Grounded answer:** An answer supported by retrieved evidence or
    actual computed results.

------------------------------------------------------------------------

## Final vision

Silvera should eventually answer three kinds of questions in one
governed workspace:

1.  **"What do our documents say?"** --- document intelligence with
    evidence and citations.
2.  **"What does our data show?"** --- safe natural-language-to-SQL and
    analytics.
3.  **"How do these pieces fit together?"** --- cross-source
    investigation, reporting, and carefully controlled workflows.

It should also make its work inspectable: which sources it used, which
query it executed, which permissions applied, what assumptions were
made, how reliable the result is, and where the system failed.

**Silvera is an evolving enterprise intelligence platform---not just a
chatbot.**
