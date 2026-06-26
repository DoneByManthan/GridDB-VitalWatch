# vitals.py
# Wearable profile configuration for VitalWatch.
# Defines normal ranges, alert thresholds, sensor weights, and physiological
# chain rules for three simulated wearer profiles.
#
# NOTE: All health estimations in this project are simulated for demonstration
# purposes only. They do not constitute medical advice.

WEARERS = {
    "athlete": {
        "display_name": "Athlete",
        "container": "wearer_athlete",
        "description": "Trained athlete with high aerobic capacity and lower resting heart rate.",
        "thresholds": {
            "heart_rate":     {"warning": 155,  "critical": 185},
            "spo2":           {"warning": 92,   "critical": 88,  "inverted": True},
            "temperature":    {"warning": 38.0, "critical": 39.0},
            "activity_level": {"warning": 140,  "critical": 170},
        },
        "normal": {
            "heart_rate":     (50, 80),
            "spo2":           (96, 100),
            "temperature":    (36.0, 37.2),
            "activity_level": (0, 60),
        },
    },
    "elderly": {
        "display_name": "Elderly Patient",
        "container": "wearer_elderly",
        "description": "Senior patient requiring closer cardiovascular and thermal monitoring.",
        "thresholds": {
            "heart_rate":     {"warning": 100,  "critical": 120},
            "spo2":           {"warning": 94,   "critical": 90,  "inverted": True},
            "temperature":    {"warning": 37.5, "critical": 38.2},
            "activity_level": {"warning": 60,   "critical": 90},
        },
        "normal": {
            "heart_rate":     (65, 90),
            "spo2":           (95, 100),
            "temperature":    (36.1, 37.3),
            "activity_level": (0, 30),
        },
    },
    "office_worker": {
        "display_name": "Office Worker",
        "container": "wearer_office_worker",
        "description": "Sedentary adult with standard cardiovascular and metabolic thresholds.",
        "thresholds": {
            "heart_rate":     {"warning": 110,  "critical": 140},
            "spo2":           {"warning": 93,   "critical": 89,  "inverted": True},
            "temperature":    {"warning": 37.8, "critical": 38.5},
            "activity_level": {"warning": 100,  "critical": 130},
        },
        "normal": {
            "heart_rate":     (60, 95),
            "spo2":           (96, 100),
            "temperature":    (36.2, 37.4),
            "activity_level": (0, 50),
        },
    },
}

# Physiological chain rules define known correlations between vital signs.
# If a "source" vital is in a danger state AND the "target" vital is also
# elevated / depressed, a chain alert is triggered for that wearer.
VITAL_CHAIN_RULES = [
    {
        "source": "spo2",
        "target": "heart_rate",
        "message": (
            "Oxygen-Cardiac Chain: Falling SpO2 is driving compensatory heart rate elevation. "
            "The body is increasing cardiac output to offset reduced blood oxygen."
        ),
    },
    {
        "source": "heart_rate",
        "target": "temperature",
        "message": (
            "Cardiac-Thermal Chain: Elevated heart rate is correlating with rising body temperature. "
            "Increased metabolic activity is generating excess heat."
        ),
    },
    {
        "source": "spo2",
        "target": "temperature",
        "message": (
            "Full Physiological Chain: Simultaneous SpO2 desaturation and thermal elevation detected. "
            "This pattern may indicate acute physiological stress or systemic illness."
        ),
    },
]

# Contribution of each vital sign toward a wearer's combined health risk score.
VITAL_WEIGHTS = {
    "heart_rate":     0.35,
    "spo2":           0.40,   # SpO2 carries the highest weight; oxygen deprivation escalates fastest
    "temperature":    0.15,
    "activity_level": 0.10,
}

# Contribution of each wearer profile toward the fleet-wide health risk score.
WEARER_WEIGHTS = {
    "elderly":       0.50,   # elderly patient is the highest-priority monitoring subject
    "athlete":       0.30,
    "office_worker": 0.20,
}
