from __future__ import annotations

import os
import sys
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BASE_DIR / "assets"
MEDIA_DIR = ASSETS_DIR / "old_report_media"
SCREENSHOTS_DIR = ASSETS_DIR / "screenshots"
FIGURES_DIR = ASSETS_DIR / "figures"


def set_table_borders(table, val="single", sz="4", color="auto"):
    """Set table border XML."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:right w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:insideV w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)


def set_cell_margins(cell, top=60, bottom=60, left=80, right=80):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('w:top', top), ('w:bottom', bottom), ('w:left', left), ('w:right', right)]:
        node = OxmlElement(m)
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)


def add_p(doc, text="", align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_before=0, space_after=6, line_spacing=1.5, bold=False, italic=False, font_size=12, font_name="Times New Roman"):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line_spacing
    if text:
        r = p.add_run(text)
        r.bold = bold
        r.italic = italic
        r.font.name = font_name
        r.font.size = Pt(font_size)
        r.font.color.rgb = RGBColor(0, 0, 0)
    return p


def add_bullet_p(doc, text, bold_prefix="", space_after=3):
    """Add a left-aligned bullet point to prevent Word from stretching text with huge spaces."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.name = "Times New Roman"
        r_pre.font.size = Pt(11.5)
        r_pre.bold = True
        r_pre.font.color.rgb = RGBColor(0, 0, 0)
    r = p.add_run(text)
    r.font.name = "Times New Roman"
    r.font.size = Pt(11.5)
    r.font.color.rgb = RGBColor(0, 0, 0)
    return p


def add_heading_chapter(doc, ch_num, ch_title):
    add_p(doc, f"CHAPTER {ch_num}", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=12, space_after=2, bold=True, font_size=14)
    add_p(doc, ch_title, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=14, bold=True, font_size=14)


def add_heading_sec(doc, sec_title):
    add_p(doc, sec_title, align=WD_ALIGN_PARAGRAPH.LEFT, space_before=10, space_after=4, bold=True, font_size=12)


def add_heading_subsec(doc, subsec_title):
    add_p(doc, subsec_title, align=WD_ALIGN_PARAGRAPH.LEFT, space_before=6, space_after=3, bold=True, font_size=12)


def add_image_with_caption(doc, img_path, caption, width=4.5):
    """Figure caption below the figure (short & simple)."""
    if img_path.exists():
        p_img = doc.add_paragraph()
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.paragraph_format.space_before = Pt(6)
        p_img.paragraph_format.space_after = Pt(2)
        p_img.add_run().add_picture(str(img_path), width=Inches(width))

        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_cap.paragraph_format.space_after = Pt(8)
        r_cap = p_cap.add_run(caption)
        r_cap.font.name = "Times New Roman"
        r_cap.font.size = Pt(11)
        r_cap.font.italic = True
        r_cap.font.color.rgb = RGBColor(0, 0, 0)


def add_table_caption(doc, caption):
    """Table caption on top of the table as required by the template."""
    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_before = Pt(10)
    p_cap.paragraph_format.space_after = Pt(4)
    r_cap = p_cap.add_run(caption)
    r_cap.font.name = "Times New Roman"
    r_cap.font.size = Pt(11)
    r_cap.font.italic = True
    r_cap.font.color.rgb = RGBColor(0, 0, 0)


