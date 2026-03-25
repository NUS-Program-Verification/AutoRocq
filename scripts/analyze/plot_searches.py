import matplotlib.pyplot as plt

filename = "./eval/final/searches.txt"

count_by_command = {
    "Search": 0,
    "About": 0,
    "Print": 0,
    "Check": 0,
    "Locate": 0,
}

lengths = []
with open(filename) as f:
    for line in f:
        if not line.strip():
            lengths.append(0)
            continue
        items = line.strip().split('; ')
        lengths.append(len(items))
        for item in items:
            command = item.split(" ")[0]
            if command not in count_by_command:
                continue
            count_by_command[command] += 1


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

fig, ax = plt.subplots(figsize=(10, 6))
commands = list(count_by_command.keys())
counts = list(count_by_command.values())
colors = plt.cm.tab20.colors

# Add background grid (behind bars)
ax.set_axisbelow(True)
ax.grid(True, linestyle="--", alpha=0.6, axis='y')

ax.bar(commands, counts, 0.5, color=colors[:len(commands)], alpha=1.0)
ax.set_yscale('log')
ax.set_ylabel('Log Count', fontsize=20)
ax.tick_params(axis='y', labelsize=20)
ax.tick_params(axis='x', labelsize=20)
plt.tight_layout()
plt.savefig('search_command.pdf', bbox_inches='tight', dpi=300)