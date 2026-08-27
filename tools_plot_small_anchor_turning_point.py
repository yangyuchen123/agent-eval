"""Render the controlled five-case 2-through-9 anchor-resolution experiment.

The source JSON is produced from real Judge runs. The plot deliberately shows raw
observed points and does not fit a bell/U curve to four discrete observations.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run/meta_eval/failure-handling-anchor-small-v1/curve-analysis.json"
OUT = ROOT / "docs/assets/anchor_resolution_small_turning_point.png"

BG = "#F5F7FB"
CARD = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
GRID = "#E4E8F0"
BLUE = "#4169E1"
TEAL = "#0EA5A8"
ORANGE = "#F59E0B"
RED = "#E45756"
PURPLE = "#8B5CF6"
GREEN = "#22A06B"
GRAY = "#AAB2C0"

FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def line_panel(draw, box, title, subtitle, levels, series, yrange, yfmt="{:.2f}"):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=22, fill=CARD)
    draw.text((x0 + 28, y0 + 20), title, font=font(24, True), fill=INK)
    draw.text((x0 + 28, y0 + 55), subtitle, font=font(15), fill=MUTED)
    px0, py0, px1, py1 = x0 + 78, y0 + 102, x1 - 30, y1 - 58
    ymin, ymax = yrange

    def xx(v):
        return px0 + (v - min(levels)) / (max(levels) - min(levels)) * (px1 - px0)

    def yy(v):
        return py1 - (v - ymin) / (ymax - ymin) * (py1 - py0)

    for i in range(5):
        value = ymin + (ymax - ymin) * i / 4
        y = yy(value)
        draw.line((px0, y, px1, y), fill=GRID, width=2)
        draw.text((px0 - 11, y), yfmt.format(value), font=font(13), fill=MUTED, anchor="rm")
    for level in levels:
        x = xx(level)
        draw.text((x, py1 + 17), str(level), font=font(15, True), fill=INK, anchor="ma")
    draw.text(((px0 + px1) / 2, py1 + 42), "评分挡位数量", font=font(14), fill=MUTED, anchor="ma")

    legend_x = px1
    legend_y = y0 + 27
    for idx, item in enumerate(reversed(series)):
        label = item["label"]
        width = draw.textbbox((0, 0), label, font=font(13))[2]
        lx = legend_x - width - 32
        ly = legend_y + idx * 25
        draw.line((lx, ly + 7, lx + 22, ly + 7), fill=item["color"], width=4)
        draw.text((lx + 29, ly), label, font=font(13), fill=MUTED)

    for item in series:
        points = [(xx(level), yy(value)) for level, value in zip(levels, item["values"])]
        draw.line(points, fill=item["color"], width=5)
        for (x, y), value in zip(points, item["values"]):
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=CARD, outline=item["color"], width=4)
            draw.text((x, y - 15), item.get("value_fmt", "{:.2f}").format(value), font=font(13, True), fill=item["color"], anchor="ms")


def main():
    data = json.loads(SOURCE.read_text())
    levels = sorted(int(level) for level in data["levels"])
    metrics = {level: data["levels"][str(level)] for level in levels}

    width, height = 1800, 1550
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((60, 34), "5-case 小样本：2–9 挡评分分辨率与 Judge 可靠性", font=font(38, True), fill=INK)
    draw.text((60, 88), "同一 5 个 Gold case、同一模型与 trace、每挡位 3 次；共 120 个真实 observation", font=font(19), fill=MUTED)
    draw.rounded_rectangle((1370, 28, 1740, 105), radius=18, fill="#FFF4E5")
    draw.text((1555, 66), "5挡定性组合局部最优", font=font(20, True), fill=ORANGE, anchor="mm")

    boxes = [
        (60, 140, 870, 560),
        (930, 140, 1740, 560),
        (60, 600, 870, 1020),
        (930, 600, 1740, 1020),
    ]
    line_panel(draw, boxes[0], "Gold 一致性", "五挡在相邻 4/6 挡之间形成局部峰值；全曲线仍有明显噪声", levels, [
        {"label": "Strict exact accuracy", "color": BLUE, "values": [metrics[x]["strict_exact_accuracy"] for x in levels]},
        {"label": "Threshold agreement", "color": TEAL, "values": [metrics[x]["threshold_agreement"] for x in levels]},
    ], (0.25, 1.0), "{:.0%}")
    line_panel(draw, boxes[1], "误差", "五挡是 2–9 挡中的全局最低点，六挡立即显著反弹", levels, [
        {"label": "MAE", "color": RED, "values": [metrics[x]["mae"] for x in levels]},
        {"label": "RMSE", "color": PURPLE, "values": [metrics[x]["rmse"] for x in levels]},
    ], (0.0, 0.55), "{:.2f}")
    line_panel(draw, boxes[2], "重复稳定性", "低方差可能是稳定地判错，必须与 Gold 误差联合解释", levels, [
        {"label": "Mean per-case std", "color": ORANGE, "values": [metrics[x]["mean_per_case_std"] for x in levels]},
        {"label": "Stable-case ratio", "color": GREEN, "values": [metrics[x]["stable_cases"] / 5 for x in levels]},
    ], (0.0, 1.0), "{:.2f}")
    line_panel(draw, boxes[3], "成本", "九挡均值被单次 922k-token 调查拉高；中位数更接近典型成本", levels, [
        {"label": "Mean cost / obs ×100", "color": RED, "values": [metrics[x]["cost_per_observation"] * 100 for x in levels]},
        {"label": "Median cost / obs ×100", "color": BLUE, "values": [metrics[x]["median_cost_per_observation"] * 100 for x in levels]},
    ], (0.0, 3.1), "{:.2f}")

    # Per-case mean score trajectories reveal which cases drive the aggregate curve.
    box = (60, 1060, 1740, 1455)
    draw.rounded_rectangle(box, radius=22, fill=CARD)
    draw.text((88, 1080), "逐 case 平均分轨迹", font=font(24, True), fill=INK)
    draw.text((88, 1115), "每个点为三次重复的平均分；五挡后困难 case 呈明显非单调，易 case 仍保持稳定。", font=font(15), fill=MUTED)
    labels = {
        "att_fa8655f8ce1d": "Ignored failure · Gold 0",
        "att_8ca4f9ec3ba9": "Partial recovery A · Gold 0.5",
        "att_9c539666b31d": "Partial recovery B · Gold 0.5",
        "att_a1bb35bb6955": "Successful recovery · Gold 1",
        "att_07d7cc78f5b0": "Observer / N-A control · Gold 1",
    }
    colors = [RED, ORANGE, PURPLE, GREEN, BLUE]
    px0, py0, px1, py1 = 145, 1170, 1680, 1380
    for i in range(5):
        value = i / 4
        y = py1 - value * (py1 - py0)
        draw.line((px0, y, px1, y), fill=GRID, width=2)
        draw.text((px0 - 12, y), f"{value:.2f}", font=font(13), fill=MUTED, anchor="rm")
    for level in levels:
        x = px0 + (level - min(levels)) / (max(levels) - min(levels)) * (px1 - px0)
        draw.text((x, py1 + 18), str(level), font=font(15, True), fill=INK, anchor="ma")
    for idx, case_id in enumerate(data["case_ids"]):
        points = []
        for level in levels:
            value = metrics[level]["per_case"][case_id]["mean"]
            x = px0 + (level - min(levels)) / (max(levels) - min(levels)) * (px1 - px0)
            y = py1 - value * (py1 - py0)
            points.append((x, y))
        draw.line(points, fill=colors[idx], width=4)
        for x, y in points:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=CARD, outline=colors[idx], width=3)
        lx = 120 + (idx % 3) * 535
        ly = 1410 + (idx // 3) * 27
        draw.line((lx, ly + 7, lx + 24, ly + 7), fill=colors[idx], width=4)
        draw.text((lx + 31, ly), labels[case_id], font=font(13), fill=MUTED)

    draw.text((60, 1500), "后续 2×2 消融确认：五挡优势是 resolution × wording 交互，不是可脱离 qualitative anchors 的纯挡位数量效应。", font=font(18, True), fill=INK)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.resize((width * 2, height * 2), Image.Resampling.LANCZOS).save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
