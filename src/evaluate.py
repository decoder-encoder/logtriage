"""Final evaluation on the held-out test set: metrics, confusion matrices, PR curves, feature importance."""
import json
import warnings

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix, f1_score,
                             precision_recall_curve, precision_score, recall_score)

from data import ROOT, load_data, load_templates
from split import SEED, load_split

# Same spurious Apple Accelerate warning as in train.py
warnings.filterwarnings("ignore", message=".*encountered in matmul", category=RuntimeWarning)

PLOT_DIR = ROOT / "reports" / "plots"
MODELS = {"Logistic Regression": "logreg", "Random Forest": "random_forest"}
COLORS = {"Logistic Regression": "#eb6834", "Random Forest": "#2a78d6"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "figure.dpi": 150,
})


def metrics(y_true, y_pred, y_score):
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred),
        "recall": recall_score(y_true, y_pred),
        "f1": f1_score(y_true, y_pred),
        "pr_auc": average_precision_score(y_true, y_score),
        "missed_failures": int(((y_true == 1) & (y_pred == 0)).sum()),
        "false_alarms": int(((y_true == 0) & (y_pred == 1)).sum()),
    }


def plot_confusion(cms):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    for ax, (name, cm) in zip(axes, cms.items()):
        ax.imshow(cm / cm.sum(axis=1, keepdims=True), cmap="Blues", vmin=0, vmax=1)
        for (i, j), v in np.ndenumerate(cm):
            ax.text(j, i, f"{v:,}", ha="center", va="center",
                    color="white" if i == j else INK, fontsize=11)
        ax.set(title=name, xticks=[0, 1], yticks=[0, 1],
               xticklabels=["Normal", "Failure"], yticklabels=["Normal", "Failure"],
               xlabel="Predicted", ylabel="Actual")
        ax.grid(False)
    fig.suptitle("Confusion matrix on test set (cell shade = row %)", x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "confusion_matrix.png")
    plt.close(fig)


def plot_pr(curves, y_test):
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for name, (p, r, ap) in curves.items():
        ax.plot(r, p, color=COLORS[name], lw=2, label=f"{name} (PR-AUC {ap:.3f})")
    ax.axhline(y_test.mean(), color=MUTED, lw=1, ls="--", label=f"Random guess ({y_test.mean():.1%})")
    ax.set(xlabel="Recall (share of failures caught)", ylabel="Precision (share of alerts that are real)",
           xlim=(0, 1.01), ylim=(0, 1.02), title="Precision–recall on test set")
    ax.legend(loc="lower left", frameon=False)
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "pr_curve.png")
    plt.close(fig)


def plot_importance(imp):
    top = imp.head(10).iloc[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for ax, col, title in [(axes[0], "impurity", "Impurity-based"),
                           (axes[1], "permutation", "Permutation (drop in test F1)")]:
        ax.barh(top["label"], top[col], color=COLORS["Random Forest"], height=0.6)
        ax.set_title(title)
        ax.grid(axis="y", visible=False)
    fig.suptitle("Random Forest: top 10 log events that signal a failure", x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "feature_importance.png")
    plt.close(fig)


def main():
    X, y, _ = load_data()
    train_idx, test_idx = load_split()
    X_te, y_te = X.iloc[test_idx], y.iloc[test_idx]
    templates = load_templates()
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    # Only a few hundred distinct event vectors exist, so most test rows have an exact copy in train.
    # The "unseen" subset (pattern never seen in training) is the honest generalization check.
    row_hash = pd.util.hash_pandas_object(X, index=False)
    unseen = ~row_hash.iloc[test_idx].isin(set(row_hash.iloc[train_idx])).to_numpy()

    results, unseen_results, cms, curves = {}, {}, {}, {}
    for name, fname in MODELS.items():
        model = joblib.load(ROOT / "models" / f"{fname}.joblib")
        score = model.predict_proba(X_te)[:, 1]
        pred = (score >= 0.5).astype(int)
        results[name] = metrics(y_te, pred, score)
        cms[name] = confusion_matrix(y_te, pred)
        p, r, _ = precision_recall_curve(y_te, score)
        curves[name] = (p, r, results[name]["pr_auc"])
        yu, pu = y_te.to_numpy()[unseen], pred[unseen]
        unseen_results[name] = {
            "f1": f1_score(yu, pu), "recall": recall_score(yu, pu), "precision": precision_score(yu, pu),
            "missed_failures": int(((yu == 1) & (pu == 0)).sum()),
            "false_alarms": int(((yu == 0) & (pu == 1)).sum()),
        }

    rf = joblib.load(ROOT / "models" / "random_forest.joblib")
    perm = permutation_importance(rf, X_te, y_te, scoring="f1", n_repeats=5, random_state=SEED, n_jobs=-1)
    imp = pd.DataFrame({
        "event": X.columns, "impurity": rf.feature_importances_,
        "permutation": perm.importances_mean, "permutation_std": perm.importances_std,
    }).sort_values("permutation", ascending=False)
    imp["template"] = imp["event"].map(templates).str.replace("[*]", " … ", regex=False).str.strip(" …")
    imp["label"] = imp["event"] + ": " + imp["template"].str.slice(0, 40)

    plot_confusion(cms)
    plot_pr(curves, y_te)
    plot_importance(imp)

    out = {
        "test_set": {"blocks": len(y_te), "failures": int(y_te.sum())},
        "threshold": 0.5,
        "models": results,
        "data_overlap": {
            "distinct_event_vectors": int(row_hash.nunique()),
            "test_rows_seen_in_train": float(1 - unseen.mean()),
            "unseen_test_blocks": int(unseen.sum()),
            "unseen_test_failures": int(y_te.to_numpy()[unseen].sum()),
        },
        "unseen_pattern_models": unseen_results,
        "top_events": imp.head(10)[["event", "template", "impurity", "permutation"]].to_dict("records"),
    }
    with open(ROOT / "reports" / "results.json", "w") as f:
        json.dump(out, f, indent=2)

    table = pd.DataFrame(results).T
    print(f"Test set: {len(y_te):,} blocks, {int(y_te.sum()):,} failures\n")
    print(table.to_string(float_format=lambda v: f"{v:.4f}"))
    print(f"\nDistinct event vectors: {row_hash.nunique():,}. Test rows with an exact copy in train: "
          f"{1 - unseen.mean():.2%}")
    print(f"Unseen-pattern test subset: {unseen.sum()} blocks, {int(y_te.to_numpy()[unseen].sum())} failures")
    print(pd.DataFrame(unseen_results).T.to_string(float_format=lambda v: f"{v:.4f}"))
    print("\nTop 10 events (Random Forest, by permutation importance on test F1):")
    print(imp.head(10)[["event", "permutation", "impurity", "template"]].to_string(
        index=False, float_format=lambda v: f"{v:.4f}"))
    print("\nSaved reports/results.json and reports/plots/{confusion_matrix,pr_curve,feature_importance}.png")


if __name__ == "__main__":
    main()
