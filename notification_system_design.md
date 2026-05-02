# Notification System Design Notes

## Stage 1

So for the notification platform, we basically need to do a few things: get a student's notifications (with some basic filtering), mark them as read, send out new ones, and push real-time updates so the frontend doesn't have to keep polling constantly.

### REST API Endpoints

**GET /notifications**

Gets notifications for a student. Needs to support filtering by type/read status and some simple pagination.

Headers:
```
Authorization: Bearer <token>
Accept: application/json
```

Query params: `studentId` (required), `type` (Event / Result / Placement), `isRead` (boolean), `limit` (default 20), `offset` (default 0)

Response 200:
```json
{
  "total": 142,
  "notifications": [
    {
      "id": "d146095a-0d86-4a34-9e69-3900a14576bc",
      "type": "Placement",
      "message": "Google hiring drive on 5th May",
      "isRead": false,
      "createdAt": "2026-04-22T17:51:30Z"
    }
  ]
}
```

**POST /notifications**

Fires off a notification to one or multiple students.

Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`

Request body:
```json
{
  "studentIds": ["s1", "s2"],
  "type": "Placement",
  "message": "Google hiring drive on 5th May"
}
```

Response 201: `{ "queued": 2 }`

**PATCH /notifications/:id/read**

Marks a specific notification as read. Returns the updated object.

**PATCH /notifications/read-all**

Marks all unread notifications as read for a given student. Just returns how many rows got updated.

**DELETE /notifications/:id**

Nukes a notification.

### Real-Time Notifications

I'd go with **Server-Sent Events (SSE)** over WebSocket here. The data only flows one way — server to client — so the full-duplex overhead of WebSocket isn't needed. SSE reconnects automatically using `Last-Event-ID`, works over plain HTTP/1.1, and is much easier to scale behind a load balancer.

Endpoint: `GET /notifications/stream?studentId=<id>`

When a new notification is created on the backend, it publishes to a Redis channel (`notifications:<studentId>`). Each open SSE connection subscribes to that channel and forwards the event to the browser.

```
event: notification
data: {"id":"abc","type":"Placement","message":"Google hiring","createdAt":"2026-04-22T18:00:00Z"}
```

---

## Stage 2

### Why PostgreSQL

The notification data has a fixed, well-known shape — there's no reason to reach for a document store. PostgreSQL handles the ORDER BY + index range scans we need very well, gives us partial indexes (which matter a lot here), and ACID guarantees that partial failures (like only half the rows getting marked read) don't happen.

### Schema

```sql
CREATE TYPE notification_type AS ENUM ('Event', 'Result', 'Placement');

