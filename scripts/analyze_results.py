#!/usr/bin/env python3
"""Compute speedup / efficiency from results/raw_results.csv and draw plots.

Two sequential baselines are used (p = number of workers, T(p) = mean total
time of the parallel algorithm measured on the master):

  * T_seq   -- the sequential algorithm run on the master node (as measured);
  * T_seq*  -- pure encryption time of ONE worker processing the whole input
               (compute_max_s at p = 1). The master turned out to encrypt about
               10 % slower than a worker, so T_seq slightly overstates the
               speedup; T_seq* gives a conservative estimate.

    S(p)  = T_seq  / T(p),   E(p)  = S(p)  / p
    S*(p) = T_seq* / T(p),   E*(p) = S*(p) / p

Outputs:
    results/analysis.csv          one row per (size, p) with means and metrics
    report/figures/*.pdf, *.png   plots for the report
    report/tables/*.tex           LaTeX table bodies included by the report

Usage:
    python3 scripts/analyze_results.py [results/raw_results.csv]
"""
import csv
import os
import statistics
import sys
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FIG_DIR = os.path.join(ROOT, "report", "figures")
TAB_DIR = os.path.join(ROOT, "report", "tables")

# Categorical slots 1-4 of the reference palette (validated, adjacent pairs),
# plus distinct markers so series are not identified by color alone.
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
MARKERS = ["o", "s", "^", "D"]
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
REFERENCE = "#8a8984"
OVERHEAD_COLORS = {"compute": "#2a78d6", "network": "#eb6834", "prepare": "#1baf7a", "merge": "#eda100"}


def load(path):
    with open(path) as f:
        rows = [r for r in csv.DictReader(f)]
    bad = [r for r in rows if r["matches_sequential"] != "1"]
    if bad:
        sys.exit("%d runs do not match the sequential result!" % len(bad))
    return rows


def aggregate(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(int(r["size_bytes"]), int(r["workers"]))].append(r)
    agg = {}
    for key, items in groups.items():
        def mean(col):
            return statistics.mean(float(r[col]) for r in items)

        def std(col):
            values = [float(r[col]) for r in items]
            return statistics.stdev(values) if len(values) > 1 else 0.0

        agg[key] = {
            "runs": len(items),
            "total": mean("total_s"), "total_std": std("total_s"),
            "compute_max": mean("compute_max_s"),
            "compute_sum": mean("compute_sum_s"),
            "overhead": mean("overhead_s"),
            "prepare": mean("prepare_s"), "merge": mean("merge_s"),
            "wait": mean("wait_s"),
        }
    return agg


def metrics(agg):
    sizes = sorted({s for s, _ in agg})
    out = []
    for size in sizes:
        t_seq = agg[(size, 0)]["total"]
        t_seq_worker = agg[(size, 1)]["compute_max"]
        for p in sorted(w for s, w in agg if s == size):
            a = agg[(size, p)]
            row = {
                "size_mb": size / 2 ** 20, "workers": p, "runs": a["runs"],
                "total_s": a["total"], "total_std_s": a["total_std"],
                "compute_max_s": a["compute_max"], "overhead_s": a["overhead"],
                "prepare_s": a["prepare"], "merge_s": a["merge"],
                # network + Pyro4 serialisation + base64 on the workers:
                "transfer_s": a["wait"] - a["compute_max"],
                "throughput_mb_s": size / 2 ** 20 / a["total"],
            }
            if p > 0:
                row["speedup"] = t_seq / a["total"]
                row["efficiency"] = row["speedup"] / p
                row["speedup_worker_base"] = t_seq_worker / a["total"]
                row["efficiency_worker_base"] = row["speedup_worker_base"] / p
                row["overhead_share"] = a["overhead"] / a["total"]
            else:
                row.update(speedup=1.0, efficiency="", speedup_worker_base="",
                           efficiency_worker_base="", overhead_share=0.0)
            out.append(row)
    return out


def style_axes(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel, color=INK_SECONDARY)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_SECONDARY)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(REFERENCE)
    ax.tick_params(colors=INK_SECONDARY)


def save(fig, name):
    os.makedirs(FIG_DIR, exist_ok=True)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(FIG_DIR, "%s.%s" % (name, ext)), dpi=200)
    plt.close(fig)


def by_size(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r["size_mb"]].append(r)
    return sorted(groups.items())


