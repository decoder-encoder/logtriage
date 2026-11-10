"""Load the preprocessed HDFS_v1 data and run sanity checks."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "HDFS_v1" / "preprocessed"


def load_templates():
    """EventId -> template text."""
    df = pd.read_csv(DATA_DIR / "HDFS.log_templates.csv")
    return dict(zip(df["EventId"], df["EventTemplate"]))


def load_data():
    """Return (X, y, meta).

    X    : event count matrix (one row per block, columns E1..E29)
    y    : 1 = anomaly, 0 = normal
    meta : BlockId and Type. Type is only set for failures, so it must never be used as a feature.
    """
    df = pd.read_csv(DATA_DIR / "Event_occurrence_matrix.csv")
    event_cols = [c for c in df.columns if c.startswith("E")]
    X = df[event_cols].astype("int32")
    y = (df["Label"] == "Fail").astype(int)
    meta = df[["BlockId", "Type"]]
    return X, y, meta


def check_data(X, y, meta):
    labels = pd.read_csv(DATA_DIR / "anomaly_label.csv")
    label_map = dict(zip(labels["BlockId"], labels["Label"] == "Anomaly"))
    matches = (meta["BlockId"].map(label_map).astype(int) == y).mean()

    print(f"Blocks: {len(X):,}   Event columns: {X.shape[1]}")
    print(f"Missing values: {int(X.isna().sum().sum())}")
    print(f"Duplicate BlockIds: {int(meta['BlockId'].duplicated().sum())}")
    print(f"Labels agree with anomaly_label.csv: {matches:.2%}")
    print(f"Normal: {(y == 0).sum():,}   Anomaly: {(y == 1).sum():,}   "
          f"Anomaly ratio: {y.mean():.2%}")
    print(f"Type filled for: {meta['Type'].notna().sum():,} blocks "
          f"(anomalies only: {meta.loc[meta['Type'].notna()].index.isin(y[y == 1].index).all()})")
    print("\nTop failure Types:")
    print(meta.loc[y == 1, "Type"].value_counts().head(10).to_string())
    print("\nEvents never seen (all-zero columns):",
          [c for c in X.columns if X[c].sum() == 0])
    print("\nEvents per block: "
          f"median {int(X.sum(axis=1).median())}, max {int(X.sum(axis=1).max())}")


if __name__ == "__main__":
    X, y, meta = load_data()
    check_data(X, y, meta)
    print(f"\nTemplates loaded: {len(load_templates())}")