CREATE TABLE students (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       VARCHAR(255) NOT NULL,
  email      VARCHAR(255) UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE notifications (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  type       notification_type NOT NULL,
  message    TEXT NOT NULL,
  is_read    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notif_student_unread
  ON notifications (student_id, is_read, created_at DESC)
  WHERE is_read = FALSE;
```

The partial index (`WHERE is_read = FALSE`) is intentional — it only indexes the rows we actually query for, so it stays small as notifications get marked read over time.

### Problems at Scale

When we get to like 50K students and millions of rows, we're gonna hit some bottlenecks:

- Full table scans if the index isn't being used (missing or wrong query shape)
- Index bloat from high insert volume
- `PATCH /read-all` locking too many rows at once
- Too many concurrent DB connections from polling clients
- Students with old accounts accumulating huge notification histories

How to fix: The partial index I put above takes care of the read query. For the read-all thing, we should batch the UPDATEs with a cursor so we aren't running one massive statement. Definitely need PgBouncer for connection pooling. We should probably also archive old read notifications (maybe > 90 days) to cold storage. If the table gets way too huge (like 10M+ rows), we can look into partitioning it by student_id hash.

### Queries

Fetch unread notifications:
```sql
SELECT id, type, message, is_read, created_at
FROM notifications
WHERE student_id = $1
  AND is_read = FALSE
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;
```

Mark one read:
```sql
UPDATE notifications SET is_read = TRUE WHERE id = $1 RETURNING id, is_read;
```

Mark all read:
```sql
UPDATE notifications SET is_read = TRUE WHERE student_id = $1 AND is_read = FALSE;
```

Bulk insert (for POST /notifications with multiple students):
```sql
INSERT INTO notifications (student_id, type, message)
SELECT unnest($1::uuid[]), $2::notification_type, $3;
```

---

## Stage 3

### The slow query

```sql
SELECT * FROM notifications
WHERE studentID = 1042 AND isRead = false
ORDER BY createdAt DESC;
```

The logic itself is fine — it returns the right data. The problem is performance. With 5M rows and no index on `(studentID, isRead, createdAt)`, Postgres has to do a full sequential scan every time. It reads all 5M rows, filters down, then sorts. Even if the student only has 30 unread notifications, the DB is scanning the entire table to find them.

`SELECT *` makes it worse — it fetches every column including potentially large text fields, adding unnecessary I/O.

### Fix

Add a composite partial index:
```sql
CREATE INDEX idx_notif_student_unread
  ON notifications (studentID, isRead, createdAt DESC)
  WHERE isRead = FALSE;
```

And rewrite the query:
```sql
SELECT id, type, message, createdAt
FROM notifications
WHERE studentID = 1042
  AND isRead = false
ORDER BY createdAt DESC;
```

Before the fix, cost is O(n) — scanning all 5M rows. After, it's O(log n + k) where k is the number of results. For a student with 30 unread notifications, that's the difference between 5M row reads and roughly 30. The sort is also free because the index is already ordered by `createdAt DESC`.

### Indexing every column

Bad idea. Every index you add slows down your INSERTs, UPDATEs, and DELETEs because the index has to be updated too. For a table that's gonna get hammered with writes, adding a bunch of indexes will tank our write throughput. A single well-thought-out composite index is way better than a dozen single-column indexes for what we need.

### Students who received a Placement notification in the last 7 days

```sql
SELECT DISTINCT student_id
FROM notifications
WHERE notificationType = 'Placement'
  AND created_at >= NOW() - INTERVAL '7 days';
```

Supporting index:
```sql
CREATE INDEX idx_notif_type_created ON notifications (notificationType, created_at DESC);
```

---

## Stage 4

### The problem

Every time a student loads a page, we hit the DB. With 50K students, that's gonna be thousands of queries per second hitting our Postgres instance during peak times. The DB will just fall over.

### What I'd do

**Redis cache per student** — cache the first page of notifications with a ~60s TTL. On a cache hit, skip the DB entirely. Invalidate the key whenever a new notification arrives or one gets marked read. The tradeoff is up to 60s of stale data, which is acceptable for a notification inbox.

**Cache just the unread count** — most students only care about the badge count, not the full list. Store `notif:{studentId}:unread_count` in Redis and increment/decrement it on events. Much cheaper than caching full pages. Risk: the count can drift if an invalidation is missed, so a periodic reconcile helps.

**Cursor-based pagination** — offset pagination (`LIMIT 20 OFFSET 200`) makes Postgres skip rows, which gets slower the deeper you go. A cursor (the `createdAt` of the last seen row) makes every page fetch equally fast.

**Read replica** — route all SELECT queries to a replica, keep writes on the primary. Tradeoff is a small replication lag (~ms), which is fine for notifications.

**SSE push instead of polling** — if the client holds an SSE connection open, it doesn't need to query on every page load. The backend pushes new notifications as they arrive. The page-load query becomes a one-time bootstrap fetch instead of a recurring hammer on the DB.

My recommendation: combine SSE with a Redis unread count cache and a read replica. That covers the three main pressure points — polling, DB reads, and connection count.

---

## Stage 5

### Problems with the current approach

```
function notify_all(student_ids, message):
    for student_id in student_ids:
        send_email(student_id, message)
        save_to_db(student_id, message)
        push_to_app(student_id, message)
```

Everything is sequential and blocking. At ~100ms per student, 50K students takes over an hour. If `send_email` fails on student 200, the loop crashes — students 201 to 50000 get nothing, and the ones before 200 are in an inconsistent state (some got email+DB+push, some got only DB). There's no retry, no way to resume, and no audit trail.

### What happened when email failed at student 200

Students 1–199 got everything. Students 200–50000 got nothing. The 49,800 missed students have no DB record either, so there's no way to retry just the failures. The system is silently broken and you'd only find out if someone complained.

### Should DB save and email happen together?

No. The DB write is the source of truth — if a notification exists in the DB, it happened. Email is best-effort delivery that can fail for reasons outside our control (provider down, rate limits, spam filters). If we tie them together, an email failure kills the DB write for everyone downstream. They need to be decoupled so they can fail independently.

### Redesign

```
function notify_all(student_ids, message):
    # First, commit everything to DB in one atomic bulk insert.
    # If this fails, nothing has been sent yet — safe to retry the whole thing.
    batch_save_to_db(student_ids, message)

    # Then enqueue async jobs for email and push separately.
    for student_id in student_ids:
        email_queue.publish({ student_id, message, retries: 3 })
        push_queue.publish({ student_id, message })


function email_worker(job):
    attempts = 0
    while attempts < job.retries:
        try:
            send_email(job.student_id, job.message)
            return
        except TransientError:
            attempts += 1
            sleep(exponential_backoff(attempts))
    log_failure(job.student_id)


function push_worker(job):
    push_to_app(job.student_id, job.message)
```

The bulk DB insert is atomic — either all 50K rows land or none do. Email and push workers run in parallel across a worker pool, bringing the total time down from ~83 minutes to a few minutes. If an email worker fails after 3 retries, only that student's email is missed — the DB record is intact and the push still went through. Email failures don't cascade.

---

## Stage 6

### Approach

Priority is a combination of notification type and recency. I assigned weights: Placement = 3, Result = 2, Event = 1. Each notification gets a score of `(type_weight, unix_timestamp)`. Tuple comparison is lexicographic, so type always dominates — a Result from yesterday ranks above an Event from today. Within the same type, the more recent notification wins.

For a static list, sorting by score descending and taking the first N works fine — O(n log n).

### Maintaining top-N as new notifications come in

Re-sorting the whole list every time a new notification comes in is just a waste of CPU. Instead, we can use a min-heap of size N. The root of the heap is always the weakest notification in our top-N.

When a new notification arrives:
- If the heap has fewer than N items, push it in.
- If the new item's score beats the root (the current weakest), swap it in with `heapreplace` — O(log N).
- Otherwise, ignore it.

This way, handling a new notification is just O(log N) no matter how many we've processed, and the heap always perfectly tracks the top N.

### Code

See `notification_app_be/priority_inbox.py`.

Key functions: `score(notif)` builds the sort key, `top_n(notifs, n)` runs the initial heap build, and `push_one(notif, heap, n, seq)` handles streaming inserts.
