# OtterWorks Flow Guide

This document maps the main system flows from simple to complex, and shows how services communicate in each path.

## 0) System Map

```mermaid
flowchart LR
  U[User] --> W[Web App / Admin UI]
  W --> G[API Gateway]
  G --> A[Auth Service]
  G --> F[File Service]
  G --> D[Document Service]
  G --> C[Collab Service]
  G --> S[Search Service]
  G --> N[Notification Service]
  G --> AU[Audit Service]
  G --> AN[Analytics Service]
  G --> R[Report Service]
  G --> AD[Admin Service]
  W -->|/billing-api| B[Billing Service]
  F --> S3[S3]
  F --> DD[DynamoDB]
  D --> PG[PostgreSQL]
  A --> PG
  AD --> PG
  R --> PG
  B --> BPG[Billing PostgreSQL]
  AD --> SL[Slack / Devin triage]
  C --> RE[Redis]
  S --> MS[MeiliSearch]
  N --> Q[SQS/SNS]
  AN --> DL[S3 Data Lake]
```

---

## 1) Login Flow (Auth Bootstrap)

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant UI as Web App
  participant GW as API Gateway
  participant AUTH as Auth Service
  participant PG as PostgreSQL

  U->>UI: Enter credentials
  UI->>GW: POST /auth/login
  GW->>AUTH: Forward login request
  AUTH->>PG: Validate user + password hash
  PG-->>AUTH: User record
  AUTH-->>GW: JWT + refresh token
  GW-->>UI: Auth response
  UI-->>U: Logged in state
```

---

## 2) Authenticated Read Request

```mermaid
sequenceDiagram
  autonumber
  participant UI as Web/Admin App
  participant GW as API Gateway
  participant SVC as Domain Service
  participant DB as Data Store

  UI->>GW: GET /api/... + JWT
  Note over GW: Middleware: request-id, rate-limit, CORS, JWT
  GW->>SVC: Proxied request by route prefix
  SVC->>DB: Query
  DB-->>SVC: Result
  SVC-->>GW: JSON response
  GW-->>UI: Response
```

---

## 3) File CRUD - Create (Upload)

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant UI as Web App
  participant GW as API Gateway
  participant FILE as File Service
  participant S3 as S3
  participant DDB as DynamoDB
  participant BUS as SNS/SQS Event Bus

  U->>UI: Upload file
  UI->>GW: POST /api/files (multipart)
  GW->>FILE: Forward upload request
  FILE->>S3: Store file blob
  FILE->>DDB: Store file metadata/version
  FILE->>BUS: Publish file_uploaded
  FILE-->>GW: 201 Created + file metadata
  GW-->>UI: Upload success
```

---

## 4) File CRUD - Read (Download/Open)

```mermaid
sequenceDiagram
  autonumber
  participant UI as Web App
  participant GW as API Gateway
  participant FILE as File Service
  participant DDB as DynamoDB
  participant S3 as S3

  UI->>GW: GET /api/files/{id}
  GW->>FILE: Forward request
  FILE->>DDB: Read metadata + ACL
  DDB-->>FILE: Metadata
  FILE->>S3: Generate presigned URL (or stream)
  S3-->>FILE: Access URL
  FILE-->>GW: Metadata + URL
  GW-->>UI: Response
```

---

## 5) Document CRUD (Versioned)

```mermaid
sequenceDiagram
  autonumber
  participant UI as Web App
  participant GW as API Gateway
  participant DOC as Document Service
  participant PG as PostgreSQL
  participant BUS as SNS/SQS

  UI->>GW: POST/PUT/DELETE /api/documents/...
  GW->>DOC: Forward request
  DOC->>PG: Write document + version history
  PG-->>DOC: Commit success
  DOC->>BUS: Publish document_created/edited/deleted
  DOC-->>GW: CRUD response
  GW-->>UI: Success/failure
```

---

## 6) Post-CRUD Async Fanout

```mermaid
flowchart LR
  E[Domain Event: file_uploaded / document_edited] --> BUS[SNS Topic]
  BUS --> NQ[Notification Queue]
  BUS --> SQ[Search Queue]
  BUS --> AQ[Audit Queue]
  BUS --> ANQ[Analytics Queue]

  NQ --> N[Notification Service]
  SQ --> S[Search Service]
  AQ --> AU[Audit Service]
  ANQ --> AN[Analytics Service]

  N --> OUT1[Email / In-app / Webhook]
  S --> MS[MeiliSearch Index Update]
  AU --> DDB[(DynamoDB Audit Log)]
  AN --> DL[(S3 Data Lake)]
```

