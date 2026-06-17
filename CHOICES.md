# Technical Design Choices - Store Intelligence

This document records the major design trade-offs, options considered, AI recommendations, and final architectural choices made during the development of the **Store Intelligence** retail analytics platform.

---

### Decision 1: Detection Model (YOLOv8n vs YOLOv8m vs RT-DETR vs MediaPipe)
**Options Considered:**
1. **YOLOv8n (Ultralytics)**: Nano version of YOLOv8 optimized for speed and edge performance.
2. **YOLOv8m**: Medium version of YOLOv8 with higher accuracy but larger weight footprint.
3. **RT-DETR (Real-Time DEtection TRansformer)**: Transformer-based detector offering state-of-the-art accuracy.
4. **MediaPipe Object Detector (Google)**: Lightweight CPU-friendly object detection framework.

**What AI Suggested:**
The AI suggested using **RT-DETR** because of its superior performance in crowded environments and its transformer-based attention mechanism, which excels at detecting people even when they overlap or stand close together in queues. The AI reasoned that the increased parameter count would be manageable on modern GPU instances and would yield higher precision tracking data.

**What I Chose and Why:**
I chose **YOLOv8n** for edge deployment. Surveliance feeds are processed locally on store gateway systems. RT-DETR and YOLOv8m require significant GPU memory and cannot achieve real-time rates on standard edge processors (like Nvidia Jetson Nano or lower-end server CPUs). YOLOv8n performs inference in under 10ms per frame on CPU/low-end GPU, leaving ample resources for Re-ID embedding extraction and Kalman tracking. Since we project coordinates onto coarse zone areas rather than tracking fine hand movements, the accuracy of YOLOv8n is more than sufficient. MediaPipe was rejected due to its poor accuracy under varying store lighting conditions.

---

### Decision 2: Event Schema Design (Flat vs Nested Metadata, UUID vs Hash event_ids, and Timing of ZONE_DWELL)
**Options Considered:**
1. **Flat Schema with MD5 Hash event_ids**: All parameters (visitor_id, store_id, camera_id, queue_depth, etc.) stored as top-level flat table columns. Event ID computed as a hash of the event parameters.
2. **Nested Metadata Schema, UUIDv4 event_ids, and periodic 30s ZONE_DWELL**: Event structure contains core fields (event_id, store_id, camera_id, event_type, timestamp) with dynamic context details (e.g. queue_depth, sku_zone) nested inside a JSON metadata block. Event ID uses randomly generated UUIDv4. Dwell events are accumulated and emitted periodically every 30 seconds of continuous presence.
3. **Raw Frame Timestamp Streaming**: Emitting an event block for every frame containing the current coordinates and zone, storing raw timeseries data in the database.

**What AI Suggested:**
The AI suggested using a **Flat Schema with MD5 Hash event_ids** and **Raw Frame Timestamp Streaming**. It reasoned that flat schemas are faster to index and query in databases, and raw timestamp streaming guarantees that no detail is lost, allowing the backend to calculate arbitrary dwell statistics on the fly. It recommended MD5 hashes of timestamps and IDs to make events naturally idempotent.

**What I Chose and Why:**
I chose **Option 2: Nested Metadata Schema, UUIDv4 event_ids, and periodic 30s ZONE_DWELL**.
- **Nested Schema**: Retail cameras generate different context data (e.g. checkout cameras emit `queue_depth`, aisle cameras emit `sku_zone`). Storing these in flat columns would result in extremely sparse databases with dozens of null columns. A nested JSON metadata block allows high schema flexibility.
- **UUIDv4 event_ids**: Generating UUIDv4 at the edge prevents hash collisions and guarantees uniqueness across multiple store nodes. Ingest routers use `ON CONFLICT (event_id) DO NOTHING` to guarantee idempotency.
- **Periodic ZONE_DWELL**: Streaming every frame timestamp would flood the server with up to 5 events/sec per person, crashing DB performance. Emitting a summary `ZONE_DWELL` every 30 seconds of continuous presence reduces database inserts by 99% while ensuring dashboard graphs show real-time activity.

---

### Decision 3: Storage Engine (SQLite vs PostgreSQL vs DuckDB for Time-Series Analytics)
**Options Considered:**
1. **SQLite (in-memory or local file)**: Serverless, lightweight relational database.
2. **PostgreSQL**: Production-grade relational database with support for indexing, JSONB queries, and high concurrency.
3. **DuckDB**: Embedded analytical database optimized for columnar aggregation.

**What AI Suggested:**
The AI suggested using **DuckDB** because of its columnar storage format, which is extremely efficient for analytical aggregate queries (such as calculating average dwell times, conversion funnels, and rolling counts over millions of timeseries rows).

**What I Chose and Why:**
I chose **PostgreSQL** (with **SQLite** serving as an isolated test-suite database fallback). While DuckDB is excellent for read-heavy OLAP, it is serverless and does not handle concurrent write operations (ingesting batch events while concurrently executing dashboard analytical queries) without locking issues. PostgreSQL's MVCC model allows concurrent bulk-inserts and analytics aggregates. We leverage PostgreSQL's indexes (`(store_id, timestamp)` composite, and JSONB index on metadata) to optimize lookup speeds, satisfying both write-concurrency and read-analytical speeds in a single database engine.
