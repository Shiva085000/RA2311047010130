import os
import sys
import json
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from middleware.logger import Log

BASE = "http://20.207.122.201/evaluation-service"


def fetch(endpoint, tok):
    url = f"{BASE}/{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode())
            ms = (time.time() - t0) * 1000
            Log("backend", "info", "service", f"GET {url} -> {r.status} ({ms:.0f}ms)")
            return body
    except urllib.error.HTTPError as e:
        Log("backend", "error", "handler", f"GET {url} failed: {e.code} {e.reason}")
        sys.exit(1)
    except Exception as e:
        Log("backend", "fatal", "service", f"GET {url} unreachable: {e}")
        sys.exit(1)


def knapsack(tasks, cap):
    n = len(tasks)
    dp = [[0] * (cap + 1) for _ in range(n + 1)]

    for i, t in enumerate(tasks, 1):
        dur, imp = t["Duration"], t["Impact"]
        for w in range(cap + 1):
            dp[i][w] = dp[i - 1][w]
            if w >= dur:
                alt = dp[i - 1][w - dur] + imp
                if alt > dp[i][w]:
                    dp[i][w] = alt

    chosen = []
    w = cap
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            chosen.append(tasks[i - 1])
            w -= tasks[i - 1]["Duration"]

    return dp[n][cap], chosen


def main():
    tok = os.environ.get("AUTH_TOKEN", "")
    if not tok:
        Log("backend", "fatal", "config", "AUTH_TOKEN not set")
        print("Error: set AUTH_TOKEN before running")
        sys.exit(1)

    Log("backend", "info", "service", "starting vehicle maintenance scheduler")

    depots = fetch("depots", tok)["depots"]
    Log("backend", "info", "service", f"fetched {len(depots)} depots")

    tasks = fetch("vehicles", tok)["vehicles"]
    Log("backend", "info", "service", f"fetched {len(tasks)} vehicle tasks")

    print(f"\n{'='*60}")
    print(f"Depots: {len(depots)}  |  Total tasks: {len(tasks)}")
    print(f"{'='*60}")

    for depot in depots:
        did, cap = depot["ID"], depot["MechanicHours"]
        Log("backend", "debug", "service", f"solving knapsack for depot {did}, cap={cap}h, n={len(tasks)}")

        best, chosen = knapsack(tasks, cap)
        used = sum(t["Duration"] for t in chosen)

        Log("backend", "info", "service",
            f"depot {did}: max_impact={best}, tasks={len(chosen)}, hours_used={used}/{cap}")

        print(f"\nDepot {did}  |  Budget: {cap}h  |  Used: {used}h  |  Max Impact: {best}")
        print(f"  {'TaskID':<40} {'Dur':>4}  {'Imp':>4}")
        print(f"  {'-'*40} {'-'*4}  {'-'*4}")
        for t in chosen:
            print(f"  {t['TaskID']}  {t['Duration']:>4}h  {t['Impact']:>4}")

    Log("backend", "info", "service", "scheduler run complete")


if __name__ == "__main__":
    main()
