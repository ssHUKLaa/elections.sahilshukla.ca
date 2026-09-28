"""Render the figures used by the 2026 model article from the saved forecast."""

from collections import defaultdict
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FORECAST = json.loads((ROOT / "artifacts/nowcast/forecast_2026.json").read_text(encoding="utf-8"))
PARAMETERS = json.loads((ROOT / "artifacts/nowcast/model_parameters.json").read_text(encoding="utf-8"))
assert FORECAST["metadata"]["information_cutoff_utc"] == PARAMETERS["metadata"]["information_cutoff_utc"]

BLUE = "#2869bd"
BLUE_DARK = "#123c83"
BLUE_LIGHT = "#e8f0fb"
RED = "#bd2840"
RED_LIGHT = "#fbecef"
PURPLE = "#7c60a9"
PURPLE_LIGHT = "#f0ebf7"
GREY = "#79818c"
GREY_LIGHT = "#eef1f4"
INK = "#202735"
MUTED = "#5f6c7c"
LINE = "#d8dee7"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": LINE,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def save(fig, name):
    fig.savefig(OUT / name, dpi=220, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)


def flow_box(ax, x, y, w, h, title, subtitle, fill, edge):
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.16",
                           linewidth=1.5, edgecolor=edge, facecolor=fill, zorder=2)
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h * .65, title, ha="center", va="center",
            fontsize=12.2, weight="bold", color=INK, zorder=3)
    ax.text(x + w / 2, y + h * .30, subtitle, ha="center", va="center",
            fontsize=9.1, color=MUTED, zorder=3)


def flow_arrow(ax, start, end):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=15,
                                 linewidth=1.7, color="#9aa5b4", zorder=1,
                                 connectionstyle="arc3,rad=0"))


def model_flow():
    fig, ax = plt.subplots(figsize=(11.4, 6.7))
    ax.set(xlim=(0, 12), ylim=(0, 7.6))
    ax.axis("off")
    ax.text(.15, 7.22, "From data to election outcomes", fontsize=20, weight="bold", color=INK)
    ax.text(.15, 6.87, "The same process runs across 506 races.", fontsize=11, color=MUTED)

    flow_arrow(ax, (1.95, 5.48), (3.18, 4.68))
    flow_arrow(ax, (5.95, 5.48), (4.37, 4.68))
    flow_arrow(ax, (9.95, 5.48), (9.18, 4.68))
    flow_arrow(ax, (5.60, 4.15), (7.05, 4.15))
    flow_arrow(ax, (8.92, 3.53), (6.05, 2.79))
    flow_arrow(ax, (6.0, 1.78), (6.0, 1.45))

    flow_box(ax, .40, 5.55, 3.1, .82, "Previous results", "seat history + district lines", BLUE_LIGHT, BLUE)
    flow_box(ax, 4.40, 5.55, 3.1, .82, "National signals", "generic ballot + approval", PURPLE_LIGHT, PURPLE)
    flow_box(ax, 8.40, 5.55, 3.1, .82, "Race polls", "candidates + pollster quality", RED_LIGHT, RED)
    flow_box(ax, 2.0, 3.57, 3.6, 1.03, "Prior vote shares", "D / R / other, with uncertainty", BLUE_LIGHT, BLUE)
    flow_box(ax, 7.05, 3.57, 3.75, 1.03, "Poll update", "candidate shares move with evidence", RED_LIGHT, RED)
    flow_box(ax, 4.15, 1.78, 3.7, .91, "75,000 linked elections", "national, state and race shifts", PURPLE_LIGHT, PURPLE)
    flow_box(ax, 4.15, .40, 3.7, .91, "Winners and seat totals", "after each race's counting rule", GREY_LIGHT, GREY)
    save(fig, "model_flow.png")


def national_blend():
    signal = PARAMETERS["national_signal_update"]
    generic = 100 * signal["generic_ballot"]["raw_implied_D_two_party_margin"]
    approval = 100 * signal["approval_conditioned_prior"]["implied_D_two_party_margin"]
    combined = 100 * signal["posterior"]["implied_D_two_party_margin"]
    approval_weight = signal["approval_blend_weight"]

    fig = plt.figure(figsize=(9.4, 5.1))
    fig.text(.10, .93, "The national starting point", fontsize=20, weight="bold", color=INK)
    fig.text(.10, .865, "September 27 snapshot · Democratic two-party margin", fontsize=10.5, color=MUTED)

    ax = fig.add_axes([.37, .32, .54, .47])
    rows = [
        ("Generic ballot", generic, BLUE, 3),
        ("Approval benchmark", approval, PURPLE, 2),
        ("Combined center", combined, BLUE_DARK, 1),
    ]
    for label, value, color, y in rows:
        ax.plot([6.65, value], [y, y], lw=3, color=color, alpha=.28, solid_capstyle="round")
        ax.scatter([value], [y], s=155 if y == 1 else 100, color=color, zorder=3)
        ax.text(6.58, y, label, ha="right", va="center", color=INK,
                weight="bold" if y == 1 else "normal", fontsize=10.7)
        ax.text(value + .08, y, f"D+{value:.2f}", ha="left", va="center",
                color=color, weight="bold", fontsize=11)
    ax.set(xlim=(6.6, 9.45), ylim=(.45, 3.55))
    ax.set_xticks([7, 7.5, 8, 8.5, 9])
    ax.set_xlabel("D minus R, percentage points")
    ax.set_yticks([])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.grid(axis="x", color=LINE, alpha=.7)
    ax.set_axisbelow(True)

    band = fig.add_axes([.10, .13, .80, .095])
    band.barh([0], [100 * (1 - approval_weight)], color=BLUE, height=.65)
    band.barh([0], [100 * approval_weight], left=[100 * (1 - approval_weight)],
              color=PURPLE, height=.65)
    band.text(47.5, 0, f"{100 * (1 - approval_weight):.0f}% generic ballot",
              ha="center", va="center", color="white", weight="bold", fontsize=10.8)
    band.text(97.5, 0, "5%", ha="center", va="center", color="white", weight="bold", fontsize=9)
    band.set(xlim=(0, 100), ylim=(-.55, .55))
    band.axis("off")
    fig.text(.10, .055, "Weights are applied to D/R log odds; the margins above are their vote-share equivalents.",
             fontsize=9.5, color=MUTED)
    save(fig, "national_blend.png")


