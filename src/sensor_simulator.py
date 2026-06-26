# sensor_simulator.py
# Simulates wearable sensor output for three wearer profiles.
#
# Data is generated in three phases to model a realistic health event:
#   Normal      – all wearers within safe vital ranges
#   Stress      – athlete begins showing physiological stress (HR rises, SpO2 drops)
#   Deterioration – athlete reaches critical levels; other wearers start to show
#                   secondary stress (models a shared environmental trigger, e.g.
#                   extreme heat or altitude during a group sporting event)
#
# Derived health metrics (BP, blood sugar) are computed via health_estimator
# so that each row stored in GridDB contains the full set of vitals.

import random
from datetime import datetime, timedelta, timezone

from vitals import WEARERS
from health_estimator import derive_health_metrics


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def _reading(wearer_id: str, heart_rate: float, spo2: float,
             temperature: float, activity_level: float, timestamp: datetime) -> dict:
    """Build one complete sensor reading including derived health metrics."""
    derived = derive_health_metrics(heart_rate, spo2, temperature, activity_level)
    return {
        "wearer_id":      wearer_id,
        "timestamp":      timestamp.isoformat() + "Z",
        "heart_rate":     round(heart_rate, 1),
        "spo2":           round(spo2, 1),
        "temperature":    round(temperature, 2),
        "activity_level": round(activity_level, 1),
        "systolic_bp":    derived["systolic_bp"],
        "diastolic_bp":   derived["diastolic_bp"],
        "blood_sugar":    derived["blood_sugar"],
    }


def _interpolate(low: float, high: float, progress: float = None) -> float:
    """Smoothly interpolate between two values with optional random progress."""
    if progress is None:
        progress = random.uniform(0.0, 1.0)
    return low + progress * (high - low)


