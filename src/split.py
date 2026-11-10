"""Stratified 80/20 train/test split. The test set is not touched until final evaluation."""
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

from data import ROOT, load_data

SEED = 42
SPLIT_PATH = ROOT / "splits.npz"


def make_split():
    X, y, meta = load_data()
    idx = np.arange(len(X))
    train_idx, test_idx = train_test_split(
        idx, test_size=0.2, stratify=y, random_state=SEED
    )
    np.savez(SPLIT_PATH, train_idx=train_idx, test_idx=test_idx, seed=SEED)
    return y, train_idx, test_idx


def load_split():
    s = np.load(SPLIT_PATH)
    return s["train_idx"], s["test_idx"]


if __name__ == "__main__":
    y, train_idx, test_idx = make_split()
    assert len(np.intersect1d(train_idx, test_idx)) == 0
    assert len(train_idx) + len(test_idx) == len(y)
    for name, i in [("Train", train_idx), ("Test", test_idx)]:
        print(f"{name}: {len(i):,} blocks   anomalies: {y.iloc[i].sum():,} "
              f"({y.iloc[i].mean():.2%})")
    print(f"No overlap, all blocks used. Saved to {SPLIT_PATH.name} (seed={SEED})")
