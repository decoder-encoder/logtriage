"""Train the Logistic Regression baseline and a tuned Random Forest. Uses the training set only."""
import json
import time
import warnings

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from data import ROOT, load_data
from split import SEED, load_split

# numpy on macOS uses Apple Accelerate, which raises spurious matmul FP warnings;
# coefficients were checked to be finite and LogReg converges.
warnings.filterwarnings("ignore", message=".*encountered in matmul", category=RuntimeWarning)

MODEL_DIR = ROOT / "models"


def baseline():
    # log1p tames heavy-tailed counts (e.g. E3 can be 200+)
    return make_pipeline(
        FunctionTransformer(np.log1p),
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=1000),
    )


def main():
    X, y, _ = load_data()
    train_idx, _ = load_split()
    X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
    cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
    MODEL_DIR.mkdir(exist_ok=True)
    summary = {}

    t = time.time()
    lr = baseline()
    lr_cv = cross_val_score(lr, X_tr, y_tr, cv=cv, scoring="f1")  # single process so the warning filter applies
    lr.fit(X_tr, y_tr)
    joblib.dump(lr, MODEL_DIR / "logreg.joblib")
    summary["logreg"] = {"cv_f1_mean": lr_cv.mean(), "cv_f1_std": lr_cv.std()}
    print(f"LogReg   CV F1: {lr_cv.mean():.4f} ± {lr_cv.std():.4f}   ({time.time() - t:.0f}s)")

    t = time.time()
    search = RandomizedSearchCV(
        RandomForestClassifier(class_weight="balanced", random_state=SEED, n_jobs=-1),
        param_distributions={
            "n_estimators": [100, 200, 300],
            "max_depth": [None, 10, 20, 40],
            "min_samples_leaf": [1, 2, 5],
            "max_features": ["sqrt", "log2", 0.5],
        },
        n_iter=10, scoring="f1", cv=cv, random_state=SEED,
    )
    search.fit(X_tr, y_tr)  # refit=True retrains the best params on the full training set
    rf = search.best_estimator_
    i = search.best_index_
    rf_mean = search.cv_results_["mean_test_score"][i]
    rf_std = search.cv_results_["std_test_score"][i]
    joblib.dump(rf, MODEL_DIR / "random_forest.joblib")
    summary["random_forest"] = {
        "cv_f1_mean": rf_mean, "cv_f1_std": rf_std, "best_params": search.best_params_,
    }
    print(f"RF       CV F1: {rf_mean:.4f} ± {rf_std:.4f}   best: {search.best_params_}   ({time.time() - t:.0f}s)")

    (ROOT / "reports").mkdir(exist_ok=True)
    with open(ROOT / "reports" / "train_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print("Saved models/logreg.joblib, models/random_forest.joblib, reports/train_summary.json")


if __name__ == "__main__":
    main()