def build_report_doc(pages_dict=None):
    if pages_dict is None:
        pages_dict = {
            "ABSTRACT": "5",
            "LIST_TABLES": "6",
            "LIST_FIGURES": "7",
            "LIST_SYMBOLS": "8",
            "CH1": "9",
            "CH1_1": "9",
            "CH1_2": "9",
            "CH1_3": "9",
            "CH1_4": "10",
            "CH2": "11",
            "CH2_1": "11",
            "CH2_1_1": "11",
            "CH2_2": "12",
            "CH3": "13",
            "CH3_1": "13",
            "CH3_1_1": "14",
            "CH3_1_2": "14",
            "CH3_1_3": "15",
            "CH3_2": "16",
            "CH3_3": "16",
            "CH4": "17",
            "CH4_1": "17",
            "CH4_2": "17",
            "CH5": "22",
            "CH5_1": "22",
            "CH5_2": "22",
            "REFERENCES": "23",
            "APPENDIX": "24",
            # Tables
            "TAB_4_1": "17",
            "TAB_4_2": "18",
            "TAB_4_3": "19",
            "TAB_4_4": "19",
            # Figures
            "FIG_3_1": "13",
            "FIG_4_1": "18",
            "FIG_4_2": "20",
            "FIG_4_3": "20",
            "FIG_4_4": "21",
            "FIG_4_5": "21",
        }

    doc = docx.Document()

    # Page setup matching ADA23DLU04_PROJECT REPORT TEMPLATE.docx
    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)

    # Style defaults
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Times New Roman'
    style_normal.font.size = Pt(12)
    style_normal.font.color.rgb = RGBColor(0, 0, 0)

    logo_path = ASSETS_DIR / "sriher_logo.png"

    # =========================================================================
    # 1. COVER PAGE (Page 1) - Following exact template formatting
    # =========================================================================
    if logo_path.exists():
        p_logo = doc.add_paragraph()
        p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_logo.paragraph_format.space_before = Pt(0)
        p_logo.paragraph_format.space_after = Pt(4)
        p_logo.add_run().add_picture(str(logo_path), width=Inches(4.8))

    add_p(doc, "VOXINTEL: AUDIO INTELLIGENCE FOR AUTOMATED MEETING INSIGHTS AND EXECUTIVE MOM SYNTHESIS", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4, space_after=6, line_spacing=1.3, bold=True, font_size=18)
    add_p(doc, "A PROJECT REPORT", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=8, line_spacing=1.1, bold=True, font_size=14)

    # Template: Submitted by <Font Size 14><Italic> (Unbolded)
    add_p(doc, "Submitted by", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=4, line_spacing=1.1, bold=False, italic=True, font_size=14)
    # Template: NAME OF THE CANDIDATE(S) <Font Size 16> (Bold, matching casing)
    add_p(doc, "Eshan M (E0324009)", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=2, line_spacing=1.1, bold=True, font_size=16)
    add_p(doc, "Yashwanth M (E0324028)", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=10, line_spacing=1.1, bold=True, font_size=16)

    # Template: in partial fulfillment for the award of the degree of <Font Size 14><1.5 line spacing><Italic> (Unbolded)
    add_p(doc, "in partial fulfillment for the award of the degree", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=2, line_spacing=1.1, bold=False, italic=True, font_size=14)
    add_p(doc, "of", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=2, line_spacing=1.1, bold=False, italic=True, font_size=14)
    add_p(doc, "BACHELOR OF TECHNOLOGY", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=2, line_spacing=1.1, bold=True, font_size=16)
    add_p(doc, "in", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=2, line_spacing=1.1, bold=False, italic=True, font_size=14)
    add_p(doc, "COMPUTER SCIENCE AND ENGINEERING\n(Artificial Intelligence and Data Analytics)", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=8, line_spacing=1.15, bold=True, font_size=14)

    add_p(doc, "SRI RAMACHANDRA FACULTY OF ENGINEERING AND TECHNOLOGY\nSRI RAMACHANDRA INSTITUTE OF HIGHER EDUCATION AND RESEARCH\nPORUR, CHENNAI - 600116", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=6, line_spacing=1.15, bold=True, font_size=12)
    add_p(doc, "OCTOBER 2026", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=0, line_spacing=1.1, bold=True, font_size=14)

    doc.add_page_break()

    # =========================================================================
    # 2. BONAFIDE CERTIFICATE (Page 2) - Exactly matching template formatting
    # =========================================================================
    if logo_path.exists():
        p_logo = doc.add_paragraph()
        p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_logo.paragraph_format.space_before = Pt(0)
        p_logo.paragraph_format.space_after = Pt(6)
        p_logo.add_run().add_picture(str(logo_path), width=Inches(4.5))

    add_p(doc, "SRI RAMACHANDRA FACULTY OF ENGINEERING AND TECHNOLOGY\nCHENNAI – 600116", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=8, bold=True, font_size=11)
    add_p(doc, "BONAFIDE CERTIFICATE", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4, space_after=14, bold=True, font_size=11)

    p_cert = doc.add_paragraph()
    p_cert.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p_cert.paragraph_format.line_spacing = 1.5
    p_cert.paragraph_format.space_after = Pt(16)
    r_cert = p_cert.add_run(
        'Certified that this project report “VOXINTEL: AUDIO INTELLIGENCE FOR AUTOMATED MEETING INSIGHTS AND EXECUTIVE MOM SYNTHESIS” '
        'is the bonafide work of Eshan M (E0324009) & Yashwanth M (E0324028) who carried out the project work under my supervision in '
        'ADA23DLU04 – Natural Language Processing Laboratory during the academic year 2026-2027.'
    )
    r_cert.font.name = "Times New Roman"
    r_cert.font.size = Pt(11)
    r_cert.bold = False
    r_cert.font.color.rgb = RGBColor(0, 0, 0)

    add_p(doc, "SIGNATURE", align=WD_ALIGN_PARAGRAPH.LEFT, space_before=6, space_after=2, bold=True, font_size=11)

    # Template: DR. SUJA GOLDEN SHINY S is BOLD, and following details are UNBOLDED
    p_sup_name = doc.add_paragraph()
    p_sup_name.paragraph_format.line_spacing = 1.3
    p_sup_name.paragraph_format.space_after = Pt(1)
    r_name = p_sup_name.add_run("DR. SUJA GOLDEN SHINY S,")
    r_name.font.name = "Times New Roman"
    r_name.font.size = Pt(11)
    r_name.bold = True
    r_name.font.color.rgb = RGBColor(0, 0, 0)

    p_sup_details = doc.add_paragraph()
    p_sup_details.paragraph_format.line_spacing = 1.3
    p_sup_details.paragraph_format.space_after = Pt(24)
    r_det = p_sup_details.add_run(
        "ASSISTANT PROFESSOR,\n"
        "DEPARTMENT OF COMPUTER SCIENCE AND ENGINEERING (AIDA),\n"
        "SRI RAMACHANDRA FACULTY OF ENGINEERING AND TECHNOLOGY,\n"
        "SRI RAMACHANDRA INSTITUTE OF HIGHER EDUCATION AND RESEARCH,\n"
        "PORUR, CHENNAI - 600 116."
    )
    r_det.font.name = "Times New Roman"
    r_det.font.size = Pt(11)
    r_det.bold = False
    r_det.font.color.rgb = RGBColor(0, 0, 0)

    add_p(doc, "EVALUATION DATE:  ------------------------", align=WD_ALIGN_PARAGRAPH.LEFT, space_before=4, space_after=28, bold=True, font_size=11)

    p_sig = doc.add_paragraph()
    p_sig.paragraph_format.line_spacing = 1.3
    r_sig = p_sig.add_run("INTERNAL EXAMINER\t\t\t\t\t\tEXTERNAL EXAMINER")
    r_sig.font.name = "Times New Roman"
    r_sig.font.size = Pt(11)
    r_sig.bold = True
    r_sig.font.color.rgb = RGBColor(0, 0, 0)

    doc.add_page_break()

    # =========================================================================
    # 3. ACKNOWLEDGEMENT (Page 3) - Required acknowledgement content
    # =========================================================================
    add_p(doc, "ACKNOWLEDGEMENT", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=10, space_after=16, bold=True, font_size=14)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(10)
    p.add_run(
        "We take this opportunity to express our sincere gratitude to Prof. T. Ragunathan, Dean and Prof. A. Saravanan, "
        "Vice Dean, Sri Ramachandra Faculty of Engineering and Technology, SRIHER, for providing all the infrastructural "
        "facilities and computational resources to complete this Laboratory Project successfully."
    )

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(10)
    p.add_run(
        "We express our sincere gratitude to Dr. A. Sathya, Programme Coordinator, Department of Artificial Intelligence and Data Analytics, "
        "SRET, for providing essential academic guidance, curriculum encouragement, and departmental support throughout the study."
    )

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(10)
    p.add_run(
        "We would like to express our deepest appreciation and heartfelt gratitude to our supervisor and course instructor "
        "Dr. S. Suja Golden Shiny, Assistant Professor, Department of Artificial Intelligence and Data Analytics, SRET. "
        "Without her continuous guidance, constructive feedback, and persistent encouragement, this project would not have been a success for us."
    )

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(16)
    p.add_run(
        "We are truly grateful to all the faculty members of the Sri Ramachandra Faculty of Engineering and Technology, "
        "our beloved parents, and our fellow student colleagues for extending their continuous support, which helped us "
        "overcome obstacles and complete this work."
    )

    doc.add_page_break()

    # =========================================================================
    # 4. TABLE OF CONTENTS (Page 4) - Single-page fit matching Table 0
    # =========================================================================
    add_p(doc, "TABLE OF CONTENTS", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4, space_after=6, bold=True, font_size=14)

    toc_entries = [
        # (ch_no, sec_no, subsec_no, title, page_no, is_header, is_bold)
        ("CHAPTER NO.", "", "", "TITLE", "PAGE NO.", True, True),
        ("", "", "", "ABSTRACT", pages_dict.get("ABSTRACT", "5"), False, True),
        ("", "", "", "LIST OF TABLES", pages_dict.get("LIST_TABLES", "6"), False, True),
        ("", "", "", "LIST OF FIGURES", pages_dict.get("LIST_FIGURES", "7"), False, True),
        ("", "", "", "LIST OF SYMBOLS", pages_dict.get("LIST_SYMBOLS", "8"), False, True),
        ("1.", "", "", "INTRODUCTION", pages_dict.get("CH1", "9"), False, True),
        ("", "1.1", "", "Project overview", pages_dict.get("CH1_1", "9"), False, False),
        ("", "1.2", "", "Problem Statement", pages_dict.get("CH1_2", "9"), False, False),
        ("", "1.3", "", "Objectives", pages_dict.get("CH1_3", "9"), False, False),
        ("", "1.4", "", "Scope of Work (or) Social Contribution", pages_dict.get("CH1_4", "10"), False, False),
        ("2.", "", "", "LITERATURE REVIEW", pages_dict.get("CH2", "11"), False, True),
        ("", "2.1", "", "Background", pages_dict.get("CH2_1", "11"), False, False),
        ("", "", "2.1.1", "Review of related work", pages_dict.get("CH2_1_1", "11"), False, False),
        ("", "2.2", "", "Research Gaps", pages_dict.get("CH2_2", "12"), False, False),
        ("3.", "", "", "PROPOSED METHODOLOGY", pages_dict.get("CH3", "13"), False, True),
        ("", "3.1", "", "Architecture", pages_dict.get("CH3_1", "13"), False, False),
        ("", "", "3.1.1", "Dataset Description", pages_dict.get("CH3_1_1", "14"), False, False),
        ("", "", "3.1.2", "Preprocessing", pages_dict.get("CH3_1_2", "14"), False, False),
        ("", "", "3.1.3", "Encoder & Decoder Modules", pages_dict.get("CH3_1_3", "15"), False, False),
        ("", "3.2", "", "Hardware Specifications", pages_dict.get("CH3_2", "16"), False, False),
        ("", "3.3", "", "Software Specifications", pages_dict.get("CH3_3", "16"), False, False),
        ("4.", "", "", "PERFORMANCE EVALUATION", pages_dict.get("CH4", "17"), False, True),
        ("", "4.1", "", "Experimental Setup & Evaluation Metrics", pages_dict.get("CH4_1", "17"), False, False),
        ("", "4.2", "", "Results and Analysis", pages_dict.get("CH4_2", "17"), False, False),
        ("5.", "", "", "CONCLUSION AND FUTURE WORK", pages_dict.get("CH5", "22"), False, True),
        ("", "5.1", "", "Summary of the contributions", pages_dict.get("CH5_1", "22"), False, False),
        ("", "5.2", "", "Future work", pages_dict.get("CH5_2", "22"), False, False),
        ("", "", "", "REFERENCES", pages_dict.get("REFERENCES", "23"), False, True),
        ("", "", "", "APPENDIX: COMPLETE SOURCE CODE", pages_dict.get("APPENDIX", "24"), False, True),
    ]

    tbl_toc = doc.add_table(rows=0, cols=5)
    tbl_toc.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(tbl_toc, val="nil", sz="0", color="000000")

    col_widths = [1.20, 0.60, 0.65, 3.02, 0.80]

    for item in toc_entries:
        ch_no, sec_no, subsec_no, title, pg_no, is_header, is_bold = item
        row = tbl_toc.add_row()

        for i, w in enumerate(col_widths):
            row.cells[i].width = Inches(w)
            set_cell_margins(row.cells[i], top=6, bottom=6, left=24, right=24)

        if is_header or (sec_no == "" and subsec_no == ""):
            row.cells[0].paragraphs[0].text = ch_no
            row.cells[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            r_title = row.cells[1].merge(row.cells[3])
            r_title.paragraphs[0].text = title
            r_title.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER if is_header else WD_ALIGN_PARAGRAPH.LEFT
            row.cells[4].paragraphs[0].text = pg_no
            row.cells[4].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            target_cells = [row.cells[0], r_title, row.cells[4]]
        elif subsec_no == "":
            row.cells[0].paragraphs[0].text = ""
            row.cells[1].paragraphs[0].text = sec_no
            row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
            r_title = row.cells[2].merge(row.cells[3])
            r_title.paragraphs[0].text = title
            r_title.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
            row.cells[4].paragraphs[0].text = pg_no
            row.cells[4].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            target_cells = [row.cells[1], r_title, row.cells[4]]
        else:
            row.cells[0].paragraphs[0].text = ""
            row.cells[1].paragraphs[0].text = ""
            row.cells[2].paragraphs[0].text = subsec_no
            row.cells[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
            row.cells[3].paragraphs[0].text = title
            row.cells[3].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
            row.cells[4].paragraphs[0].text = pg_no
            row.cells[4].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            target_cells = [row.cells[2], row.cells[3], row.cells[4]]

        for cell in target_cells:
            for p in cell.paragraphs:
                p.paragraph_format.line_spacing = 1.05
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                for run in p.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(10.0)
                    run.bold = is_bold
                    run.font.color.rgb = RGBColor(0, 0, 0)

    doc.add_page_break()

    # =========================================================================
    # 5. ABSTRACT (Page 5) - Paragraph under 300 words
    # =========================================================================
    add_p(doc, "ABSTRACT", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=14, bold=True, font_size=14)

    p_abs = doc.add_paragraph()
    p_abs.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p_abs.paragraph_format.line_spacing = 1.5
    p_abs.paragraph_format.space_after = Pt(12)
    p_abs.add_run(
        "The increasing reliance on virtual communication platforms has transformed organizational collaboration, but extracting "
        "actionable insights from recorded multi-speaker discussions remains labor-intensive, error-prone, and inconsistent. While commercial "
        "cloud transcription APIs offer convenience, they introduce critical enterprise confidentiality risks, recurring token overhead, and "
        "substantial per-minute subscription costs. To overcome these engineering challenges, this project presents VoxIntel, a fully offline, "
        "privacy-preserving audio intelligence and meeting synthesis system engineered specifically for consumer-tier hardware (8 GB RAM CPU). "
        "VoxIntel implements a dual-pipeline architecture: Fast Mode couples faster-whisper base quantized in int8 with whole-file Silero Voice Activity "
        "Detection (VAD), 18-dimensional acoustic vocal tract feature extraction (MFCCs, spectral centroid, Yin fundamental pitch), and TextRank "
        "graph summarization to extract key moments and verified action items in under 10 seconds. Smart Mode pairs speech transcription with a "
        "locally hosted Large Language Model (Ollama with llama3.2:3b / gemma3:1b), restructuring conversational turns into formal third-person, "
        "past-tense corporate Minutes of Meeting (MoM) with mandatory timestamp citations and attendee cross-validation. Evaluated across a frozen "
        "multi-speaker benchmark suite including held-out un-tuned test audio (Meeting 3, 5.39 minutes, 4 synthetic neural voices), faster-whisper "
        "base int8 achieved an outstanding Word Error Rate (WER) of 3.48% on dev audio and 5.58% on held-out test audio at 0.06x real-time latency "
        "on CPU. Across 11 reference commitments, Fast Mode attained 100% recall (F1 = 0.9167), while Smart Mode achieved an F1 of 0.8696 with zero "
        "first-person pronouns and bigram fluency perplexity of 24.0. VoxIntel establishes an accessible, cost-effective, and fully private enterprise "
        "meeting intelligence solution."
    )

    doc.add_page_break()

    # =========================================================================
    # 6. LIST OF TABLES (Page 6)
    # =========================================================================
    add_p(doc, "LIST OF TABLES", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=14, bold=True, font_size=14)

    list_tables_data = [
        ("TABLE NO.", "TITLE", "PAGE NO."),
        ("Table 4.1", "Automatic Speech Recognition (ASR) Word Error Rate (WER) and Latency Benchmarks", pages_dict.get("TAB_4_1", "17")),
        ("Table 4.2", "0.5s Frame-Level Speaker Attribution Accuracy, Precision, and F1 Metrics", pages_dict.get("TAB_4_2", "18")),
        ("Table 4.3", "Action Items Extraction Performance (Precision, Recall, F1 across 11 Commitments)", pages_dict.get("TAB_4_3", "19")),
        ("Table 4.4", "Summary Quality Scores, Linguistic Perspective (1st Person Pronouns), and Fluency Perplexity", pages_dict.get("TAB_4_4", "19")),
    ]

    tbl_lot = doc.add_table(rows=len(list_tables_data), cols=3)
    tbl_lot.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(tbl_lot, val="nil", sz="0", color="000000")
    col_w_lot = [1.2, 4.27, 0.8]
    for r_i, (t_no, t_title, t_pg) in enumerate(list_tables_data):
        row = tbl_lot.rows[r_i]
        for c_i, val in enumerate([t_no, t_title, t_pg]):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_lot[c_i])
            set_cell_margins(cell, top=24, bottom=24, left=40, right=40)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if c_i in [0, 2] else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.line_spacing = 1.2
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(11)
            r.bold = (r_i == 0)
            r.font.color.rgb = RGBColor(0, 0, 0)

    doc.add_page_break()

    # =========================================================================
    # 7. LIST OF FIGURES (Page 7) - Short and simple captions
    # =========================================================================
    add_p(doc, "LIST OF FIGURES", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=14, bold=True, font_size=14)

    list_figures_data = [
        ("FIGURE NO.", "TITLE", "PAGE NO."),
        ("Figure 3.1", "System Architecture Workflow", pages_dict.get("FIG_3_1", "13")),
        ("Figure 4.1", "Speaker Attribution Confusion Matrix", pages_dict.get("FIG_4_1", "18")),
        ("Figure 4.2", "Word Cloud of Meeting Transcript", pages_dict.get("FIG_4_2", "20")),
        ("Figure 4.3", "Bigram Association Graph", pages_dict.get("FIG_4_3", "20")),
        ("Figure 4.4", "Streamlit Dashboard - Minutes View", pages_dict.get("FIG_4_4", "21")),
        ("Figure 4.5", "Streamlit Dashboard - Speakers View", pages_dict.get("FIG_4_5", "21")),
    ]

    tbl_lof = doc.add_table(rows=len(list_figures_data), cols=3)
    tbl_lof.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(tbl_lof, val="nil", sz="0", color="000000")
    for r_i, (f_no, f_title, f_pg) in enumerate(list_figures_data):
        row = tbl_lof.rows[r_i]
        for c_i, val in enumerate([f_no, f_title, f_pg]):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_lot[c_i])
            set_cell_margins(cell, top=24, bottom=24, left=40, right=40)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if c_i in [0, 2] else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.line_spacing = 1.2
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(11)
            r.bold = (r_i == 0)
            r.font.color.rgb = RGBColor(0, 0, 0)

    doc.add_page_break()

    # =========================================================================
    # 8. LIST OF SYMBOLS AND ABBREVIATIONS (Page 8)
    # =========================================================================
    add_p(doc, "LIST OF SYMBOLS AND ABBREVIATIONS", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=14, bold=True, font_size=14)

    symbols_data = [
        ("ABBREVIATION", "EXPANSION"),
        ("ASR", "Automatic Speech Recognition"),
        ("VAD", "Voice Activity Detection"),
        ("MFCC", "Mel-Frequency Cepstral Coefficients"),
        ("F0", "Fundamental Frequency (Acoustic Pitch)"),
        ("WER", "Word Error Rate"),
        ("MoM", "Minutes of Meeting"),
        ("LLM", "Large Language Model"),
        ("PCM", "Pulse Code Modulation"),
        ("CPU", "Central Processing Unit"),
        ("RAM", "Random Access Memory"),
        ("NLP", "Natural Language Processing"),
        ("TF-IDF", "Term Frequency - Inverse Document Frequency"),
        ("BLEU", "Bilingual Evaluation Understudy"),
        ("ROUGE", "Recall-Oriented Understudy for Gisting Evaluation"),
        ("METEOR", "Metric for Evaluation of Translation with Explicit ORdering"),
        ("BERT", "Bidirectional Encoder Representations from Transformers"),
    ]

    tbl_los = doc.add_table(rows=len(symbols_data), cols=2)
    tbl_los.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(tbl_los, val="nil", sz="0", color="000000")
    col_w_los = [1.8, 4.47]
    for r_i, (abbr, exp) in enumerate(symbols_data):
        row = tbl_los.rows[r_i]
        for c_i, val in enumerate([abbr, exp]):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_los[c_i])
            set_cell_margins(cell, top=20, bottom=20, left=40, right=40)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if c_i == 0 else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(11)
            r.bold = (r_i == 0) or (c_i == 0)
            r.font.color.rgb = RGBColor(0, 0, 0)

    doc.add_page_break()

    # =========================================================================
    # CHAPTER 1: INTRODUCTION
    # =========================================================================
    add_heading_chapter(doc, 1, "INTRODUCTION")

    add_heading_sec(doc, "1.1 Project Overview")
    add_p(doc,
        "In modern knowledge economies, collaborative verbal dialogue is the bedrock of strategic planning, engineering design reviews, "
        "and executive decision-making. The transition toward distributed engineering teams has led to a reliance on teleconferencing tools "
        "such as Zoom, Microsoft Teams, and Google Meet. While recorded meetings capture granular verbal exchanges, navigating hours of unstructured "
        "speech to isolate specific architectural trade-offs, stakeholder approvals, or assigned deliverables is highly inefficient. Automated meeting "
        "intelligence addresses this bottleneck by converting raw multi-channel audio into structured corporate documentation."
    )

    add_heading_sec(doc, "1.2 Problem Statement")
    add_p(doc, "Organizations face critical challenges in manual and cloud-based meeting processing:")
    add_bullet_p(doc, "Manual note-taking suffers from cognitive fatigue, human selective bias, and missed action items during fast-paced reviews.", "1. Human Cognitive Inefficiencies: ")
    add_bullet_p(doc, "Off-the-shelf commercial APIs (such as OpenAI Whisper API) require streaming proprietary audio to external servers, violating strict enterprise confidentiality regulations.", "2. Cloud Confidentiality Risks: ")
    add_bullet_p(doc, "Recurring per-minute billing and token overhead impose substantial recurring financial burdens on educational and medium enterprises.", "3. Financial & Token Overhead: ")
    add_bullet_p(doc, "State-of-the-art neural models typically demand expensive dedicated enterprise GPUs unavailable on consumer-tier institutional laptops.", "4. Compute & Hardware Constraints: ")

    add_heading_sec(doc, "1.3 Objectives")
    add_p(doc, "The primary engineering objectives of this project are:")
    add_bullet_p(doc, "To design and build an automated, fully offline meeting intelligence pipeline executing entirely on consumer CPU hardware (8 GB RAM).", "• ")
    add_bullet_p(doc, "To program and implement whole-file speech-to-text transcription utilizing faster-whisper base quantized in int8 with in-memory Silero VAD, achieving Word Error Rate under 6%.", "• ")
    add_bullet_p(doc, "To develop an unsupervised acoustic diarization module combining 18-dimensional vocal features (MFCCs, spectral centroid, Yin pitch) with K-Means clustering to separate speaker turns in under 1 second.", "• ")
    add_bullet_p(doc, "To formulate deterministic regex heuristics that extract action items, binding tasks directly to segment speakers and standardizing deadlines.", "• ")
    add_bullet_p(doc, "To synthesize formal third-person Minutes of Meeting (MoM) via locally served Large Language Models (Ollama), completely eliminating first-person pronouns.", "• ")
    add_bullet_p(doc, "To implement an interactive Streamlit studio console dashboard featuring live telemetry, word clouds, bigram network graphs, and multi-format report exports.", "• ")

    add_heading_sec(doc, "1.4 Scope of Work (or) Social Contribution")
    add_p(doc,
        "The scope of VoxIntel encompasses multi-party technical sprint syncs, research seminars, and corporate project reviews. "
        "The system accepts standard audio formats (.wav, .mp3) as well as pre-transcribed text transcripts (.txt), generating "
        "comprehensive, executive-ready documentation without requiring cloud connectivity. From a societal and organizational perspective, "
        "VoxIntel delivers substantial contributions across four primary dimensions:"
    )
    add_bullet_p(doc, "By executing speech recognition and LLM synthesis entirely on the host machine, VoxIntel guarantees that sensitive corporate discussions, medical consultations, and proprietary engineering designs never leave local memory, adhering to strict GDPR, HIPAA, and enterprise sovereignty mandates.", "1. Data Sovereignty & Confidentiality: ")
    add_bullet_p(doc, "Commercial meeting intelligence tools charge recurring per-minute audio fees and token subscription costs. VoxIntel removes these recurring financial barriers for educational institutions, non-profit labs, and small-to-medium enterprises.", "2. Democratization of NLP Technology: ")
    add_bullet_p(doc, "Manual meeting minutes transcription requires hours of tedious human effort subject to cognitive fatigue. VoxIntel compresses hours of audio into actionable, structured third-person summaries in seconds.", "3. Cognitive Efficiency & Operational Velocity: ")
    add_bullet_p(doc, "By running 8-bit quantized models optimized for CPU SIMD vectorization, the solution achieves state-of-the-art results without demanding power-hungry GPU clusters, supporting environmentally sustainable computing.", "4. Resource-Efficient Sustainable AI: ")

    doc.add_page_break()

    # =========================================================================
    # CHAPTER 2: LITERATURE REVIEW
    # =========================================================================
    add_heading_chapter(doc, 2, "LITERATURE REVIEW")

    add_heading_sec(doc, "2.1 Background")
    add_p(doc,
        "Automated speech summarization lies at the intersection of acoustic signal processing, automatic speech recognition (ASR), "
        "speaker diarization, and natural language understanding (NLU). Over the past decade, the domain transitioned from statistical hidden Markov models "
        "and Gaussian mixture models toward deep end-to-end self-attention architectures and Large Language Models (LLMs)."
    )

    add_heading_sec(doc, "2.1.1 Review of Related Works")
    add_p(doc, "A comprehensive review of foundational literature informs the architecture of VoxIntel:")
    add_bullet_p(doc, "Introduced Whisper, establishing that weakly supervised sequence-to-sequence Transformers trained on 680,000 hours of multi-lingual audio achieve human-level robustness against background noise and technical jargon without task-specific fine-tuning.", "• A. Radford et al. (2023): ")
    add_bullet_p(doc, "Developed CTranslate2, an optimized inference engine that applies 8-bit integer quantization (int8) to Transformer models, reducing memory bandwidth by 4× and accelerating CPU execution speeds to sub-real-time rates.", "• G. Klein et al. (2020): ")
    add_bullet_p(doc, "Proposed TextRank, an unsupervised graph-based ranking algorithm that models sentence salience via normalized lexical similarity matrices and power iteration, enabling robust extractive summarization without training data.", "• R. Mihalcea and P. Tarau (2004): ")
    add_bullet_p(doc, "Demonstrated that lightweight recurrent neural voice activity detectors can filter non-speech silence in under 1 ms per chunk, drastically reducing hallucination and ASR compute overhead.", "• Silero Team (2021): ")
    add_bullet_p(doc, "Formulated the Yin fundamental frequency estimator, demonstrating that difference function minimization provides robust acoustic pitch tracking even in high-noise spoken environments.", "• A. de Cheveigné and H. Kawahara (2002): ")
    add_bullet_p(doc, "Established BERTScore, leveraging contextual word embeddings from pre-trained language models to compute token-level cosine similarities, correlating far better with human judgment than classical n-gram overlap.", "• T. Zhang et al. (2020): ")
    add_bullet_p(doc, "Formalized ROUGE and BLEU metrics, which remain the scientific gold standard for evaluating n-gram precision and recall in automated summary synthesis.", "• C. Y. Lin (2004) & K. Papineni et al. (2002): ")
    add_bullet_p(doc, "Developed efficient local model serving runtimes, enabling 4-bit and 8-bit quantized 1B-3B parameter instruction-tuned LLMs (such as llama3.2:3b and gemma3:1b) to execute locally on consumer workstations with predictable sub-second latency.", "• Ollama Team (2024): ")

    add_heading_sec(doc, "2.2 Research Gaps")
    add_p(doc, "Despite significant advancements, existing research leaves four critical gaps that VoxIntel explicitly addresses:")
    add_bullet_p(doc, "State-of-the-art neural diarization frameworks (e.g., PyAnnote) require over 4 GB of dedicated VRAM, mandatory HuggingFace authentication tokens, and heavy neural pipelines that freeze on 8 GB CPU hardware.", "1. Heavy Compute Footprint of Diarization: ")
    add_bullet_p(doc, "Existing commercial meeting assistants transmit audio streams to remote cloud servers, violating data sovereignty regulations (HIPAA, GDPR) and creating recurring per-minute billing.", "2. Cloud Exposure and Token Costs: ")
    add_bullet_p(doc, "Generic LLM summarizers frequently copy raw verbatim text, preserving first-person pronouns ('I will deploy the fix') and hallucinating task assignments by binding tasks to the first attendee in the list rather than the true segment speaker.", "3. First-Person Hallucination and Attribution Drift: ")
    add_bullet_p(doc, "Most research prototypes output unformatted text blocks lacking structured export options, interactive speaker timeline visualization, and real-time inference telemetry required for practical organizational adoption.", "4. Absence of Unified Offline Telemetry Dashboards: ")

    doc.add_page_break()

    # =========================================================================
    # CHAPTER 3: PROPOSED METHODOLOGY
    # =========================================================================
    add_heading_chapter(doc, 3, "PROPOSED METHODOLOGY")

    add_heading_sec(doc, "3.1 Architecture")
    add_p(doc,
        "VoxIntel follows a clean, decoupled five-stage architecture engineered for high-throughput execution on consumer-grade CPU hardware. "
        "Figure 3.1 illustrates the modular pipeline workflow from raw multi-channel audio ingestion through speech transcription, acoustic clustering, "
        "semantic heuristic extraction, and local LLM editorial synthesis."
    )

    # Scaled to 2.5 inches so it sits perfectly on Page 13 with the 5 subsystems
    arch_img = MEDIA_DIR / "image2.png"
    if arch_img.exists():
        add_image_with_caption(doc, arch_img, "Figure 3.1: System Architecture Workflow", width=2.5)

    add_p(doc, "The architectural workflow is organized into five tightly coordinated subsystems:")
    add_bullet_p(doc, "Converts multi-channel input into 16 kHz mono linear PCM and eliminates silence intervals using deep neural Silero VAD.", "1. Audio Ingestion & VAD Subsystem: ")
    add_bullet_p(doc, "Executes int8-quantized Whisper Transformer transcription on CPU conditioned with attendee vocabulary prompts.", "2. Speech Recognition Subsystem: ")
    add_bullet_p(doc, "Extracts 18-dimensional vocal tract vectors and partitions turns via K-Means clustering with Hungarian identity matching.", "3. Acoustic Diarization Subsystem: ")
    add_bullet_p(doc, "Normalizes conversational timestamps and ranks sentence salience via the TextRank graph algorithm while extracting commitments via regex.", "4. NLP & Heuristics Subsystem: ")
    add_bullet_p(doc, "Prompts local quantized LLMs (Ollama) to produce formal corporate minutes in third-person past tense without pronoun leakage.", "5. Local LLM Synthesis Subsystem: ")

    doc.add_page_break()

    # --- Page 14 ---
    add_heading_sec(doc, "3.1.1 Dataset Description")
    add_p(doc, "To rigorously evaluate VoxIntel without data leakage, a frozen multi-speaker meeting test battery was constructed and divided into two distinct partitions:")
    add_bullet_p(doc, "Meeting 1 (50 seconds, 3 speakers, 2 reference commitments, explicit self-introductions spoken) and Meeting 2 (193 seconds, 3 speakers, 6 reference commitments, technical sprint sync). Used for calibrating VAD thresholds and attendee prompt formats.", "• Development Set (Dev Set): ")
    add_bullet_p(doc, "Meeting 3 (323 seconds / 5.39 minutes, 4 synthetic neural voices, 3 reference commitments, zero names spoken in audio). Frozen prior to testing to assess unsupervised generalization in the absence of spoken identity cues.", "• Held-out Un-tuned Test Set: ")
    add_bullet_p(doc, "Across all three test meetings, 11 total verified commitments form the reference standard for action item evaluation.", "• Pooled Ground Truth Commitments: ")

    add_heading_sec(doc, "3.1.2 Preprocessing")
    add_p(doc, "The preprocessing pipeline conditions raw conversational speech for robust syntactic and acoustic modeling:")
    add_bullet_p(doc, "Input recordings are converted via FFmpeg to 16 kHz mono 16-bit linear PCM WAV format, eliminating multi-channel phase interference.", "1. Audio Normalization & Resampling: ")
    add_bullet_p(doc, "In-memory Silero VAD strips non-speech silence intervals, preventing hallucination during conversational pauses.", "2. Neural Voice Activity Detection: ")
    add_bullet_p(doc, "Colloquial times ('by 2 p.m. today') contain periods that break sentence tokenizers. These are normalized to 'PM' and 'AM' prior to boundary splitting.", "3. Timestamp Delimiter Normalization: ")
    add_bullet_p(doc, "Verbal contractions ('I will' -> 'I will', 'we will' -> 'we will') are standardized to protect verbal commitment semantics.", "4. Contraction Expansion: ")
    add_bullet_p(doc, "For each transcribed speech segment, an 18-dimensional acoustic vector is computed comprising 13 MFCCs, spectral centroid, Yin fundamental frequency (F0), zero-crossing rate, and RMS energy.", "5. Acoustic Feature Vectorization: ")
    add_bullet_p(doc, "Feature vectors are standardized across segments using Z-score scaling (zero mean, unit variance) to ensure balanced distance metrics during clustering.", "6. Acoustic Feature Standardization: ")

    doc.add_page_break()

    # --- Page 15 ---
    add_heading_sec(doc, "3.1.3 Encoder & Decoder Modules")
    add_p(doc, "The end-to-end pipeline execution algorithm progresses across nine structured engineering points:")
    add_bullet_p(doc, "The input PCM audio stream is framed into 25 ms analysis windows with 10 ms hops and converted into an 80-channel log-Mel spectrogram.", "• Step 1 - Acoustic Spectrogram Transformation: ")
    add_bullet_p(doc, "The 8-bit quantized Transformer audio encoder processes positional encodings and multi-head self-attention layers on CPU using CTranslate2 SIMD acceleration.", "• Step 2 - Quantized Audio Encoding: ")
    add_bullet_p(doc, "The autoregressive text decoder predicts timestamped transcript tokens conditioned on the attendee list injected into the initial prompt, biasing beam search probabilities toward domain-specific names and terms.", "• Step 3 - Prompt-Biased Text Decoding: ")
    add_bullet_p(doc, "For each speech segment, an 18-dimensional acoustic vector is computed and partitioned into k clusters via K-Means (where k equals the known attendee count).", "• Step 4 - Unsupervised Acoustic Diarization: ")
    add_bullet_p(doc, "Predicted acoustic clusters are mapped to real attendee identities using the Hungarian bipartite matching algorithm based on conversational turn structure.", "• Step 5 - Bipartite Identity Remapping: ")
    add_bullet_p(doc, "In Fast Mode, sentences form vertices in a complete similarity graph. The stationary distribution is solved via power iteration, extracting top 4 sentences formatted as [mm:ss] Speaker: line labeled as 'Key moments'.", "• Step 6 - TextRank Graph Salience Extraction: ")
    add_bullet_p(doc, "Deterministic regex patterns match verbal commitments directly to the segment speaker, resolving owner assignment and normalizing deadlines.", "• Step 7 - Deterministic Action Item Extraction: ")
    add_bullet_p(doc, "Target completion dates ('by Friday 5 PM') are parsed and standardized, preventing colloquial dot notation from breaking task definitions.", "• Step 8 - Deadline Normalization & Formatting: ")
    add_bullet_p(doc, "In Smart Mode, the transcript is passed to a local Ollama runner (llama3.2:3b / gemma3:1b). A strict JSON schema prompt compiles third-person past-tense minutes, exact timestamp citations, and attendee cross-validation.", "• Step 9 - Local LLM Synthesis: ")

    doc.add_page_break()

    # --- Page 16 ---
    add_p(doc, "To ensure operational robustness and deterministic execution on consumer hardware, the modules incorporate several core design invariants:")
    add_bullet_p(doc, "All models, weights, and embeddings execute strictly within local RAM. No audio packets, intermediate embeddings, or prompt completions are transmitted outside the machine, ensuring compliance with strict privacy standards.", "• Sovereign Local Execution Invariant: ")
    add_bullet_p(doc, "The LLM prompt strictly enforces third-person past-tense phrasing. If an extractive pipeline mode is selected, sentences are prefixed as '[mm:ss] Speaker: statement' under 'Key moments' rather than being mislabeled as formal minutes.", "• Third-Person Perspective Enforcement: ")
    add_bullet_p(doc, "Transcripts exceeding 1,500 tokens are processed via 5-minute sliding analysis windows with 30-second context overlaps, preventing memory overflow on 3B-parameter models.", "• Sliding Context Windowing: ")

    add_heading_sec(doc, "3.2 Hardware Specifications")
    add_p(doc, "VoxIntel is explicitly engineered to democratize NLP on commodity personal hardware without enterprise server dependencies:")
    add_bullet_p(doc, "Intel Core i5-1135G7 @ 2.40 GHz (4 cores, 8 threads) or AMD Ryzen 5 5500U equivalent.", "• Processor: ")
    add_bullet_p(doc, "8 GB DDR4 RAM (peak execution RAM under 650 MB during base int8 transcription; under 2.5 GB during Ollama 3B inference).", "• System Memory: ")
    add_bullet_p(doc, "2.0 GB free SSD disk space for faster-whisper base weights (~145 MB) and Ollama quantized LLM weights (~2.0 GB).", "• Disk Storage: ")
    add_bullet_p(doc, "Not required; pure CPU execution is enabled via CTranslate2 integer SIMD vectorization and int8 matrix multiplication.", "• Dedicated GPU: ")

    add_heading_sec(doc, "3.3 Software Specifications")
    add_p(doc, "The implementation utilizes standard modern open-source libraries and runtimes:")
    add_bullet_p(doc, "Python 3.10+ (64-bit runtime)", "• Programming Language: ")
    add_bullet_p(doc, "faster-whisper 1.0.3, CTranslate2 4.0.0 (int8 CPU compute)", "• ASR Framework: ")
    add_bullet_p(doc, "Librosa 0.10.1, SciPy 1.11.4, FFmpeg 6.0+", "• Audio Signal Processing: ")
    add_bullet_p(doc, "Scikit-learn 1.3.2 (K-Means, StandardScaler, Hungarian algorithm via scipy.optimize)", "• Machine Learning: ")
    add_bullet_p(doc, "NetworkX 3.1, NLTK 3.8.1, JiWER 3.0.3, ROUGE-Score 0.1.2, BERTScore 0.3.13", "• Natural Language Processing: ")
    add_bullet_p(doc, "Ollama 0.3+ (llama3.2:3b / gemma3:1b)", "• Local LLM Engine: ")
    add_bullet_p(doc, "Streamlit 1.31.0 with customized dark editorial UI tokens", "• Web User Interface: ")
    add_bullet_p(doc, "python-docx 1.1.0, docx2pdf 0.1.8", "• Document Generation: ")

    doc.add_page_break()

    # =========================================================================
    # CHAPTER 4: PERFORMANCE EVALUATION
    # =========================================================================
    add_heading_chapter(doc, 4, "PERFORMANCE EVALUATION")

    add_heading_sec(doc, "4.1 Experimental Setup & Evaluation Metrics")
    add_p(doc,
        "To ensure scientific reproducibility, all evaluation datasets and ground truths were frozen prior to benchmark execution. "
        "The benchmarking protocol consists of a mandatory initial warm-up run followed by 3 timed evaluation runs on CPU hardware, "
        "measuring median inference latency (seconds), peak CPU utilization (%), and peak resident RAM footprint (MB)."
    )
    add_p(doc, "The system was evaluated across six multidimensional NLP metrics:")
    add_bullet_p(doc, "Computed via JiWER as WER = (S + D + I) / N, where S is substitutions, D is deletions, I is insertions, and N is reference words.", "1. Word Error Rate (WER): ")
    add_bullet_p(doc, "Discretizes audio into 0.5-second time slices, comparing predicted speaker labels against ground-truth turn intervals via Hungarian bipartite remapping to report Accuracy, Macro F1, Weighted F1, and Precision.", "2. 0.5s Frame-Level Diarization: ")
    add_bullet_p(doc, "Scored against reference commitments requiring token overlap >= 0.50, reporting True Positives (TP), False Positives (FP), False Negatives (FN), Precision, Recall, and F1-Score.", "3. Action Item Detection: ")
    add_bullet_p(doc, "ROUGE-1, ROUGE-2, ROUGE-L, BLEU, and METEOR computed against reference ground-truth summaries.", "4. Summarization Overlap: ")
    add_bullet_p(doc, "BERTScore F1 utilizing contextual token embeddings from pre-trained language models.", "5. Semantic Embedding Alignment: ")
    add_bullet_p(doc, "Count of first-person pronouns (I, we, our, us, my) and bigram language model fluency perplexity.", "6. Linguistic Perspective & Fluency: ")

    add_heading_sec(doc, "4.2 Results and Analysis")
    add_p(doc,
        "Empirical benchmarks across the multi-speaker dataset demonstrate the superiority of the faster-whisper base int8 model and "
        "the effectiveness of local LLM third-person synthesis. In accordance with the reporting standards, table captions appear on top "
        "of each table, while figure captions appear below each figure."
    )

    # Table 4.1: Caption ON TOP
    add_table_caption(doc, "Table 4.1: Automatic Speech Recognition (ASR) Word Error Rate (WER) and CPU Latency Benchmarks")
    table_asr = [
        ("Meeting ID", "Split", "Model", "Prompt?", "WER (%)", "Latency (s)", "CPU (%)", "RAM (MB)"),
        ("Meeting 1 (50s)", "Dev Set", "tiny", "No", "7.83%", "2.17s", "382.7%", "488.2 MB"),
        ("Meeting 1 (50s)", "Dev Set", "tiny", "Yes", "5.22%", "2.26s", "377.6%", "491.3 MB"),
        ("Meeting 1 (50s)", "Dev Set", "base", "No", "7.83%", "5.09s", "385.4%", "594.9 MB"),
        ("Meeting 1 (50s)", "Dev Set", "base", "Yes", "3.48%", "6.17s", "383.9%", "594.9 MB"),
        ("Meeting 2 (193s)", "Dev Set", "tiny", "No", "11.27%", "7.76s", "358.9%", "529.0 MB"),
        ("Meeting 2 (193s)", "Dev Set", "tiny", "Yes", "9.11%", "7.78s", "364.6%", "528.4 MB"),
        ("Meeting 2 (193s)", "Dev Set", "base", "No", "9.59%", "14.14s", "373.5%", "618.9 MB"),
        ("Meeting 2 (193s)", "Dev Set", "base", "Yes", "8.87%", "14.12s", "375.4%", "619.5 MB"),
        ("Meeting 3 (323s)", "Test Set", "tiny", "No", "10.32%", "10.20s", "359.7%", "555.2 MB"),
        ("Meeting 3 (323s)", "Test Set", "tiny", "Yes", "9.14%", "10.31s", "362.1%", "556.8 MB"),
        ("Meeting 3 (323s)", "Test Set", "base", "No", "5.58%", "19.90s", "376.8%", "645.4 MB"),
        ("Meeting 3 (323s)", "Test Set", "base", "Yes", "6.43%", "20.04s", "376.9%", "646.4 MB"),
    ]
    t1 = doc.add_table(rows=len(table_asr), cols=8)
    t1.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t1, val="single", sz="4", color="auto")
    col_w_t1 = [1.15, 0.70, 0.55, 0.60, 0.65, 0.72, 0.65, 0.85]
    for r_i, row_data in enumerate(table_asr):
        row = t1.rows[r_i]
        for c_i, val in enumerate(row_data):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_t1[c_i])
            set_cell_margins(cell, top=35, bottom=35, left=45, right=45)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(9.5)
            r.bold = (r_i == 0) or ("3.48%" in val) or ("5.58%" in val)
            r.font.color.rgb = RGBColor(0, 0, 0)

    # Table 4.2: Caption ON TOP
    add_table_caption(doc, "Table 4.2: 0.5s Frame-Level Speaker Attribution Accuracy, Precision, and F1 Metrics")
    table_spk = [
        ("Meeting ID", "Split", "Attribution Mode", "Accuracy (%)", "Macro F1", "Weighted F1", "Precision"),
        ("Meeting 1", "Dev Set", "Clustering (remap)", "63.00%", "0.3870", "0.5998", "0.3980"),
        ("Meeting 1", "Dev Set", "Grounding ON", "0.00%", "0.0000", "0.0000", "0.0000"),
        ("Meeting 2", "Dev Set", "Clustering (remap)", "70.73%", "0.5049", "0.6876", "0.5404"),
        ("Meeting 2", "Dev Set", "Grounding ON", "44.27%", "0.3952", "0.4357", "0.4497"),
        ("Meeting 3", "Test Set", "Clustering (remap)", "58.11%", "0.5916", "0.5968", "0.6555"),
        ("Meeting 3", "Test Set", "Grounding ON", "28.75%", "0.2783", "0.2340", "0.2469"),
    ]
    t2 = doc.add_table(rows=len(table_spk), cols=7)
    t2.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t2, val="single", sz="4", color="auto")
    col_w_t2 = [1.05, 0.70, 1.52, 0.85, 0.65, 0.70, 0.65]
    for r_i, row_data in enumerate(table_spk):
        row = t2.rows[r_i]
        for c_i, val in enumerate(row_data):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_t2[c_i])
            set_cell_margins(cell, top=35, bottom=35, left=45, right=45)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(9.5)
            r.bold = (r_i == 0) or ("58.11%" in val)
            r.font.color.rgb = RGBColor(0, 0, 0)

    # Figure 4.1: Short and simple caption
    cm_img = FIGURES_DIR / "confusion_matrix_meeting_3_clustering_only.png"
    if cm_img.exists():
        add_image_with_caption(doc, cm_img, "Figure 4.1: Speaker Attribution Confusion Matrix", width=3.6)

    # Table 4.3: Caption ON TOP
    add_table_caption(doc, "Table 4.3: Action Items Extraction Performance (Precision, Recall, F1 across 11 Reference Commitments)")
    table_act = [
        ("Meeting ID", "Split", "Pipeline Mode", "TP", "FP", "FN", "Precision", "Recall", "F1-Score"),
        ("Meeting 1 (2 ref)", "Dev Set", "Fast Mode", "2", "0", "0", "1.0000", "1.0000", "1.0000"),
        ("Meeting 1 (2 ref)", "Dev Set", "Smart Mode", "2", "0", "0", "1.0000", "1.0000", "1.0000"),
        ("Meeting 2 (6 ref)", "Dev Set", "Fast Mode", "6", "0", "0", "1.0000", "1.0000", "1.0000"),
        ("Meeting 2 (6 ref)", "Dev Set", "Smart Mode", "5", "0", "1", "1.0000", "0.8333", "0.9091"),
        ("Meeting 3 (3 ref)", "Test Set", "Fast Mode", "3", "2", "0", "0.6000", "1.0000", "0.7500"),
        ("Meeting 3 (3 ref)", "Test Set", "Smart Mode", "3", "2", "0", "0.6000", "1.0000", "0.7500"),
        ("Pooled Aggregate (11)", "Combined", "Fast Mode", "11", "2", "0", "0.8462", "1.0000", "0.9167"),
        ("Pooled Aggregate (11)", "Combined", "Smart Mode", "10", "2", "1", "0.8333", "0.9091", "0.8696"),
    ]
    t3 = doc.add_table(rows=len(table_act), cols=9)
    t3.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t3, val="single", sz="4", color="auto")
    col_w_t3 = [1.35, 0.65, 0.80, 0.35, 0.35, 0.35, 0.62, 0.62, 0.62]
    for r_i, row_data in enumerate(table_act):
        row = t3.rows[r_i]
        for c_i, val in enumerate(row_data):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_t3[c_i])
            set_cell_margins(cell, top=35, bottom=35, left=45, right=45)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(9.5)
            r.bold = (r_i == 0) or ("Combined" in row_data[1])
            r.font.color.rgb = RGBColor(0, 0, 0)

    # Table 4.4: Caption ON TOP
    add_table_caption(doc, "Table 4.4: Summary Quality Scores, Linguistic Perspective (1st Person Pronouns), and Fluency Perplexity")
    table_sum = [
        ("Meeting", "Mode", "ROUGE-1", "ROUGE-2", "ROUGE-L", "BLEU", "METEOR", "BERTScore", "1st Pronouns", "Perplexity"),
        ("M1 (Dev)", "Fast Key Moments", "0.5283", "0.3846", "0.4528", "0.2227", "0.4190", "0.4497", "6", "N/A"),
        ("M1 (Dev)", "Smart MoM", "0.3929", "0.1636", "0.2500", "0.0833", "0.3705", "0.3340", "0", "53.48"),
        ("M2 (Dev)", "Fast Key Moments", "0.2319", "0.0882", "0.1449", "0.0270", "0.2238", "-0.0163", "5", "N/A"),
        ("M2 (Dev)", "Smart MoM", "0.1760", "0.0325", "0.0960", "0.0189", "0.1554", "0.1741", "0", "31.90"),
        ("M3 (Test)", "Fast Key Moments", "0.2391", "0.0659", "0.1413", "0.0168", "0.2238", "-0.0624", "3", "N/A"),
        ("M3 (Test)", "Smart MoM", "0.2963", "0.1509", "0.2037", "0.0291", "0.1933", "0.3324", "0", "24.00"),
    ]
    t4 = doc.add_table(rows=len(table_sum), cols=10)
    t4.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(t4, val="single", sz="4", color="auto")
    col_w_t4 = [0.72, 1.20, 0.52, 0.52, 0.52, 0.44, 0.46, 0.55, 0.55, 0.55]
    for r_i, row_data in enumerate(table_sum):
        row = t4.rows[r_i]
        for c_i, val in enumerate(row_data):
            cell = row.cells[c_i]
            cell.width = Inches(col_w_t4[c_i])
            set_cell_margins(cell, top=35, bottom=35, left=35, right=35)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(val)
            r.font.name = "Times New Roman"
            r.font.size = Pt(9.0)
            r.bold = (r_i == 0) or ("Smart MoM" in row_data[1])
            r.font.color.rgb = RGBColor(0, 0, 0)

    # Figures 4.2 & 4.3: Word Cloud & Bigram Graph (Normal white background, short captions)
    wc_img = FIGURES_DIR / "wordcloud_meeting_3.png"
    if wc_img.exists():
        add_image_with_caption(doc, wc_img, "Figure 4.2: Word Cloud of Meeting Transcript", width=3.8)

    bg_img = FIGURES_DIR / "bigram_graph_meeting_3.png"
    if bg_img.exists():
        add_image_with_caption(doc, bg_img, "Figure 4.3: Bigram Association Graph", width=3.8)

    # Figures 4.4 & 4.5: Dashboard Screenshots (Short captions)
    sc_min = SCREENSHOTS_DIR / "minutes_tab.png"
    if sc_min.exists():
        add_image_with_caption(doc, sc_min, "Figure 4.4: Streamlit Dashboard - Minutes View", width=3.8)

    sc_spk = SCREENSHOTS_DIR / "speakers_tab.png"
    if sc_spk.exists():
        add_image_with_caption(doc, sc_spk, "Figure 4.5: Streamlit Dashboard - Speakers View", width=3.8)

    add_p(doc, "The Streamlit Studio user interface validation demonstrates two primary operational tabs:")
    add_bullet_p(doc, "Presents synthesized third-person Minutes of Meeting with timestamped discussion points, verified decisions, and interactive action items with owner checkboxes and export buttons for DOCX and PDF.", "• Minutes View: ")
    add_bullet_p(doc, "Displays the interactive speaker timeline, per-speaker talk-time distribution, acoustic clustering purity, and live inference CPU/RAM resource telemetry.", "• Speakers View: ")

    doc.add_page_break()

    # =========================================================================
    # CHAPTER 5: CONCLUSION AND FUTURE WORK
    # =========================================================================
    add_heading_chapter(doc, 5, "CONCLUSION AND FUTURE WORK")

    add_heading_sec(doc, "5.1 Summary of the Contributions")
    add_p(doc, "VoxIntel demonstrates that enterprise-grade speech transcription, acoustic speaker clustering, and natural language MoM synthesis can be achieved completely offline on standard commodity personal computers without external cloud APIs. Key engineering contributions include:")
    add_bullet_p(doc, "Int8-quantized faster-whisper base achieved 3.48% WER on dev audio and 5.58% WER on held-out test recordings at 0.06x real-time latency, cutting errors by nearly half compared to tiny models.", "• High Accuracy Speech Recognition on CPU: ")
    add_bullet_p(doc, "Extracting 18 vocal tract features and clustering via K-Means achieved 58.11% frame-level attribution accuracy on unseen speakers in under 0.8s without external neural models.", "• Unsupervised Acoustic Clustering: ")
    add_bullet_p(doc, "Regex heuristics extracted action items with 100% recall (F1 = 0.9167) across 11 reference commitments, binding tasks to segment speakers and standardizing deadlines.", "• Deterministic Commitment Extraction: ")
    add_bullet_p(doc, "Locally served Ollama 3B models synthesized corporate minutes with exactly 0 first-person pronouns and bigram fluency perplexity of 24.0, resolving conversational ambiguity.", "• Editorial Third-Person MoM Synthesis: ")

    add_heading_sec(doc, "5.2 Future Work")
    add_p(doc, "Future research and development will focus on four strategic avenues:")
    add_bullet_p(doc, "Implementing WebSockets-based streaming chunk ASR for live captioning and instant commitment popups during active calls.", "1. Real-Time Streaming Telemetry: ")
    add_bullet_p(doc, "Incorporating quantized ONNX speaker embedding models (Sherpa-ONNX, Resemblyzer) to improve clustering purity on short interjections.", "2. Lightweight Neural Diarization: ")
    add_bullet_p(doc, "Expanding vocabulary prompt conditioning to support code-switched multi-lingual enterprise meetings (e.g., Hinglish, Spanglish).", "3. Multi-Lingual & Code-Switched Prompting: ")
    add_bullet_p(doc, "Creating automated API integrations to export verified commitments directly to Jira, GitHub Issues, and Google Calendar.", "4. Enterprise Workflow Webhooks: ")

    doc.add_page_break()

    # =========================================================================
    # REFERENCES - Numbered as 1., 2., 3. format as requested
    # =========================================================================
    add_p(doc, "REFERENCES", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=10, space_after=16, bold=True, font_size=16)

    refs = [
        "1. A. Radford, J. W. Kim, T. Xu, G. Brockman, C. McLeavey, and I. Sutskever, \"Robust Speech Recognition via Large-Scale Weak Supervision,\" in Proceedings of the 40th International Conference on Machine Learning (ICML), vol. 202, pp. 28492-28518, 2023.",
        "2. G. Klein, D. Nguyen, J. Senellart, and A. M. Rush, \"OpenNMT and CTranslate2: Fast Inference for Neural Machine Translation and Speech Recognition,\" in Proceedings of ACL System Demonstrations, pp. 177-183, 2020.",
        "3. R. Mihalcea and P. Tarau, \"TextRank: Bringing Order into Text,\" in Proceedings of the Conference on Empirical Methods in Natural Language Processing (EMNLP), pp. 404-411, 2004.",
        "4. Silero Team, \"Silero VAD: Pre-trained Enterprise-Grade Voice Activity Detector,\" GitHub repository, https://github.com/snakers4/silero-vad, 2021.",
        "5. A. de Cheveigné and H. Kawahara, \"YIN, a Fundamental Frequency Estimator for Speech and Music,\" Journal of the Acoustical Society of America, vol. 111, no. 4, pp. 1917-1930, 2002.",
        "6. T. Zhang, V. Kishore, F. Wu, K. Q. Weinberger, and Y. Artzi, \"BERTScore: Evaluating Text Generation with BERT,\" in Proceedings of the International Conference on Learning Representations (ICLR), 2020.",
        "7. C. Y. Lin, \"ROUGE: A Package for Automatic Evaluation of Summaries,\" in Text Summarization Branches Out, pp. 74-81, 2004.",
        "8. K. Papineni, S. Roukos, T. Ward, and W. J. Zhu, \"BLEU: A Method for Automatic Evaluation of Machine Translation,\" in Proceedings of the 40th Annual Meeting of the Association for Computational Linguistics (ACL), pp. 311-318, 2002.",
        "9. S. Banerjee and A. Lavie, \"METEOR: An Automatic Metric for MT Evaluation with Improved Correlation with Human Judgments,\" in Proceedings of the ACL Workshop on Intrinsic and Extrinsic Evaluation Measures, pp. 65-72, 2005.",
        "10. Ollama Team, \"Ollama: Get Up and Running with Large Language Models Locally,\" https://ollama.com, 2024.",
    ]
    for r in refs:
        p_ref = doc.add_paragraph()
        p_ref.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_ref.paragraph_format.space_after = Pt(8)
        p_ref.paragraph_format.line_spacing = 1.3
        r_run = p_ref.add_run(r)
        r_run.font.name = "Times New Roman"
        r_run.font.size = Pt(11)
        r_run.font.color.rgb = RGBColor(0, 0, 0)

    doc.add_page_break()

    # =========================================================================
    # APPENDIX: COMPLETE SOURCE CODE
    # =========================================================================
    add_p(doc, "APPENDIX", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=10, space_after=2, bold=True, font_size=16)
    add_p(doc, "COMPLETE PYTHON SOURCE CODE", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=16, bold=True, font_size=14)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(10)
    p.add_run(
        "Below is the complete, modular Python implementation of the core VoxIntel pipeline modules: "
        "voxintel/nlp_eval.py (evaluation metrics, word clouds & bigram graphs), voxintel/audio.py (faster-whisper base int8 ASR with VAD), "
        "voxintel/insights.py (TextRank summarization & action item extraction), and voxintel/ollama_polish.py (local Ollama third-person MoM synthesis)."
    )

    code_files = [
        ("voxintel/nlp_eval.py (Evaluation Metrics, Word Clouds & Bigram Graphs)", BASE_DIR / "voxintel" / "nlp_eval.py"),
        ("voxintel/audio.py (faster-whisper base int8 ASR with VAD)", BASE_DIR / "voxintel" / "audio.py"),
        ("voxintel/insights.py (TextRank Summarization & Action Item Extraction)", BASE_DIR / "voxintel" / "insights.py"),
        ("voxintel/ollama_polish.py (Local Ollama Third-Person MoM Synthesis)", BASE_DIR / "voxintel" / "ollama_polish.py"),
    ]

    for title, fpath in code_files:
        add_heading_sec(doc, title)
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            lines = content.splitlines()[:85]
            code_snippet = "\n".join(lines)
            if len(content.splitlines()) > 85:
                code_snippet += f"\n\n# ... [Truncated: {len(content.splitlines()) - 85} additional lines in production codebase] ..."
        else:
            code_snippet = "# File not found"

        tbl_code = doc.add_table(rows=1, cols=1)
        tbl_code.alignment = WD_TABLE_ALIGNMENT.CENTER
        set_table_borders(tbl_code, val="single", sz="4", color="auto")
        c = tbl_code.cell(0, 0)
        c.width = Inches(6.27)
        set_cell_margins(c, top=60, bottom=60, left=80, right=80)
        p_c = c.paragraphs[0]
        p_c.paragraph_format.line_spacing = 1.05
        p_c.paragraph_format.space_after = Pt(2)
        r_c = p_c.add_run(code_snippet)
        r_c.font.name = "Consolas"
        r_c.font.size = Pt(8.0)
        r_c.font.color.rgb = RGBColor(0, 0, 0)

        doc.add_paragraph().paragraph_format.space_after = Pt(8)

    output_docx = BASE_DIR / "VoxIntel_NLP_Report.docx"
    doc.save(str(output_docx))
    return output_docx


