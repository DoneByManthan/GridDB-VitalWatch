# app.py
# Flask backend for VitalWatch.
# Serves the monitoring dashboard and exposes REST API endpoints
# that the dashboard polls to retrieve live health data from GridDB.
#
# Endpoints:
#   GET  /                        → serves dashboard.html
#   GET  /api/fleet               → fleet-wide health status + chains + risk score
#   GET  /api/wearer/<wearer_id>  → per-wearer reading history + analysis
#   GET  /api/timeline            → chronological log of health status changes
#   POST /api/sim/start           → begin live alert simulation
#   POST /api/sim/resolve         → stop simulation and inject recovery readings
#   GET  /api/sim/status          → check whether simulation is active

import jpype
import os
import random
import threading
from flask import Flask, jsonify, send_from_directory
from datetime import datetime, timezone

import query_data
import insert_data
from vitals import WEARERS

# ── JVM / GridDB bootstrap ────────────────────────────────────────────────────
classpath = os.environ.get("CLASSPATH", "")
if not jpype.isJVMStarted():
    jpype.startJVM(classpath=classpath.split(":"))

import griddb_python as griddb

app = Flask(__name__, static_folder="dashboard")

# Thread-local GridDB store: GridDB connections are not safe to share across
# threads, so each Flask worker thread gets its own connection object.
_local     = threading.local()
sim_state  = {"active": False}


def get_store():
    """Return the current thread's GridDB store, creating one if needed."""
    if not hasattr(_local, "store") or _local.store is None:
        _local.store = query_data.get_gridstore()
    return _local.store


def _jitter(val: float, pct: float = 0.02) -> float:
    return val + random.uniform(-pct, pct) * val


def inject_recovery() -> None:
    """
    Push a batch of normal-range readings for all wearers into GridDB.

    Called immediately after the alert simulation ends so the dashboard
    returns to a healthy state without waiting for the next heartbeat cycle.
    """
    try:
        from health_estimator import derive_health_metrics
        store = get_store()
        ts    = datetime.now(timezone.utc)
        batch = {}
        for wearer_id, cfg in WEARERS.items():
            nrm = cfg["normal"]
            hr  = _jitter(random.uniform(*nrm["heart_rate"]))
            sp  = _jitter(random.uniform(*nrm["spo2"]))
            tmp = _jitter(random.uniform(*nrm["temperature"]))
            act = _jitter(random.uniform(*nrm["activity_level"]))
            drv = derive_health_metrics(hr, sp, tmp, act)
            batch[cfg["container"]] = [[
                ts, hr, sp, tmp, act,
                drv["systolic_bp"], drv["diastolic_bp"], drv["blood_sugar"],
            ]]
        store.multi_put(batch)
        print(f"Recovery batch injected at {ts.strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"Recovery injection failed: {e}")


# ── static routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("/app/dashboard", "dashboard.html")


# ── data API endpoints ────────────────────────────────────────────────────────

@app.route("/api/fleet")
def fleet():
    """Return fleet-wide health status: all wearers + chains + risk score."""
    try:
        result = query_data.get_fleet_health_status(get_store())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/wearer/<wearer_id>")
def wearer(wearer_id: str):
    """Return reading history and health analysis for a single wearer."""
    if wearer_id not in WEARERS:
        return jsonify({"error": f"Unknown wearer: {wearer_id}"}), 404

    try:
        store    = get_store()
        readings = query_data.query_recent(store, wearer_id, limit=50)
        status   = query_data.analyze_wearer(wearer_id, readings)

        return jsonify({
            "wearer_id":    wearer_id,
            "display_name": WEARERS[wearer_id]["display_name"],
            "description":  WEARERS[wearer_id]["description"],
            "status":       status,
            "history":      list(reversed(readings)),  # chronological order for charts
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/timeline")
def timeline():
    """
    Return a chronological log of health status transitions.

    Only logs events where the status changed or where a danger status
    persisted past a 5-minute cooldown — avoids flooding the log with
    repeated identical entries.
    """
    try:
        store            = get_store()
        events           = []
        COOLDOWN_SECONDS = 300

        for wearer_id in WEARERS:
            readings        = query_data.query_recent(store, wearer_id, limit=100)
            readings_chrono = list(reversed(readings))

            last_status = "Normal"
            last_time   = datetime.min

            for r in readings_chrono:
                ts     = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                status = query_data.analyze_wearer(wearer_id, [r])["status"]

                if status == "Normal":
                    last_status = "Normal"
                    continue

                time_gap     = (ts - last_time).total_seconds()
                changed      = status != last_status
                stale_danger = (status == last_status) and (time_gap > COOLDOWN_SECONDS)

                if changed or stale_danger:
                    events.append({
                        "timestamp":    r["timestamp"],
                        "wearer_id":    wearer_id,
                        "display_name": WEARERS[wearer_id]["display_name"],
                        "status":       status,
                    })
                    last_status = status
                    last_time   = ts

        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return jsonify(events[:20])

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── simulation control endpoints ──────────────────────────────────────────────

@app.route("/api/sim/start", methods=["POST"])
def sim_start():
    sim_state["active"] = True
    return jsonify({"status": "Simulation Active"})


@app.route("/api/sim/resolve", methods=["POST"])
def sim_resolve():
    """Stop the simulation and push recovery data so the dashboard clears."""
    sim_state["active"] = False
    inject_recovery()
    return jsonify({"status": "Alert Addressed"})


@app.route("/api/sim/status")
def sim_status():
    return jsonify(sim_state)


if __name__ == "__main__":
    print("Starting VitalWatch Health Monitor ...")
    print("Dashboard: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
