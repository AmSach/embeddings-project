import os
import re
import sqlite3
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.pdfgen import canvas

EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)

class NumberedCanvas(canvas.Canvas):
    """Custom canvas to draw running footers and 'Page X of Y' page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            super().showPage()
        super().save()

    def draw_page_elements(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b")) # Slate gray
        
        # Draw top running header (skip page 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "MODEL UN RESEARCH ASSISTANT — MASTERCLASS DOSSIER")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)
            
        # Draw bottom footer
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 50, 558, 50)
        
        self.drawString(54, 38, f"Report Generated: {datetime.now().strftime('%B %d, %Y')}")
        self.drawRightString(558, 38, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def clean_markdown_to_reportlab_html(md_text: str) -> str:
    """Converts basic Markdown formatting into XML-like tags accepted by ReportLab Paragraph."""
    if not md_text:
        return ""
    
    # 1. Temporarily extract links to avoid escaping issues
    links = []
    def save_link(match):
        text = match.group(1)
        url = match.group(2)
        # Escape URL for XML attributes
        url_escaped = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        idx = len(links)
        links.append((text, url_escaped))
        return f"__LINK_PLACEHOLDER_{idx}__"
        
    html = re.sub(r"\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)", save_link, md_text)
    
    # 2. Handle HTML-safe chars
    html = html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # 3. Bold: **text** -> <b>text</b>
    html = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"__(.*?)__", r"<b>\1</b>", html)
    
    # 4. Italics: *text* -> <i>text</i>
    html = re.sub(r"\*(.*?)\*", r"<i>\1</i>", html)
    
    # 5. Restore links with proper styling and inner tag support
    for idx, (text, url_escaped) in enumerate(links):
        text_escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text_escaped = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text_escaped)
        text_escaped = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text_escaped)
        
        link_tag = f'<font color="#4f46e5"><u><a href="{url_escaped}">{text_escaped}</a></u></font>'
        html = html.replace(f"__LINK_PLACEHOLDER_{idx}__", link_tag)
        
    return html.strip()



def export_to_latex(title: str, country: str, content_markdown: str) -> str:
    """Converts Markdown study guide content into a high-quality compiled LaTeX structure."""
    
    def clean_markdown_to_latex(md_text: str) -> str:
        if not md_text:
            return ""
        
        # 1. Extract links to prevent their URLs from being escaped
        links = []
        def save_link(match):
            link_text = match.group(1)
            url = match.group(2)
            idx = len(links)
            links.append((link_text, url))
            return f"__LINK_PLACEHOLDER_{idx}__"
            
        text = re.sub(r"\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)", save_link, md_text)
        
        # 2. Escape LaTeX special characters in the text
        escapes = {
            '&': r'\&',
            '%': r'\%',
            '$': r'\$',
            '#': r'\#',
            '_': r'\_',
            '{': r'\{',
            '}': r'\}',
            '~': r'\textasciitilde{}',
            '^': r'\textasciicircum{}',
        }
        escaped_text = ""
        for char in text:
            escaped_text += escapes.get(char, char)
            
        # 3. Handle bold/italic formatting
        escaped_text = re.sub(r"\*\*(.*?)\*\*", r"\\textbf{\1}", escaped_text)
        escaped_text = re.sub(r"\*(.*?)\*", r"\\textit{\1}", escaped_text)
        
        # 4. Restore links
        for idx, (link_text, url) in enumerate(links):
            # Escape link text
            escaped_link_text = ""
            for char in link_text:
                escaped_link_text += escapes.get(char, char)
            escaped_link_text = re.sub(r"\*\*(.*?)\*\*", r"\\textbf{\1}", escaped_link_text)
            escaped_link_text = re.sub(r"\*(.*?)\*", r"\\textit{\1}", escaped_link_text)
            
            # Escape url special characters for href: % and #
            url_escaped = url.replace("%", r"\%").replace("#", r"\#")
            
            href_tag = f"\\href{{{url_escaped}}}{{{escaped_link_text}}}"
            escaped_text = escaped_text.replace(f"__LINK_PLACEHOLDER_{idx}__", href_tag)
            
        return escaped_text

    # Standard Markdown translation to LaTeX
    lines = content_markdown.split('\n')
    latex_content = []
    
    in_bullet_list = False
    in_num_list = False
    in_quote = False
    
    def end_lists_and_quotes():
        nonlocal in_bullet_list, in_num_list, in_quote
        out = []
        if in_bullet_list:
            out.append(r"\end{itemize}")
            in_bullet_list = False
        if in_num_list:
            out.append(r"\end{enumerate}")
            in_num_list = False
        if in_quote:
            out.append(r"\end{quote}")
            in_quote = False
        return out

    for line in lines:
        stripped = line.strip()
        
        # 1. Headers
        if stripped.startswith("#### "):
            latex_content.extend(end_lists_and_quotes())
            title_text = clean_markdown_to_latex(stripped[5:])
            latex_content.append(f"\\paragraph*{{{title_text}}}")
        elif stripped.startswith("### "):
            latex_content.extend(end_lists_and_quotes())
            title_text = clean_markdown_to_latex(stripped[4:])
            latex_content.append(f"\\subsubsection*{{{title_text}}}")
        elif stripped.startswith("## "):
            latex_content.extend(end_lists_and_quotes())
            title_text = clean_markdown_to_latex(stripped[3:])
            latex_content.append(f"\\subsection*{{{title_text}}}")
        elif stripped.startswith("# "):
            latex_content.extend(end_lists_and_quotes())
            title_text = clean_markdown_to_latex(stripped[2:])
            latex_content.append(f"\\section*{{{title_text}}}")
            
        # 2. Blockquotes
        elif stripped.startswith(">"):
            if in_bullet_list:
                latex_content.append(r"\end{itemize}")
                in_bullet_list = False
            if in_num_list:
                latex_content.append(r"\end{enumerate}")
                in_num_list = False
            if not in_quote:
                latex_content.append(r"\begin{quote}\itshape")
                in_quote = True
            content_text = clean_markdown_to_latex(stripped[1:].strip())
            latex_content.append(content_text)
            
        # 3. Horizontal Rules
        elif stripped in ["---", "***"] or re.match(r"^[-*_]{3,}$", stripped):
            latex_content.extend(end_lists_and_quotes())
            latex_content.append(r"\noindent\rule{\textwidth}{0.5pt}")
            
        # 4. Bullet Lists
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if in_num_list:
                latex_content.append(r"\end{enumerate}")
                in_num_list = False
            if in_quote:
                latex_content.append(r"\end{quote}")
                in_quote = False
            if not in_bullet_list:
                latex_content.append(r"\begin{itemize}[leftmargin=*,noitemsep]")
                in_bullet_list = True
            item_text = clean_markdown_to_latex(stripped[2:])
            latex_content.append(f"  \\item {item_text}")
            
        # 5. Numbered Lists
        elif re.match(r"^(\d+[a-zA-Z]?)\.\s+(.*)$", stripped):
            match = re.match(r"^(\d+[a-zA-Z]?)\.\s+(.*)$", stripped)
            num = match.group(1)
            item_text = clean_markdown_to_latex(match.group(2))
            if in_bullet_list:
                latex_content.append(r"\end{itemize}")
                in_bullet_list = False
            if in_quote:
                latex_content.append(r"\end{quote}")
                in_quote = False
            if not in_num_list:
                latex_content.append(r"\begin{enumerate}[leftmargin=*,noitemsep]")
                in_num_list = True
            latex_content.append(f"  \\item {item_text}")
            
        # 6. Empty Line
        elif not stripped:
            latex_content.extend(end_lists_and_quotes())
            latex_content.append("")
            
        # 7. Standard Paragraph
        else:
            latex_content.extend(end_lists_and_quotes())
            para_text = clean_markdown_to_latex(stripped)
            latex_content.append(para_text)
            
    # Clean up any open list/quote at the end
    latex_content.extend(end_lists_and_quotes())

    latex_body = "\n".join(latex_content)

    # Compile Full LaTeX Document template
    latex_document = f"""\\documentclass[11pt,a4paper]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{booktabs}}
