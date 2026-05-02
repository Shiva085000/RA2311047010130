import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify, request
from middleware.logger import Log
from notification_app_be.priority_inbox import fetch_notifs, top_n

app = Flask(__name__)


@app.route("/api/notifications/top", methods=["GET"])
def get_top():
    tok = os.environ.get("AUTH_TOKEN", "")
    if not tok:
        Log("backend", "error", "handler", "AUTH_TOKEN not set, cannot process request")
        return jsonify({"error": "AUTH_TOKEN not configured on server"}), 500

    n = request.args.get("n", 10, type=int)
    if n < 1:
        Log("backend", "warn", "handler", f"invalid n={n}, must be >= 1")
        return jsonify({"error": "n must be >= 1"}), 400

    Log("backend", "info", "handler", f"GET /api/notifications/top?n={n} received")

    notifs = fetch_notifs(tok)
    Log("backend", "info", "service", f"fetched {len(notifs)} notifications from upstream")

    results = top_n(notifs, n)
    Log("backend", "info", "utils", f"top-{n} selection complete")

    out = []
    for rank, (w, ts, _, notif) in enumerate(results, 1):
        out.append({
            "rank": rank,
            "type": notif["Type"],
            "message": notif["Message"],
            "timestamp": notif["Timestamp"],
            "priorityWeight": w
        })
        Log("backend", "debug", "controller",
            f"rank={rank} type={notif['Type']} weight={w} msg={notif['Message']}")

    Log("backend", "info", "handler",
        f"GET /api/notifications/top -> 200, returned {len(out)} notifications")
    return jsonify({"requestedTop": n, "notifications": out})


if __name__ == "__main__":
    Log("backend", "info", "config", "notification server starting on port 5001")
    app.run(port=5001, debug=False)
