import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle, KeepTogether, Preformatted)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

OUT = sys.argv[1]
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
ACC = colors.HexColor("#0f766e")
ACC_L = colors.HexColor("#e6f4f2")
WARN = colors.HexColor("#b45309")
WARN_L = colors.HexColor("#fef3e2")
GRID = colors.HexColor("#d1d5db")

base = ParagraphStyle("b", fontName="Helvetica", fontSize=8.1, leading=10.1, textColor=INK)
small = ParagraphStyle("s", parent=base, fontSize=7.3, leading=9)
bullet = ParagraphStyle("bl", parent=base, leftIndent=7, bulletIndent=0, spaceAfter=0.6)
sbullet = ParagraphStyle("sbl", parent=small, leftIndent=7, bulletIndent=0, spaceAfter=0.4)
h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=14.5, leading=17)
sub = ParagraphStyle("sub", parent=base, textColor=MUTED, fontSize=7.4)
h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=9.4, leading=11,
                    textColor=ACC, spaceBefore=4.5, spaceAfter=2)
h3 = ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=7.8, spaceAfter=1.2)
cell = ParagraphStyle("c", parent=small)
code = ParagraphStyle("code", parent=base, fontName="Courier", fontSize=6.9, leading=8.4, backColor=colors.HexColor("#f6f8fa"), borderPadding=4, leftIndent=4, rightIndent=4, spaceBefore=2)
cellb = ParagraphStyle("cb", parent=small, fontName="Helvetica-Bold")


def P(t, s=base):
    return Paragraph(t, s)


def bl(items, s=bullet):
    return [Paragraph(i, s, bulletText="•") for i in items]


