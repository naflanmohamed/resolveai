"""Small, transparent intent classifier for the portfolio demo.

The bundled examples are synthetic. Train and evaluate on real labeled support
traffic before calling this a production quality model.
"""
from functools import lru_cache
from pathlib import Path
import os
import json
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import Pipeline

DATA = {
    "Billing": [
        "I was charged twice on my card this month", "My invoice shows an incorrect total", "Why did my subscription renewal cost more", "Please refund the duplicate payment", "My credit card payment failed but money was deducted", "Need a copy of last month's invoice", "I want to change my billing address", "Can you explain the extra fee on my receipt", "The invoice contains the wrong tax", "I need to update my payment method", "Why am I billed for a cancelled plan", "My trial was charged before the end date", "The payment receipt has not arrived", "Request a refund for an accidental purchase", "I have a pricing question about the monthly plan", "Our annual subscription renewal amount is incorrect",
    ],
    "Technical": [
        "The dashboard keeps showing a server error", "Application crashes when I upload a file", "I cannot connect to the API endpoint", "The page is frozen after the latest update", "My integration returns a 500 error", "The site is slow and times out repeatedly", "Webhooks have stopped delivering events", "I found a bug in the mobile app", "The export button does not work", "Notifications are not loading in the dashboard", "I see a blank screen after signing in", "The database sync is failing every hour", "The application says service temporarily unavailable", "The report download is stuck", "Our integration stopped working after deployment", "There is a technical issue with the settings page",
    ],
    "Account": [
        "I forgot my password and cannot log in", "Help me reset my account password", "Please change the email linked to my account", "My account was locked after too many attempts", "How can I enable two factor authentication", "I want to delete my account", "Please update the owner of our workspace", "How can I invite a new team member", "I cannot verify my email address", "Our admin left and we need account access", "Can you change my username", "Need to recover access to my profile", "How do I deactivate the account", "My login verification link has expired", "My profile details are outdated", "Need to revoke access for a former employee",
    ],
    "Product": [
        "Does your platform support CSV exports", "Do you provide an integration with Slack", "Where can I find the product roadmap", "Can I enable dark mode in the dashboard", "How does the reporting feature work", "Is there a mobile application available", "Can the system support multiple workspaces", "Do you offer a trial for the team plan", "How many users can I invite", "Is there a feature for scheduled reports", "What options are available in the premium plan", "Do you support bulk document uploads", "Can I customize the dashboard", "Where is the API documentation", "Does your product have multilingual support", "What is the maximum upload size for documents",
    ],
}


@lru_cache(maxsize=1)
def classifier():
    model_path = os.getenv("ML_MODEL_PATH", "").strip()
    if model_path and Path(model_path).is_file():
        # Only load artifacts YOU generated. joblib files are not safe for untrusted input.
        return joblib.load(model_path)
    texts, labels = [], []
    for label, examples in DATA.items():
        for example in examples:
            texts.append(example)
            labels.append(label)
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)),
        ("model", LogisticRegression(max_iter=800, class_weight="balanced", random_state=42)),
    ])
    pipeline.fit(texts, labels)
    return pipeline


def predict(text: str) -> tuple[str, float]:
    model = classifier()
    probabilities = model.predict_proba([text[:12000]])[0]
    idx = int(probabilities.argmax())
    return str(model.classes_[idx]), round(float(probabilities[idx]), 3)


def evaluate() -> dict:
    model_path = os.getenv("ML_MODEL_PATH", "").strip()
    if model_path:
        metrics_file = Path(model_path + ".metrics.json")
        if metrics_file.is_file():
            return json.loads(metrics_file.read_text(encoding="utf-8"))
    texts, labels = [], []
    for label, examples in DATA.items():
        texts.extend(examples)
        labels.extend([label] * len(examples))
    train_x, test_x, train_y, test_y = train_test_split(texts, labels, test_size=0.25, random_state=42, stratify=labels)
    model = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)),
        ("model", LogisticRegression(max_iter=800, class_weight="balanced", random_state=42)),
    ])
    model.fit(train_x, train_y)
    pred = model.predict(test_x)
    return {
        "dataset": "64 synthetic examples (16 per category)",
        "warning": "Illustrative benchmark only; real-world generalization is unverified.",
        "train_samples": len(train_x),
        "test_samples": len(test_x),
        "accuracy": round(float(accuracy_score(test_y, pred)), 4),
        "report": classification_report(test_y, pred, output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(test_y, pred, labels=sorted(DATA)).tolist(),
        "labels": sorted(DATA),
    }
