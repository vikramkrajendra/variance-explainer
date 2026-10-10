"""Minimal markdown -> PDF for the product brief (headings, paragraphs, bullets, tables, quotes, hr)."""
import re, sys
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                HRFlowable, PageBreak, KeepTogether)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

D = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Sans", D + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", D + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Oblique", D + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("Sans-BoldOblique", D + "DejaVuSans-BoldOblique.ttf"))
from reportlab.lib.fonts import addMapping
addMapping("Sans", 0, 0, "Sans"); addMapping("Sans", 1, 0, "Sans-Bold")
addMapping("Sans", 0, 1, "Sans-Oblique"); addMapping("Sans", 1, 1, "Sans-BoldOblique")

INK = colors.HexColor("#1c2230"); ACCENT = colors.HexColor("#3b5bdb"); MUTED = colors.HexColor("#5c6577")
LINE = colors.HexColor("#d9dee8"); HEAD_BG = colors.HexColor("#eef1f8")

body = ParagraphStyle("body", fontName="Sans", fontSize=9.6, leading=14, textColor=INK, spaceAfter=6)
small = ParagraphStyle("small", parent=body, fontSize=8.4, leading=11.2, spaceAfter=0)
smallb = ParagraphStyle("smallb", parent=small, fontName="Sans-Bold")
h1 = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=22, leading=27, textColor=INK, spaceAfter=2)
sub = ParagraphStyle("sub", fontName="Sans", fontSize=12, leading=16, textColor=ACCENT, spaceAfter=10)
h2 = ParagraphStyle("h2", fontName="Sans-Bold", fontSize=14, leading=18, textColor=ACCENT, spaceBefore=12, spaceAfter=6, keepWithNext=1)
quote = ParagraphStyle("quote", parent=body, leftIndent=12, borderPadding=(6, 8, 6, 8), backColor=HEAD_BG,
                       borderColor=ACCENT, borderWidth=0, fontSize=10.2, leading=15)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=3, spaceAfter=3)


def inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", t)
    return t


def footer(c, doc):
    c.saveState(); c.setFont("Sans", 7.5); c.setFillColor(MUTED)
    c.drawString(18 * mm, 10 * mm, "VarianceLens — Forecast vs Actual Variance Explainer · Product Brief")
    c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    c.restoreState()


def build(src, out):
    lines = open(src, encoding="utf-8").read().splitlines()
    story, i = [], 0
    width = A4[0] - 36 * mm
    first_h2 = True
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1; continue
        if ln.startswith("# "):
            story.append(Paragraph(inline(ln[2:]), h1)); i += 1; continue
        if ln.startswith("## ") and not re.match(r"## \d", ln):
            story.append(Paragraph(inline(ln[3:]), sub)); i += 1; continue
        if ln.startswith("## "):
            first_h2 = False
            story.append(Paragraph(inline(ln[3:]), h2)); i += 1; continue
        if ln.strip() == "---":
            story.append(HRFlowable(width="100%", thickness=0.6, color=LINE, spaceBefore=4, spaceAfter=8)); i += 1; continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").rstrip()); i += 1
            qp = Paragraph("<br/>".join(inline(b) for b in buf), quote)
            grp = [qp]
            if story and isinstance(story[-1], Paragraph) and story[-1].style.name == "h2":
                grp.insert(0, story.pop())
            story.append(KeepTogether(grp)); story.append(Spacer(1, 6)); continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            ncol = len(rows[0])
            header_blank = all(not c for c in rows[0])
            data = []
            for r_i, r in enumerate(rows):
                if header_blank and r_i == 0:
                    continue
                st = smallb if (r_i == 0 and not header_blank) or (ncol == 2 and header_blank) and False else small
                data.append([Paragraph(inline(c), smallb if (r_i == 0 and not header_blank) else small) for c in r])
            if ncol == 2 and header_blank:
                cw = [width * 0.24, width * 0.76]
            elif ncol == 5:
                cw = [width * w for w in (0.05, 0.42, 0.25, 0.11, 0.17)]
            elif ncol == 4:
                cw = [width * w for w in (0.22, 0.24, 0.17, 0.37)]
            elif ncol == 3:
                cw = [width * w for w in (0.46, 0.27, 0.27)]
            else:
                cw = [width / ncol] * ncol
            t = Table(data, colWidths=cw, repeatRows=0 if header_blank else 1)
            style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                     ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
            if not header_blank:
                style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD_BG))
            else:
                style.append(("BACKGROUND", (0, 0), (0, -1), HEAD_BG))
            t.setStyle(TableStyle(style))
            story.append(t); story.append(Spacer(1, 8)); continue
        if re.match(r"\d+\. ", ln):
            while i < len(lines) and re.match(r"\d+\. ", lines[i]):
                m = re.match(r"(\d+)\. (.*)", lines[i])
                story.append(Paragraph(inline(m.group(2)), bullet, bulletText=m.group(1) + ".")); i += 1
            story.append(Spacer(1, 4)); continue
        if ln.startswith("- "):
            while i < len(lines) and lines[i].startswith("- "):
                story.append(Paragraph(inline(lines[i][2:]), bullet, bulletText="•")); i += 1
            story.append(Spacer(1, 4)); continue
        buf = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "- ", ">", "---")) and not re.match(r"\d+\. ", lines[i]):
            buf.append(lines[i].strip()); i += 1
        txt = " ".join(buf)
        st = body
        if re.fullmatch(r"\*[^*].*\*", txt):
            st = ParagraphStyle("note", parent=body, textColor=MUTED)
        story.append(Paragraph(inline(txt), st))
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title="VarianceLens — Product Brief", author="Vikram")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