def box(flowables, bg, border, width):
    t = Table([[flowables]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg),
                           ("BOX", (0, 0), (-1, -1), 0.6, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def grid_table(rows, widths, header=True):
    data = [[P(c, cellb if (header and r == 0) else cell) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
          ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), ACC_L))
    t.setStyle(TableStyle(st))
    return t


# ---------- diagram ----------
def arrow(d, x1, y1, x2, y2, col=MUTED, dash=None):
    ln = Line(x1, y1, x2, y2, strokeColor=col, strokeWidth=0.8)
    if dash:
        ln.strokeDashArray = dash
    d.add(ln)
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    s = 3.2
    p1 = (x2 - s * math.cos(a - 0.45), y2 - s * math.sin(a - 0.45))
    p2 = (x2 - s * math.cos(a + 0.45), y2 - s * math.sin(a + 0.45))
    d.add(Polygon([x2, y2, p1[0], p1[1], p2[0], p2[1]], fillColor=col, strokeColor=col, strokeWidth=0.1))


def node(d, x, y, w, h, title, lines=(), fill=ACC_L, stroke=ACC, tcol=INK, fs=6.6):
    d.add(Rect(x, y, w, h, rx=2.5, ry=2.5, fillColor=fill, strokeColor=stroke, strokeWidth=0.7))
    d.add(String(x + w / 2, y + h - 8.2, title, fontName="Helvetica-Bold", fontSize=fs,
                 fillColor=tcol, textAnchor="middle"))
    for i, ln in enumerate(lines):
        d.add(String(x + w / 2, y + h - 16.5 - i * 7.3, ln, fontName="Helvetica", fontSize=5.7,
                     fillColor=MUTED, textAnchor="middle"))


def pipeline(W):
    H = 190
    d = Drawing(W, H)
    # top row: offline + online pipeline
    bw, bh, gap = 82, 40, 9.5
    y = H - bh - 4
    top = [("0  Knowledge build", ["WHO ClaML -> SQLite", "tree + rules + FTS"]),
           ("A  Ingest & layout", ["OCR + VLM, pages,", "sections, tables -> MD"]),
           ("B  Clinical extractor", ["mentions + assertion,", "laterality, timing"]),
           ("C  Normaliser", ["shorthand, brand drugs,", "Index-term retrieval"])]
    xs = []
    for i, (t, l) in enumerate(top):
        x = 2 + i * (bw + gap)
        xs.append(x)
        node(d, x, y, bw, bh, t, l, fill=colors.white if i == 0 else ACC_L,
             stroke=MUTED if i == 0 else ACC)
        if i > 0:
            arrow(d, x - gap, y + bh / 2, x, y + bh / 2)
    # right column: review
    rx = xs[-1] + bw + gap
    node(d, rx, y, W - rx - 2, bh, "Q  Output + coder review", ["codes, evidence spans,", "alts, doctor queries"],
         fill=WARN_L, stroke=WARN)
    # beam region
    by = 8
    bH = y - 18
    d.add(Rect(2, by, W - 4, bH, rx=3, ry=3, fillColor=colors.HexColor("#fafafa"),
               strokeColor=GRID, strokeWidth=0.6))
    d.add(String(8, by + bH - 9, "Per-concept beam search (k <= 3)  -  worked trace for: "
                 "\"k/c/o DM2 on Inj. Lantus, adm. for non-healing ulcer L heel, burning feet - diab. neuropathy, "
                 "RBS 380\"", fontName="Helvetica-Bold", fontSize=6.4, fillColor=INK))
    arrow(d, xs[-1] + bw / 2, y, xs[-1] + bw / 2, by + bH)
    cols = [8, 120, 238, 372]
    labels = ["L1  Chapter router", "L2  Block -> category", "L3  4th char (class or modifier)", "V  Rules & sequencing"]
    for c, lab in zip(cols, labels):
        d.add(String(c, by + bH - 21, lab, fontName="Helvetica-Bold", fontSize=6.4, fillColor=ACC))
    nw, nh = 100, 20

    def bnode(x, yy, t, l, pruned=False, w=nw):
        node(d, x, yy, w, nh, t, [l], fill=colors.HexColor("#f3f4f6") if pruned else colors.white,
             stroke=GRID if pruned else ACC, tcol=MUTED if pruned else INK, fs=6.2)
    r1, r2, r3 = by + bH - 50, by + bH - 80, by + bH - 110
    bnode(cols[0], r1, "IV (E00-E90)  0.55", "ulcer: diabetes w/ complication")
    bnode(cols[0], r2, "XII (L00-L99)  0.35", "ulcer: skin, lower limb")
    bnode(cols[0], r3, "VI (G00-G99)  0.80", "burning feet: polyneuropathy")
    bnode(cols[1], r1, "E11  0.82", "type 2; insulin alone is not E10")
    bnode(cols[1], r2, "L97  NEC  x", "rival loses: E11.5 includes it", pruned=True)
    bnode(cols[1], r3, "G63  0.78", "polyneuropathy in diseases CE")
    bnode(cols[2], r1, "E11.5", "inclusion \"Diabetic: ulcer\"", w=122)
    bnode(cols[2], r3, "G63.2*  <->  E11.4+", "asterisk needs its dagger", w=122)
    arrow(d, cols[0] + nw, r1 + nh / 2, cols[1], r1 + nh / 2, col=ACC)
    arrow(d, cols[1] + nw, r1 + nh / 2, cols[2], r1 + nh / 2, col=ACC)
    arrow(d, cols[0] + nw, r2 + nh / 2, cols[1], r2 + nh / 2, col=GRID)
    arrow(d, cols[0] + nw, r3 + nh / 2, cols[1], r3 + nh / 2, col=ACC)
    arrow(d, cols[1] + nw, r3 + nh / 2, cols[2], r3 + nh / 2, col=ACC)
    arrow(d, cols[1] + nw, r2 + nh / 2, cols[2] + 20, r1, col=WARN, dash=[2, 1.5])
    d.add(String(cols[2] + 26, r2 + 8, "excludes / NEC re-route", fontName="Helvetica", fontSize=5.6,
                 fillColor=WARN))
    vx = cols[3]
    vw = W - vx - 8
    node(d, vx, r3, vw, r1 + nh - r3, "Merged final set", [], fill=ACC_L, stroke=ACC, fs=6.4)
    out = ["1. E11.5  main: T2DM periph. circ.", "2. E11.4+ T2DM neurological compl.",
           "3. G63.2* diabetic polyneuropathy", "4. Z92.2  long-term meds (optional)",
           "E11.7 rejected: ulcer is the focus (Vol.2).", "R73.9 dropped: diabetes is confirmed.",
           "+ dagger, * asterisk: companions, not rivals."]
    for i, t in enumerate(out):
        d.add(String(vx + 5, r1 + nh - 18 - i * 8.2, t, fontName="Helvetica" if i > 3 else "Courier-Bold",
                     fontSize=5.9 if i > 3 else 5.8, fillColor=MUTED if i > 3 else INK))
    arrow(d, cols[2] + 122, r1 + nh / 2, vx, r1 + nh / 2, col=ACC)
    arrow(d, cols[2] + 122, r3 + nh / 2, vx, r3 + nh / 2, col=ACC)
    # back to review
    arrow(d, vx + vw - 10, r1 + nh, vx + vw - 10, y, col=WARN)
    return d


def build():
    doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=13 * mm, rightMargin=13 * mm,
                          topMargin=11 * mm, bottomMargin=11 * mm,
                          title="WHO ICD-10 Auto-Coding Approach", author="Vaibhav Singh")
    W = A4[0] - 26 * mm
    frame = Frame(doc.leftMargin, doc.bottomMargin, W, A4[1] - 22 * mm, id="f",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    def foot(c, d):
        c.setFont("Helvetica", 6.3)
        c.setFillColor(MUTED)
        c.drawString(13 * mm, 6 * mm, "WHO ICD-10 auto-coding for Indian discharge summaries  -  approach note")
        c.drawRightString(A4[0] - 13 * mm, 6 * mm, f"{d.page} / 2")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=foot)])

    s = []
    s.append(P("ICD-10 auto-coding for Indian discharge summaries", h1))
    s.append(P("Hierarchical multi-agent coding (L1 chapter, L2 category, L3 billable code) with beam routing. "
               "<b>Code set: WHO ICD-10 2019</b> (incl. COVID-19 updates). Knowledge base built by "
               "<font face='Courier'>data/who-icd10/prepare_who_icd10.py</font>. The problem was first studied "
               "on icd10data.com (ICD-10-CM).  -  17 Oct 2026", sub))
    s.append(Spacer(1, 3))

    # 1. problem
    s.append(P("1.  The real problem: two languages that don't match", h2))
    half = (W - 8) / 2
    left = [P("What the discharge summaries look like", h3)] + bl([
        "2-30 pages: scanned and digital pages mixed, letterheads, stamps, handwritten addenda, lab and drug-chart "
        "tables that run across pages.",
        "No standard template. Diagnoses sit under <i>Final Dx / Impression / Diagnosis</i>, but also in "
        "<i>Course in hospital</i>, procedure notes and the discharge medicines.",
        "Shorthand: <i>k/c/o T2DM, HTN on Tab Glycomet GP2</i>, <i>s/p PTCA to LAD 2019</i>, "
        "<i>?Dengue NS1 +ve</i>, <i>AKI on CKD</i>, <i>c/o fever x5d</i>, plus Hinglish and Indian brand names.",
        "Assertion changes the code. <i>no h/o</i> means no code. <i>?sepsis / r/o</i> means code the symptom "
        "(R-code), not the disease. <i>old CVA</i> becomes a sequela (I69) or history (Z86) code.",
    ])
    right = [P("What the WHO code book looks like (parsed ClaML)", h3)] + bl([
        "Tree: 22 chapters (I-XXII), 274 blocks, 2,090 three-character categories, <b>10,633 valid codes</b>. "
        "Only leaves can be coded; 1,058 of them (e.g. E11.5) are built from shared 4th-character tables.",
        "Formal titles are not doctor language. <i>\"non-healing ulcer, k/c/o DM2\"</i> is coded E11.5 "
        "<i>T2DM with peripheral circulatory complications</i>. Only the <b>inclusion term</b> "
        "\"Diabetic: ulcer\" connects them. There are 9.7k inclusion terms, and <b>no Alphabetic Index</b> in the "
        "WHO file, so we must build our own synonym layer.",
        "The rules sit in rubrics: <b>exclusions</b> (4,980 'not here, go to X' references), notes, coding hints, "
        "and <b>dagger (+) / asterisk (*)</b> pairs: cause + manifestation, e.g. E11.4+ G63.2*. "
        "Asterisk codes (373) are never coded alone or as the main condition.",
        "Main-condition choice follows WHO Volume 2 morbidity rules (MB1-MB5). Example: E1x.7 'multiple "
        "complications' only when no single complication is preferred. Detail codes are optional extras.",
    ])
    t = Table([[left, right]], colWidths=[half, half])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (0, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    s.append(t)
    s.append(Spacer(1, 2.5))
    s.append(P("<b>So coding is a constrained walk down a graph, not a text-similarity lookup.</b> Each level narrows "
               "the options, exclusions and dagger/asterisk pairs say which branches must, may or must not appear "
               "together, and missing documentation should lead to an '.9 unspecified' code plus a doctor query, "
               "never a guess.", base))
    s.append(Spacer(1, 3))
    s.append(box([P("<b>Decision: WHO ICD-10 2019 for India.</b> Source: WHO's public download page "
                    "(icdcdn.who.int/icd10, no login). The ClaML XML (9.6 MB) holds the tree and every rule; "
                    "the meta tables are the list of valid codes. <b>Differences from ICD-10-CM that change the "
                    "design:</b> codes are at most 4-5 characters, with no laterality and no 7th character (keep side and "
                    "encounter as evidence fields, since PM-JAY packages may need them). Code First / Use Additional "
                    "become dagger/asterisk. There are fewer combination codes (no E11.65; hyperglycaemia is not coded separately). "
                    "Long-term insulin is Z92.2, not Z79.4. Before commercial use, check WHO's licence terms and each "
                    "payer's (NHA/PM-JAY, IRDAI) code-set version. ICD-11 is the next migration; keep the graph "
                    "independent of code system.", small)],
                 ACC_L, ACC, W))

    # 2. architecture
    s.append(P("2.  Architecture: offline knowledge graph, online agent pipeline", h2))
    s.append(pipeline(W))

    # 3. agents
    s.append(P("3.  The agents", h2))
    rows = [["Agent", "What it does", "Inputs / tools", "Output (always with evidence spans)"],
            ["A  Ingest", "OCR (DocAI / Azure DI; a vision LLM for handwriting), classify pages, segment sections, rebuild tables, "
             "drop repeated headers, handle PDF or Markdown input", "PDF/MD, layout model", "Clean Markdown with page:line anchors"],
            ["B  Extractor", "Find every diagnosis, symptom, procedure and drug mention, with assertion (present / negated / "
             "possible / history / family), timing, laterality, acuity, cause links (<i>due to, secondary to</i>), "
             "and main-condition candidates", "LLM + Indian abbreviation and brand-drug lexicon", "Concept list in JSON"],
            ["C  Normaliser", "Expand shorthand (<i>Glycomet</i> to metformin, <i>Lantus</i> to insulin glargine), map "
             "each concept to WHO wording", "SQLite FTS5 over titles + inclusion terms + parent titles; vectors; "
             "synonym layer", "Canonical concept + top candidate codes"],
            ["L1  Chapter router", "Pick 1-3 of the 22 chapters. The prompt includes chapter notes and exclusions, plus priors: "
             "pregnancy goes to XV (O) first, neoplasm to II, injury to XIX + XX, XVIII (R) only if no confirmed diagnosis",
             "Small fast LLM + rules", "Scored chapter beam"],
            ["L2  Category", "Within each surviving chapter, choose block and then 3-char category using inclusions and "
             "exclusions. An exclusion re-routes the path to the referenced code instead of killing it",
             "<font face='Courier'>nodes WHERE parent=?</font>, edges", "Scored category beam"],
            ["L3  4th character", "Each split is one question (type? with which complication? acute?). The 4th character "
             "comes from the class or its shared modifier table. If nothing is documented, use .8/.9 and raise a query",
             "Children + inclusions of each", "Valid code or unspecified + query"],
            ["V  Validator", "Mostly hard-coded checks: valid leaf, exclusion clashes, <b>every * paired with its +, "
             "and * never as main</b>, MB1-MB5 main-condition rules, the .7 multiple-complications rule, drop R-codes covered "
             "by a confirmed diagnosis, age/sex edits", "Rules engine on the edges table + LLM explainer",
             "Final ordered code set"],
            ]
    s.append(grid_table(rows, [W * 0.12, W * 0.47, W * 0.19, W * 0.22]))

    # 4. beam
    s.append(KeepTogether([P("4.  Parallel routing: keep the top-N, then prune as evidence arrives", h2)] + bl([
        "<b>Branch only when needed:</b> fork a concept only if the gap between candidates #1 and #2 is under "
        "&delta; (around 0.15), or the knowledge base says the concept spans chapters (a dagger/asterisk pair or "
        "an exclusion pointing elsewhere). Keep at most 3 paths per concept, so cost stays bounded.",
        "<b>Score</b> = agreement across 5 LLM samples (self-consistency) x retrieval similarity x rule prior, "
        "calibrated on the gold set. The score and the reasoning travel with each path.",
        "<b>Prune when</b> new evidence contradicts a path (negation, sex or age, an exclusion clash with a confirmed "
        "code), a 'not elsewhere classified' path loses to a code that includes the concept (L97 vs E11.5), "
        "a path dead-ends, or its score drops below &tau; x best. Late evidence such as discharge meds, labs or the "
        "procedure note re-scores the paths still alive. For example, Inj. Lantus with no type 1 history keeps E11 "
        "and adds the optional Z92.2.",
        "<b>Backtrack instead of forcing:</b> if no 4th character fits, go back to the L2 alternatives before "
        "settling for '.9'. At the end the validator labels surviving paths as <b>rivals</b> (keep one, others go "
        "to the coder as alternatives) or <b>companions</b> (code all of them: dagger + asterisk, optional detail "
        "codes).",
    ])))

    # 5. knowledge base
    s.append(KeepTogether([P("5.  Knowledge base: built and validated "
                             "(<font face='Courier'>data/who-icd10/</font>)", h2)] + bl([
        "<b>One command</b>, <font face='Courier'>python3 prepare_who_icd10.py</font>, using only the standard "
        "library. It downloads both WHO zips (SHA-256 recorded), extracts them, parses the ClaML, expands "
        "modifier-derived codes (E11 + '.5' -> E11.5, only those WHO lists as valid), validates, and builds the "
        "outputs. Hard checks: 22 chapters, all 10,633 valid codes present, every parent exists, valid = leaf. "
        "All pass.",
        "<b>Outputs:</b> <font face='Courier'>nodes.jsonl</font> (12,597 nodes with path, inclusions, exclusions, "
        "notes, hints, dagger/asterisk flag, mortality lists); <font face='Courier'>edges.csv</font> (child_of "
        "12,575, excludes 4,980, dagger->asterisk 304, asterisk->dagger 114); <font face='Courier'>.sqlite</font> "
        "with an FTS5 <i>search</i> table (the agents' retrieval tool); <font face='Courier'>manifest.json</font> "
        "for audit. The README explains the XML element by element.",
        "<b>Still to add:</b> a synonym layer for doctor language (Indian abbreviations, brand drugs, coder-accepted "
        "phrasings, optionally ICD-11 index terms mapped to ICD-10), and payer package mappings (PM-JAY HBP). "
        "Use icd10data.com only as a human reference.",
    ])))

    # 6. eval
    s.append(P("6.  Evaluation, guardrails and rollout", h2))
    ev = [["Gold set and metrics", "Guardrails", "Phases"],
          ["300-500 de-identified summaries from 3+ hospitals, double-coded in WHO ICD-10 by certified coders and "
           "adjudicated. Measure: main-condition exact match; code-level P/R/F1 at 3 and 4 characters; top-3 "
           "recall; dagger/asterisk pairing accuracy; % auto-accepted at 95% or higher precision; evidence "
           "faithfulness.",
           "No code without a quoted evidence span. Never invent a complication link (<i>diabetic</i> X) the doctor "
           "did not write; raise a query instead. PHI stays in an India region (DPDP Act 2023). Log every beam "
           "decision for audit. Coder edits feed a hospital-specific shorthand memory and few-shot examples.",
           "W1: knowledge base (done).  W2-3: ingestion.  W4-7: extractor and L1-L3 agents.  W8-10: validator + "
           "coder UI.  W11+: shadow mode next to human coders, active learning, then auto-accept for "
           "high-confidence chapters first."]]
    s.append(grid_table(ev, [W * 0.36, W * 0.34, W * 0.30]))
    s.append(Spacer(1, 2))
    s.append(P("Model choice: a small, fast model (e.g. Claude Haiku 5.5) for L1 routing and OCR clean-up; a "
               "mid-size model (Sonnet 5.5) for extraction and L2/L3; the largest (Opus 5.5) only for low-margin "
               "paths and validator explanations. Every prompt gets only the subtree in play (one SQL query), not "
               "the whole code set.", small))

    # 7. output contract
    s.append(KeepTogether([P("7.  Output contract (one record per concept, so every step can be audited)", h2),
        Preformatted("""{ "concept": "diabetic foot ulcer, left heel",
  "evidence": [{"page": 3, "line": 14, "text": "k/c/o DM2 on Inj. Lantus ... non-healing ulcer L heel"}],
  "assertion": "present", "laterality": "left (evidence only - not in WHO code)", "acuity": "chronic",
  "beam": [ {"path": ["IV", "E10-E14", "E11", "E11.5"], "score": 0.84, "status": "main condition",
             "matched": "inclusion 'Diabetic: ulcer'"},
            {"path": ["XII", "L80-L99", "L97"],          "score": 0.35, "status": "pruned: NEC, included at E11.5"},
            {"path": ["IV", "E10-E14", "E11", "E11.7"], "score": 0.30, "status": "rejected: ulcer is the focus (MB rules)"} ],
  "companions": ["E11.4+ / G63.2* (diabetic polyneuropathy)", "Z92.2 (optional: long-term insulin)"],
  "queries": [],
  "rules_fired": ["G63.2 asterisk_needs_dagger -> E11.4", "R73.9 dropped: diabetes confirmed"] }""", code)]))
    doc.build(s)


build()
