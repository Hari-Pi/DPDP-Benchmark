"""Chart the DPDPA-Bench results that scripts/benchmark.py writes.

Reads benchmark_results.json and renders a one-page summary:
headline rates, where the correct clause ranked, and how much
non-operative text each query pulled in.

    python scripts/report_charts.py [--results PATH] [--out PATH]
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
ACCENT = "#2a78d6"


def load(path: Path) -> pd.DataFrame:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        raise SystemExit(f"{path} has no records - run scripts/benchmark.py first.")
    df = pd.DataFrame(rows)
    for col in ("negative", "retrieval_hit", "answer_ok", "cites_expected"):
        if col not in df:
            df[col] = False
    df["ungrounded_count"] = df.get(
        "ungrounded_citations", pd.Series([[]] * len(df))
    ).apply(len)
    return df


def headline(df: pd.DataFrame) -> pd.DataFrame:
    """The three rates, weakest last so the gap is the thing you read."""
    pos = df[~df["negative"]]
    n = len(pos)
    return pd.DataFrame(
        [
            ("Correct clause retrieved", pos["retrieval_hit"].sum(), n),
            ("Answer factually correct", pos["answer_ok"].sum(), n),
            ("Cited the expected clause", pos["cites_expected"].sum(), n),
        ],
        columns=["metric", "passed", "total"],
    ).assign(rate=lambda d: d["passed"] / d["total"])


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


def panel_headline(ax, df):
    h = headline(df)
    weakest = h["rate"].idxmin()
    # Emphasis: the laggard carries the hue, the rest recede.
    colors = [ACCENT if i == weakest else MUTED for i in h.index]

    y = range(len(h))
    ax.barh(y, h["rate"], height=0.55, color=colors, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(h["metric"], color=INK_SOFT, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.34)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    for i, r in h.iterrows():
        ax.text(r["rate"] + 0.015, i, f"{r['rate']:.0%}  ({r['passed']}/{r['total']})",
                va="center", ha="left", color=INK, fontsize=9.5)
    style(ax)
    ax.set_title("Where the pipeline stands", color=INK, fontsize=12,
                 fontweight="bold", loc="left", pad=10)


def panel_rank(ax, df):
    hits = df[df["retrieval_hit"] & ~df["negative"]]
    counts = hits["retrieval_rank"].value_counts().sort_index()

    ax.bar(counts.index.astype(str), counts.values, width=0.5, color=ACCENT, zorder=3)
    ax.set_xlabel("Position of the correct clause among retrieved passages",
                  color=MUTED, fontsize=9.5, labelpad=8)
    for x, v in zip(counts.index.astype(str), counts.values):
        ax.text(x, v + counts.max() * 0.04, f"{v} question" + ("s" if v != 1 else ""),
                ha="center", color=INK, fontsize=9.5)
    ax.set_ylim(0, counts.max() * 1.22)
    style(ax)
    # Every bar is directly labelled, so the count axis is redundant.
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_title("How high it ranked", color=INK, fontsize=12,
                 fontweight="bold", loc="left", pad=10)


def panel_noise(ax, df):
    pos = df[~df["negative"]].sort_values("noise_ratio", ascending=True)
    y = range(len(pos))
    ax.barh(y, pos["noise_ratio"], height=0.6, color=MUTED, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(pos["id"], color=INK_SOFT, fontsize=8.5)
    ax.set_xlim(0, 1.0)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    mean = pos["noise_ratio"].mean()
    ax.axvline(mean, color=ACCENT, linewidth=1.5, zorder=4)
    ax.text(mean, -1.1, f"mean {mean:.0%}", color=ACCENT, fontsize=9,
            ha="center", va="center")
    ax.set_ylim(-1.6, len(pos) - 0.3)
    style(ax)
    ax.set_title("Share of retrieved text that is not operative law", color=INK,
                 fontsize=12, fontweight="bold", loc="left", pad=10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=Path("benchmark_results.json"))
    ap.add_argument("--out", type=Path, default=Path("docs/benchmark.png"))
    args = ap.parse_args()

    df = load(args.results)
    n_neg = int(df["negative"].sum())

    fig = plt.figure(figsize=(11, 9), facecolor=SURFACE)
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.5], hspace=0.45, wspace=0.3,
                          left=0.22, right=0.96, top=0.88, bottom=0.07)
    panel_headline(fig.add_subplot(gs[0, 0]), df)
    panel_rank(fig.add_subplot(gs[0, 1]), df)
    panel_noise(fig.add_subplot(gs[1, :]), df)

    fig.suptitle("DPDPA-Bench - retrieval and answer quality", x=0.02, y=0.965,
                 ha="left", color=INK, fontsize=15, fontweight="bold")
    sub = f"{len(df) - n_neg} answerable questions"
    sub += f" · {n_neg} unanswerable" if n_neg else " · no unanswerable cases in this run"
    fig.text(0.02, 0.925, sub, ha="left", color=INK_SOFT, fontsize=10)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=150, facecolor=SURFACE)
    print(f"wrote {args.out}")

    h = headline(df)
    for _, r in h.iterrows():
        print(f"  {r['metric']:<28} {r['rate']:.0%} ({r['passed']}/{r['total']})")
    print(f"  {'Ungrounded citations':<28} {int(df['ungrounded_count'].sum())}")
    if not n_neg:
        print("\nNote: no unanswerable cases present, so abstention is unmeasured.")


if __name__ == "__main__":
    main()
