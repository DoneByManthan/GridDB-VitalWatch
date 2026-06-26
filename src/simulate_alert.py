# simulate_alert.py
# Live health alert simulation for VitalWatch.
#
# Gradually deteriorates wearable readings to mimic a real-world health event
# (e.g. heat exhaustion during a group sporting event).
#
# Phases:
#   Phase 1 (steps 0–2)   – All wearers normal (baseline)
#   Phase 2 (steps 3–8)   – Athlete begins showing cardiovascular stress
#   Phase 3 (steps 9+)    – Athlete critical; elderly shows distress;
#                           office worker shows early stress
#
# The simulation runs until the user clicks "Alert Addressed" in the dashboard,
# which calls POST /api/sim/resolve and sets the simulation flag to False.
# Once that happens, the script injects a final batch of normal readings to
# restore the dashboard to a healthy state.

import jpype
import os
import time
import random
import urllib.request
import json
from datetime import datetime, timezone

import insert_data
from vitals import WEARERS
from health_estimator import derive_health_metrics

# ── JVM / GridDB bootstrap ────────────────────────────────────────────────────
classpath = os.environ.get("CLASSPATH", "")
if not jpype.isJVMStarted():
    jpype.startJVM(classpath=classpath.split(":"))

import griddb_python as griddb


def _jitter(val: float, pct: float = 0.02) -> float:
    return val + random.uniform(-pct, pct) * val


def _interpolate(low: float, high: float, progress: float = None) -> float:
    """Smoothly interpolate between two boundary values."""
    if progress is None:
        progress = random.uniform(0.0, 1.0)
    return low + progress * (high - low)


def _make_row(ts: datetime, wearer_id: str, target: str) -> list:
    """
    Build a realistic sensor row for the given wearer and target health state.

    Returns a list matching the GridDB container schema:
    [timestamp, heart_rate, spo2, temperature, activity_level,
     systolic_bp, diastolic_bp, blood_sugar]
    """
    thr = WEARERS[wearer_id]["thresholds"]
    nrm = WEARERS[wearer_id]["normal"]

    hr_lo,  hr_hi   = nrm["heart_rate"]
    sp_lo,  sp_hi   = nrm["spo2"]
    tmp_lo, tmp_hi  = nrm["temperature"]
    act_lo, act_hi  = nrm["activity_level"]

    hr_warn,  hr_crit  = thr["heart_rate"]["warning"],   thr["heart_rate"]["critical"]
    sp_warn,  sp_crit  = thr["spo2"]["warning"],          thr["spo2"]["critical"]
    tmp_warn, tmp_crit = thr["temperature"]["warning"],   thr["temperature"]["critical"]

    # environmental noise
    n_hr  = random.uniform(-2.0, 2.0)
    n_sp  = random.uniform(-0.3, 0.3)
    n_tmp = random.uniform(-0.1, 0.1)
    n_act = random.uniform(-2.0, 2.0)

    if target == "Normal":
        hr  = _interpolate(hr_lo,  hr_hi)  + n_hr
        sp  = _interpolate(sp_lo,  sp_hi)  + n_sp
        tmp = _interpolate(tmp_lo, tmp_hi) + n_tmp
        act = _interpolate(act_lo, act_hi) + n_act

    elif target == "Stress":
        prog = random.uniform(0.1, 0.55)
        hr   = _interpolate(hr_hi,  hr_warn, prog)  + n_hr
        sp   = _interpolate(sp_lo,  sp_warn, prog)  + n_sp     # SpO2 decreases
        tmp  = _interpolate(tmp_hi, tmp_warn, prog * 0.5) + n_tmp
        act  = _interpolate(act_lo, act_hi)  + n_act

    elif target == "Distress":
        prog = random.uniform(0.4, 0.82)
        hr   = _interpolate(hr_warn,  hr_crit, prog)  + n_hr
        sp   = _interpolate(sp_warn,  sp_crit, prog)  + n_sp
        tmp  = _interpolate(tmp_warn, tmp_crit, prog * 0.75) + n_tmp
        act  = _interpolate(act_lo, act_hi) + n_act

    else:  # Critical
        prog = random.uniform(0.85, 1.20)
        hr   = _interpolate(hr_warn,  hr_crit, prog)  + n_hr
        sp   = _interpolate(sp_warn,  sp_crit, prog)  + n_sp
        tmp  = _interpolate(tmp_warn, tmp_crit, prog)  + n_tmp
        act  = random.uniform(*nrm["activity_level"])  + n_act

    # clamp to physiological limits
    hr  = max(20.0, min(hr,  250.0))
    sp  = max(70.0, min(sp,  100.0))
    tmp = max(34.0, min(tmp,  42.0))
    act = max(0.0,  min(act, 200.0))

    drv = derive_health_metrics(hr, sp, tmp, act)
    return [ts, hr, sp, tmp, act, drv["systolic_bp"], drv["diastolic_bp"], drv["blood_sugar"]]


def is_sim_active() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:5000/api/sim/status")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()).get("active", False)
    except Exception:
        return False