def plot_time(rows):
    """Time vs p. The sequential run is a separate point (not joined by a line):
    it is a different algorithm, not "0 workers"."""
    p_max = max(r["workers"] for r in rows)
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    ax.axvline(0.5, color=GRID, linewidth=1.2)
    for i, (size, items) in enumerate(by_size(rows)):
        seq = [r for r in items if r["workers"] == 0][0]
        par = [r for r in items if r["workers"] > 0]
        style = dict(color=SERIES_COLORS[i], marker=MARKERS[i], markersize=6)
        ax.plot([0], [seq["total_s"]], linestyle="none", markerfacecolor="white",
                markeredgewidth=2, **style)
        ax.errorbar([r["workers"] for r in par], [r["total_s"] for r in par],
                    yerr=[r["total_std_s"] for r in par], linewidth=2, capsize=3,
                    label="%g МіБ" % size, **style)
    ax.set_yscale("log")
    ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "%g" % v))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.set_ylim(0.1, 50)
    ax.set_xticks(range(0, p_max + 1))
    ax.set_xticklabels(["посл."] + [str(p) for p in range(1, p_max + 1)])
    style_axes(ax, "Кількість воркерів p (посл. = послідовний алгоритм на master)",
               "Час T, с (логарифмічна шкала)")
    ax.legend(title="Розмір даних", frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    save(fig, "time_vs_workers")


def plot_two_baselines(rows, key, key_worker, symbol, ylabel, ideal, name, ylim):
    """Two panels: (a) baseline = sequential on master, (b) baseline = one worker."""
    par = [r for r in rows if r["workers"] > 0]
    p_max = max(r["workers"] for r in par)
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.9), sharey=True)
    titles = ["(а) %s: база — послідовний алгоритм на master" % symbol,
              "(б) %s*: база — шифрування одним воркером" % symbol]
    for ax, metric, title in zip(axes, (key, key_worker), titles):
        if ideal == "linear":
            ax.plot([1, p_max], [1, p_max], color=REFERENCE, linestyle="--", linewidth=1.5,
                    label="Ідеальне")
        else:
            ax.axhline(1.0, color=REFERENCE, linestyle="--", linewidth=1.5, label="Ідеальна")
        for i, (size, items) in enumerate(by_size(par)):
            ax.plot([r["workers"] for r in items], [r[metric] for r in items],
                    color=SERIES_COLORS[i], marker=MARKERS[i], markersize=6, linewidth=2,
                    label="%g МіБ" % size)
        ax.set_xticks(range(1, p_max + 1))
        ax.set_xlim(0.8, p_max + 0.2)
        ax.set_ylim(*ylim)
        ax.set_title(title, fontsize=9, color=INK_SECONDARY)
        style_axes(ax, "Кількість воркерів p", ylabel if ax is axes[0] else "")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=5, loc="lower center", fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    os.makedirs(FIG_DIR, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(FIG_DIR, "%s.%s" % (name, ext)), dpi=200)
    plt.close(fig)


def plot_breakdown(rows, size_mb):
    items = [r for r in rows if r["size_mb"] == size_mb and r["workers"] > 0]
    labels = [str(r["workers"]) for r in items]
    parts = [
        ("compute", "Шифрування (найповільніший воркер)", [r["compute_max_s"] for r in items]),
        ("network", "Передача, серіалізація Pyro4, base64 на воркерах", [r["transfer_s"] for r in items]),
        ("prepare", "Розбиття + base64 на master", [r["prepare_s"] for r in items]),
        ("merge", "Декодування + склеювання на master", [r["merge_s"] for r in items]),
    ]
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    bottom = [0.0] * len(items)
    for key, label, values in parts:
        ax.bar(labels, values, bottom=bottom, width=0.55, color=OVERHEAD_COLORS[key],
               edgecolor="white", linewidth=2, label=label)
        bottom = [b + v for b, v in zip(bottom, values)]
    t_seq = [r for r in rows if r["size_mb"] == size_mb and r["workers"] == 0][0]["total_s"]
    ax.axhline(t_seq, color=REFERENCE, linestyle="--", linewidth=1.5)
    ax.text(len(items) - 0.6, t_seq, "послідовний алгоритм на master: %.3g с" % t_seq,
            color=INK_SECONDARY, ha="right", va="bottom", fontsize=9)
    style_axes(ax, "Кількість воркерів p", "Час, с")
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    save(fig, "breakdown_%gmb" % size_mb)


def fmt(value, digits=3):
    return "--" if value == "" else ("%.*f" % (digits, value))


def write_tables(rows):
    os.makedirs(TAB_DIR, exist_ok=True)
    # Rules are written here (not in report.tex): \input followed by \bottomrule
    # inside a tabular gives "Misplaced \noalign".
    with open(os.path.join(TAB_DIR, "results_table.tex"), "w") as f:
        for i, (size, items) in enumerate(by_size(rows)):
            if i:
                f.write("\\midrule\n")
            for r in items:
                f.write("%g & %s & %s $\\pm$ %s & %s & %s & %s & %s & %s & %s \\\\\n" % (
                    size, "посл." if r["workers"] == 0 else r["workers"],
                    fmt(r["total_s"]), fmt(r["total_std_s"]), fmt(r["compute_max_s"]),
                    fmt(r["overhead_s"]), fmt(r["speedup"], 2), fmt(r["efficiency"], 2),
                    fmt(r["speedup_worker_base"], 2), fmt(r["efficiency_worker_base"], 2)))
        f.write("\\bottomrule\n")
    with open(os.path.join(TAB_DIR, "overhead_table.tex"), "w") as f:
        for size, items in by_size(rows):
            shares = ["%.0f\\%%" % (100 * r["overhead_share"]) for r in items if r["workers"] >= 1]
            f.write("%g & %s \\\\\n" % (size, " & ".join(shares)))
        f.write("\\bottomrule\n")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results", "raw_results.csv")
    rows = metrics(aggregate(load(path)))

    out = os.path.join(ROOT, "results", "analysis.csv")
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    plot_time(rows)
    plot_two_baselines(rows, "speedup", "speedup_worker_base", "S", "Прискорення",
                       "linear", "speedup", (0, 4.3))
    plot_two_baselines(rows, "efficiency", "efficiency_worker_base", "E", "Ефективність",
                       "one", "efficiency", (0, 1.1))
    plot_breakdown(rows, max(r["size_mb"] for r in rows))
    write_tables(rows)

    print("size_MB  p   T,s      S     E      S*    E*    overhead")
    for r in rows:
        print("%6g  %2d  %7.3f  %5.2f  %5s  %5s  %5s  %6.1f%%" % (
            r["size_mb"], r["workers"], r["total_s"], r["speedup"], fmt(r["efficiency"], 2),
            fmt(r["speedup_worker_base"], 2), fmt(r["efficiency_worker_base"], 2),
            100 * r["overhead_share"]))
    print("Wrote %s, figures to %s, tables to %s" % (out, FIG_DIR, TAB_DIR))


if __name__ == "__main__":
    main()
