import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from venn import pseudovenn

if len(sys.argv) != 5:
    print(f"Usage: python {sys.argv[0]} <svcomp_results.csv> <svcomp_complexity.csv> <coqgym_results.csv> <coqgym_complexity.csv>")
    sys.exit(1)


tools = ["AutoRocq", "Rango", "PALM", "COPRA", "QEDCartographer", "Proverbot9001"]
names = ["AutoRocq", "Rango", "PALM", "COPRA", "QEDC", "P9001"]
colors = [
    "#455db4",
    "#5eb3ae",
    "#9ec25f",
    "#ffb968",
    "#ff9989",
    "#d5a0d5",
]

# Prepare SV-Comp results

svcomp_result_file = sys.argv[1]
complexity_file_1 = sys.argv[2]
svcomp_df = pd.read_csv(svcomp_result_file)
svcomp_complexity = pd.read_csv(complexity_file_1)

merged_svcomp = pd.merge(svcomp_df, svcomp_complexity, on="lemma_name", how="inner")

# Prepare CoqGym results

coqgym_result_file = sys.argv[3]
complexity_file_2 = sys.argv[4]
coqgym_df = pd.read_csv(coqgym_result_file)
coqgym_complexity = pd.read_csv(complexity_file_2)

def normalize_lemma_name(name):
    if pd.isnull(name):
        return ""
    return str(name).split(":")[0].strip().lower()

coqgym_df["lemma_name_norm"] = coqgym_df["lemma_name"].apply(normalize_lemma_name)
coqgym_complexity["lemma_name_norm"] = coqgym_complexity["lemma_name"].apply(normalize_lemma_name)

merged_coqgym = pd.merge(coqgym_df, coqgym_complexity, on=["file", "lemma_name_norm"], how="left")

# Setup plot style
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 12,
        "axes.linewidth": 1.2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.alpha": 0.3,
        "figure.dpi": 300,
    }
)

# 1. Total successes per tool by benchmark

succ_svcomp = []
for tool in tools:
    col = f"{tool}_succ"
    if col in merged_svcomp.columns:
        succ_svcomp.append((tool, merged_svcomp[col].sum()))
    else:
        succ_svcomp.append((tool, 0))

succ_coqgym = []
for tool in tools:
    col = f"{tool}_succ"
    if col in merged_coqgym.columns:
        succ_coqgym.append((tool, merged_coqgym[col].sum()))
    else:
        succ_coqgym.append((tool, 0))

# Prepare tool success sets for Venn diagrams
tool_success_sets_coqgym = {}
for tool in tools:
    col = f"{tool}_succ"
    if col in merged_coqgym.columns:
        tool_success_sets_coqgym[tool] = set(merged_coqgym.loc[merged_coqgym[col] == 1, "lemma_name_norm"])
    else:
        tool_success_sets_coqgym[tool] = set()

tool_success_sets_svcomp = {}
for tool in tools:
    col = f"{tool}_succ"
    if col in merged_svcomp.columns:
        tool_success_sets_svcomp[tool] = set(merged_svcomp.loc[merged_svcomp[col] == 1, "lemma_name"])
    else:
        tool_success_sets_svcomp[tool] = set()

# Consistent font size for all text
title_size = 18
text_size = 16

