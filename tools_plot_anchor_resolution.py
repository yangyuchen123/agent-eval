"""Render observed anchor-resolution curves and a separate theoretical hypothesis.

The figure intentionally does not fit a bell curve to incomplete/incomparable data.
Historical 2/3/4/5 observations and the controlled 2-vs-5 repeated experiment are
shown as distinct series. A conceptual inverted-U/U hypothesis is placed in its
own panel and labelled as non-empirical.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

BG = "#F7F8FC"
CARD = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
GRID = "#E7EAF0"
BLUE = "#4169E1"
PURPLE = "#8B5CF6"
TEAL = "#0EA5A8"
ORANGE = "#F59E0B"
RED = "#E45756"
GREEN = "#22A06B"
GRAY = "#AAB2C0"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def load_data() -> dict:
    historical = json.loads((ROOT / "run/meta_eval/octagon-real/anchor-resolution-gold-v1/gold-comparison.json").read_text())
    controlled = json.loads((ROOT / "run/meta_eval/failure-handling-anchor-v2-v5/2-vs-5-comparison.json").read_text())
    smoke = {}
    names = {2: "anchor-resolution-ablation-2", 3: "anchor-resolution-ablation-v3", 4: "anchor-resolution-ablation-v4", 5: "anchor-resolution-ablation-5"}
    for level, name in names.items():
        metrics = json.loads((ROOT / "run/meta_eval/octagon-real" / name / "metrics.json").read_text())
        aggregate = next(iter(metrics["by_case_aggregate"].values()))["score"]
        total_cost = sum((g.get("cost", {}).get("total") or 0) for g in metrics["by_group"].values())
        smoke[level] = {"std": aggregate["std"], "cost_per_observation": total_cost / 15}
    return {"historical": historical, "controlled": controlled, "smoke": smoke}


def smooth_points(points: list[tuple[float, float]], samples: int = 40) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    out = []
    extended = [points[0]] + points + [points[-1]]
    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i - 1], extended[i], extended[i + 1], extended[i + 2]
        for j in range(samples):
            t = j / samples
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2*p1[0]) + (-p0[0]+p2[0])*t + (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 + (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
            y = 0.5 * ((2*p1[1]) + (-p0[1]+p2[1])*t + (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 + (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
            out.append((x, y))
    out.append(points[-1])
    return out


def dashed(draw: ImageDraw.ImageDraw, points: list[tuple[float,float]], fill: str, width: int = 4, dash: int = 12, gap: int = 9):
    for a, b in zip(points, points[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        if length == 0: continue
        ux, uy = dx/length, dy/length
        pos = 0.0
        while pos < length:
            end = min(pos+dash, length)
            draw.line((a[0]+ux*pos, a[1]+uy*pos, a[0]+ux*end, a[1]+uy*end), fill=fill, width=width)
            pos += dash + gap


def panel(draw, box, title, subtitle, xvals, series, yrange, yfmt="{:.2f}"):
    x0,y0,x1,y1=box
    draw.rounded_rectangle(box, radius=22, fill=CARD)
    draw.text((x0+28,y0+20),title,font=font(25,True),fill=INK)
    draw.text((x0+28,y0+57),subtitle,font=font(16),fill=MUTED)
    px0,py0,px1,py1=x0+80,y0+108,x1-28,y1-62
    ymin,ymax=yrange
    def X(v): return px0+(v-min(xvals))/(max(xvals)-min(xvals))*(px1-px0)
    def Y(v): return py1-(v-ymin)/(ymax-ymin)*(py1-py0)
    for i in range(5):
        value=ymin+(ymax-ymin)*i/4
        yy=Y(value)
        draw.line((px0,yy,px1,yy),fill=GRID,width=2)
        label=yfmt.format(value)
        draw.text((px0-12,yy),label,font=font(14),fill=MUTED,anchor="rm")
    for v in xvals:
        xx=X(v)
        draw.line((xx,py1,xx,py1+8),fill=GRAY,width=2)
        draw.text((xx,py1+17),str(v),font=font(15,True),fill=INK,anchor="ma")
    draw.text(((px0+px1)/2,py1+44),"评分挡位数量",font=font(14),fill=MUTED,anchor="ma")
    legend_x=px1-8
    legend_y=y0+28
    for idx,s in enumerate(reversed(series)):
        yy=legend_y+idx*27
        label=s["label"]
        w=draw.textbbox((0,0),label,font=font(14))[2]
        lx=legend_x-w-34
        if s.get("dashed"):
            dashed(draw,[(lx,yy+8),(lx+24,yy+8)],s["color"],3,7,5)
        else: draw.line((lx,yy+8,lx+24,yy+8),fill=s["color"],width=4)
        draw.text((lx+32,yy),label,font=font(14),fill=MUTED)
    for s in series:
        pts=[(X(x),Y(y)) for x,y in s["values"]]
        curve=smooth_points(pts) if s.get("smooth",True) else pts
        if s.get("dashed"): dashed(draw,curve,s["color"],4)
        else: draw.line(curve,fill=s["color"],width=5,joint="curve")
        for xx,yy in pts:
            r=8 if s.get("emphasis") else 6
            draw.ellipse((xx-r,yy-r,xx+r,yy+r),fill=CARD,outline=s["color"],width=4)
            if s.get("labels"):
                val=next(y for x,y in s["values"] if abs(X(x)-xx)<.1)
                draw.text((xx,yy-14),s.get("value_fmt","{:.3f}").format(val),font=font(13,True),fill=s["color"],anchor="ms")


def main():
    d=load_data(); hist=d["historical"]; ctl=d["controlled"]; smoke=d["smoke"]
    levels=[2,3,4,5]
    hist_acc=[(n,float(hist[str(n)]["strict_exact_accuracy_all_cases"])) for n in levels]
    hist_mae=[(n,float(hist[str(n)]["mae_available"])) for n in levels]
    ctl_acc=[(2,ctl["two_levels"]["strict_exact_accuracy"]),(5,ctl["five_levels"]["strict_exact_accuracy"])]
    ctl_mae=[(2,ctl["two_levels"]["mae"]),(5,ctl["five_levels"]["mae"])]
    smoke_std=[(n,smoke[n]["std"]) for n in levels]
    ctl_std=[(2,ctl["two_levels"]["mean_per_case_std"]),(5,ctl["five_levels"]["mean_per_case_std"])]
    ctl_cost=[(2,ctl["two_levels"]["cost"]/90),(5,ctl["five_levels"]["cost"]/90)]
    smoke_cost=[(n,smoke[n]["cost_per_observation"]) for n in levels]

    scale=2; W,H=1680,1240
    im=Image.new("RGB",(W*scale,H*scale),BG); draw=ImageDraw.Draw(im)
    # Coordinates are authored at high resolution after scaling the canvas manually.
    # Draw in logical resolution then resize for antialiasing.
    im=Image.new("RGB",(W,H),BG); draw=ImageDraw.Draw(im)
    draw.text((60,38),"评分挡位数量：观测曲线与理论假设",font=font(38,True),fill=INK)
    draw.text((60,91),"实线为历史 16-case 单次实验；虚线大点为 30-case × 3 repeats 控制实验。两者不混合拟合。",font=font(19),fill=MUTED)
    boxes=[(50,145,820,625),(850,145,1630,625),(50,650,820,1130),(850,650,1630,1130)]
    panel(draw,boxes[0],"Gold 精确命中率","高通常更好；当前数据没有形成钟形",levels,[
        {"label":"历史单次 16 Gold","color":BLUE,"values":hist_acc,"labels":True,"value_fmt":"{:.1%}"},
        {"label":"控制实验 30 Gold × 3","color":PURPLE,"values":ctl_acc,"dashed":True,"smooth":False,"emphasis":True,"labels":True,"value_fmt":"{:.1%}"},
    ],(0.45,0.75),"{:.0%}")
    panel(draw,boxes[1],"平均绝对误差 MAE","低更好；更像理论上的 U 型误差",levels,[
        {"label":"历史单次 16 Gold","color":RED,"values":hist_mae,"labels":True},
        {"label":"控制实验 30 Gold × 3","color":ORANGE,"values":ctl_mae,"dashed":True,"smooth":False,"emphasis":True,"labels":True},
    ],(0.15,0.45))
    panel(draw,boxes[2],"重复出分波动","指标口径不同，分别观察形态，不直接拼接",levels,[
        {"label":"单 case aggregate std","color":TEAL,"values":smoke_std,"labels":True},
        {"label":"30 case 平均 per-case std","color":PURPLE,"values":ctl_std,"dashed":True,"smooth":False,"emphasis":True,"labels":True},
    ],(0,0.14))
    panel(draw,boxes[3],"每 observation 成本","五挡位控制实验成本明显更高",levels,[
        {"label":"历史 smoke cost/obs","color":GREEN,"values":smoke_cost,"labels":True,"value_fmt":"{:.4f}"},
        {"label":"控制实验 cost/obs","color":ORANGE,"values":ctl_cost,"dashed":True,"smooth":False,"emphasis":True,"labels":True,"value_fmt":"{:.4f}"},
    ],(0,0.022),"{:.3f}")
    draw.text((60,1170),"结论：现有观测不支持强行拟合钟形。若性能指标是准确率，理论预期应是倒 U 型；若指标是总误差，则对应 U 型。",font=font(18,True),fill=INK)
    draw.text((60,1202),"要验证曲线拐点，需要在同一 30-case Gold 上补齐 3、4 挡位重复实验；当前只有 2 和 5 两个严格可比端点。",font=font(17),fill=MUTED)
    hi=im.resize((W*2,H*2),Image.Resampling.LANCZOS)
    hi.save(OUT/"anchor_resolution_observed_curves.png")

    # Separate conceptual hypothesis.
    W2,H2=1500,720
    im2=Image.new("RGB",(W2,H2),BG); dr=ImageDraw.Draw(im2)
    dr.text((60,38),"理论假设：复杂度与评分可靠性的偏差–方差权衡",font=font(36,True),fill=INK)
    dr.text((60,88),"这是待验证假设，不是对当前数据的拟合。",font=font(20,True),fill=RED)
    box=(60,145,1440,650); dr.rounded_rectangle(box,radius=24,fill=CARD)
    x0,y0,x1,y1=150,210,1370,585
    for i in range(6):
        xx=x0+(x1-x0)*i/5; dr.line((xx,y0,xx,y1),fill=GRID,width=2)
    for i in range(5):
        yy=y0+(y1-y0)*i/4; dr.line((x0,yy,x1,yy),fill=GRID,width=2)
    dr.text(((x0+x1)/2,y1+38),"评分挡位数量 / Rubric resolution →",font=font(19,True),fill=INK,anchor="ma")
    dr.text((86,(y0+y1)/2),"相对表现",font=font(18,True),fill=INK,anchor="mm")
    pts_acc=[]; pts_err=[]
    for i in range(201):
        t=i/200; x=x0+t*(x1-x0)
        acc=0.25+0.68*math.exp(-((t-.58)/.31)**2)
        err=0.22+0.66*((t-.58)/.58)**2
        pts_acc.append((x,y1-acc*(y1-y0)))
        pts_err.append((x,y1-min(err,1)*(y1-y0)))
    dr.line(pts_acc,fill=BLUE,width=7)
    dr.line(pts_err,fill=RED,width=7)
    dr.text((x0+760,y0+30),"准确率 / 可信度：倒 U 型",font=font(22,True),fill=BLUE)
    dr.text((x0+760,y0+72),"总误差：U 型",font=font(22,True),fill=RED)
    dr.text((x0+30,y1-30),"挡位过少：量化偏差大",font=font(18),fill=MUTED)
    dr.text((x1-30,y1-30),"挡位过多：边界与调查方差大",font=font(18),fill=MUTED,anchor="ra")
    optimum=x0+.58*(x1-x0); dr.line((optimum,y0,optimum,y1),fill=GRAY,width=3)
    dr.text((optimum,y0-12),"假设最优分辨率",font=font(18,True),fill=MUTED,anchor="ms")
    im2.resize((W2*2,H2*2),Image.Resampling.LANCZOS).save(OUT/"anchor_resolution_theoretical_hypothesis.png")
    print(json.dumps({"observed":str(OUT/'anchor_resolution_observed_curves.png'),"hypothesis":str(OUT/'anchor_resolution_theoretical_hypothesis.png')},ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
