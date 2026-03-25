import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from scipy.ndimage import gaussian_filter1d

if len(sys.argv) != 3:
    print(f"Usage: python {sys.argv[0]} <complexity_1.csv> <complexity_2.csv>")
    sys.exit(1)

filename_1 = sys.argv[1]
filename_2 = sys.argv[2]
df_1 = pd.read_csv(filename_1)
df_2 = pd.read_csv(filename_2)


def draw_histogram(column_name: str, cutoff: int, label_name: str, output_name: str):
    data_1 = df_1[column_name].dropna()
    data_2 = df_2[column_name].dropna()

    # Clipped histogram
    data_1 = np.clip(data_1, None, cutoff)
    data_2 = np.clip(data_2, None, cutoff)
    step_size = max(1, cutoff / 60)
    bins = np.arange(0, cutoff + step_size, step_size)

    plt.figure(figsize=(6, 3))
    plt.hist([data_1, data_2], bins=bins, rwidth=0.85, color=["blue", "orange"], edgecolor="none", alpha=0.7, density=True)
    plt.gca().yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y*100:.0f}%"))

    # Overlay smoothed curves
    c1, _ = np.histogram(data_1, bins=bins, density=True)
    c2, _ = np.histogram(data_2, bins=bins, density=True)
    sigma = 1.3  # smoothness
    s1 = gaussian_filter1d(c1.astype(float), sigma=sigma)
    s2 = gaussian_filter1d(c2.astype(float), sigma=sigma)
    centers = 0.5 * (bins[1:] + bins[:-1])
    plt.plot(centers, s1, linewidth=3, color="blue", label="colA (smoothed)")
    plt.plot(centers, s2, linewidth=3, color="orange", label="colB (smoothed)")


    step = len(bins) // 6
    xticks_pos = bins[::step].tolist() + [bins[-1]]
    xticks_labels = [str(int(b)) for b in bins[::step]] + [f"{cutoff}+"]
    plt.xticks(xticks_pos, xticks_labels, fontsize=16)
    plt.yticks(fontsize=16)
    plt.locator_params(axis="y", nbins=3)
    plt.grid(True, linestyle="--", alpha=0.6, axis='y')

    # plt.xlabel(label_name)
    # plt.ylabel("Frequency (%)")
    
    plt.legend(labels=["SV-COMP", "CoqGym"], fontsize=16)
    plt.tight_layout()
    plt.savefig(output_name)
    plt.close()

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

# draw_histogram("statement_length", 300, "String Length Per Lemma", "length.pdf")

# draw_histogram("quantifier_count", 10, "Quantifier Per Lemma", "quant.pdf")

draw_histogram("term_complexity", 300, "Term Complexity Per Lemma", "term.pdf")

draw_histogram("hypothesis_count", 30, "Hypothesis Per Lemma", "hypothesis.pdf")

