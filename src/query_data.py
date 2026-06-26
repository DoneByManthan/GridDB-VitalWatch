# query_data.py
# GridDB queries, per-wearer vital analysis, risk scoring,
# and physiological health chain detection.

import jpype
import os

from vitals import WEARERS, VITAL_CHAIN_RULES, VITAL_WEIGHTS, WEARER_WEIGHTS

# ── JVM / GridDB bootstrap ────────────────────────────────────────────────────
classpath = os.environ.get("CLASSPATH", "")
if not jpype.isJVMStarted():
    jpype.startJVM(classpath=classpath.split(":"))

import griddb_python as griddb

# ── connection parameters ─────────────────────────────────────────────────────
NOTIFICATION_MEMBER = os.environ.get("GRIDDB_NOTIFICATION_MEMBER", "griddb-server:10001")
CLUSTER_NAME        = os.environ.get("GRIDDB_CLUSTER_NAME",        "myCluster")
USERNAME            = os.environ.get("GRIDDB_USERNAME",            "admin")
PASSWORD            = os.environ.get("GRIDDB_PASSWORD",            "admin")


def get_gridstore():
    """Return a GridDB store connection using environment credentials."""
    factory = griddb.StoreFactory.get_instance()
    return factory.get_store(
        notification_member=NOTIFICATION_MEMBER,
        cluster_name=CLUSTER_NAME,
        username=USERNAME,
        password=PASSWORD,
    )


# ── TQL query helpers ─────────────────────────────────────────────────────────

def query_recent(store, wearer_id: str, limit: int = 20) -> list:
    """
    Fetch the most recent `limit` readings for a wearer using GridDB TQL.

    Returns readings newest-first so that readings[0] is always the latest.
    """
    container_name = WEARERS[wearer_id]["container"]
    container = store.get_container(container_name)
    if container is None:
        return []

    query = container.query(f"select * order by timestamp desc limit {limit}")
    rs    = query.fetch()

    readings = []
    while rs.has_next():
        row = rs.next()
        readings.append({
            "timestamp":      row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
            "heart_rate":     row[1],
            "spo2":           row[2],
            "temperature":    row[3],
            "activity_level": row[4],
            "systolic_bp":    row[5],
            "diastolic_bp":   row[6],
            "blood_sugar":    row[7],
        })
    return readings


# ── severity scoring helpers ──────────────────────────────────────────────────

def vital_severity(value: float, vital_key: str, wearer_id: str) -> float:
    """
    Return a 0.0–1.5 severity score for a single vital reading.

    Handles both "higher is worse" vitals (HR, temperature, activity) and
    "lower is worse" vitals (SpO2) via the `inverted` flag in the threshold config.

    0.0       → within normal range
    0.0–0.30  → drifting toward warning
    0.30–1.0  → between warning and critical
    1.0–1.50  → past critical (capped at 1.5)
    """
    thr      = WEARERS[wearer_id]["thresholds"][vital_key]
    nrm      = WEARERS[wearer_id]["normal"][vital_key]
    inverted = thr.get("inverted", False)

    if inverted:
        # SpO2: lower value = higher severity
        normal_safe = nrm[0]        # the lowest acceptable normal value
        warning     = thr["warning"]
        critical    = thr["critical"]

        if value >= normal_safe:
            return 0.0
        elif value >= warning:
            # drifting below normal floor toward warning
            return 0.30 * (normal_safe - value) / (normal_safe - warning)
        elif value >= critical:
            return 0.30 + 0.70 * (warning - value) / (warning - critical)
        else:
            overshoot = (critical - value) / max(warning - critical, 0.1)
            return min(1.0 + overshoot * 0.5, 1.50)
    else:
        # HR, temperature, activity: higher value = higher severity
        normal_max = nrm[1]
        warning    = thr["warning"]
        critical   = thr["critical"]

        if value <= normal_max:
            return 0.0
        elif value <= warning:
            return 0.30 * (value - normal_max) / (warning - normal_max)
        elif value <= critical:
            return 0.30 + 0.70 * (value - warning) / (critical - warning)
        else:
            overshoot = (value - critical) / max(critical - warning, 1)
            return min(1.0 + overshoot * 0.5, 1.50)