\\usepackage{{titlesec}}
\\usepackage{{enumitem}}
\\usepackage{{xcolor}}
\\usepackage{{hyperref}}

\\definecolor{{navy}}{{HTML}}{{1e3a8a}}
\\definecolor{{indigo}}{{HTML}}{{4f46e5}}

\\hypersetup{{
    colorlinks=true,
    linkcolor=navy,
    filecolor=navy,      
    urlcolor=indigo,
    pdftitle={{{title}}},
    pdfauthor={{{country}}}
}}

\\titleformat{{\\section}}
{{\\color{{navy}}\\normalfont\\Large\\bfseries}}
{{}}{{0em}}{{\\hrulefill\\\\[0.5ex]}}[\\vspace{{1ex}}]

\\titleformat{{\\subsection}}
{{\\color{{navy}}\\normalfont\\large\\bfseries}}
{{}}{{0em}}{{}}[\\vspace{{0.5ex}}]

\\title{{{title}}}
\\author{{Represented Delegation: {country}}}
\\date{{Generated: \\today}}

\\begin{{document}}

\\maketitle

\\begin{{abstract}}
This research dossier contains a structured, semantically compiled, and trust-reranked strategic Masterclass Course. It includes primary sources retrieved directly from crawled geopolitics archives.
\\end{{abstract}}

