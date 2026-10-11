"""Train a customized support-ticket classifier from labeled CSV data.

Usage:
  python train_model.py --example-csv labeled_examples.csv
  python train_model.py --csv my_training_data.csv --output models/intent.joblib

Input CSV must contain `text` and `label` columns. The script creates a held-out
classification report and then refits on all examples to produce the final
artifact. Only load artifacts you generated yourself; joblib uses pickle.
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from app.ml import DATA


def make_pipeline():
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)),
        ("model", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
    ])


def main():
    parser = argparse.ArgumentParser(description="Train a supervised ticket classifier")
    parser.add_argument("--example-csv", type=Path, help="Write synthetic example CSV for experimentation and exit")
    parser.add_argument("--csv", type=Path, help="Input CSV containing text,label columns")
    parser.add_argument("--output", type=Path, default=Path("models/intent.joblib"))
    args = parser.parse_args()
    if args.example_csv:
        args.example_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.example_csv.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["text", "label"])
            writer.writeheader()
            for label, examples in DATA.items():
                for text in examples:
                    writer.writerow({"text": text, "label": label})
        print(f"Wrote {sum(map(len, DATA.values()))} synthetic examples to {args.example_csv}")
        return
    if not args.csv:
        parser.error("--csv required, or use --example-csv to make starter data")
    with args.csv.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or not {"text", "label"}.issubset(rows[0]):
        parser.error("CSV must have text and label headers")
    clean = [(row["text"].strip(), row["label"].strip()) for row in rows if row["text"].strip() and row["label"].strip()]
    texts = [row[0] for row in clean]
    labels = [row[1] for row in clean]
    counts = Counter(labels)
    if len(counts) < 2 or min(counts.values()) < 5:
        parser.error("Provide >=2 classes with >=5 labeled examples per class")
    train_x, test_x, train_y, test_y = train_test_split(texts, labels, test_size=0.25, random_state=42, stratify=labels)
    model = make_pipeline()
    model.fit(train_x, train_y)
    pred = model.predict(test_x)
    classes = sorted(counts)
    metrics = {
        "dataset": f"Custom labeled CSV ({len(texts)} examples)",
        "warning": "Metrics are from a random held-out split. Check dataset representativeness, leakage and out-of-distribution performance.",
        "train_samples": len(train_x), "test_samples": len(test_x),
        "accuracy": round(float(accuracy_score(test_y, pred)), 4),
        "report": classification_report(test_y, pred, output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(test_y, pred, labels=classes).tolist(),
        "labels": classes,
    }
    # Fit final inference model on the full dataset AFTER evaluating hold-out.
    final = make_pipeline()
    final.fit(texts, labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, args.output)
    Path(str(args.output) + ".metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({"model": str(args.output), "accuracy": metrics["accuracy"], "train_samples": len(train_x), "test_samples": len(test_x)}, indent=2))
    print("Set ML_MODEL_PATH to the model's absolute file path, then restart the API.")


if __name__ == "__main__":
    main()
