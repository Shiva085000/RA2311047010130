import os
import sys
import json
import time
import heapq
import urllib.request
import urllib.error
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from middleware.logger import Log

BASE = "http://20.207.122.201/evaluation-service"

TYPE_WEIGHT = {"Placement": 3, "Result": 2, "Event": 1}
TS_FMT = "%Y-%m-%d %H:%M:%S"


def fetch_notifs(tok):
    url = f"{BASE}/notifications"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode())
            ms = (time.time() - t0) * 1000
            Log("backend", "info", "service", f"GET {url} -> {r.status} ({ms:.0f}ms)")
            return body["notifications"]
    except urllib.error.HTTPError as e:
        Log("backend", "error", "handler", f"GET {url} failed: {e.code} {e.reason}")
        sys.exit(1)
    except Exception as e:
        Log("backend", "fatal", "service", f"GET {url} unreachable: {e}")
        sys.exit(1)


def score(notif):
    w = TYPE_WEIGHT.get(notif["Type"], 0)
    ts = int(datetime.strptime(notif["Timestamp"], TS_FMT).timestamp())
    return w, ts


def top_n(notifs, n):
    h = []
    for seq, notif in enumerate(notifs):
        w, ts = score(notif)
        entry = (w, ts, seq, notif)
        if len(h) < n:
            heapq.heappush(h, entry)
        elif (w, ts) > (h[0][0], h[0][1]):
            heapq.heapreplace(h, entry)
    return sorted(h, key=lambda e: (e[0], e[1]), reverse=True)


def push_one(notif, heap, n, seq):
    """Insert a single incoming notification into the existing top-n heap."""
    w, ts = score(notif)
    entry = (w, ts, seq, notif)
    if len(heap) < n:
        heapq.heappush(heap, entry)
    elif (w, ts) > (heap[0][0], heap[0][1]):
        heapq.heapreplace(heap, entry)


def main():
    tok = os.environ.get("AUTH_TOKEN", "")
    if not tok:
        Log("backend", "fatal", "config", "AUTH_TOKEN not set")
        print("Error: set AUTH_TOKEN before running")
        sys.exit(1)

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    Log("backend", "info", "service", f"priority inbox requested top={n}")

    notifs = fetch_notifs(tok)
    Log("backend", "info", "service", f"received {len(notifs)} notifications from API")

    results = top_n(notifs, n)
    Log("backend", "debug", "utils", f"top-{n} selection complete")

    print(f"\n{'='*70}")
    print(f"  Top {n} Priority Notifications")
    print(f"{'='*70}")
    print(f"  {'#':>2}  {'Type':<12}  {'Message':<30}  Timestamp")
    print(f"  {'--':>2}  {'-'*12}  {'-'*30}  {'-'*19}")

    for rank, (w, ts, _, notif) in enumerate(results, 1):
        print(f"  {rank:>2}  {notif['Type']:<12}  {notif['Message']:<30}  {notif['Timestamp']}")
        Log("backend", "info", "controller",
            f"rank={rank} type={notif['Type']} weight={w} msg={notif['Message']}")

    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
