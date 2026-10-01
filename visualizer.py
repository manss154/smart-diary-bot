"""Построение недельного графика задач и потребления калорий."""

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import MaxNLocator

from config import CHARTS_DIR
from database import get_weekly_stats


RUSSIAN_FONT = Path("C:/Windows/Fonts/segoeui.ttf")


def create_weekly_chart(user_id: int) -> Path:
    """Создаёт PNG с выполненными задачами и калориями за последние семь дней."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    stats = get_weekly_stats(user_id)
    days = [date.fromisoformat(str(row["day"])) for row in stats]
    completed = [int(row["completed_tasks"]) for row in stats]
    calories = [int(row["calories"]) for row in stats]

    font = FontProperties(fname=str(RUSSIAN_FONT)) if RUSSIAN_FONT.exists() else None
    plt.rcParams.update(
        {
            "figure.facecolor": "#17211d",
            "axes.facecolor": "#202c27",
            "axes.edgecolor": "#53635a",
            "axes.labelcolor": "#e7eee9",
            "xtick.color": "#d2ded6",
            "ytick.color": "#d2ded6",
            "text.color": "#f1f5f2",
            "grid.color": "#45534b",
            "font.family": "sans-serif",
        }
    )
    figure, (tasks_axis, calories_axis) = plt.subplots(
        2, 1, figsize=(9, 6), sharex=True, constrained_layout=True
    )
    figure.suptitle("Итоги недели", fontsize=17, fontproperties=font, fontweight="bold")

    tasks_axis.bar(days, completed, width=0.62, color="#8bcf9b", zorder=3)
    tasks_axis.set_title("Выполненные задачи", loc="left", fontsize=12, fontproperties=font)
    tasks_axis.set_ylabel("Задачи", fontproperties=font)
    tasks_axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    tasks_axis.grid(axis="y", linestyle="--", alpha=0.45, zorder=0)

    calories_axis.plot(days, calories, color="#f2a36f", marker="o", linewidth=2.5)
    calories_axis.fill_between(days, calories, color="#f2a36f", alpha=0.12)
    calories_axis.set_title("Калории", loc="left", fontsize=12, fontproperties=font)
    calories_axis.set_ylabel("ккал", fontproperties=font)
    calories_axis.grid(axis="y", linestyle="--", alpha=0.45)
    calories_axis.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    calories_axis.set_xlabel("Дата", fontproperties=font)

    for axis in (tasks_axis, calories_axis):
        for label in axis.get_xticklabels() + axis.get_yticklabels():
            if font:
                label.set_fontproperties(font)
        axis.spines[["top", "right"]].set_visible(False)

    output_path = CHARTS_DIR / f"weekly_{user_id}.png"
    figure.savefig(output_path, dpi=140, bbox_inches="tight")
    plt.close(figure)
    return output_path
