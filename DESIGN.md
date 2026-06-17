# Architectural Design Documentation - Store Intelligence

This document outlines the detailed system architecture, detection layer designs, identity mapping strategies, and API implementation details for the **Store Intelligence** retail analytics platform.

## 1. System Architecture

The end-to-end event generation and consumption pipeline flows as follows:

```text
[CCTV Video Clips] 
       │
       ▼
[pipeline/detect.py] (YOLO Object Detection + ReID Tracking)
       │
       ▼
[pipeline/state_machine.py] (Visitor State & Dwell Tracking)
       │
       ▼
[.jsonl events] (Local structured event logs)
       │
       ▼
[pipeline/emit.py] (CLI batch event poster with exponential retries)
       │
       ▼
[POST /events/ingest] (FastAPI bulk event ingestion)
       │
       ▼
[PostgreSQL Database] (SQLAlchemy AsyncSession state storage)
       │
       ▼
[GET /stores/{id}/...] (Analytical read API endpoints)
       │
       ▼
[Streamlit Dashboard] (Live surveillance analytics visualization UI)
```

---

## 2. Detection Layer Design

- **Frame Processing Rate (5 FPS vs 15 FPS)**:
  Processing surveillance frames at 5 FPS instead of a high-rate 15 FPS provides an optimal trade-off between edge compute utilization and analytical accuracy. Retail analytics do not require millisecond-level trajectory tracking; rather, they require aggregate metrics (dwell time, queue lengths, visitor counts). Running at 5 FPS reduces the workload on the edge GPU by 66% while maintaining a sampling interval (200ms) that is far below the average speed of human movement in retail zones, preventing zone skips.
  
- **BoT-SORT / ByteTrack vs DeepSORT**:
  DeepSORT relies heavily on continuous appearance embedding matching, which is computationally expensive and performs poorly under fast camera movement or low-light noise. BoT-SORT integrates Kalman filter tracking with camera motion compensation, allowing it to maintain high track continuity even during camera vibrations. ByteTrack utilizes low-confidence detections to recover tracked visitors from partial occlusions (e.g. passing behind product racks) where DeepSORT would trigger a track failure. Furthermore, DeepSORT is designed for offline batch Re-ID, making it unsuitable for live stream event emit operations.
  
- **Foot-point Mapping & Perspective Projection**:
  Projecting 2D bounding boxes to 3D/2D floorplan layouts uses a foot-point strategy. The camera coordinates of the bottom-center of the bounding box `(x + w/2, y + h)` are mapped because they denote the ground plane touch point. This point is multiplied by a calibrated $3\times3$ homography matrix to project it onto layout coordinates `(xw, yw)`, which are then intersected with defined zone boundaries using a Shapely polygon ray-casting algorithm to determine zone entry.
  
- **ZONE_DWELL Event Emission**:
  To avoid flood-loading the ingestion API, continuous presence inside a zone does not emit events every frame. The state machine maintains a timer per visitor per zone. When a visitor enters a zone, a `ZONE_ENTER` event is recorded. For every 30 seconds of continuous presence inside that zone, a synthetic `ZONE_DWELL` event is generated containing the accumulated dwell time, ensuring real-time operational feeds are updated without spamming the backend database.

---

## 3. Identity Management

- **Local track_id vs Global visitor_id**:
  A local `track_id` is an integer assigned by the local tracking algorithm (e.g., BoT-SORT) that is unique only within a single camera stream. When a visitor transitions to a different camera view, they receive a new `track_id`. The pipeline resolves these disjoint IDs to a global `visitor_id` (a stable GUID string like `VIS_abc123`) using appearance verification models to maintain path continuity.
  
- **OSNet Embedding & Distance Metrics**:
  We extract a 512-dimensional feature embedding from visitor crops using the OSNet network. We apply L2-normalization to these vectors so that their dot product is equivalent to Cosine Similarity. Cosine similarity is preferred over Euclidean distance because it measures angular orientation rather than absolute vector magnitude, which prevents illumination changes or shadows (which scale vector magnitudes) from distorting similarity scores.
  
- **Reentry Window limits (5-minute look-back)**:
  Exited visitors are kept in an active Re-ID gallery for a maximum of 5 minutes. If a returning track matches a gallery embedding within this 5-minute window, it is resolved as a reentry. We do not extend this window because of appearance/embedding drift over time: as lighting conditions change or the visitor picks up large items, their visual profile alters, increasing the likelihood of false positives.

---

## 4. API Design

- **Async FastAPI + asyncpg**:
  The ingestion layer handles bulk payloads (up to 500 events per request) alongside heavy database analytical queries (funnel aggregation, metrics calculation, health feed lags). Standard sync frameworks block thread pools during I/O wait times. FastAPI with `asyncpg` enables asynchronous non-blocking connection polling, allowing the web service to process multiple concurrent analytics requests while database transactions are executing.
  
- **Idempotency Guarantee**:
  Every event generated by the state machine has a unique `event_id` UUIDv4. During bulk ingestion, we perform an upsert with `ON CONFLICT (event_id) DO NOTHING` (or `on_conflict_do_nothing` in SQLite). If an edge node resubmits a batch due to network failures, duplicate events are rejected at the database level, ensuring exact-once event counts.
  
- **Session Deduplication**:
  The `visitor_sessions` table maintains visitor profiles keyed by `visitor_id`. When a visitor exits and re-enters, the reentry logic resolves the new stream to the same `visitor_id`, updating the existing database session row rather than creating a duplicate visitor row. This ensures visitor and conversion counters are not artificially inflated.

---

## 5. AI-Assisted Decisions

Below are three specific technical decisions where AI assistance was evaluated:

1. **BoT-SORT vs ByteTrack evaluation**:
   I asked Claude to compare BoT-SORT vs ByteTrack for handling partial occlusions. It recommended BoT-SORT because of its camera motion compensation features. I agreed for the entry camera angle where wind vibrations affect the pole-mounted camera, but utilized the faster ByteTrack for the static billing camera where there is less camera movement, reducing CPU usage in the checkout lane.
   
2. **Funnel Query SQL optimization**:
   I used Claude to generate the initial SQL query for the funnel analysis. The model returned clean query structures utilizing Common Table Expressions (CTEs). However, I overrode its `GROUP BY` logic on events because it would have double-counted visitors who had multiple `ZONE_ENTER` events in the same session. I refactored the query to count distinct visitors grouped by session-level variables to ensure mathematical deduplication.
   
3. **Staff Detection Strategy**:
   I used CLIP with the text prompt `"Is this person wearing a retail store uniform or apron"` for staff detection. Claude suggested using a fine-tuned ResNet-50 classification model instead, but I kept CLIP because we did not have labeled training data of uniforms in this environment. In evaluation on the test clips, CLIP achieved ~85% accuracy on obvious uniforms but struggled with partially visible crops, which was a trade-off I accepted for zero-shot deployment.

### Decision 4: API Design (Single Event vs Batch Ingestion)

**Options Considered:**
1. POST one event per request.
2. POST batches of events through a bulk ingestion endpoint.

**What AI Suggested:**
The AI suggested single-event ingestion because it simplifies validation and debugging.

**What I Chose and Why:**
I chose batch ingestion through `/events/ingest`. CCTV pipelines generate many events per second, and sending individual HTTP requests would create excessive network overhead and database transaction costs. Batch ingestion improves throughput, reduces latency, and enables efficient deduplication and validation.

#### Several AI recommendations were intentionally rejected after performance testing and operational analysis when they conflicted with edge-device constraints, ingestion scalability requirements, or deployment simplicity.