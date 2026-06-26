# insert_data.py
# GridDB connection, container setup, bulk data insertion, and live heartbeat producer.
#
# Environment variables (set these before running):
#   GRIDDB_NOTIFICATION_MEMBER  e.g. "griddb-server:10001"
#   GRIDDB_CLUSTER_NAME         e.g. "myCluster"
#   GRIDDB_USERNAME             e.g. "admin"
#   GRIDDB_PASSWORD             e.g. "admin"
#
# Usage:
#   python insert_data.py           — seed historical data and exit
#   python insert_data.py --live    — continuous healthy-readings heartbeat

import jpype
import os
import json
import urllib.request
from datetime import datetime, timezone

import sensor_simulator
from vitals import WEARERS

# ── JVM / GridDB bootstrap ────────────────────────────────────────────────────
classpath = os.environ.get("CLASSPATH", "")
if not jpype.isJVMStarted():
    jpype.startJVM(classpath=classpath.split(":"))

import griddb_python as griddb

# ── connection parameters from environment ────────────────────────────────────
NOTIFICATION_MEMBER = os.environ.get("GRIDDB_NOTIFICATION_MEMBER", "griddb-server:10001")
CLUSTER_NAME        = os.environ.get("GRIDDB_CLUSTER_NAME",        "myCluster")
USERNAME            = os.environ.get("GRIDDB_USERNAME",            "admin")
PASSWORD            = os.environ.get("GRIDDB_PASSWORD",            "admin")
APP_URL             = os.environ.get("APP_URL",                    "http://127.0.0.1:5000")


def get_gridstore():
    """Return a GridDB store connection using environment credentials."""
    factory = griddb.StoreFactory.get_instance()
    return factory.get_store(
        notification_member=NOTIFICATION_MEMBER,
        cluster_name=CLUSTER_NAME,
        username=USERNAME,
        password=PASSWORD,
    )


def setup_containers(store) -> dict:
    """
    Create one TIME_SERIES container per wearer profile.

    Schema columns:
        timestamp      – row key (TIMESTAMP)
        heart_rate     – DOUBLE, bpm
        spo2           – DOUBLE, percentage
        temperature    – DOUBLE, °C
        activity_level – DOUBLE, steps/min proxy
        systolic_bp    – DOUBLE, mmHg (estimated)
        diastolic_bp   – DOUBLE, mmHg (estimated)
        blood_sugar    – DOUBLE, mg/dL (estimated)
    """
    containers = {}
    for wearer_id, cfg in WEARERS.items():
        con_info = griddb.ContainerInfo(
            cfg["container"],
            [
                ["timestamp",      griddb.Type.TIMESTAMP],
                ["heart_rate",     griddb.Type.DOUBLE],
                ["spo2",           griddb.Type.DOUBLE],
                ["temperature",    griddb.Type.DOUBLE],
                ["activity_level", griddb.Type.DOUBLE],
                ["systolic_bp",    griddb.Type.DOUBLE],
                ["diastolic_bp",   griddb.Type.DOUBLE],
                ["blood_sugar",    griddb.Type.DOUBLE],
            ],
            griddb.ContainerType.TIME_SERIES,
        )
        containers[wearer_id] = store.put_container(con_info)
        print(f"  ✓ Container ready: {cfg['container']}")
    return containers


def insert_dataset(store, dataset: dict) -> None:
    """
    Bulk-insert an entire simulated dataset using multi_put.

    multi_put writes rows for multiple containers in a single round-trip,
    which significantly improves throughput for continuous sensor streams.
    """
    batch = {}
    for wearer_id, readings in dataset.items():
        container_name = WEARERS[wearer_id]["container"]
        rows = []
        for r in readings:
            ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
            rows.append([
                ts,
                r["heart_rate"],
                r["spo2"],
                r["temperature"],
                r["activity_level"],
                r["systolic_bp"],
                r["diastolic_bp"],
                r["blood_sugar"],
            ])
        batch[container_name] = rows

    store.multi_put(batch)

    for wearer_id, readings in dataset.items():
        print(f"  ✓ Inserted {len(readings)} rows → {WEARERS[wearer_id]['container']}")


def is_sim_active() -> bool:
    """Check if the live alert simulation is currently running via the Flask API."""
    try:
        req = urllib.request.Request(f"{APP_URL}/api/sim/status")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            return data.get("active", False)
    except Exception:
        # If the app is unreachable, assume no active simulation
        return False


def live_producer(store) -> None:
    """
    Continuously insert Normal-range readings every 5 seconds.

    Acts as a heartbeat that keeps the dashboard "green" by default.
    Automatically pauses while simulate_alert.py is running so both
    scripts can coexist without overwriting each other's readings.
    """
    import time
    print("Background Producer Started: Sending 'Normal' vitals every 5s ...")
    print("(Will pause automatically during live alert simulations)\n")

    while True:
        try:
            if is_sim_active():
                ts_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"  [{ts_str}] ⏸  Simulation active — heartbeat paused.")
                time.sleep(5)
                continue

            ts    = datetime.now(timezone.utc)
            batch = {}
            for wearer_id, cfg in WEARERS.items():
                r = sensor_simulator.generate_reading(wearer_id, "Normal", timestamp=ts)
                batch[cfg["container"]] = [[
                    ts,
                    r["heart_rate"],
                    r["spo2"],
                    r["temperature"],
                    r["activity_level"],
                    r["systolic_bp"],
                    r["diastolic_bp"],
                    r["blood_sugar"],
                ]]
            store.multi_put(batch)
            print(f"  [{ts.strftime('%H:%M:%S')}] Heartbeat sent.")
            time.sleep(5)

        except KeyboardInterrupt:
            print("\nShutting down live producer ...")
            break
        except Exception as e:
            print(f"Producer error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VitalWatch – GridDB data inserter")
    parser.add_argument(
        "--live", action="store_true",
        help="Run as a continuous background heartbeat producer"
    )
    args = parser.parse_args()

    try:
        print("Connecting to GridDB Cloud ...")
        store = get_gridstore()
        print("✓ Connected\n")

        print("Setting up containers ...")
        setup_containers(store)
        print()

        if args.live:
            live_producer(store)
        else:
            print("Generating wearable sensor dataset ...")
            dataset = sensor_simulator.generate_dataset(normal_count=60, disaster=True)
            total   = sum(len(v) for v in dataset.values())
            print(f"  Generated {total} total readings\n")

            print("Inserting data into GridDB Cloud ...")
            insert_dataset(store, dataset)
            print("\n✓ Historical data ingested successfully.")

    except Exception:
        import traceback
        traceback.print_exc()
