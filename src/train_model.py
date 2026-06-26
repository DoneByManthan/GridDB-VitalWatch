# train_model.py
# Machine Learning pipeline for VitalWatch.
#
# Loads all wearable readings from GridDB Cloud, builds a feature matrix,
# trains a Random Forest classifier to predict health risk level, evaluates
# the model, and saves it to disk for optional inference use.
#
# Feature columns:
#   heart_rate, spo2, temperature, activity_level,
#   systolic_bp, diastolic_bp, blood_sugar
#
# Target labels (derived from rule-based analysis, same logic as query_data.py):
#   0 = Normal    1 = Stress    2 = Distress    3 = Critical
#
# Usage:
#   python train_model.py
#   python train_model.py --no-save   (skip saving the model file)

import jpype
import os
import argparse
import numpy as np
import joblib

from datetime import datetime

# ── JVM / GridDB bootstrap ────────────────────────────────────────────────────
classpath = os.environ.get("CLASSPATH", "")
if not jpype.isJVMStarted():
    jpype.startJVM(classpath=classpath.split(":"))

import griddb_python as griddb

from vitals import WEARERS
import query_data

# scikit-learn imports
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score


# ── label mapping ─────────────────────────────────────────────────────────────
STATUS_TO_INT = {"Normal": 0, "Stress": 1, "Distress": 2, "Critical": 3}
INT_TO_STATUS = {v: k for k, v in STATUS_TO_INT.items()}


def _label_reading(wearer_id: str, reading: dict) -> int:
    """
    Assign a numeric health label to a single reading using the same
    rule-based logic defined in query_data.analyze_wearer().

    This produces training labels without requiring manual annotation.
    """
    status = query_data.analyze_wearer(wearer_id, [reading])["status"]
    return STATUS_TO_INT.get(status, 0)


# ── data loading from GridDB ──────────────────────────────────────────────────

def load_training_data(store) -> tuple:
    """
    Query all available readings from GridDB across all wearer containers.

    Returns
    -------
    X : np.ndarray of shape (n_samples, 7)
        Feature matrix with columns:
        [heart_rate, spo2, temperature, activity_level,
         systolic_bp, diastolic_bp, blood_sugar]
    y : np.ndarray of shape (n_samples,)
        Integer health labels.
    wearer_labels : list[str]
        Wearer ID for each sample (useful for analysis).
    """
    X, y, wearer_labels = [], [], []

    for wearer_id in WEARERS:
        print(f"  Loading data for: {WEARERS[wearer_id]['display_name']} ...", end=" ")
        readings = query_data.query_recent(store, wearer_id, limit=500)

        for r in readings:
            features = [
                r["heart_rate"],
                r["spo2"],
                r["temperature"],
                r["activity_level"],
                r["systolic_bp"],
                r["diastolic_bp"],
                r["blood_sugar"],
            ]
            label = _label_reading(wearer_id, r)
            X.append(features)
            y.append(label)
            wearer_labels.append(wearer_id)

        print(f"{len(readings)} readings loaded.")

    return np.array(X), np.array(y), wearer_labels


# ── model training ────────────────────────────────────────────────────────────

def train(X: np.ndarray, y: np.ndarray) -> tuple:
    """
    Split data, train a Random Forest classifier, and return the model
    together with the held-out test split for evaluation.

    Random Forest is chosen because:
      - It handles the mix of physiological features well with no scaling needed.
      - It is robust to the relatively small dataset sizes typical in wearable demos.
      - Feature importances are easy to extract and explain.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y if len(np.unique(y)) > 1 else None
    )

    print(f"\n  Training samples : {len(X_train)}")
    print(f"  Test samples     : {len(X_test)}")

    model = RandomForestClassifier(
        n_estimators=150,
        max_depth=10,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    return model, X_test, y_test


# ── evaluation ────────────────────────────────────────────────────────────────

def evaluate(model, X_test: np.ndarray, y_test: np.ndarray) -> None:
    """Print a classification report and confusion matrix."""
    y_pred = model.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    print(f"\n  Test Accuracy: {acc * 100:.1f}%\n")

    labels_present = sorted(np.unique(np.concatenate([y_test, y_pred])))
    target_names   = [INT_TO_STATUS[l] for l in labels_present]

    print("  Classification Report:")
    print(classification_report(y_test, y_pred, labels=labels_present, target_names=target_names))

    print("  Confusion Matrix (rows=actual, cols=predicted):")
    cm = confusion_matrix(y_test, y_pred, labels=labels_present)
    header = "  " + "  ".join(f"{n:>10}" for n in target_names)
    print(header)
    for row_label, row in zip(target_names, cm):
        print(f"  {row_label:>10}  " + "  ".join(f"{v:>10}" for v in row))


def feature_importances(model) -> None:
    """Print the relative importance of each feature."""
    feature_names = [
        "heart_rate", "spo2", "temperature", "activity_level",
        "systolic_bp", "diastolic_bp", "blood_sugar",
    ]
    importances = model.feature_importances_
    ranked      = sorted(zip(feature_names, importances), key=lambda x: x[1], reverse=True)

    print("\n  Feature Importances:")
    for name, score in ranked:
        bar = "█" * int(score * 40)
        print(f"  {name:>20}  {bar:<40}  {score:.4f}")


# ── inference example ─────────────────────────────────────────────────────────

def run_inference_example(model) -> None:
    """
    Demonstrate model inference on two manually crafted readings:
    one clearly healthy and one clearly stressed.
    """
    examples = [
        {
            "label":   "Healthy Office Worker",
            "reading": [72, 98, 36.5, 20, 122, 81, 93],
        },
        {
            "label":   "Stressed Athlete",
            "reading": [168, 91, 38.3, 145, 148, 98, 127],
        },
    ]

    print("\n  Inference Examples:")
    for ex in examples:
        feat    = np.array([ex["reading"]])
        pred    = model.predict(feat)[0]
        proba   = model.predict_proba(feat)[0]
        col_idx = list(model.classes_).index(pred)
        status  = INT_TO_STATUS[pred]
        conf    = proba[col_idx] * 100
        print(f"  {ex['label']:30} → Predicted: {status:10} (confidence: {conf:.1f}%)")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VitalWatch – ML model trainer")
    parser.add_argument("--no-save", action="store_true", help="Skip saving the model to disk")
    args = parser.parse_args()

    print("=" * 60)
    print("  VitalWatch – Health Risk Classifier Training")
    print("=" * 60)

    try:
        print("\nConnecting to GridDB Cloud ...")
        store = query_data.get_gridstore()
        print("✓ Connected\n")

        print("Loading wearable readings from GridDB ...")
        X, y, wearer_labels = load_training_data(store)
        print(f"\n  Total samples loaded: {len(X)}")

        if len(X) < 10:
            print("\n⚠  Not enough data to train. Run insert_data.py first.")
            raise SystemExit(1)

        # Label distribution
        unique, counts = np.unique(y, return_counts=True)
        print("\n  Label distribution:")
        for label, count in zip(unique, counts):
            print(f"    {INT_TO_STATUS[label]:12}: {count:4} samples  ({count/len(y)*100:.1f}%)")

        print("\nTraining Random Forest Classifier ...")
        model, X_test, y_test = train(X, y)
        print("✓ Training complete.")

        evaluate(model, X_test, y_test)
        feature_importances(model)
        run_inference_example(model)

        if not args.no_save:
            model_path = os.path.join(os.path.dirname(__file__), "vitalwatch_model.pkl")
            joblib.dump(model, model_path)
            print(f"\n✓ Model saved → {model_path}")

        print("\n✓ Pipeline complete.")

    except SystemExit:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