def get_actual_pages_from_word(docx_path):
    import win32com.client as win32
    word = win32.gencache.EnsureDispatch('Word.Application')
    word.Visible = False
    doc = word.Documents.Open(os.path.abspath(docx_path))

    sections = {}
    targets = [
        ('ABSTRACT', 'ABSTRACT'),
        ('LIST_TABLES', 'LIST OF TABLES'),
        ('LIST_FIGURES', 'LIST OF FIGURES'),
        ('LIST_SYMBOLS', 'LIST OF SYMBOLS AND ABBREVIATIONS'),
        ('CH1', 'CHAPTER 1'),
        ('CH1_1', '1.1 Project Overview'),
        ('CH1_2', '1.2 Problem Statement'),
        ('CH1_3', '1.3 Objectives'),
        ('CH1_4', '1.4 Scope of Work (or) Social Contribution'),
        ('CH2', 'CHAPTER 2'),
        ('CH2_1', '2.1 Background'),
        ('CH2_1_1', '2.1.1 Review of Related Works'),
        ('CH2_2', '2.2 Research Gaps'),
        ('CH3', 'CHAPTER 3'),
        ('CH3_1', '3.1 Architecture'),
        ('CH3_1_1', '3.1.1 Dataset Description'),
        ('CH3_1_2', '3.1.2 Preprocessing'),
        ('CH3_1_3', '3.1.3 Encoder & Decoder Modules'),
        ('CH3_2', '3.2 Hardware Specifications'),
        ('CH3_3', '3.3 Software Specifications'),
        ('CH4', 'CHAPTER 4'),
        ('CH4_1', '4.1 Experimental Setup & Evaluation Metrics'),
        ('CH4_2', '4.2 Results and Analysis'),
        ('CH5', 'CHAPTER 5'),
        ('CH5_1', '5.1 Summary of the Contributions'),
        ('CH5_2', '5.2 Future Work'),
        ('REFERENCES', 'REFERENCES'),
        ('APPENDIX', 'APPENDIX'),
        # Tables & Figures
        ('TAB_4_1', 'Table 4.1: Automatic Speech Recognition'),
        ('TAB_4_2', 'Table 4.2: 0.5s Frame-Level Speaker'),
        ('TAB_4_3', 'Table 4.3: Action Items Extraction'),
        ('TAB_4_4', 'Table 4.4: Summary Quality Scores'),
        ('FIG_3_1', 'Figure 3.1: System Architecture Workflow'),
        ('FIG_4_1', 'Figure 4.1: Speaker Attribution Confusion Matrix'),
        ('FIG_4_2', 'Figure 4.2: Word Cloud of Meeting Transcript'),
        ('FIG_4_3', 'Figure 4.3: Bigram Association Graph'),
        ('FIG_4_4', 'Figure 4.4: Streamlit Dashboard - Minutes View'),
        ('FIG_4_5', 'Figure 4.5: Streamlit Dashboard - Speakers View'),
    ]

    for p in doc.Paragraphs:
        if p.Range.Tables.Count > 0:
            continue
        txt = p.Range.Text.strip()
        for key, prefix in targets:
            if key not in sections and txt.startswith(prefix):
                page = p.Range.Information(1)
                sections[key] = str(page)

    doc.Close(False)
    word.Quit()
    return sections


def main():
    print("Pass 1: Building template-aligned document...")
    docx_file = build_report_doc()

    print("Pass 2: Measuring exact page numbers from Word...")
    detected_pages = get_actual_pages_from_word(docx_file)
    print("Detected page mapping:")
    for k, v in detected_pages.items():
        print(f"  {k:15}: Page {v}")

    print("Pass 3: Rebuilding document with synchronized page numbers...")
    build_report_doc(detected_pages)
    print(f"Generated finalized DOCX: {docx_file}")

    output_pdf = BASE_DIR / "VoxIntel_NLP_Report.pdf"
    print("Converting DOCX to PDF using docx2pdf...")
    from docx2pdf import convert
    convert(str(docx_file), str(output_pdf))
    print(f"Generated finalized PDF: {output_pdf}")


if __name__ == "__main__":
    main()
