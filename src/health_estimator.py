# health_estimator.py
# Rule-based estimation of derived health metrics from raw wearable sensor data.
#
# DISCLAIMER: All formulas here are simplified demonstrations for educational
# purposes only. They are NOT medically accurate and should never be used for
# real clinical decision-making.
#
# The estimations intentionally mimic plausible physiological relationships:
#   - Higher heart rate tends to slightly raise blood pressure.
#   - Lower SpO2 indicates physiological stress, which elevates estimated BP.
#   - Blood sugar responds to activity, heart rate, and stress signals.

import random


def estimate_systolic_bp(heart_rate: float, spo2: float, activity_level: float) -> float:
    """
    Estimate systolic blood pressure (mmHg) from HR, SpO2, and activity level.

    Baseline 120 mmHg is adjusted upward for:
      - Heart rate deviation above the reference 72 bpm
      - Physical activity level
      - SpO2 drop below the reference 96%  (hypoxic stress)
    """
    baseline     = 120.0
    hr_delta     = (heart_rate - 72) * 0.50
    activity_adj = (activity_level / 10.0) * 4.0
    spo2_stress  = max(0.0, (96.0 - spo2) * 0.80)
    noise        = random.uniform(-3.0, 3.0)
    return round(baseline + hr_delta + activity_adj + spo2_stress + noise, 1)


def estimate_diastolic_bp(heart_rate: float, activity_level: float) -> float:
    """
    Estimate diastolic blood pressure (mmHg) from HR and activity level.

    Baseline 80 mmHg is adjusted for heart rate deviation and physical activity.
    """
    baseline     = 80.0
    hr_delta     = (heart_rate - 72) * 0.30
    activity_adj = (activity_level / 10.0) * 2.0
    noise        = random.uniform(-2.0, 2.0)
    return round(baseline + hr_delta + activity_adj + noise, 1)


def estimate_blood_sugar(heart_rate: float, activity_level: float, spo2: float) -> float:
    """
    Estimate blood glucose level (mg/dL) from HR, activity, and SpO2.

    Baseline 90 mg/dL is adjusted for:
      - Heart rate (metabolic demand signal)
      - Activity level (glucose utilization and release)
      - SpO2 drop (physiological stress triggers glucose release)
    """
    baseline     = 90.0
    hr_delta     = (heart_rate - 70) * 0.30
    activity_adj = activity_level * 0.40
    spo2_stress  = max(0.0, (96.0 - spo2) * 1.50)
    noise        = random.uniform(-5.0, 5.0)
    return round(baseline + hr_delta + activity_adj + spo2_stress + noise, 1)


def derive_health_metrics(heart_rate: float, spo2: float,
                          temperature: float, activity_level: float) -> dict:
    """
    Given raw wearable vitals, return a dictionary of all derived health metrics.

    This is the single entry point used by the sensor simulator so that
    every simulated reading automatically includes estimated metrics.
    """
    systolic  = estimate_systolic_bp(heart_rate, spo2, activity_level)
    diastolic = estimate_diastolic_bp(heart_rate, activity_level)
    blood_sugar = estimate_blood_sugar(heart_rate, activity_level, spo2)

    # Clamp estimated values to physiologically plausible ranges
    systolic    = max(80.0,  min(systolic,    220.0))
    diastolic   = max(50.0,  min(diastolic,   130.0))
    blood_sugar = max(60.0,  min(blood_sugar, 300.0))

    return {
        "systolic_bp":  systolic,
        "diastolic_bp": diastolic,
        "blood_sugar":  blood_sugar,
    }