def wearer_risk_score(wearer_id: str, avg_hr: float, avg_spo2: float,
                      avg_temp: float, avg_act: float) -> int:
    """
    Calculate a 0–100 risk score by combining severity scores across all vital signs.

    The score is a weighted sum using VITAL_WEIGHTS:
      spo2        → 40%
      heart_rate  → 35%
      temperature → 15%
      activity    → 10%
    """
    s_hr   = vital_severity(avg_hr,   "heart_rate",     wearer_id)
    s_spo2 = vital_severity(avg_spo2, "spo2",           wearer_id)
    s_temp = vital_severity(avg_temp, "temperature",    wearer_id)
    s_act  = vital_severity(avg_act,  "activity_level", wearer_id)

    weighted = (
        s_hr   * VITAL_WEIGHTS["heart_rate"]     +
        s_spo2 * VITAL_WEIGHTS["spo2"]           +
        s_temp * VITAL_WEIGHTS["temperature"]    +
        s_act  * VITAL_WEIGHTS["activity_level"]
    )

    return min(round(weighted * 100), 100)


# ── per-wearer analysis ───────────────────────────────────────────────────────

def _vital_status_for(value: float, vital_key: str, wearer_id: str) -> str:
    """Return the status string for a single vital value."""
    thr      = WEARERS[wearer_id]["thresholds"][vital_key]
    inverted = thr.get("inverted", False)

    if inverted:
        if value < thr["critical"]:   return "Critical"
        if value < thr["warning"]:    return "Warning"
        return "Normal"
    else:
        if value > thr["critical"]:   return "Critical"
        if value > thr["warning"]:    return "Warning"
        return "Normal"


def analyze_wearer(wearer_id: str, readings: list) -> dict:
    """
    Analyze recent readings for a single wearer and return their health status.

    Uses a rolling window of the 3 most recent readings to smooth sensor noise
    before evaluating thresholds — avoids false alerts from momentary spikes.
    """
    if not readings:
        return {
            "status": "Unknown", "message": "No data available.",
            "latest": None, "risk_score": 0, "vital_statuses": {},
        }

    latest = readings[0]
    name   = WEARERS[wearer_id]["display_name"]
    thr    = WEARERS[wearer_id]["thresholds"]

    # ── rolling-window average (up to 3 most recent readings) ────────────────
    window   = readings[:3]
    avg_hr   = sum(r["heart_rate"]     for r in window) / len(window)
    avg_spo2 = sum(r["spo2"]           for r in window) / len(window)
    avg_temp = sum(r["temperature"]    for r in window) / len(window)
    avg_act  = sum(r["activity_level"] for r in window) / len(window)

    score = wearer_risk_score(wearer_id, avg_hr, avg_spo2, avg_temp, avg_act)

    # ── vital-level status for chain detection ────────────────────────────────
    vital_statuses = {
        "heart_rate":     _vital_status_for(avg_hr,   "heart_rate",     wearer_id),
        "spo2":           _vital_status_for(avg_spo2, "spo2",           wearer_id),
        "temperature":    _vital_status_for(avg_temp, "temperature",    wearer_id),
        "activity_level": _vital_status_for(avg_act,  "activity_level", wearer_id),
    }

    # ── overall wearer status ─────────────────────────────────────────────────
    # Critical if ANY vital breaches critical threshold
    critical_vitals = [k for k, v in vital_statuses.items() if v == "Critical"]
    if critical_vitals:
        return {
            "status":        "Critical",
            "message":       f"{name}: CRITICAL – {', '.join(v.replace('_',' ').title() for v in critical_vitals)} exceeded safe limits!",
            "latest":        latest,
            "risk_score":    score,
            "vital_statuses": vital_statuses,
        }

    # Distress if two or more vitals are in Warning
    warning_vitals = [k for k, v in vital_statuses.items() if v == "Warning"]
    if len(warning_vitals) >= 2:
        return {
            "status":        "Distress",
            "message":       f"{name}: Physiological Distress – {' & '.join(v.replace('_',' ').title() for v in warning_vitals)} elevated.",
            "latest":        latest,
            "risk_score":    score,
            "vital_statuses": vital_statuses,
        }

    # Stress if exactly one vital is in Warning
    if len(warning_vitals) == 1:
        return {
            "status":        "Stress",
            "message":       f"{name}: Stress Detected – {warning_vitals[0].replace('_', ' ').title()} elevation noted.",
            "latest":        latest,
            "risk_score":    score,
            "vital_statuses": vital_statuses,
        }

    return {
        "status":        "Normal",
        "message":       f"{name}: All vitals within normal range.",
        "latest":        latest,
        "risk_score":    score,
        "vital_statuses": vital_statuses,
    }


