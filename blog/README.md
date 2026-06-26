# VitalWatch – Real-Time Wearable Health Monitoring with GridDB Cloud

> **Disclaimer:** All health metric estimations in this project (blood pressure, blood sugar) are simplified simulations for demonstration and educational purposes only. They are not medically accurate and must never be used for clinical decision-making.

VitalWatch is a Python-based wearable health monitoring system that simulates sensor data from three wearer profiles, stores it in **GridDB Cloud**, detects physiological stress patterns, and visualizes real-time health status on a web dashboard.

---

## Features

- **Simulated wearable sensors** – Heart Rate, SpO2, Body Temperature, Activity Level
- **Derived health metrics** – Estimated Systolic/Diastolic BP and Blood Sugar using rule-based formulas
- **Three-phase simulation** – Normal → Stress → Deterioration (cascade failure equivalent)
- **Physiological chain detection** – Identifies linked vital sign deterioration events
- **0–100 continuous risk scoring** – Weighted across vitals and wearers
- **Live alert simulation** – Gradual deterioration injected into GridDB in real time
- **Machine learning classifier** – RandomForest model trained on GridDB data to predict health risk level
- **Web dashboard** – Real-time charts, chain alerts panel, health status timeline

---

## Repository Structure

```
VitalWatch-GridDB/
├── README.md
├── requirements.txt
├── blog/
│   ├── images/
│   └── vitalwatch-griddb.md
├── dashboard/
│   └── dashboard.html
└── src/
    ├── vitals.py            ← Wearer config, thresholds, chain rules
    ├── sensor_simulator.py  ← Realistic wearable data generation
    ├── health_estimator.py  ← Rule-based BP and blood sugar estimation
    ├── insert_data.py       ← GridDB connection, container setup, bulk insert
    ├── query_data.py        ← TQL queries, analysis, risk scoring, chain detection
    ├── app.py               ← Flask backend + API endpoints
    ├── simulate_alert.py    ← Live health deterioration simulation
    └── train_model.py       ← scikit-learn ML pipeline
```

---

## Prerequisites

1. **GridDB Cloud** account (Microsoft Azure Marketplace) with cluster credentials
2. **Python 3.10+**
3. **GridDB Python client** installed per the [official GridDB documentation](https://docs.griddb.net)

---

## Environment Variables

Set these before running any script:

```bash
export GRIDDB_NOTIFICATION_MEMBER="<your-cluster-host>:10001"
export GRIDDB_CLUSTER_NAME="<your-cluster-name>"
export GRIDDB_USERNAME="<your-username>"
export GRIDDB_PASSWORD="<your-password>"
```

---

## Running the Project

### Step 1 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 2 — Seed historical data

```bash
cd src
python insert_data.py
```

### Step 3 — Start the monitoring backend

```bash
python app.py
```

Open **http://localhost:5000** to view the dashboard.

### Step 4 (optional) — Keep the dashboard alive with a heartbeat

```bash
python insert_data.py --live
```

### Step 5 (optional) — Trigger a live alert simulation

```bash
python simulate_alert.py
```

Click **"Alert Addressed"** in the dashboard to stop the simulation.

### Step 6 (optional) — Train the ML health risk classifier

```bash
python train_model.py
```

---

## Dashboard Overview

| Panel | Description |
|---|---|
| Wearer cards | Live HR, SpO2, temperature, activity + mini trend chart |
| Combined Risk Score | Fleet-wide 0–100 health risk indicator |
| Physiological Chain Alerts | Active vital-sign linkage events |
| Health Status Timeline | Chronological log of status transitions |

---

## Wearer Profiles

| Profile | Normal HR | Normal SpO2 | Key characteristic |
|---|---|---|---|
| Athlete | 50–80 bpm | 96–100% | Higher aerobic tolerance; earlier HR warning |
| Elderly Patient | 65–90 bpm | 95–100% | Lower critical thresholds; highest monitoring weight |
| Office Worker | 60–95 bpm | 96–100% | Standard adult thresholds; sedentary activity baseline |

---

## Health Status Levels

| Status | Meaning |
|---|---|
| Normal | All vitals within wearer-specific safe range |
| Stress | One vital sign elevated toward warning threshold |
| Distress | Two or more vitals in warning range simultaneously |
| Critical | Any vital exceeds its critical threshold |

---

## License

MIT
