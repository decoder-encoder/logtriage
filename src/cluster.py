"""Group failed blocks into failure categories with KMeans, and check the groups against the Type codes."""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score

from data import ROOT, load_data, load_templates
from evaluate import COLORS, INK, PLOT_DIR
from split import SEED

# Silhouette keeps rising with k (only ~600 distinct event vectors exist), so the upper bound is a
# readability cap: a triage report with more than 10 categories stops being useful.
K_RANGE = range(3, 11)
TOP_EVENTS = 3


def short(template, n=55):
    t = template.replace("[*]", " … ").strip(" …")
    return t if len(t) <= n else t[: n - 1] + "…"


def main():
    X, y, meta = load_data()
    templates = load_templates()
    fail = (y == 1).to_numpy()
    Xf, types, block_ids = X[fail], meta.loc[fail, "Type"].astype(int), meta.loc[fail, "BlockId"]

    # TF-IDF down-weights events every failure has; L2 rows make KMeans compare event mix, not session length
    Z = TfidfTransformer().fit_transform(Xf).toarray()

    scores = {}
    for k in K_RANGE:
        labels = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(Z)
        scores[k] = silhouette_score(Z, labels, sample_size=5000, random_state=SEED)
    best_k = max(scores, key=scores.get)
    km = KMeans(n_clusters=best_k, n_init=10, random_state=SEED).fit(Z)
    labels = km.labels_

    # Name each cluster by the events most over-represented vs. all failures
    overall = Z.mean(axis=0)
    clusters = []
    for c in np.argsort(-np.bincount(labels)):
        m = labels == c
        lift = Z[m].mean(axis=0) - overall
        top = np.argsort(-lift)[:TOP_EVENTS]
        top_type = types[m].value_counts()
        clusters.append({
            "cluster": int(c),
            "size": int(m.sum()),
            "share": float(m.mean()),
            "top_events": [{"event": X.columns[i], "template": short(templates[X.columns[i]])} for i in top],
            "dominant_type": int(top_type.index[0]),
            "dominant_type_share": float(top_type.iloc[0] / m.sum()),
            "n_types": int(top_type.size),
        })

    ari = adjusted_rand_score(types, labels)
    nmi = normalized_mutual_info_score(types, labels)

    pd.DataFrame({"BlockId": block_ids.to_numpy(), "cluster": labels, "Type": types.to_numpy()}).to_csv(
        ROOT / "reports" / "failure_clusters.csv", index=False)
    with open(ROOT / "reports" / "clusters.json", "w") as f:
        json.dump({"k": best_k, "silhouette": scores, "ari_vs_type": ari, "nmi_vs_type": nmi,
                   "clusters": clusters}, f, indent=2)

    plot_silhouette(scores, best_k)
    plot_clusters(clusters, Z, labels, X.columns, templates)

    print(f"Failed blocks clustered: {fail.sum():,}")
    print("Silhouette by k: " + ", ".join(f"{k}={s:.3f}" for k, s in scores.items()))
    print(f"Chosen k = {best_k}\n")
    for c in clusters:
        print(f"Cluster {c['cluster']}: {c['size']:,} blocks ({c['share']:.1%})   "
              f"dominant Type {c['dominant_type']} = {c['dominant_type_share']:.0%} of cluster "
              f"({c['n_types']} Types present)")
        for e in c["top_events"]:
            print(f"    {e['event']:>4}  {e['template']}")
    print(f"\nAgreement with reference Type codes: ARI {ari:.3f}, NMI {nmi:.3f}")
    print("Saved reports/clusters.json, reports/failure_clusters.csv, "
          "reports/plots/{silhouette,cluster_profile}.png")


def plot_silhouette(scores, best_k):
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    ks, vals = list(scores), list(scores.values())
    ax.plot(ks, vals, color=COLORS["Random Forest"], lw=2, marker="o", ms=8)
    ax.annotate(f"chosen k={best_k}", (best_k, scores[best_k]), textcoords="offset points",
                xytext=(-12, 0), ha="right", va="center", color=INK)
    ax.set(xlabel=f"Number of clusters (k, capped at {max(K_RANGE)} for readability)",
           ylabel="Silhouette score", title="Choosing k for failure clusters")
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "silhouette.png")
    plt.close(fig)


def plot_clusters(clusters, Z, labels, cols, templates):
    """Heatmap: rows = events used to name any cluster (readable text), columns = clusters (largest first)."""
    events = list(dict.fromkeys(e["event"] for c in clusters for e in c["top_events"]))
    idx = [list(cols).index(e) for e in events]
    mat = np.array([Z[labels == c["cluster"]][:, idx].mean(axis=0) for c in clusters]).T
    fig, ax = plt.subplots(figsize=(11, 0.42 * len(events) + 2))
    ax.imshow(mat, cmap="Blues", aspect="auto", vmin=0)
    ax.set_xticks(range(len(clusters)), [f"C{c['cluster']}\n{c['size']:,}" for c in clusters])
    ax.set_yticks(range(len(events)), [f"{e}: {short(templates[e], 50)}" for e in events])
    ax.tick_params(length=0)
    ax.grid(False)
    ax.set_xlabel("Failure cluster (number of blocks), largest first")
    fig.suptitle("What defines each failure cluster (darker = event weighs more)", x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "cluster_profile.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
