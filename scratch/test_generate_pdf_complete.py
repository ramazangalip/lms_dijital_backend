import os
import sys
import math
from io import BytesIO

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from contents.models import (
    WeeklyContent,
    StudentProgress,
    TimeTracking,
    CompletedMaterial,
    StudentQuizAttempt,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import pymupdf

User = get_user_model()

# Fonts
pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
font_reg = 'Arial'
font_bld = 'Arial-Bold'

# Styles
style_hdr_title = ParagraphStyle('HT', fontName=font_bld, fontSize=9.5, leading=11.5, textColor=colors.HexColor('#0f172a'))
style_hdr_sub = ParagraphStyle('HS', fontName=font_reg, fontSize=6.8, leading=8.5, textColor=colors.HexColor('#64748b'))
style_hdr_page = ParagraphStyle('HP', fontName=font_reg, fontSize=6.5, leading=8.5, textColor=colors.HexColor('#94a3b8'), alignment=2)
style_hdr_legend = ParagraphStyle('HL', fontName=font_reg, fontSize=6, leading=7.5, textColor=colors.HexColor('#94a3b8'), alignment=2)

style_th_stu = ParagraphStyle('THS', fontName=font_bld, fontSize=6.5, leading=8, textColor=colors.white, alignment=0)
style_th = ParagraphStyle('TH', fontName=font_bld, fontSize=6.5, leading=8, textColor=colors.white, alignment=1)

style_stu_name = ParagraphStyle('SN', fontName=font_bld, fontSize=6.2, leading=7.5, textColor=colors.HexColor('#0f172a'))
style_stu_email = ParagraphStyle('SE', fontName=font_reg, fontSize=5, leading=6, textColor=colors.HexColor('#64748b'))
style_stu_badge = ParagraphStyle('SBD', fontName=font_bld, fontSize=4.8, leading=5.8, textColor=colors.HexColor('#334155'), alignment=1)

style_t1_l = ParagraphStyle('T1L', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#334155'))
style_t1_r = ParagraphStyle('T1R', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#2563eb'), alignment=2)
style_sub_l = ParagraphStyle('SBL', fontName=font_reg, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#64748b'))
style_sub_r = ParagraphStyle('SBR', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#334155'), alignment=2)
style_quiz = ParagraphStyle('QZ', fontName=font_bld, fontSize=4.3, leading=5.2, textColor=colors.HexColor('#475569'))

style_mat_hdr = ParagraphStyle('MH', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#94a3b8'))
style_mat_item = ParagraphStyle('MI', fontName=font_bld, fontSize=4.2, leading=5.2, textColor=colors.HexColor('#1e293b'))
style_mat_dur = ParagraphStyle('MD', fontName=font_bld, fontSize=4, leading=4.8, textColor=colors.HexColor('#ce1212'))

style_t2_l = ParagraphStyle('T2L', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#92400e'))
style_t2_r = ParagraphStyle('T2R', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#78350f'), alignment=2)
style_t2_sub_r = ParagraphStyle('T2SBR', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#92400e'), alignment=2)

style_tot_pts = ParagraphStyle('TP', fontName=font_bld, fontSize=7, leading=8.5, textColor=colors.HexColor('#1d4ed8'), alignment=1)
style_tot_line = ParagraphStyle('TL', fontName=font_reg, fontSize=4.8, leading=6, textColor=colors.HexColor('#475569'))
style_tot_bold = ParagraphStyle('TB', fontName=font_bld, fontSize=5, leading=6.2, textColor=colors.HexColor('#0f172a'))
style_tot_diff = ParagraphStyle('TD', fontName=font_bld, fontSize=4.8, leading=6, textColor=colors.HexColor('#ce1212'))

style_ftr_l = ParagraphStyle('FL', fontName=font_reg, fontSize=5.5, leading=7, textColor=colors.HexColor('#94a3b8'))
style_ftr_r = ParagraphStyle('FR', fontName=font_reg, fontSize=5.5, leading=7, textColor=colors.HexColor('#94a3b8'), alignment=2)

def fmt_num(val):
    if val is None:
        return "0"
    try:
        f = float(val)
        if f == int(f):
            return str(int(f))
        return f"{f:.1f}"
    except (ValueError, TypeError):
        return str(val)

def format_duration(total_seconds):
    if not total_seconds:
        return "0 dk"
    try:
        num_secs = int(total_seconds)
    except (ValueError, TypeError):
        return "0 dk"
    if num_secs <= 0:
        return "0 dk"
    hours = num_secs // 3600
    minutes = (num_secs % 3600) // 60
    if hours > 0:
        return f"{hours} sa {minutes} dk"
    return f"{minutes} dk"

def get_dept_name(dept_code):
    dept_dict = dict(User.DEPARTMENT_CHOICES)
    return dept_dict.get(dept_code, dept_code)

def fetch_bulk_data(department):
    students = User.objects.filter(
        is_staff=False, is_teacher=False, department=department, category='d2'
    ).prefetch_related(
        'timetracking_set', 
        'studentquizattempt_set__quiz__material__parent_content',
        'studentprogress_set',
        'completedmaterial_set'
    ).order_by('first_name', 'last_name')

    all_weeks = list(WeeklyContent.objects.all().prefetch_related('materials'))
    week_map = {w.week_number: w for w in all_weeks}
    
    report_data = []

    for student in students:
        student_trackings = list(student.timetracking_set.all())
        student_attempts = list(student.studentquizattempt_set.all())
        student_progresses = list(student.studentprogress_set.all())
        student_completed = list(student.completedmaterial_set.all())

        weekly_stats = []
        overall_total_seconds_1 = sum(t.duration_seconds for t in student_trackings if t.attempt_round == 1)
        overall_total_seconds_2 = sum(t.duration_seconds for t in student_trackings if t.attempt_round == 2)
        overall_total_seconds = overall_total_seconds_1 + overall_total_seconds_2
        
        for i in range(1, 15):
            week_content = week_map.get(i)
            w_id = week_content.id if week_content else None
            
            duration_1 = sum(t.duration_seconds for t in student_trackings if t.weekly_content_id == w_id and t.attempt_round == 1)
            duration_2 = sum(t.duration_seconds for t in student_trackings if t.weekly_content_id == w_id and t.attempt_round == 2)
            
            attempt_1 = next((a for a in student_attempts if a.quiz and a.quiz.material and a.quiz.material.parent_content_id == w_id and a.attempt_round == 1), None)
            attempt_2 = next((a for a in student_attempts if a.quiz and a.quiz.material and a.quiz.material.parent_content_id == w_id and a.attempt_round == 2), None)
            
            material_details = []
            week_mats = list(week_content.materials.all()) if week_content else []
            total_week_mats = len(week_mats)
            week_mat_ids = {m.id for m in week_mats}

            if week_content:
                for m in week_mats:
                    m_duration_1 = sum(t.duration_seconds for t in student_trackings if t.material_id == m.id and t.attempt_round == 1)
                    m_duration_2 = sum(t.duration_seconds for t in student_trackings if t.material_id == m.id and t.attempt_round == 2)
                    material_details.append({
                        "title": m.title,
                        "content_type": m.content_type,
                        "duration_seconds_1": m_duration_1,
                        "duration_seconds_2": m_duration_2,
                        "duration_seconds": m_duration_1 + m_duration_2
                    })

            done_count_1 = len([cm for cm in student_completed if cm.material_id in week_mat_ids and cm.attempt_round == 1])
            prog_1 = round((done_count_1 / total_week_mats) * 100) if total_week_mats > 0 else 0

            done_count_2 = len([cm for cm in student_completed if cm.material_id in week_mat_ids and cm.attempt_round == 2])
            prog_2 = round((done_count_2 / total_week_mats) * 100) if total_week_mats > 0 else 0

            progress_record = next((p for p in student_progresses if p.weekly_content_id == w_id), None)
            current_round = progress_record.current_attempt_round if progress_record else 1
            is_round_2 = (duration_2 > 0 or attempt_2 is not None or current_round == 2 or done_count_2 > 0)

            weekly_stats.append({
                "week": i,
                "progress": float(prog_1),
                "progress_1": float(prog_1),
                "progress_2": float(prog_2),
                "current_round": current_round,
                "material_details": material_details,
                "duration_seconds": duration_1,
                "correct": attempt_1.correct_answers if attempt_1 else 0,
                "wrong": attempt_1.wrong_answers if attempt_1 else 0,
                "score_1": attempt_1.score if attempt_1 else 0,
                "predicted_1": attempt_1.predicted_score if attempt_1 else 0,
                "diff_1": attempt_1.score_difference if attempt_1 else 0,
                "duration_seconds_2": duration_2,
                "correct_2": attempt_2.correct_answers if attempt_2 else 0,
                "wrong_2": attempt_2.wrong_answers if attempt_2 else 0,
                "score_2": attempt_2.score if attempt_2 else 0,
                "predicted_2": attempt_2.predicted_score if attempt_2 else 0,
                "diff_2": attempt_2.score_difference if attempt_2 else 0,
                "has_quiz": True if (attempt_1 or attempt_2) else False,
                "is_round_2_started": is_round_2
            })

        if student_attempts:
            stu_avg_pred = round(sum(a.predicted_score for a in student_attempts) / len(student_attempts), 1)
            stu_avg_act = round(sum(a.score for a in student_attempts) / len(student_attempts), 1)
            stu_avg_diff = round(sum(a.score_difference for a in student_attempts) / len(student_attempts), 1)
        else:
            stu_avg_pred = 0
            stu_avg_act = 0
            stu_avg_diff = 0

        report_data.append({
            "id": str(student.id),
            "full_name": f"{student.first_name} {student.last_name}".strip().upper(),
            "email": student.email,
            "department": student.department,
            "total_points": getattr(student, 'total_points', 0),
            "total_time_1": overall_total_seconds_1,
            "total_time_2": overall_total_seconds_2,
            "total_time": overall_total_seconds,
            "avg_predicted": stu_avg_pred,
            "avg_actual": stu_avg_act,
            "avg_diff": stu_avg_diff,
            "weekly_breakdown": weekly_stats
        })

    return report_data

def build_student_cell(student, dept_label):
    badge_table = Table([[Paragraph(dept_label, style_stu_badge)]], colWidths=[76])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))
    return [
        Paragraph(student['full_name'], style_stu_name),
        Paragraph(student['email'], style_stu_email),
        Spacer(1, 2),
        badge_table
    ]

def build_week_cell(week):
    flowables = []
    
    # 1. T1 ÜST KUTU
    dur1 = week.get('duration_seconds') or 0
    dur2 = week.get('duration_seconds_2') or 0
    prog1 = fmt_num(week.get('progress_1', 0))
    prog2 = fmt_num(week.get('progress_2', 0))
    
    t1_rows = [
        [Paragraph("T1", style_t1_l), Paragraph(f"%{prog1}", style_t1_r)],
        [Paragraph(f"{week.get('correct', 0)}D / {week.get('wrong', 0)}Y", style_sub_l), 
         Paragraph(f"T1: {format_duration(dur1)}", style_sub_r)]
    ]
    if week.get('has_quiz'):
        diff_1 = week.get('diff_1') or 0
        diff_str = f"+{fmt_num(diff_1)}" if diff_1 > 0 else fmt_num(diff_1)
        diff_color = '#047857' if diff_1 > 0 else ('#b45309' if diff_1 < 0 else '#475569')
        quiz_text = f"T:%{fmt_num(week.get('predicted_1', 0))} G:%{fmt_num(week.get('score_1', 0))} <font color='{diff_color}'><b>(F:{diff_str})</b></font>"
        t1_rows.append([Paragraph(quiz_text, style_quiz), ""])

    t1_table = Table(t1_rows, colWidths=[20, 24])
    t1_style = [
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
    ]
    if len(t1_rows) > 2:
        t1_style.append(('SPAN', (0, 2), (1, 2)))
        t1_style.append(('LINEABOVE', (0, 2), (1, 2), 0.3, colors.HexColor('#e2e8f0')))
    t1_table.setStyle(TableStyle(t1_style))
    flowables.append(t1_table)
    flowables.append(Spacer(1, 1.5))

    # 2. MATERYALLER LİSTESİ
    flowables.append(Paragraph("MATERYALLER", style_mat_hdr))
    mats = week.get('material_details') or []
    if mats:
        for m in mats:
            m_dur1 = m.get('duration_seconds_1') or 0
            m_dur2 = m.get('duration_seconds_2') or 0
            dur2_str = format_duration(m_dur2) if m_dur2 > 0 else '-'
            title = m.get('title', '')
            if len(title) > 22:
                title = title[:21] + '..'
            flowables.append(Paragraph(f"• {title}", style_mat_item))
            flowables.append(Paragraph(f"&nbsp;[T1: {format_duration(m_dur1)} | T2: {dur2_str}]", style_mat_dur))
    else:
        flowables.append(Paragraph("<i>Yok</i>", style_sub_l))

    # 3. T2 KUTUSU (Aktif ise)
    if week.get('is_round_2_started'):
        flowables.append(Spacer(1, 1.5))
        t2_rows = [
            [Paragraph("<font color='#92400e'><b>T2</b></font>", style_t2_l), Paragraph(f"%{prog2}", style_t2_r)]
        ]
        if dur2 > 0 or week.get('correct_2') or week.get('wrong_2'):
            t2_rows.append([
                Paragraph(f"{week.get('correct_2', 0)}D / {week.get('wrong_2', 0)}Y", style_sub_l),
                Paragraph(f"T2: {format_duration(dur2)}", style_t2_sub_r)
            ])
        score_2 = week.get('score_2')
        if score_2 is not None and score_2 > 0:
            diff_2 = week.get('diff_2') or 0
            diff2_str = f"+{fmt_num(diff_2)}" if diff_2 > 0 else fmt_num(diff_2)
            diff2_color = '#047857' if diff_2 > 0 else ('#b45309' if diff_2 < 0 else '#475569')
            quiz_text_2 = f"T:%{fmt_num(week.get('predicted_2', 0))} G:%{fmt_num(score_2)} <font color='{diff2_color}'><b>(F:{diff2_str})</b></font>"
            t2_rows.append([Paragraph(quiz_text_2, style_quiz), ""])

        t2_table = Table(t2_rows, colWidths=[20, 24])
        t2_style = [
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffbeb')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#fde68a')),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('LEFTPADDING', (0, 0), (-1, -1), 1),
            ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ]
        if len(t2_rows) > 2:
            t2_style.append(('SPAN', (0, 2), (1, 2)))
            t2_style.append(('LINEABOVE', (0, 2), (1, 2), 0.3, colors.HexColor('#fde68a')))
        t2_table.setStyle(TableStyle(t2_style))
        flowables.append(t2_table)

    return flowables

def build_total_cell(student):
    flowables = [
        Paragraph(f"{student.get('total_points', 0)} PUAN", style_tot_pts),
        Spacer(1, 1),
        Paragraph(f"<font color='#64748b'>T1:</font> {format_duration(student.get('total_time_1', 0))}", style_tot_line),
        Paragraph(f"<font color='#b45309'><b>T2:</b></font> {format_duration(student.get('total_time_2', 0))}", style_tot_line),
        Paragraph(f"TOP: {format_duration(student.get('total_time', 0))}", style_tot_bold),
    ]
    avg_pred = student.get('avg_predicted', 0)
    avg_act = student.get('avg_actual', 0)
    if avg_pred > 0 or avg_act > 0:
        diff = student.get('avg_diff', 0)
        diff_str = f"+{fmt_num(diff)}" if diff > 0 else fmt_num(diff)
        flowables.extend([
            Spacer(1, 1),
            Paragraph(f"Ort. T:%{fmt_num(avg_pred)} G:%{fmt_num(avg_act)}", style_tot_line),
            Paragraph(f"Fark: {diff_str} Puan", style_tot_diff),
        ])
    return flowables

def generate_pdf(department, output_filename):
    data = fetch_bulk_data(department)
    dept_label = get_dept_name(department)
    
    # 4 students per page guarantees clean layout with zero row overflow
    chunk_size = 4
    pages = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
    total_pages = len(pages) if pages else 1
    
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=landscape(A4),
        leftMargin=12,
        rightMargin=12,
        topMargin=10,
        bottomMargin=10
    )
    
    story = []
    col_widths = [86] + [47.9] * 14 + [61]
    
    for page_idx, page_students in enumerate(pages):
        # 1. SAYFA ÜST BİLGİSİ
        hdr_table = Table([
            [
                Paragraph("<b>BİNGÖL ÜNİVERSİTESİ DİJİTAL DÖNÜŞÜM DERSİ AKADEMİK PERFORMANS RAPORU</b>", style_hdr_title),
                Paragraph(f"Sayfa {page_idx + 1} / {total_pages}", style_hdr_page)
            ],
            [
                Paragraph(f"BÖLÜM: <b>{dept_label.upper()}</b> | TOPLAM ÖĞRENCİ: <b>{len(data)}</b>", style_hdr_sub),
                Paragraph("T1: 1. Tur | T2: 2. Tur", style_hdr_legend)
            ]
        ], colWidths=[600, 217])
        hdr_table.setStyle(TableStyle([
            ('LINEBELOW', (0, 1), (-1, 1), 1.5, colors.HexColor('#0f172a')),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(hdr_table)
        story.append(Spacer(1, 3))
        
        # 2. TABLO
        table_rows = []
        header_row = [Paragraph("Öğrenci Adı Soyadı", style_th_stu)]
        for w in range(1, 15):
            header_row.append(Paragraph(f"H.{w}", style_th))
        header_row.append(Paragraph("GENEL TOPLAM", style_th))
        table_rows.append(header_row)
        
        for student in page_students:
            row = [build_student_cell(student, dept_label)]
            for w_stat in student['weekly_breakdown']:
                row.append(build_week_cell(w_stat))
            row.append(build_total_cell(student))
            table_rows.append(row)
            
        t = Table(table_rows, colWidths=col_widths)
        t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ]
        for r_idx in range(1, len(table_rows)):
            t_style.append(('BACKGROUND', (0, r_idx), (0, r_idx), colors.HexColor('#f8fafc')))
            t_style.append(('BACKGROUND', (-1, r_idx), (-1, r_idx), colors.HexColor('#f8fafc')))
        t.setStyle(TableStyle(t_style))
        story.append(t)
        
        # 3. SAYFA ALTI BİLGİSİ
        story.append(Spacer(1, 3))
        now_date = timezone.now().strftime('%d.%m.%Y')
        ftr_table = Table([
            [
                Paragraph("Bingöl Üniversitesi LMS Sistemi tarafından otomatik oluşturulmuştur.", style_ftr_l),
                Paragraph(f"Rapor Tarihi: {now_date}", style_ftr_r)
            ]
        ], colWidths=[500, 317])
        ftr_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(ftr_table)
        
        if page_idx < total_pages - 1:
            story.append(PageBreak())
            
    doc.build(story)
    print(f"Generated {output_filename} successfully ({total_pages} pages)")

generate_pdf('turkdiliveedebiyati', 'scratch/turkdiliveedebiyati_test.pdf')

doc_pdf = pymupdf.open('scratch/turkdiliveedebiyati_test.pdf')
print("Actual PDF page count:", len(doc_pdf))
for p in range(len(doc_pdf)):
    page = doc_pdf[p]
    pix = page.get_pixmap(dpi=150)
    img_name = f'scratch/turkdiliveedebiyati_final_p{p+1}.png'
    pix.save(img_name)
    print(f"Saved {img_name}")
