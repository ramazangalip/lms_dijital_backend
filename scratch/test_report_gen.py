import os
import django
from io import BytesIO
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')
django.setup()

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Test fonts
pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))

font_reg = 'Arial'
font_bld = 'Arial-Bold'

style_t1_left = ParagraphStyle('T1L', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#334155'))
style_t1_right = ParagraphStyle('T1R', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#2563eb'), alignment=2)
style_sub_left = ParagraphStyle('SBL', fontName=font_reg, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#64748b'))
style_sub_right = ParagraphStyle('SBR', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#334155'), alignment=2)
style_quiz = ParagraphStyle('QZ', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#475569'))
style_mat_hdr = ParagraphStyle('MH', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#94a3b8'))
style_mat_item = ParagraphStyle('MI', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#1e293b'))
style_mat_dur = ParagraphStyle('MD', fontName=font_bld, fontSize=4, leading=5, textColor=colors.HexColor('#ce1212'))

def build_test_cell():
    flowables = []
    
    # T1 Box
    t1_data = [
        [Paragraph("T1", style_t1_left), Paragraph("%100", style_t1_right)],
        [Paragraph("10D / 0Y", style_sub_left), Paragraph("T1: 33 dk", style_sub_right)],
        [Paragraph("T:%80 G:%100 <font color='#047857'>(F:+20)</font>", style_quiz), ""]
    ]
    t1_table = Table(t1_data, colWidths=[20, 24])
    t1_table.setStyle(TableStyle([
        ('SPAN', (0, 2), (1, 2)),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('LINEBELOW', (0, 1), (-1, 1), 0.3, colors.HexColor('#e2e8f0')),
    ]))
    flowables.append(t1_table)
    flowables.append(Spacer(1, 2))
    
    # MATERYALLER
    flowables.append(Paragraph("MATERYALLER", style_mat_hdr))
    mats = [
        ("• 4.Hafta Öğrenilecekler", "[T1: 3 dk | T2: -]"),
        ("• 4.Hafta Ders İçeriği", "[T1: 1 dk | T2: -]"),
        ("• 4.Hafta Video", "[T1: 6 dk | T2: -]"),
    ]
    for title, dur in mats:
        flowables.append(Paragraph(title, style_mat_item))
        flowables.append(Paragraph(f"&nbsp;&nbsp;{dur}", style_mat_dur))
    
    return flowables

print("Building sample PDF...")
doc = SimpleDocTemplate("scratch/test_report.pdf", pagesize=landscape(A4), leftMargin=12, rightMargin=12, topMargin=12, bottomMargin=12)
sample_cell = build_test_cell()
data = [
    ["Öğrenci"] + [f"H.{i}" for i in range(1, 15)] + ["GENEL TOPLAM"],
    ["Ali Veli"] + [sample_cell for _ in range(14)] + ["5 PUAN"]
]
col_widths = [86] + [47.9] * 14 + [61]
table = Table(data, colWidths=col_widths)
table.setStyle(TableStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
]))
doc.build([table])
print("PDF created successfully, size:", os.path.getsize("scratch/test_report.pdf"))