def poll_weights():
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6), gridspec_kw={"wspace": .30})
    fig.suptitle("How a poll's weight changes", x=.08, ha="left", y=.98,
                 fontsize=20, weight="bold", color=INK)
    fig.text(.08, .88, "Holding the other inputs fixed", fontsize=10.5, color=MUTED)
    fig.subplots_adjust(left=.08, right=.97, bottom=.18, top=.78)

    age = np.linspace(0, 90, 300)
    age_weight = 2 ** (-age / 30)
    ax = axes[0]
    ax.plot(age, age_weight, color=BLUE, lw=3)
    for x in (0, 30, 60, 90):
        y = 2 ** (-x / 30)
        ax.scatter([x], [y], color=BLUE_DARK, s=45, zorder=3)
        label = "12.5%" if x == 90 else f"{y:.0%}"
        ax.annotate(label, (x, y), xytext=(0, 9), textcoords="offset points",
                    ha="center", color=BLUE_DARK, fontsize=9.5)
    ax.set(xlim=(-4, 94), ylim=(0, 1.18), xlabel="Days since poll ended",
           ylabel="Relative age weight")
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.grid(axis="y", color=LINE, alpha=.75)
    ax.set_axisbelow(True)
    ax.set_title("Age: 30-day half-life", loc="left", fontsize=12.5, weight="bold", color=INK)

    n = np.linspace(100, 2500, 300)
    n_weight = np.sqrt(n / 600)
    ax = axes[1]
    ax.plot(n, n_weight, color=PURPLE, lw=3)
    for x in (100, 600, 2400):
        y = np.sqrt(x / 600)
        ax.scatter([x], [y], color=PURPLE, s=45, zorder=3)
        ax.annotate(f"{y:.2g}×", (x, y), xytext=(0, 9), textcoords="offset points",
                    ha="center", color=PURPLE, fontsize=9.5)
    ax.set(xlim=(0, 2550), ylim=(0, 2.30), xlabel="Sample size",
           ylabel="Relative sample weight")
    ax.set_xticks([100, 600, 1200, 1800, 2400])
    ax.grid(axis="y", color=LINE, alpha=.75)
    ax.set_axisbelow(True)
    ax.set_title("Sample: square-root scaling", loc="left", fontsize=12.5, weight="bold", color=INK)
    save(fig, "poll_weights.png")


def house_distribution():
    house = FORECAST["joint_summaries"]["house"]
    counts = defaultdict(lambda: {"D": 0.0, "R": 0.0, "O": 0.0})
    for result, probability in house["joint_D_R_O_distribution"].items():
        d, r, other = map(int, result.split("-"))
        control = "D" if d >= 218 else "R" if r >= 218 else "O"
        counts[d][control] += probability
    assert abs(sum(sum(groups.values()) for groups in counts.values()) - 1) < 1e-8
    seats = np.arange(min(counts), max(counts) + 1)
    republican = np.array([100 * counts[s]["R"] for s in seats])
    neither = np.array([100 * counts[s]["O"] for s in seats])
    democratic = np.array([100 * counts[s]["D"] for s in seats])
    control = house["control"]

    fig, ax = plt.subplots(figsize=(10.5, 5.3))
    fig.subplots_adjust(left=.08, right=.98, bottom=.18, top=.79)
    fig.text(.08, .94, "House seats across 75,000 elections", fontsize=20, weight="bold", color=INK)
    fig.text(.08, .875, "September 27 snapshot · one bar for each Democratic seat total",
             fontsize=10.5, color=MUTED)

    ax.bar(seats, republican, color=RED, width=.93,
           label=f"Republican majority  {100 * control['R_control_probability']:.1f}%")
    ax.bar(seats, neither, bottom=republican, color=GREY, width=.93,
           label=f"Neither party  {100 * control['neither_probability']:.1f}%")
    ax.bar(seats, democratic, bottom=republican + neither, color=BLUE, width=.93,
           label=f"Democratic majority  {100 * control['D_control_probability']:.1f}%")
    ax.set(xlim=(min(seats) - 3, max(seats) + 3), ylim=(0, None),
           xlabel="Democratic House seats", ylabel="Share of simulations per seat total (%)")
    ax.set_xticks([150, 175, 200, 218, 225, 250, 275, 300, 325])
    ax.grid(axis="y", color=LINE, alpha=.75)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", frameon=False, fontsize=9.6, ncol=1)
    ax.text(218, -.17, "218 for a majority", ha="center", va="top",
            fontsize=9.4, color=MUTED, transform=ax.get_xaxis_transform())
    save(fig, "house_seat_distribution.png")


if __name__ == "__main__":
    model_flow()
    national_blend()
    poll_weights()
    house_distribution()
    print(f"Wrote four article figures to {OUT}")
