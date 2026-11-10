"""Build reports/triage_report.md from the outputs of train.py, evaluate.py and cluster.py."""
import json
from datetime import datetime

import pandas as pd

from data import DATA_DIR, ROOT, load_templates

REPORT_DIR = ROOT / "reports"
RAW_LOG = DATA_DIR.parent / "HDFS.log"
SAMPLE_BLOCKS = 2   # example blocks per cluster
SAMPLE_LINES = 4    # raw log lines per example block


def load(name):
    with open(REPORT_DIR / name) as f:
        return json.load(f)


def raw_lines(block_ids):
    """One pass over HDFS.log, collecting every line of the requested blocks."""
    wanted = {b: [] for b in block_ids}
    with open(RAW_LOG, errors="replace") as f:
        for line in f:
            i = line.find("blk_")
            if i < 0:
                continue
            j = i + 4
            while j < len(line) and (line[j].isdigit() or line[j] == "-"):
                j += 1
            hits = wanted.get(line[i:j])
            if hits is not None:
                hits.append(line.rstrip())
    return wanted


def matches(line, template):
    """True if the template's fixed parts appear in the line, in order."""
    pos = 0
    for part in filter(None, (p.strip() for p in template.split("[*]"))):
        pos = line.find(part, pos)
        if pos < 0:
            return False
        pos += len(part)
    return True


def pick_lines(lines, event_ids, templates):
    """Show lines for the cluster's defining events (top-ranked event first), then pad with the block's first lines."""
    def rank(line):
        return next((r for r, e in enumerate(event_ids) if matches(line, templates[e])), len(event_ids))

    ordered = sorted(lines, key=rank)  # stable sort keeps time order within each event
    return ordered[:SAMPLE_LINES]


def pct(v):
    return f"{v:.1%}"


def main():
    train = load("train_summary.json")
    res = load("results.json")
    clu = load("clusters.json")
    assign = pd.read_csv(REPORT_DIR / "failure_clusters.csv")
    templates = load_templates()

    samples = {c["cluster"]: assign.loc[assign["cluster"] == c["cluster"], "BlockId"]
               .sample(SAMPLE_BLOCKS, random_state=0).tolist() for c in clu["clusters"]}
    logs = raw_lines([b for bs in samples.values() for b in bs]) if RAW_LOG.exists() else {}

    rf, lr = res["models"]["Random Forest"], res["models"]["Logistic Regression"]
    ov = res["data_overlap"]
    unseen_rf = res["unseen_pattern_models"]["Random Forest"]
    n_test, n_fail = res["test_set"]["blocks"], res["test_set"]["failures"]
    total_fail = sum(c["size"] for c in clu["clusters"])
    top = clu["clusters"][:3]

    md = [
        "# LogTriage report: HDFS failure triage",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M} by `src/report.py`. "
        "Dataset: Loghub HDFS_v1 (Xu et al., SOSP 2009; Zhu et al., ISSRE 2023)._",
        "",
        "## Summary",
        f"- **{n_test:,} test sessions** analysed, **{n_fail:,} failures ({n_fail / n_test:.2%})**.",
        f"- The Random Forest caught **{rf['recall']:.2%}** of failures "
        f"(missed {rf['missed_failures']}) with **{rf['false_alarms']} false alarms**, vs. "
        f"{lr['false_alarms']} for the Logistic Regression baseline.",
        f"- {total_fail:,} failed sessions grouped into **{clu['k']} categories**. The three largest "
        f"cover {pct(sum(c['share'] for c in top))} of failures.",
        f"- The categories match the dataset's reference failure-type codes with ARI {clu['ari_vs_type']:.2f} "
        f"/ NMI {clu['nmi_vs_type']:.2f}, without using those codes.",
        "",
        "## Failure detection",
        "| Model | Precision | Recall | F1 | PR-AUC | Missed failures | False alarms | CV F1 (train) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, key in [("Logistic Regression", "logreg"), ("Random Forest", "random_forest")]:
        m = res["models"][name]
        md.append(f"| {name} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['pr_auc']:.4f} | "
                  f"{m['missed_failures']} | {m['false_alarms']} | {train[key]['cv_f1_mean']:.4f} |")
    md += [
        "",
        f"> **Caveat:** only {ov['distinct_event_vectors']} distinct event patterns exist, and "
        f"{ov['test_rows_seen_in_train']:.2%} of test sessions have an exact copy in training. "
        f"On the {ov['unseen_test_blocks']} test sessions with a pattern never seen in training "
        f"({ov['unseen_test_failures']} failures), Random Forest F1 is **{unseen_rf['f1']:.3f}** "
        f"(missed {unseen_rf['missed_failures']}, {unseen_rf['false_alarms']} false alarm). "
        "That subset is small, so treat it as indicative.",
        "",
        "![Confusion matrix](plots/confusion_matrix.png)",
        "",
        "## Failure categories",
        "Each category is named after its most distinctive log event (auto-generated).",
        "",
        "| # | Category (top event) | Sessions | Share | Purity vs. Type code |",
        "|---|---|---|---|---|",
    ]
    for c in clu["clusters"]:
        e = c["top_events"][0]
        md.append(f"| C{c['cluster']} | {e['event']}: `{e['template']}` | {c['size']:,} | {pct(c['share'])} | "
                  f"{c['dominant_type_share']:.0%} Type {c['dominant_type']} |")
    md += ["", "![Cluster profile](plots/cluster_profile.png)", "", "## Category details"]
    for c in clu["clusters"]:
        md += [
            f"### C{c['cluster']}: {c['size']:,} sessions ({pct(c['share'])})",
            "Defining events: " + "; ".join(f"**{e['event']}** `{e['template']}`" for e in c["top_events"]),
            "",
        ]
        event_ids = [e["event"] for e in c["top_events"]]
        for b in samples[c["cluster"]]:
            if logs.get(b):
                md += [f"Example `{b}` ({len(logs[b])} lines; defining events shown first):", "```",
                       *pick_lines(logs[b], event_ids, templates), "```"]
        md.append("")
    md += [
        "## Log events that signal failure",
        "Random Forest, ranked by permutation importance (drop in test F1 when the event is shuffled).",
        "",
        "| Event | Template | Permutation | Impurity |",
        "|---|---|---|---|",
        *[f"| {t['event']} | `{t['template']}` | {t['permutation']:.4f} | {t['impurity']:.4f} |"
          for t in res["top_events"]],
        "",
        "![Feature importance](plots/feature_importance.png)",
        "",
        "## Method and limitations",
        "- Features: per-session counts of 29 log templates (Loghub preprocessed). Stratified 80/20 split, seed 42.",
        "- Models tuned with 3-fold stratified CV on the training set only, scored by F1; threshold 0.5.",
        "- Categories: KMeans on TF-IDF of failed sessions' event counts. k chosen by silhouette, "
        f"capped at {clu['k']} for readability (silhouette kept rising).",
        "- Category names are derived from log templates, not verified root causes.",
        "- HDFS_v1 is a well-known, easy benchmark. These are system logs, not cellular test logs; "
        "the pipeline transfers, but the scores do not.",
    ]

    out = REPORT_DIR / "triage_report.md"
    out.write_text("\n".join(md) + "\n")
    print(f"Wrote {out.relative_to(ROOT)}  ({len(md)} lines, raw log samples: "
          f"{sum(bool(v) for v in logs.values())}/{len(logs)} blocks)")


if __name__ == "__main__":
    main()
