"""Render the 2x2 anchor count × wording ablation."""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "run/meta_eval/failure-handling-anchor-wording-ablation-v1/analysis.json"
OUT = ROOT / "docs/assets/anchor_wording_2x2_ablation.png"
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
BG="#F5F7FB"; CARD="#FFFFFF"; INK="#172033"; MUTED="#667085"; GRID="#E4E8F0"
BLUE="#4169E1"; TEAL="#0EA5A8"; RED="#E45756"; ORANGE="#F59E0B"; GREEN="#22A06B"; PURPLE="#8B5CF6"

def font(size,bold=False): return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR,size)

def metric_card(draw, box, title, values, lower_better=False, fmt="{:.3f}"):
    x0,y0,x1,y1=box
    draw.rounded_rectangle(box,radius=22,fill=CARD)
    draw.text((x0+28,y0+20),title,font=font(24,True),fill=INK)
    draw.text((x0+28,y0+56),"越低越好" if lower_better else "越高越好",font=font(14),fill=MUTED)
    labels=[("A","5 挡 qualitative"),("B","5 挡 continuum"),("C","6 挡 qualitative"),("D","6 挡 continuum")]
    best=min(values) if lower_better else max(values)
    positions=[(x0+185,y0+145),(x0+515,y0+145),(x0+185,y0+280),(x0+515,y0+280)]
    for (key,label),value,(cx,cy) in zip(labels,values,positions):
        color=GREEN if abs(value-best)<1e-12 else BLUE
        draw.rounded_rectangle((cx-135,cy-48,cx+135,cy+48),radius=16,fill="#ECFDF3" if color==GREEN else "#EEF3FF")
        draw.text((cx-112,cy-12),key,font=font(18,True),fill=color,anchor="mm")
        draw.text((cx,cy-12),fmt.format(value),font=font(25,True),fill=color,anchor="mm")
        draw.text((cx,cy+24),label,font=font(13),fill=MUTED,anchor="mm")

def main():
    d=json.loads(DATA.read_text()); c=d["cells"]
    order=["A_5_qualitative","B_5_continuum","C_6_qualitative","D_6_continuum"]
    W,H=1800,1370
    im=Image.new("RGB",(W,H),BG); dr=ImageDraw.Draw(im)
    dr.text((60,35),"Anchor 数量 × Anchor 表达：2×2 决定性消融",font=font(38,True),fill=INK)
    dr.text((60,88),"同一 5 cases、同一 trace/model/seeds；A/D 复用，B/C 各新增 15 observations",font=font(19),fill=MUTED)
    dr.rounded_rectangle((1320,28,1740,105),radius=18,fill="#FFF4E5")
    dr.text((1530,66),"结论：强 crossover interaction",font=font(19,True),fill=ORANGE,anchor="mm")
    boxes=[(60,140,870,515),(930,140,1740,515),(60,555,870,930),(930,555,1740,930)]
    metric_card(dr,boxes[0],"Strict exact accuracy",[c[x]["strict_exact_accuracy"] for x in order],False,"{:.1%}")
    metric_card(dr,boxes[1],"MAE",[c[x]["mae"] for x in order],True,"{:.3f}")
    metric_card(dr,boxes[2],"Threshold agreement",[c[x]["threshold_agreement"] for x in order],False,"{:.1%}")
    metric_card(dr,boxes[3],"Mean per-case std",[c[x]["mean_per_case_std"] for x in order],True,"{:.3f}")
    # Effect summary.
    dr.rounded_rectangle((60,970,1740,1280),radius=22,fill=CARD)
    dr.text((88,992),"效应方向（右条件 − 左条件）",font=font(24,True),fill=INK)
    rows=[
        ("Wording @ 5: continuum − qualitative","MAE +0.233（变差）","Exact −26.7pp","Threshold −33.3pp",RED),
        ("Wording @ 6: continuum − qualitative","MAE −0.040（略改善）","Exact +26.7pp","Threshold 0pp",TEAL),
        ("Resolution under qualitative: 6 − 5","MAE +0.190（变差）","Exact −33.3pp","Threshold −33.3pp",RED),
        ("Resolution under continuum: 6 − 5","MAE −0.083（改善）","Exact +20.0pp","Threshold 0pp",TEAL),
    ]
    for i,(name,mae,exact,threshold,color) in enumerate(rows):
        y=1045+i*53
        dr.text((95,y),name,font=font(16,True),fill=INK)
        dr.text((780,y),mae,font=font(16,True),fill=color)
        dr.text((1120,y),exact,font=font(16),fill=MUTED)
        dr.text((1400,y),threshold,font=font(16),fill=MUTED)
    dr.text((60,1325),"interaction 的幅度大于两个平均主效应：5→6 是否变差取决于 anchor wording；原 A→D 崩溃不能归因于 resolution alone。",font=font(18,True),fill=INK)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    im.resize((W*2,H*2),Image.Resampling.LANCZOS).save(OUT)
    print(OUT)
if __name__=="__main__": main()