# ── physiological chain detection ─────────────────────────────────────────────

def detect_health_chains(wearer_id: str, vital_statuses: dict) -> list:
    """
    Check VITAL_CHAIN_RULES against a single wearer's per-vital status dict.

    A chain alert fires when the source vital is in a danger state AND the
    target vital is also at risk — this indicates a linked physiological event
    rather than an isolated measurement spike.
    """
    chains       = []
    danger_states   = {"Distress", "Critical"}
    at_risk_states  = {"Stress", "Distress", "Critical"}

    for rule in VITAL_CHAIN_RULES:
        src_status = vital_statuses.get(rule["source"], "Normal")
        tgt_status = vital_statuses.get(rule["target"], "Normal")
        if src_status in danger_states and tgt_status in at_risk_states:
            chains.append({
                "wearer_id": wearer_id,
                "source":    rule["source"],
                "target":    rule["target"],
                "message":   rule["message"],
            })

    return chains


# ── fleet-wide health status ──────────────────────────────────────────────────

def get_fleet_health_status(store) -> dict:
    """
    Analyze all wearers and return a combined fleet health report.

    Fleet score = weighted average of individual risk scores (WEARER_WEIGHTS)
                + a 10-point penalty for each active health chain (max +30)
    """
    wearer_statuses = {}
    all_chains      = []

    for wearer_id in WEARERS:
        readings = query_recent(store, wearer_id, limit=10)
        status   = analyze_wearer(wearer_id, readings)
        wearer_statuses[wearer_id] = status

        # Check physiological chains for this wearer
        chains = detect_health_chains(wearer_id, status.get("vital_statuses", {}))
        all_chains.extend(chains)

    # Weighted average across wearers
    fleet_score = sum(
        wearer_statuses[w]["risk_score"] * WEARER_WEIGHTS[w]
        for w in WEARERS
    )

    # Each active chain adds a 10-point urgency penalty (cap at +30)
    chain_penalty = min(len(all_chains) * 10, 30)
    risk_score    = min(round(fleet_score + chain_penalty), 100)

    return {
        "wearers":    wearer_statuses,
        "chains":     all_chains,
        "risk_score": risk_score,
    }


if __name__ == "__main__":
    try:
        store = get_gridstore()
        fleet = get_fleet_health_status(store)

        print("\n=== VITALWATCH FLEET HEALTH STATUS ===")
        for wearer_id, status in fleet["wearers"].items():
            print(
                f"  [{status['status']:10}] {WEARERS[wearer_id]['display_name']:20} "
                f"(risk: {status['risk_score']:3}/100): {status['message']}"
            )

        if fleet["chains"]:
            print("\nPHYSIOLOGICAL CHAIN ALERTS:")
            for c in fleet["chains"]:
                src = c["source"].replace("_", " ").title()
                tgt = c["target"].replace("_", " ").title()
                print(f"  {WEARERS[c['wearer_id']]['display_name']} | {src} → {tgt}: {c['message']}")
        else:
            print("\nNo physiological chain conditions detected.")

        print(f"\n  Fleet Health Risk Score: {fleet['risk_score']} / 100")

    except Exception:
        import traceback
        traceback.print_exc()