def start_sim() -> None:
    try:
        req = urllib.request.Request("http://127.0.0.1:5000/api/sim/start", method="POST")
        urllib.request.urlopen(req)
    except Exception:
        pass


def trigger_alert() -> None:
    """
    Run the three-phase live alert simulation and write readings to GridDB Cloud
    every second until the dashboard operator clicks 'Alert Addressed'.
    """
    try:
        store = insert_data.get_gridstore()
        print("Starting VitalWatch Live Alert Simulation ...")
        start_sim()

        i = 0
        while is_sim_active():
            ts    = datetime.now(timezone.utc)
            batch = {}

            # ── Phase 1: Normal baseline ──────────────────────────────────────
            if i < 3:
                for w in WEARERS:
                    nrm = WEARERS[w]["normal"]
                    hr  = _jitter(random.uniform(*nrm["heart_rate"]))
                    sp  = _jitter(random.uniform(*nrm["spo2"]))
                    tmp = _jitter(random.uniform(*nrm["temperature"]))
                    act = _jitter(random.uniform(*nrm["activity_level"]))
                    drv = derive_health_metrics(hr, sp, tmp, act)
                    batch[WEARERS[w]["container"]] = [[
                        ts, hr, sp, tmp, act,
                        drv["systolic_bp"], drv["diastolic_bp"], drv["blood_sugar"],
                    ]]
                print(f"[{ts.strftime('%H:%M:%S')}] Phase: Normal Baseline")

            # ── Phase 2: Athlete Stress (steps 3–8) ──────────────────────────
            elif i < 9:
                progress = (i - 3) / 6.0
                for w in WEARERS:
                    if w == "athlete":
                        thr = WEARERS["athlete"]["thresholds"]
                        nrm = WEARERS["athlete"]["normal"]
                        hr  = nrm["heart_rate"][1] + progress * (thr["heart_rate"]["critical"] - nrm["heart_rate"][1]) + random.uniform(-3, 3)
                        sp  = nrm["spo2"][0]       - progress * (nrm["spo2"][0] - thr["spo2"]["warning"]) + random.uniform(-0.5, 0.5)
                        tmp = nrm["temperature"][1] + progress * (thr["temperature"]["warning"] - nrm["temperature"][1]) * 0.6 + random.uniform(-0.1, 0.1)
                        act = random.uniform(*nrm["activity_level"])
                        drv = derive_health_metrics(hr, sp, tmp, act)
                        batch[WEARERS[w]["container"]] = [[
                            ts, hr, sp, tmp, act,
                            drv["systolic_bp"], drv["diastolic_bp"], drv["blood_sugar"],
                        ]]
                    else:
                        nrm = WEARERS[w]["normal"]
                        hr  = _jitter(random.uniform(*nrm["heart_rate"]))
                        sp  = _jitter(random.uniform(*nrm["spo2"]))
                        tmp = _jitter(random.uniform(*nrm["temperature"]))
                        act = _jitter(random.uniform(*nrm["activity_level"]))
                        drv = derive_health_metrics(hr, sp, tmp, act)
                        batch[WEARERS[w]["container"]] = [[
                            ts, hr, sp, tmp, act,
                            drv["systolic_bp"], drv["diastolic_bp"], drv["blood_sugar"],
                        ]]
                print(f"[{ts.strftime('%H:%M:%S')}] Phase: Athlete Under Stress ...")

            # ── Phase 3: Full Deterioration ───────────────────────────────────
            else:
                targets = {
                    "athlete":       random.choice(["Distress", "Critical", "Critical"]),
                    "elderly":       random.choice(["Normal", "Stress", "Distress"]),
                    "office_worker": random.choice(["Normal", "Normal", "Stress"]),
                }
                for w, target in targets.items():
                    batch[WEARERS[w]["container"]] = [_make_row(ts, w, target)]
                print(f"[{ts.strftime('%H:%M:%S')}] Phase: HEALTH ALERT IN PROGRESS!")

            store.multi_put(batch)
            i += 1
            time.sleep(1)

        # ── post-simulation recovery ──────────────────────────────────────────
        print("\nAlert Addressed by operator.")
        print("Injecting recovery readings to restore dashboard ...")
        ts    = datetime.now(timezone.utc)
        batch = {}
        for w in WEARERS:
            nrm = WEARERS[w]["normal"]
            hr  = _jitter(random.uniform(*nrm["heart_rate"]))
            sp  = _jitter(random.uniform(*nrm["spo2"]))
            tmp = _jitter(random.uniform(*nrm["temperature"]))
            act = _jitter(random.uniform(*nrm["activity_level"]))
            drv = derive_health_metrics(hr, sp, tmp, act)
            batch[WEARERS[w]["container"]] = [[
                ts, hr, sp, tmp, act,
                drv["systolic_bp"], drv["diastolic_bp"], drv["blood_sugar"],
            ]]
        store.multi_put(batch)
        print("Simulation complete. System returned to stable state.")

    except Exception:
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    trigger_alert()