def draw_combined_plot(benchmark_name, succ_data, tool_success_sets, output_name, ylim_val):
    """Draw a combined plot with Venn diagram and bar plot for a single benchmark."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 6), gridspec_kw={'width_ratios': [1, 1.3]})
    
    # Left: Bar plot (smaller)
    bar_width = 0.6
    x = np.arange(len(tools))
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(names, fontsize=text_size-2, rotation=35, ha='center')
    axes[0].tick_params(axis='y', labelsize=text_size, labelrotation=45)
    axes[0].set_ylim(0, ylim_val)
    axes[0].set_title("# of Proved Lemmas", fontsize=title_size)
    axes[0].set_axisbelow(True)
    axes[0].grid(True, linestyle="--", alpha=0.6, axis='y')
    
    vals = [succ_data[idx][1] for idx in range(len(tools))]
    bars = axes[0].bar(x, vals, bar_width, color=colors, alpha=1.0)
    # Add number on top of each bar
    for bar in bars:
        height = bar.get_height()
        axes[0].text(bar.get_x() + bar.get_width()/2, height + 2, f'{int(height)}', 
                     ha='center', va='bottom', fontsize=text_size)
    
    # Right: Venn diagram (larger)
    pseudovenn(tool_success_sets, cmap=colors, fontsize=text_size, ax=axes[1], hint_hidden=False, legend_loc=None)
    axes[1].autoscale()
    axes[1].margins(0.001)
    axes[1].set_title("Venn Diagram", fontsize=title_size)
    
    # Single legend at the center top
    legend_handles = [mpatches.Patch(color=colors[i], label=names[i]) for i in range(len(tools))]
    fig.legend(handles=legend_handles, loc="upper center", ncol=len(tools), fontsize=title_size, 
               bbox_to_anchor=(0.5, 1.02), frameon=False,
               columnspacing=1.0, handletextpad=0.3, handlelength=1.0)
    fig.suptitle(benchmark_name, fontsize=22, fontweight="bold", y=1.08)
    plt.tight_layout()
    plt.subplots_adjust(top=0.82, wspace=-0.05) # spacing in between
    
    # Move venn diagram lower and scale it larger (without affecting title)
    pos = axes[1].get_position()
    axes[1].set_position([pos.x0 + 0.03, pos.y0 - 0.08, pos.width * 1.15, pos.height * 1.15])
    
    plt.savefig(output_name, bbox_inches='tight', dpi=300)
    plt.close()


# Draw combined plot for CoqGym
draw_combined_plot("Mathematical Lemmas (CoqGym)", succ_coqgym, tool_success_sets_coqgym, "coqgym_results.pdf", 900)

# Draw combined plot for SV-COMP
draw_combined_plot("Verification Lemmas (SV-COMP)", succ_svcomp, tool_success_sets_svcomp, "svcomp_results.pdf", 220)


# 3. Breakdown of success by complexity buckets

def draw_success_by_complexity(metric, base, output_name):
    bucket_edges = np.array([0, 0.75, 1.5, 2.25, 10]) * base
    bucket_labels = [f"{bucket_edges[i]:.0f}-{bucket_edges[i+1]-1:.0f}" for i in range(len(bucket_edges)-1)]
    bucket_labels[-1] = f"{bucket_edges[-2]:.0f}+"

    def assign_bucket(val):
        for i in range(len(bucket_edges)-1):
            if bucket_edges[i] <= val < bucket_edges[i+1]:
                return bucket_labels[i]
        return f">={bucket_edges[-2]}"

    merged_svcomp["comp_bucket"] = merged_svcomp[metric].apply(assign_bucket)

    bar_data = {tool: [] for tool in tools}
    for label in bucket_labels:
        df_bucket = merged_svcomp[merged_svcomp["comp_bucket"] == label]
        for tool in tools:
            col = f"{tool}_succ"
            if col in df_bucket.columns:
                bar_data[tool].append(df_bucket[col].sum())
            else:
                bar_data[tool].append(0)

    x = np.arange(len(bucket_labels))
    width = 0.15
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Add background grid
    ax.set_axisbelow(True)
    ax.grid(True, linestyle="--", alpha=0.6, axis='y')
    
    for idx, tool in enumerate(tools):
        ax.bar(x + idx*width, bar_data[tool], width, color=colors[idx], alpha=1.0, label=names[idx])

    ax.set_xticks(x + width*2)
    ax.set_xticklabels(bucket_labels, fontsize=text_size)
    ax.tick_params(axis='y', labelsize=text_size)
    ax.set_ylabel("# of Proved Lemmas", fontsize=title_size)
    ax.legend(fontsize=text_size)
    plt.tight_layout()
    plt.savefig(output_name, bbox_inches='tight', dpi=300)
    plt.close()


draw_success_by_complexity("term_complexity", 100, "success_by_complexity_term.pdf")

draw_success_by_complexity("hypothesis_count", 10, "success_by_complexity_hypo.pdf")


# 4. Breakdown of SV-COMP successes by lemma type
import re
lemma_types = [
    ("assert_rte_signed_overflow", re.compile(r"assert_rte_signed_overflow", re.IGNORECASE)),
    ("loop_invariant", re.compile(r"loop_invariant", re.IGNORECASE)),
    ("assert_reachability", re.compile(r"assert_reachability", re.IGNORECASE)),
]

def get_lemma_type(lemma_name):
    for tname, tpat in lemma_types:
        if tpat.search(lemma_name):
            return tname

merged_svcomp["lemma_type"] = merged_svcomp["lemma_name"].astype(str).apply(get_lemma_type)

type_labels = [t[0] for t in lemma_types]
type_labels_display = ["Non-Overflow", "Loop Inv.", "Func. Correctness"]
type_bar_data = {tool: [] for tool in tools}
for tlabel in type_labels:
    df_type = merged_svcomp[merged_svcomp["lemma_type"] == tlabel]
    print(f"Type {tlabel}: {len(df_type)} lemmas ({len(df_type)/len(merged_svcomp)*100:.1f}%)")
    for tool in tools:
        col = f"{tool}_succ"
        if col in df_type.columns:
            type_bar_data[tool].append(df_type[col].sum())
        else:
            type_bar_data[tool].append(0)

x = np.arange(len(type_labels))
width = 0.12
fig, ax = plt.subplots(figsize=(10, 6))

# Add background grid
ax.set_axisbelow(True)
ax.grid(True, linestyle="--", alpha=0.6, axis='y')

for idx, tool in enumerate(tools):
    bars = ax.bar(x + idx*width, type_bar_data[tool], width, color=colors[idx], alpha=1.0, label=names[idx])
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height, f'{int(height)}', ha='center', va='bottom', fontsize=text_size)

ax.set_xticks(x + width*2)
ax.set_xticklabels(type_labels_display, fontsize=title_size)
ax.set_ylim(0, 100)
ax.tick_params(axis='y', labelsize=text_size)
ax.set_ylabel("# of Proved Lemmas", fontsize=title_size)
ax.legend(fontsize=text_size)
plt.tight_layout()
plt.savefig("success_by_type.pdf", bbox_inches='tight', dpi=300)