---

## 7) Search Flows

### 7.1 Query Path

```mermaid
sequenceDiagram
  autonumber
  participant UI as Web App
  participant GW as API Gateway
  participant SEARCH as Search Service
  participant MS as MeiliSearch

  UI->>GW: GET /api/search?q=...
  GW->>SEARCH: Forward query
  SEARCH->>MS: Full-text query
  MS-->>SEARCH: Ranked hits
  SEARCH-->>GW: Search results
  GW-->>UI: Results
```

### 7.2 Indexing Path

```mermaid
sequenceDiagram
  autonumber
  participant DOC as Document/File Service
  participant BUS as SNS/SQS
  participant SEARCH as Search Service
  participant MS as MeiliSearch

  DOC->>BUS: Publish create/edit/delete event
  BUS-->>SEARCH: Deliver event
  SEARCH->>MS: Index/Reindex/Delete document
  MS-->>SEARCH: Ack
```

---

## 8) Collaboration Flow (Real-Time)

```mermaid
sequenceDiagram
  autonumber
  participant U1 as User A
  participant U2 as User B
  participant UI1 as Client A
  participant UI2 as Client B
  participant COL as Collab Service
  participant REDIS as Redis
  participant DOC as Document Service

  U1->>UI1: Open document
  U2->>UI2: Open same document
  UI1->>COL: WS connect + join room
  UI2->>COL: WS connect + join room

  UI1->>COL: CRDT update
  COL->>REDIS: Pub update/presence
  REDIS-->>COL: Fanout to subscribers
  COL-->>UI2: Apply remote update

  UI2->>COL: CRDT update
  COL-->>UI1: Apply remote update

  Note over COL,DOC: Periodic checkpoint / save
  COL->>DOC: Persist snapshot/version
```

---

## 9) Notification Flow

```mermaid
sequenceDiagram
  autonumber
  participant SVC as File/Document Service
  participant BUS as SNS/SQS
  participant NOTIF as Notification Service
  participant DDB as DynamoDB
  participant CH as Email/InApp/Webhook

  SVC->>BUS: Publish file_shared/comment_added
  BUS-->>NOTIF: Queue message
  NOTIF->>DDB: Persist notification record
  NOTIF->>CH: Deliver notification by channel
  CH-->>NOTIF: Delivery status
```

---

## 10) Audit Flow

```mermaid
sequenceDiagram
  autonumber
  participant GW as API Gateway
  participant BUS as SNS/SQS
  participant AUD as Audit Service
  participant DDB as DynamoDB
  participant S3 as S3 Archive

  GW->>BUS: Emit action context/event
  BUS-->>AUD: Deliver audit event
  AUD->>DDB: Append immutable audit record
  AUD->>S3: Archive for long-term retention
```

---

## 11) Analytics Flow

```mermaid
flowchart LR
  EV[Usage/API/Domain Events] --> BUS[SQS/SNS]
  BUS --> AN[Analytics Service]
  AN --> RAW[S3 Raw Events]
  RAW --> ETL[Airflow + Spark Jobs]
  ETL --> CUR[S3 Curated Parquet]
  CUR --> API[Analytics API / Report Service]
  API --> DASH[Admin Dashboard / Reports]
```

---

## 12) Full Complex End-to-End: Live Edit + Side Effects

```mermaid
sequenceDiagram
  autonumber
  participant UI as Web App
  participant GW as API Gateway
  participant COL as Collab Service
  participant DOC as Document Service
  participant BUS as SNS/SQS
  participant SEARCH as Search Service
  participant NOTIF as Notification Service
  participant AUD as Audit Service
  participant AN as Analytics Service

  UI->>GW: Open document + JWT
  GW->>DOC: Fetch metadata/version
  DOC-->>GW: Document state
  GW-->>UI: Initial state

  UI->>COL: Start WS collaboration
  UI->>COL: Live CRDT edits
  COL->>DOC: Persist checkpoint/version
  DOC->>BUS: Publish document_edited

  BUS-->>SEARCH: Reindex content
  BUS-->>NOTIF: Notify collaborators
  BUS-->>AUD: Record immutable audit event
  BUS-->>AN: Track usage metrics
```

---

## Mental Model

- **CRUD path**: API Gateway -> domain service -> primary datastore (synchronous, user-facing)
- **After-CRUD path**: domain event -> SNS/SQS -> search/notification/audit/analytics (asynchronous)
- **Collaboration path**: WebSocket + CRDT in collab-service, with persisted versions in document-service
