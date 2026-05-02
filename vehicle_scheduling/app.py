import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify
from middleware.logger import Log
from vehicle_scheduling.scheduler import fetch, knapsack

app = Flask(__name__)


@app.route("/api/schedule", methods=["GET"])
def schedule():
    tok = os.environ.get("AUTH_TOKEN", "")
    if not tok:
        Log("backend", "error", "handler", "AUTH_TOKEN not set, cannot process request")
        return jsonify({"error": "AUTH_TOKEN not configured on server"}), 500

    Log("backend", "info", "handler", "GET /api/schedule received")

    depots = fetch("depots", tok)["depots"]
    Log("backend", "info", "service", f"fetched {len(depots)} depots")

    tasks = fetch("vehicles", tok)["vehicles"]
    Log("backend", "info", "service", f"fetched {len(tasks)} vehicle tasks")

    out = []
    for depot in depots:
        did, cap = depot["ID"], depot["MechanicHours"]
        Log("backend", "debug", "service", f"solving knapsack depot={did} cap={cap}h n={len(tasks)}")

        best, chosen = knapsack(tasks, cap)
        used = sum(t["Duration"] for t in chosen)

        Log("backend", "info", "service",
            f"depot {did}: max_impact={best} tasks_selected={len(chosen)} hours_used={used}/{cap}")

        out.append({
            "depotId": did,
            "budgetHours": cap,
            "hoursUsed": used,
            "maxImpact": best,
            "tasksSelected": len(chosen),
            "tasks": [
                {
                    "taskId": t["TaskID"],
                    "duration": t["Duration"],
                    "impact": t["Impact"]
                }
                for t in chosen
            ]
        })

    Log("backend", "info", "handler", f"GET /api/schedule -> 200, {len(out)} depots processed")
    return jsonify({"depots": out})


if __name__ == "__main__":
    Log("backend", "info", "config", "vehicle scheduling server starting on port 5000")
    app.run(port=5000, debug=False)