\\vspace{{2em}}

{latex_body}

\\end{{document}}
"""
    # Write to static exports folder
    safe_title = re.sub(r"[^\w\-_]", "_", title.lower())[:30]
    filename = f"study_guide_{safe_title}_{int(datetime.now().timestamp())}.tex"
    filepath = os.path.join(EXPORTS_DIR, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(latex_document)
        
    return f"/exports/{filename}"



def export_to_pdf(title: str, country: str, content_markdown: str) -> str:
    """Generates a beautifully styled, publication-ready PDF document from Markdown."""
    
    safe_title = re.sub(r"[^\w\-_]", "_", title.lower())[:30]
    filename = f"study_guide_{safe_title}_{int(datetime.now().timestamp())}.pdf"
    filepath = os.path.join(EXPORTS_DIR, filename)

    # Document setup (Letter size, margins leaving space for custom header/footers)
    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72
    )

    styles = getSampleStyleSheet()
    
    # Custom Palette
    COLOR_PRIMARY = colors.HexColor("#1e1b4b")  # Dark Indigo
    COLOR_SECONDARY = colors.HexColor("#4f46e5") # Indigo Accent
    COLOR_TEXT = colors.HexColor("#1e293b")      # Slate 800
    
    # Define custom styles
    style_normal = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=15,
        textColor=COLOR_TEXT,
        alignment=TA_LEFT,
        spaceAfter=10
    )
    
    style_h1 = ParagraphStyle(
        'CustomH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=COLOR_PRIMARY,
        spaceBefore=15,
        spaceAfter=15,
        keepWithNext=True
    )
    
    style_h2 = ParagraphStyle(
        'CustomH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=COLOR_PRIMARY,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    style_h3 = ParagraphStyle(
        'CustomH3',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=COLOR_SECONDARY,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    )

    style_h4 = ParagraphStyle(
        'CustomH4',
        parent=styles['Heading4'],
        fontName='Helvetica-BoldOblique',
        fontSize=10,
        leading=13,
        textColor=COLOR_SECONDARY,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    
    style_bullet = ParagraphStyle(
        'CustomBullet',
        parent=style_normal,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=5
    )

    style_blockquote = ParagraphStyle(
        'CustomBlockquote',
        parent=style_normal,
        leftIndent=20,
        rightIndent=20,
        fontName='Helvetica-Oblique',
        textColor=colors.HexColor("#475569"),
        backColor=colors.HexColor("#f8fafc"),
        borderColor=colors.HexColor("#cbd5e1"),
        borderWidth=0.5,
        borderPadding=8,
        spaceAfter=12
    )

    story = []

    # 1. COVER PAGE / INTRO COVER
    story.append(Spacer(1, 20))
    
    # Header Banner Table style
    header_data = [
        [Paragraph(f"<b>MODEL UN BATTLE DOSSIER</b>", ParagraphStyle('HData1', fontName='Helvetica-Bold', fontSize=9, textColor=COLOR_SECONDARY, leading=10))],
        [Paragraph(f"<font size=22><b>{title}</b></font>", ParagraphStyle('HData2', fontName='Helvetica-Bold', textColor=colors.white, leading=26))],
        [Paragraph(f"Delegation: {country} | Generated: {datetime.now().strftime('%B %d, %Y')}", ParagraphStyle('HData3', fontSize=10, textColor=colors.HexColor("#cbd5e1"), leading=12))]
    ]
    banner_table = Table(header_data, colWidths=[504])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), COLOR_PRIMARY),
        ('PADDING', (0,0), (-1,-1), 16),
        ('BOTTOMPADDING', (0,0), (-1,0), 0),
        ('TOPPADDING', (0,2), (-1,2), 10),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 20))

    # Parse lines for Table of Contents (TOC) extraction
    lines = content_markdown.split('\n')
    
    toc_entries = []
    for line in lines:
        s_line = line.strip()
        if s_line.startswith("# ") and not s_line.startswith("# 🎓 Best Delegate"):
            toc_entries.append((1, s_line[2:].strip()))
        elif s_line.startswith("## "):
            toc_entries.append((2, s_line[3:].strip()))

    # Build TOC Page if we have headers
    if toc_entries:
        story.append(PageBreak())
        story.append(Paragraph("<b>Table of Contents</b>", style_h1))
        story.append(Spacer(1, 15))
        
        toc_table_data = []
        for level, title_text in toc_entries:
            clean_title = clean_markdown_to_reportlab_html(title_text)
            if level == 1:
                p_text = f"<b>{clean_title}</b>"
                indent = 0
            else:
                p_text = f"<font color='#475569'>{clean_title}</font>"
                indent = 20
                
            toc_table_data.append([
                Paragraph(p_text, ParagraphStyle('TOCItem', parent=style_normal, leftIndent=indent, spaceAfter=2))
            ])
        
        toc_table = Table(toc_table_data, colWidths=[504])
        toc_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(toc_table)
        story.append(PageBreak())

    # Build story from content lines
    for line in lines:
        stripped = line.strip()
        
        # Headers
        if stripped.startswith("#### "):
            text = clean_markdown_to_reportlab_html(stripped[5:])
            story.append(Paragraph(text, style_h4))
        elif stripped.startswith("### "):
            text = clean_markdown_to_reportlab_html(stripped[4:])
            story.append(Paragraph(text, style_h3))
        elif stripped.startswith("## "):
            text = clean_markdown_to_reportlab_html(stripped[3:])
            story.append(Paragraph(text, style_h2))
        elif stripped.startswith("# "):
            text = clean_markdown_to_reportlab_html(stripped[2:])
            story.append(Paragraph(text, style_h1))
            
        # Blockquotes
        elif stripped.startswith(">"):
            text = clean_markdown_to_reportlab_html(stripped[1:].strip())
            story.append(Paragraph(text, style_blockquote))

        # Horizontal rules
        elif stripped in ["---", "***"] or re.match(r"^[-*_]{3,}$", stripped):
            hr_table = Table([[""]], colWidths=[504], rowHeights=[1])
            hr_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#cbd5e1")),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
            ]))
            story.append(Spacer(1, 10))
            story.append(hr_table)
            story.append(Spacer(1, 10))

        # Bullet items
        elif stripped.startswith("- ") or stripped.startswith("* "):
            text = clean_markdown_to_reportlab_html(stripped[2:])
            bullet_text = f"&bull; {text}"
            story.append(Paragraph(bullet_text, style_bullet))
            
        # Numbered items
        elif re.match(r"^(\d+[a-zA-Z]?)\.\s+(.*)$", stripped):
            match = re.match(r"^(\d+[a-zA-Z]?)\.\s+(.*)$", stripped)
            num = match.group(1)
            text = clean_markdown_to_reportlab_html(match.group(2))
            bullet_text = f"{num}. {text}"
            story.append(Paragraph(bullet_text, style_bullet))

        # Empty space
        elif not stripped:
            story.append(Spacer(1, 6))
            
        # Normal paragraph
        else:
            text = clean_markdown_to_reportlab_html(stripped)
            if text == "Placeholder":
                continue
            story.append(Paragraph(text, style_normal))

    # Build the document
    doc.build(story, canvasmaker=NumberedCanvas)
    return f"/exports/{filename}"



def export_full_dossier(db_path: str) -> dict:
    """Exports the entire research database as a comprehensive dossier with PDF and Markdown outputs."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # 1. Query all data
    # ------------------------------------------------------------------
    sources = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    chunks = conn.execute(
        "SELECT c.*, s.title AS source_title, s.url AS source_url, "
        "s.trust_score AS source_trust, s.category AS source_category "
        "FROM chunks c JOIN sources s ON c.source_id = s.id ORDER BY c.source_id, c.chunk_index"
    ).fetchall()
    entities = conn.execute("SELECT * FROM entities ORDER BY type, name").fetchall()
    relations = conn.execute(
        "SELECT er.*, s.title AS source_title, s.trust_score "
        "FROM entity_relations er LEFT JOIN sources s ON er.source_id = s.id "
        "ORDER BY er.id"
    ).fetchall()
    conn.close()

    num_sources = len(sources)
    num_chunks = len(chunks)
    num_entities = len(entities)
    num_relations = len(relations)

    # ------------------------------------------------------------------
    # 2. Compute breakdowns
    # ------------------------------------------------------------------
    category_counts: dict[str, int] = {}
    for s in sources:
        cat = s["category"] or "Uncategorized"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    entity_type_counts: dict[str, int] = {}
    for e in entities:
        etype = e["type"] or "Unknown"
        entity_type_counts[etype] = entity_type_counts.get(etype, 0) + 1

    # ------------------------------------------------------------------
    # 3. Build markdown
    # ------------------------------------------------------------------
    md_lines: list[str] = []

    md_lines.append("# 📋 COMPLETE RESEARCH DATABASE DOSSIER\n")
    md_lines.append(f"*Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}*\n")

    # Executive summary table
    md_lines.append("## Executive Summary\n")
    md_lines.append("| Metric | Count |")
    md_lines.append("|--------|------:|")
    md_lines.append(f"| Sources | {num_sources} |")
    md_lines.append(f"| Chunks | {num_chunks} |")
    md_lines.append(f"| Entities | {num_entities} |")
    md_lines.append(f"| Relations | {num_relations} |")
    md_lines.append("")

    # Source categories breakdown
    md_lines.append("### Source Categories Breakdown\n")
    md_lines.append("| Category | Count |")
    md_lines.append("|----------|------:|")
    for cat, cnt in sorted(category_counts.items()):
        md_lines.append(f"| {cat} | {cnt} |")
    md_lines.append("")

    # Entity types breakdown
    md_lines.append("### Entity Types Breakdown\n")
    md_lines.append("| Type | Count |")
    md_lines.append("|------|------:|")
    for etype, cnt in sorted(entity_type_counts.items()):
        md_lines.append(f"| {etype} | {cnt} |")
    md_lines.append("")

    # ------------------------------------------------------------------
    # Section 1: Complete Source Registry
    # ------------------------------------------------------------------
    md_lines.append("## Section 1: Complete Source Registry\n")
    md_lines.append("| # | Trust | Category | Title | URL | Crawled |")
    md_lines.append("|---|-------|----------|-------|-----|---------|")
    for idx, s in enumerate(sources, 1):
        title = (s["title"] or "Untitled").replace("|", "\\|")
        url = s["url"] or ""
        trust = s["trust_score"] if s["trust_score"] is not None else "N/A"
        category = s["category"] or "N/A"
        crawled = s["crawled_at"] if s["crawled_at"] else "N/A"
        md_lines.append(f"| {idx} | {trust} | {category} | {title} | {url} | {crawled} |")
    md_lines.append("")

    # ------------------------------------------------------------------
    # Section 2: Full Research Content
    # ------------------------------------------------------------------
    md_lines.append("## Section 2: Full Research Content\n")

    # Group chunks by source_id
    chunks_by_source: dict[int, list] = {}
    for c in chunks:
        sid = c["source_id"]
        if sid not in chunks_by_source:
            chunks_by_source[sid] = []
        chunks_by_source[sid].append(c)

    for s in sources:
        s_title = s["title"] or "Untitled"
        s_url = s["url"] or ""
        s_trust = s["trust_score"] if s["trust_score"] is not None else "N/A"
        s_category = s["category"] or "N/A"

        md_lines.append(f"### {s_title}\n")
        md_lines.append(f"**URL:** {s_url}  ")
        md_lines.append(f"**Trust Score:** {s_trust} | **Category:** {s_category}\n")

        source_chunks = chunks_by_source.get(s["id"], [])
        if not source_chunks:
            md_lines.append("*No chunks available for this source.*\n")
        else:
            for c in source_chunks:
                chunk_idx = c["chunk_index"] if c["chunk_index"] is not None else "?"
                text = (c["text"] or "").strip()
                # Blockquote each line of the chunk text
                quoted_text = "\n".join(f"> {line}" for line in text.split("\n"))
                md_lines.append(f"> **[Chunk {chunk_idx}]**")
                md_lines.append(quoted_text)
                md_lines.append("")
            md_lines.append(f"*Source: [{s_title}]({s_url})*\n")

    # ------------------------------------------------------------------
    # Section 3: Entity Registry
    # ------------------------------------------------------------------
    md_lines.append("## Section 3: Entity Registry\n")

    entities_by_type: dict[str, list] = {}
    for e in entities:
        etype = e["type"] or "Unknown"
        if etype not in entities_by_type:
            entities_by_type[etype] = []
        entities_by_type[etype].append(e)

    for etype in sorted(entities_by_type.keys()):
        md_lines.append(f"### {etype}\n")
        for e in entities_by_type[etype]:
            md_lines.append(f"- {e['name']}")
        md_lines.append("")

    # ------------------------------------------------------------------
    # Entity Relations table
    # ------------------------------------------------------------------
    md_lines.append("## Entity Relations\n")
    md_lines.append("| Entity 1 | Entity 2 | Description | Source Title | Trust |")
    md_lines.append("|----------|----------|-------------|-------------|------:|")
    for r in relations:
        e1 = (r["entity_1"] or "").replace("|", "\\|")
        e2 = (r["entity_2"] or "").replace("|", "\\|")
        desc = (r["description"] or "").replace("|", "\\|")
        src_title = (r["source_title"] or "N/A").replace("|", "\\|")
        trust = r["trust_score"] if r["trust_score"] is not None else "N/A"
        md_lines.append(f"| {e1} | {e2} | {desc} | {src_title} | {trust} |")
    md_lines.append("")

    # ------------------------------------------------------------------
    # Appendix: Direct Source URL Index
    # ------------------------------------------------------------------
    md_lines.append("## Appendix: Direct Source URL Index\n")
    for idx, s in enumerate(sources, 1):
        url = s["url"] or "N/A"
        title = s["title"] or "Untitled"
        md_lines.append(f"{idx}. [{title}]({url})")
    md_lines.append("")

    markdown_string = "\n".join(md_lines)

    # ------------------------------------------------------------------
    # 4. Generate PDF
    # ------------------------------------------------------------------
    pdf_url = export_to_pdf(
        title='Complete Research Database Dossier',
        country='All Domains',
        content_markdown=markdown_string,
    )

    # ------------------------------------------------------------------
    # 5. Save markdown file
    # ------------------------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    md_filename = f"full_dossier_export_{timestamp}.md"
    md_filepath = os.path.join(EXPORTS_DIR, md_filename)
    with open(md_filepath, "w", encoding="utf-8") as f:
        f.write(markdown_string)

    return {
        'pdf_url': pdf_url,
        'markdown_url': f'/exports/{md_filename}',
        'stats': {
            'sources': num_sources,
            'chunks': num_chunks,
            'entities': num_entities,
            'relations': num_relations,
        },
    }