def generate_reading(wearer_id: str, status: str = "Normal",
                     progress: float = 0.0, timestamp: datetime = None) -> dict:
    """
    Generate a single wearable sensor reading for the given wearer and health status.

    Parameters
    ----------
    wearer_id : str
        Key from WEARERS config.
    status : str
        One of "Normal", "Stress", "Distress", or "Critical".
    progress : float
        0.0–1.0 — how far into the current phase the reading falls.
        Drives smooth transitions rather than instantaneous jumps.
    timestamp : datetime
        UTC timestamp for the reading; defaults to now.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    cfg = WEARERS[wearer_id]
    nrm = cfg["normal"]
    thr = cfg["thresholds"]

    # ── pull baseline values from normal ranges ─────────────────────────────
    hr_base   = random.uniform(*nrm["heart_rate"])
    spo2_base = random.uniform(*nrm["spo2"])
    t_base    = random.uniform(*nrm["temperature"])
    act_base  = random.uniform(*nrm["activity_level"])

    # ── environmental noise added to every reading ───────────────────────────
    noise_hr   = random.uniform(-2.0, 2.0)
    noise_spo2 = random.uniform(-0.3, 0.3)
    noise_temp = random.uniform(-0.1, 0.1)
    noise_act  = random.uniform(-2.0, 2.0)

    if status == "Normal":
        # Occasional minor physiological jitter to avoid perfectly flat lines
        if random.random() < 0.05:
            hr_base += random.uniform(3, 8)
            spo2_base -= random.uniform(0.3, 0.8)

    elif status == "Stress":
        # HR ramps upward; SpO2 begins to drop; temperature slightly elevated
        hr_base   = _interpolate(nrm["heart_rate"][1], thr["heart_rate"]["warning"],   progress)
        spo2_base = _interpolate(nrm["spo2"][0],       thr["spo2"]["warning"],          progress)
        t_base    = _interpolate(nrm["temperature"][1], thr["temperature"]["warning"],  progress * 0.6)
        act_base  = _interpolate(nrm["activity_level"][1], thr["activity_level"]["warning"], progress * 0.4)

    elif status == "Distress":
        # HR between warning and critical; SpO2 approaching critical level
        hr_base   = _interpolate(thr["heart_rate"]["warning"],   thr["heart_rate"]["critical"],   progress * 0.85)
        spo2_base = _interpolate(thr["spo2"]["warning"],         thr["spo2"]["critical"],          progress * 0.85)
        t_base    = _interpolate(thr["temperature"]["warning"],  thr["temperature"]["critical"],  progress * 0.70)
        act_base  = _interpolate(nrm["activity_level"][1],       thr["activity_level"]["warning"], progress * 0.50)

    elif status == "Critical":
        # All vitals past critical thresholds
        hr_base   = thr["heart_rate"]["critical"]   + progress * random.uniform(5, 15)
        spo2_base = thr["spo2"]["critical"]          - progress * random.uniform(1, 3)
        t_base    = thr["temperature"]["critical"]   + progress * random.uniform(0.2, 0.5)
        act_base  = thr["activity_level"]["critical"] + progress * random.uniform(5, 15)

    # ── apply noise and clamp to physically plausible limits ─────────────────
    hr   = _clamp(hr_base   + noise_hr,    20.0, 250.0)
    spo2 = _clamp(spo2_base + noise_spo2,  70.0, 100.0)
    temp = _clamp(t_base    + noise_temp,  34.0, 42.0)
    act  = _clamp(act_base  + noise_act,    0.0, 200.0)

    return _reading(wearer_id, hr, spo2, temp, act, timestamp)


def generate_dataset(normal_count: int = 60, disaster: bool = True) -> dict:
    """
    Generate a full historical dataset across all wearers.

    Dataset is structured in up to three phases:
      1. Normal (normal_count readings)
      2. Stress — athlete starts showing elevated vitals (20 readings)
      3. Deterioration — athlete critical; other wearers start secondary stress (15 readings)

    Returns
    -------
    dict
        { wearer_id: [list of reading dicts] }
    """
    wearer_ids = list(WEARERS.keys())
    interval   = 60  # seconds between readings

    stress_count = 20 if disaster else 0
    det_count    = 15 if disaster else 0
    total        = normal_count + stress_count + det_count

    start_time = datetime.now(timezone.utc) - timedelta(seconds=total * interval)
    dataset    = {w: [] for w in wearer_ids}

    for i in range(total):
        ts = start_time + timedelta(seconds=i * interval)

        # ── Phase 1: Normal ───────────────────────────────────────────────────
        if i < normal_count:
            for w in wearer_ids:
                dataset[w].append(generate_reading(w, "Normal", timestamp=ts))

        # ── Phase 2: Stress (athlete only) ────────────────────────────────────
        elif i < normal_count + stress_count:
            prog   = (i - normal_count) / stress_count
            status = "Stress" if prog < 0.65 else "Distress"
            dataset["athlete"].append(generate_reading("athlete", status, progress=prog, timestamp=ts))
            dataset["elderly"].append(generate_reading("elderly", "Normal", timestamp=ts))
            dataset["office_worker"].append(generate_reading("office_worker", "Normal", timestamp=ts))

        # ── Phase 3: Deterioration (cascade to other wearers) ─────────────────
        else:
            prog = (i - normal_count - stress_count) / det_count
            dataset["athlete"].append(generate_reading("athlete", "Critical", progress=prog, timestamp=ts))
            # Elderly begins showing stress (secondary environmental effect)
            e_status = "Stress" if prog < 0.50 else "Distress"
            dataset["elderly"].append(generate_reading("elderly", e_status, progress=prog, timestamp=ts))
            # Office worker shows early stress
            ow_status = "Normal" if prog < 0.60 else "Stress"
            dataset["office_worker"].append(generate_reading("office_worker", ow_status, progress=prog, timestamp=ts))

    return dataset


if __name__ == "__main__":
    data = generate_dataset()
    for wearer_id, readings in data.items():
        name = WEARERS[wearer_id]["display_name"]
        print(f"\n--- {name} (last 3 readings) ---")
        for r in readings[-3:]:
            print(
                f"  {r['timestamp']}  "
                f"HR={r['heart_rate']}bpm  "
                f"SpO2={r['spo2']}%  "
                f"Temp={r['temperature']}°C  "
                f"Act={r['activity_level']}  "
                f"SBP={r['systolic_bp']}  "
                f"DBP={r['diastolic_bp']}  "
                f"BS={r['blood_sugar']}"
            )
    print(f"\nTotal readings per wearer: {len(list(data.values())[0])}")
