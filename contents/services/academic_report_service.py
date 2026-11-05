"""
Akademik Raporlama ve Otomatik Bildirim Servisi

Bu servis:
1. Akademisyen panelinde bulunan 3 temel analiz dökümünü bölüm bazlı (Kategori D2) olarak üretir:
   - Öğrenci Analizleri (14 Haftalık Genel Akademik Performans Raporu)
   - Chatbot Analizi (Yapay Zeka Soru ve Yanıt Analiz Raporu)
   - Ön Değerlendirme Analizi (Ön Değerlendirme Test Sonuçları & Telafi İlerlemeleri Raporu)
2. Bu 3 PDF raporunu e-posta ekine ekler.
3. Sonraki haftanın açılışından 1 gün önce 20:00'da veya mevcut haftanın kapanış günü 20:00'da
   rolü akademisyen olan kişilere otomatik mail bildirimi olarak ulaştırır.
4. Mükerrer gönderimleri engellemek için AcademicReportEmailLog tablosunu kullanır.
"""

import os
import sys
import logging
from io import BytesIO
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth import get_user_model

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    colors = None
    A4 = landscape = None
    SimpleDocTemplate = Paragraph = Spacer = Table = TableStyle = PageBreak = KeepTogether = None
    getSampleStyleSheet = ParagraphStyle = None
    pdfmetrics = TTFont = None
    canvas = None
    REPORTLAB_AVAILABLE = False

from contents.models import (
    WeeklyContent,
    WeeklyContentDepartmentSchedule,
    Material,
    StudentProgress,
    TimeTracking,
    CompletedMaterial,
    StudentQuizAttempt,
    AcademicReportEmailLog,
    TemporaryWeekUnlock,
    RemediationCompletedMaterial,
    RemediationTimeTracking,
    StudentQuestion,
    PreEvaluationAttempt,
    PreEvaluationAnswer,
    Quiz,
    QuizQuestion,
    StudentAnswer
)
from preevaluation.models import PreEvaluationTest

logger = logging.getLogger(__name__)
User = get_user_model()
ISTANBUL_TZ = ZoneInfo('Europe/Istanbul')


# --- FONT VE TÜRKÇE KARAKTER YÖNETİMİ ---

_font_initialized = False
_primary_font = 'Helvetica'
_primary_font_bold = 'Helvetica-Bold'

def _init_pdf_fonts():
    """ReportLab için Türkçe karakter destekli fontları kaydeder."""
    global _font_initialized, _primary_font, _primary_font_bold
    if not REPORTLAB_AVAILABLE:
        return 'Helvetica', 'Helvetica-Bold'
    if _font_initialized:
        return _primary_font, _primary_font_bold

    font_candidates = [
        ('Arial', 'C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
        ('SegoeUI', 'C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/segoeuib.ttf'),
        ('DejaVuSans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ]

    for name, regular_path, bold_path in font_candidates:
        if os.path.exists(regular_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont(name, regular_path))
                pdfmetrics.registerFont(TTFont(f"{name}-Bold", bold_path))
                _primary_font = name
                _primary_font_bold = f"{name}-Bold"
                _font_initialized = True
                logger.info(f"ReportLab fontu kaydedildi: {_primary_font}")
                return _primary_font, _primary_font_bold
            except Exception as e:
                logger.warning(f"Font kaydedilemedi ({name}): {e}")

    _font_initialized = True
    return _primary_font, _primary_font_bold


def safe_tr(text):
    """Metni güvenli hale getirir."""
    if text is None:
        return ""
    return str(text)


if REPORTLAB_AVAILABLE:
    class NumberedCanvas(canvas.Canvas):
        """Sayfa numaralarını ve altbilgiyi dinamik olarak ekleyen özel canvas."""
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
                self.draw_footer(num_pages)
                super().showPage()
            super().save()

        def draw_footer(self, page_count):
            self.saveState()
            self.setFont(_primary_font, 8)
            self.setFillColor(colors.HexColor('#64748b'))
            width, height = landscape(A4)
            self.setStrokeColor(colors.HexColor('#e2e8f0'))
            self.setLineWidth(0.5)
            self.line(20, 22, width - 20, 22)
            self.drawString(20, 12, "Bingöl Üniversitesi LMS Dijital Sınıf Sistemi • Resmi Akademik Rapor")
            self.drawRightString(width - 20, 12, f"Sayfa {self._pageNumber} / {page_count}")
            self.restoreState()
else:
    class NumberedCanvas:
        pass


# --- TARİH VE TETİKLEME HESAPLAMA ---

def get_effective_dates(weekly_content, department):
    """
    Belirli bir haftalık içerik ve bölüm için geçerli açılış ve kapanış tarihlerini döndürür.
    Öncelikle WeeklyContentDepartmentSchedule tablosuna bakar, yoksa WeeklyContent'e döner.
    """
    if not weekly_content:
        return None, None

    rel_date = weekly_content.release_date
    deact_date = weekly_content.deactivation_date

    if department:
        sched = WeeklyContentDepartmentSchedule.objects.filter(
            weekly_content=weekly_content,
            department=department
        ).first()
        if sched:
            if sched.release_date is not None:
                rel_date = sched.release_date
            if sched.deactivation_date is not None:
                deact_date = sched.deactivation_date

    return rel_date, deact_date


def get_trigger_datetime_for_week(weekly_content, department):
    """
    Hafta W ve Bölüm için mail gönderim tetikleme zamanını (datetime) hesaplar.
    
    Kural 1:
      O bölüme ait bir sonraki haftanın (W+1) aktif etme tarihi (release_date) ne ise,
      o tarihten BİR GÜN ÖNCE saat 20:00'da.
      
    Kural 2:
      Eğer sonraki haftanın aktif etme tarihi belli değilse (None veya sonraki hafta eklenmemişse),
      o mevcut haftanın (W) pasif etme (deactivation_date) tarihinin olduğu gün saat 20:00'da.
    """
    next_week = WeeklyContent.objects.filter(week_number=weekly_content.week_number + 1).first()
    rel_date_next, _ = get_effective_dates(next_week, department) if next_week else (None, None)

    if rel_date_next is not None:
        rel_local = rel_date_next.astimezone(ISTANBUL_TZ)
        target_date = rel_local.date() - timedelta(days=1)
        trigger_dt = datetime.combine(target_date, time(20, 0), tzinfo=ISTANBUL_TZ)
        trigger_reason = (
            f"Sonraki hafta ({weekly_content.week_number + 1}. Hafta) açılışından "
            f"({rel_local.strftime('%d.%m.%Y %H:%M')}) 1 gün önce saat 20:00"
        )
        return trigger_dt, target_date, 'NEXT_WEEK_MINUS_ONE_DAY', trigger_reason

    _, deact_date_curr = get_effective_dates(weekly_content, department)
    if deact_date_curr is not None:
        deact_local = deact_date_curr.astimezone(ISTANBUL_TZ)
        target_date = deact_local.date()
        trigger_dt = datetime.combine(target_date, time(20, 0), tzinfo=ISTANBUL_TZ)
        trigger_reason = (
            f"Mevcut hafta ({weekly_content.week_number}. Hafta) kapanış günü "
            f"({deact_local.strftime('%d.%m.%Y %H:%M')}) saat 20:00"
        )
        return trigger_dt, target_date, 'CURRENT_WEEK_DEACTIVATION_DAY', trigger_reason

    return None, None, None, "Açılış veya kapanış tarihi tanımlı değil"


# =====================================================================
# 1. ÖĞRENCİ ANALİZLERİ RAPORU (BULK AKADEMİK RAPOR - 14 HAFTALIK DÖKÜM)
# =====================================================================

def fmt_num(val):
    """Sayıları gereksiz .0 olmadan temiz formatlar (örn: 100 veya 15.5)."""
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
    """Süreleri TeacherBulkReportPrint formatında formatlar (örn: '0 dk', '33 dk', '1 sa 15 dk')."""
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


def fetch_bulk_academic_report_data(department):
    """
    Akademisyen panelindeki Öğrenci Analizleri sekmesinin kullandığı verinin
    birebir aynısını üretir.
    """
    students = User.objects.filter(
        is_staff=False, is_teacher=False, department=department, category__iexact='d2'
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


def generate_student_analytics_bulk_pdf(department):
    """
    Akademisyen panelindeki 'Öğrenci Analizleri' sekmesinde bulunan
    14 haftalık akademik performans tablosunu aynen A4 Yatay PDF formatında üretir.
    TeacherBulkReportPrint.tsx görsel şablonunun birebir kopyasıdır.
    """
    font_reg, font_bld = _init_pdf_fonts()
    data = fetch_bulk_academic_report_data(department)
    dept_label = dict(User.DEPARTMENT_CHOICES).get(department, department)

    # Stiller
    style_hdr_title = ParagraphStyle('HT_B', fontName=font_bld, fontSize=9.5, leading=11.5, textColor=colors.HexColor('#0f172a'))
    style_hdr_sub = ParagraphStyle('HS_B', fontName=font_reg, fontSize=6.8, leading=8.5, textColor=colors.HexColor('#64748b'))
    style_hdr_page = ParagraphStyle('HP_B', fontName=font_reg, fontSize=6.5, leading=8.5, textColor=colors.HexColor('#94a3b8'), alignment=2)
    style_hdr_legend = ParagraphStyle('HL_B', fontName=font_reg, fontSize=6, leading=7.5, textColor=colors.HexColor('#94a3b8'), alignment=2)

    style_th_stu = ParagraphStyle('THS_B', fontName=font_bld, fontSize=6.5, leading=8, textColor=colors.white, alignment=0)
    style_th = ParagraphStyle('TH_B', fontName=font_bld, fontSize=6.5, leading=8, textColor=colors.white, alignment=1)

    style_stu_name = ParagraphStyle('SN_B', fontName=font_bld, fontSize=6.2, leading=7.5, textColor=colors.HexColor('#0f172a'))
    style_stu_email = ParagraphStyle('SE_B', fontName=font_reg, fontSize=5, leading=6, textColor=colors.HexColor('#64748b'))
    style_stu_badge = ParagraphStyle('SBD_B', fontName=font_bld, fontSize=4.8, leading=5.8, textColor=colors.HexColor('#334155'), alignment=1)

    style_t1_l = ParagraphStyle('T1L_B', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#334155'))
    style_t1_r = ParagraphStyle('T1R_B', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#2563eb'), alignment=2)
    style_sub_l = ParagraphStyle('SBL_B', fontName=font_reg, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#64748b'))
    style_sub_r = ParagraphStyle('SBR_B', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#334155'), alignment=2)
    style_quiz = ParagraphStyle('QZ_B', fontName=font_bld, fontSize=4.3, leading=5.2, textColor=colors.HexColor('#475569'))

    style_mat_hdr = ParagraphStyle('MH_B', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#94a3b8'))
    style_mat_item = ParagraphStyle('MI_B', fontName=font_bld, fontSize=4.2, leading=5.2, textColor=colors.HexColor('#1e293b'))
    style_mat_dur = ParagraphStyle('MD_B', fontName=font_bld, fontSize=4, leading=4.8, textColor=colors.HexColor('#ce1212'))

    style_t2_l = ParagraphStyle('T2L_B', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#92400e'))
    style_t2_r = ParagraphStyle('T2R_B', fontName=font_bld, fontSize=5.5, leading=6.5, textColor=colors.HexColor('#78350f'), alignment=2)
    style_t2_sub_r = ParagraphStyle('T2SBR_B', fontName=font_bld, fontSize=4.5, leading=5.5, textColor=colors.HexColor('#92400e'), alignment=2)

    style_tot_pts = ParagraphStyle('TP_B', fontName=font_bld, fontSize=7, leading=8.5, textColor=colors.HexColor('#1d4ed8'), alignment=1)
    style_tot_line = ParagraphStyle('TL_B', fontName=font_reg, fontSize=4.8, leading=6, textColor=colors.HexColor('#475569'))
    style_tot_bold = ParagraphStyle('TB_B', fontName=font_bld, fontSize=5, leading=6.2, textColor=colors.HexColor('#0f172a'))
    style_tot_diff = ParagraphStyle('TD_B', fontName=font_bld, fontSize=4.8, leading=6, textColor=colors.HexColor('#ce1212'))

    style_ftr_l = ParagraphStyle('FL_B', fontName=font_reg, fontSize=5.5, leading=7, textColor=colors.HexColor('#94a3b8'))
    style_ftr_r = ParagraphStyle('FR_B', fontName=font_reg, fontSize=5.5, leading=7, textColor=colors.HexColor('#94a3b8'), alignment=2)

    def _build_student_cell(student):
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

    def _build_week_cell(week):
        flowables = []
        dur1 = week.get('duration_seconds') or 0
        dur2 = week.get('duration_seconds_2') or 0
        prog1 = fmt_num(week.get('progress_1', 0))
        prog2 = fmt_num(week.get('progress_2', 0))

        # 1. T1 ÜST KUTU
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

    def _build_total_cell(student):
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

    chunk_size = 4
    pages = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
    total_pages = len(pages) if pages else 1

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
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
            row = [_build_student_cell(student)]
            for w_stat in student['weekly_breakdown']:
                row.append(_build_week_cell(w_stat))
            row.append(_build_total_cell(student))
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
        now_date = timezone.now().astimezone(ISTANBUL_TZ).strftime('%d.%m.%Y')
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
    return buffer.getvalue()


# =====================================================================
# 2. CHATBOT ANALİZİ RAPORU (SORU VE YANIT ANALİZ RAPORU)
# =====================================================================

def generate_chatbot_analytics_pdf(department):
    """
    Akademisyen panelindeki 'Chatbot Analizi' sekmesinde oluşturulan
    Chatbot Soru ve Yanıt Analiz Raporunu aynen A4 Yatay PDF formatında üretir.
    """
    font_reg, font_bld = _init_pdf_fonts()
    dept_name = dict(User.DEPARTMENT_CHOICES).get(department, department).upper()

    students = User.objects.filter(is_staff=False, is_teacher=False, department=department, category__iexact='d2').order_by('first_name', 'last_name')
    questions = StudentQuestion.objects.filter(student__in=students).select_related('student', 'weekly_content').order_by('-created_at')

    total_q = questions.count()
    active_users = questions.values('student').distinct().count()
    total_users = students.count()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=30
    )

    header_cell = ParagraphStyle('HC_Chat', fontName=font_bld, fontSize=8, leading=10, textColor=colors.white, alignment=1)
    cell_style = ParagraphStyle('C_Chat', fontName=font_reg, fontSize=7.5, leading=9.5, textColor=colors.HexColor('#1e293b'))
    cell_bold = ParagraphStyle('CB_Chat', fontName=font_bld, fontSize=7.5, leading=9.5, textColor=colors.HexColor('#0f172a'))

    story = []

    now_str = timezone.now().astimezone(ISTANBUL_TZ).strftime('%d.%m.%Y %H:%M')
    banner_data = [
        [
            Paragraph(f"<b>{dept_name} - CHATBOT SORU VE YANIT ANALİZ RAPORU</b>", ParagraphStyle('BT_Chat', fontName=font_bld, fontSize=11, leading=14, textColor=colors.white)),
            Paragraph(f"<b>Tarih:</b> {now_str}", ParagraphStyle('BS_Chat', fontName=font_reg, fontSize=8, leading=10, textColor=colors.white, alignment=2))
        ],
        [
            Paragraph(f"Toplam Soru: <b>{total_q}</b> &nbsp;|&nbsp; Aktif Kullanıcı: <b>{active_users} / {total_users}</b> &nbsp;|&nbsp; Kategori: <b>D2</b>", ParagraphStyle('BS2_Chat', fontName=font_reg, fontSize=8, leading=10, textColor=colors.HexColor('#fee2e2'))),
            ""
        ]
    ]
    banner_table = Table(banner_data, colWidths=[580, 221])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#ce1212')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('SPAN', (0, 1), (1, 1)),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 8))

    headers = [
        Paragraph("Sıra", header_cell),
        Paragraph("Öğrenci Adı Soyadı", header_cell),
        Paragraph("Hafta", header_cell),
        Paragraph("Tarih / Saat", header_cell),
        Paragraph("Öğrencinin Sorusu", header_cell),
        Paragraph("Chatbot Yanıtı", header_cell),
    ]
    rows = [headers]

    if total_q == 0:
        rows.append([
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("Bu bölüme ait henüz chatbot soru etkileşimi bulunmamaktadır.", cell_bold),
            Paragraph("-", cell_style),
        ])
    else:
        for idx, q in enumerate(questions):
            s_name = f"{q.student.first_name} {q.student.last_name}".strip().upper()
            w_str = f"{q.weekly_content.week_number}. Hafta" if q.weekly_content else "-"
            dt_str = q.created_at.astimezone(ISTANBUL_TZ).strftime("%d.%m.%Y %H:%M") if q.created_at else "-"

            rows.append([
                Paragraph(str(idx + 1), cell_style),
                Paragraph(f"<b>{s_name}</b>", cell_bold),
                Paragraph(w_str, cell_style),
                Paragraph(dt_str, cell_style),
                Paragraph(q.question_text, cell_style),
                Paragraph(q.response_text or "Henüz yanıt kaydedilmemiş.", cell_style),
            ])

    table = Table(
        rows,
        colWidths=[25, 120, 55, 75, 260, 266],
        repeatRows=1
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ce1212')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (3, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.append(table)
    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


# =====================================================================
# 3. ÖN DEĞERLENDİRME ANALİZİ RAPORU (ÖN TEST & TELAFİ RAPORU)
# =====================================================================

def generate_pretest_analytics_pdf(department):
    """
    Akademisyen panelindeki 'Haftalık Ön Değerlendirme Analitiği' sekmesinde oluşturulan
    Ön Değerlendirme & Telafi Raporunu aynen A4 Yatay PDF formatında üretir.
    """
    font_reg, font_bld = _init_pdf_fonts()
    dept_name = dict(User.DEPARTMENT_CHOICES).get(department, department).upper()

    students = User.objects.filter(is_staff=False, is_teacher=False, department=department, category__iexact='d2').order_by('first_name', 'last_name')
    weeks = list(WeeklyContent.objects.filter(week_number__gte=2).order_by('week_number'))
    week_ids = [w.id for w in weeks]

    pre_tests = list(PreEvaluationTest.objects.filter(weekly_content_id__in=week_ids))
    pre_test_ids = [pt.id for pt in pre_tests]

    student_ids = [s.id for s in students]
    attempts = list(PreEvaluationAttempt.objects.filter(student_id__in=student_ids, pre_test_id__in=pre_test_ids).select_related('pre_test__weekly_content'))
    att_map = {(a.student_id, a.pre_test.weekly_content_id): a for a in attempts}

    answers = list(PreEvaluationAnswer.objects.filter(attempt_id__in=[a.id for a in attempts]).select_related('question', 'selected_option'))
    answers_by_att = defaultdict(list)
    for ans in answers:
        answers_by_att[ans.attempt_id].append(ans)

    temp_unlocks = list(TemporaryWeekUnlock.objects.filter(student_id__in=student_ids).select_related('weekly_content'))
    unlocks_by_student = defaultdict(list)
    now = timezone.now()
    for tu in temp_unlocks:
        is_active = tu.expires_at > now
        hrs = max(0, int((tu.expires_at - now).total_seconds() // 3600)) if is_active else 0
        unlocks_by_student[tu.student_id].append({
            'week_number': tu.weekly_content.week_number,
            'is_active': is_active,
            'hours_remaining': hrs,
            'completion_percentage': round(tu.completion_percentage, 1),
            'duration_minutes': round(tu.total_duration_seconds / 60, 1),
        })

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=30
    )

    header_cell = ParagraphStyle('HC_Pre', fontName=font_bld, fontSize=8, leading=10, textColor=colors.white, alignment=1)
    cell_style = ParagraphStyle('C_Pre', fontName=font_reg, fontSize=7.5, leading=9.5, textColor=colors.HexColor('#1e293b'))
    cell_bold = ParagraphStyle('CB_Pre', fontName=font_bld, fontSize=7.5, leading=9.5, textColor=colors.HexColor('#0f172a'))

    story = []

    now_str = timezone.now().astimezone(ISTANBUL_TZ).strftime('%d.%m.%Y %H:%M')
    avg_score = round(sum(a.score for a in attempts) / len(attempts), 1) if attempts else 0.0
    active_rem_count = sum(1 for tu in temp_unlocks if tu.expires_at > now)

    banner_data = [
        [
            Paragraph(f"<b>{dept_name} - D2 HAFTALIK ÖN DEĞERLENDİRME & TELAFİ RAPORU</b>", ParagraphStyle('BT_Pre', fontName=font_bld, fontSize=11, leading=14, textColor=colors.white)),
            Paragraph(f"<b>Tarih:</b> {now_str}", ParagraphStyle('BS_Pre', fontName=font_reg, fontSize=8, leading=10, textColor=colors.white, alignment=2))
        ],
        [
            Paragraph(f"Toplam D2 Öğrenci: <b>{students.count()}</b> &nbsp;|&nbsp; Ort. Ön Test Başarısı: <b>%{avg_score}</b> &nbsp;|&nbsp; Aktif Telafi: <b>{active_rem_count}</b>", ParagraphStyle('BS2_Pre', fontName=font_reg, fontSize=8, leading=10, textColor=colors.HexColor('#e0e7ff'))),
            ""
        ]
    ]
    banner_table = Table(banner_data, colWidths=[580, 221])
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#312e81')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('SPAN', (0, 1), (1, 1)),
    ]))
    story.append(banner_table)
    story.append(Spacer(1, 8))

    headers = [
        Paragraph("#", header_cell),
        Paragraph("Öğrenci Adı Soyadı", header_cell),
        Paragraph("E-Posta", header_cell),
        Paragraph("Bölüm", header_cell),
        Paragraph("Telafi Kilitleri & İlerleme", header_cell),
        Paragraph("Haftalık Ön Test Sonuçları & Tetiklenen Haftalar", header_cell),
    ]
    rows = [headers]

    for idx, s in enumerate(students):
        s_unlocks = unlocks_by_student.get(s.id, [])
        if s_unlocks:
            rem_lines = []
            for u in s_unlocks:
                st_str = f"Aktif ({u['hours_remaining']}s kaldı)" if u['is_active'] else "Süre Doldu"
                rem_lines.append(f"• {u['week_number']}.H [{st_str}]: %{u['completion_percentage']} ({u['duration_minutes']} dk)")
            rem_text = "<br/>".join(rem_lines)
        else:
            rem_text = "Telafi Kilidi Yok"

        w_results = []
        for w in weeks:
            att = att_map.get((s.id, w.id))
            if not att:
                w_results.append(f"• {w.week_number}.H: Çözmedi")
            else:
                ans_list = answers_by_att.get(att.id, [])
                wrongs = [a for a in ans_list if not a.is_correct]
                if wrongs:
                    wrong_notes = ", ".join(f"W{a.question.target_week} telafi" for a in wrongs)
                    w_results.append(f"• {w.week_number}.H: %{att.score} ({att.correct_answers}D/{att.wrong_answers}Y) [Yanlış: {wrong_notes}]")
                else:
                    w_results.append(f"• {w.week_number}.H: %{att.score} ({att.correct_answers}D/{att.wrong_answers}Y) [Tam]")

        results_text = "<br/>".join(w_results) if w_results else "Kayıtlı ön test yok"

        rows.append([
            Paragraph(str(idx + 1), cell_style),
            Paragraph(f"<b>{s.first_name} {s.last_name}</b>", cell_bold),
            Paragraph(s.email, cell_style),
            Paragraph(dept_name, cell_style),
            Paragraph(rem_text, cell_style),
            Paragraph(results_text, cell_style),
        ])

    table = Table(
        rows,
        colWidths=[25, 125, 130, 95, 215, 211],
        repeatRows=1
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#312e81')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.append(table)
    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


# =====================================================================
# 4. KONU BAZLI EKSİKLİK ANALİZİ (D2 ÖĞRENCİLERİ)
# =====================================================================

def fetch_topic_deficiency_data(department, week_number=None):
    """
    Belirtilen bölümdeki Kategori D2 öğrencileri için haftalık sınav sorularındaki
    konu başlıklarına göre eksiklik analizi verilerini çeker ve hesaplar.
    """
    students = list(User.objects.filter(
        is_staff=False,
        is_teacher=False,
        department__iexact=department,
        category__iexact='d2'
    ).order_by('first_name', 'last_name'))
    student_ids = [s.id for s in students]

    weeks_qs = WeeklyContent.objects.all().order_by('week_number')
    if week_number is not None:
        weeks_qs = weeks_qs.filter(week_number=week_number)
    weeks = list(weeks_qs)
    week_ids = [w.id for w in weeks]

    quizzes = list(Quiz.objects.filter(material__parent_content_id__in=week_ids).select_related('material__parent_content'))
    quiz_ids = [q.id for q in quizzes]

    questions = list(QuizQuestion.objects.filter(quiz_id__in=quiz_ids).select_related('quiz__material__parent_content').order_by('order', 'id'))
    q_by_quiz = defaultdict(list)
    for q in questions:
        q_by_quiz[q.quiz_id].append(q)

    attempts = list(StudentQuizAttempt.objects.filter(
        quiz_id__in=quiz_ids,
        student_id__in=student_ids
    ).select_related('student', 'quiz'))

    # Her öğrenci için ilgili quizdeki öncelikli attempt (tercihen attempt_round=1)
    attempt_by_stu_quiz = {}
    for att in attempts:
        key = (att.student_id, att.quiz_id)
        if key not in attempt_by_stu_quiz or att.attempt_round == 1:
            attempt_by_stu_quiz[key] = att

    chosen_att_ids = [att.id for att in attempt_by_stu_quiz.values()]
    answers = list(StudentAnswer.objects.filter(
        attempt_id__in=chosen_att_ids
    ).select_related('question', 'attempt__student', 'selected_option'))
    
    answers_by_att_q = {}
    for ans in answers:
        answers_by_att_q[(ans.attempt_id, ans.question_id)] = ans

    result_weeks = []
    
    for w in weeks:
        w_quizzes = [q for q in quizzes if q.material.parent_content_id == w.id]
        if not w_quizzes:
            result_weeks.append({
                "week_number": w.week_number,
                "week_title": w.title,
                "has_quiz": False,
                "topics": [],
                "participating_students_count": 0,
                "total_d2_students_count": len(students),
                "student_breakdown": []
            })
            continue

        w_questions = []
        for qz in w_quizzes:
            w_questions.extend(q_by_quiz.get(qz.id, []))

        w_quiz_ids = {qz.id for qz in w_quizzes}
        participating_stu_ids = set()
        for att in attempt_by_stu_quiz.values():
            if att.quiz_id in w_quiz_ids:
                participating_stu_ids.add(att.student_id)
        
        part_count = len(participating_stu_ids)

        topics_dict = defaultdict(lambda: {
            'questions': [],
            'question_orders': [],
            'wrong_student_ids': set(),
            'total_answers_count': 0,
            'wrong_answers_count': 0
        })

        for q_idx, q in enumerate(w_questions):
            topic_name = q.topic.strip() if (q.topic and q.topic.strip()) else "Genel / Belirtilmemiş Konu"
            q_order_display = q.order + 1 if q.order is not None else q_idx + 1
            topics_dict[topic_name]['questions'].append(q)
            topics_dict[topic_name]['question_orders'].append(q_order_display)

            for stu_id in participating_stu_ids:
                att = attempt_by_stu_quiz.get((stu_id, q.quiz_id))
                if att:
                    ans = answers_by_att_q.get((att.id, q.id))
                    if ans:
                        topics_dict[topic_name]['total_answers_count'] += 1
                        if not ans.is_correct:
                            topics_dict[topic_name]['wrong_answers_count'] += 1
                            topics_dict[topic_name]['wrong_student_ids'].add(stu_id)

        total_q_count = len(w_questions)
        topic_stats = []
        for t_name, t_info in sorted(topics_dict.items(), key=lambda x: len(x[1]['wrong_student_ids']), reverse=True):
            wrong_stu_count = len(t_info['wrong_student_ids'])
            wrong_ans_count = t_info['wrong_answers_count']
            deficiency_rate = round((wrong_stu_count / part_count) * 100, 1) if part_count > 0 else 0.0
            success_rate = round(100.0 - deficiency_rate, 1) if part_count > 0 else 100.0
            
            if deficiency_rate >= 50.0:
                status_label = "CİDDİ EKSİKLİK"
                status_color = "#dc2626"
            elif deficiency_rate >= 25.0:
                status_label = "ORTA DÜZEY"
                status_color = "#ea580c"
            else:
                status_label = "DÜŞÜK DÜZEY"
                status_color = "#2563eb"

            topic_stats.append({
                "topic": t_name,
                "question_orders": sorted(t_info['question_orders']),
                "question_count": len(t_info['questions']),
                "wrong_student_count": wrong_stu_count,
                "wrong_answers_count": wrong_ans_count,
                "participating_count": part_count,
                "deficiency_percentage": deficiency_rate,
                "success_percentage": success_rate,
                "status_label": status_label,
                "status_color": status_color
            })

        stu_breakdown = []
        for stu in students:
            stu_atts = [attempt_by_stu_quiz.get((stu.id, qz.id)) for qz in w_quizzes if attempt_by_stu_quiz.get((stu.id, qz.id))]
            has_participated = len(stu_atts) > 0
            avg_score = round(sum(a.score for a in stu_atts) / len(stu_atts), 1) if has_participated else None
            
            wrong_topics_for_stu = defaultdict(list)
            if has_participated:
                for att in stu_atts:
                    for q in q_by_quiz.get(att.quiz_id, []):
                        ans = answers_by_att_q.get((att.id, q.id))
                        if ans and not ans.is_correct:
                            t_name = q.topic.strip() if (q.topic and q.topic.strip()) else "Genel / Belirtilmemiş Konu"
                            q_ord = q.order + 1 if q.order is not None else 1
                            wrong_topics_for_stu[t_name].append(q_ord)

            stu_breakdown.append({
                "student_id": stu.id,
                "email": stu.email,
                "full_name": f"{stu.first_name} {stu.last_name}".strip() or stu.username,
                "has_participated": has_participated,
                "score": avg_score,
                "wrong_topics": [
                    {"topic": tn, "wrong_questions": sorted(q_ords)}
                    for tn, q_ords in wrong_topics_for_stu.items()
                ],
                "wrong_topics_count": len(wrong_topics_for_stu)
            })

        specified_topic_count = len([t for t in topic_stats if t['topic'] != 'Genel / Belirtilmemiş Konu'])
        result_weeks.append({
            "week_number": w.week_number,
            "week_title": w.title,
            "has_quiz": True,
            "total_questions_count": total_q_count,
            "specified_topic_count": specified_topic_count if specified_topic_count > 0 else len(topic_stats),
            "topics": topic_stats,
            "participating_students_count": part_count,
            "total_d2_students_count": len(students),
            "student_breakdown": stu_breakdown
        })

    return {
        "department": department,
        "department_name": dict(User.DEPARTMENT_CHOICES).get(department, department),
        "total_d2_students": len(students),
        "weeks": result_weeks
    }


def generate_topic_deficiency_analytics_pdf(department, week_number=None):
    """
    Kategori D2 öğrencileri için haftalık sınav sorularındaki konu başlıklarına göre
    eksiklik analizi PDF raporunu üretir.
    Sadece kompakt, şık ve odaklı tek tablo formatını içerir.
    """
    font_reg, font_bld = _init_pdf_fonts()
    data = fetch_topic_deficiency_data(department, week_number=week_number)
    total_d2 = data.get('total_d2_students', 0)
    weeks = data.get('weeks', [])

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=30,
        rightMargin=30,
        topMargin=25,
        bottomMargin=25
    )

    now_str = timezone.now().astimezone(ISTANBUL_TZ).strftime('%d.%m.%Y %H:%M')

    # Temel Stiller
    style_date = ParagraphStyle(
        'RDate',
        fontName=font_reg,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#334155'),
        alignment=1
    )

    style_card_title = ParagraphStyle(
        'CTitle',
        fontName=font_bld,
        fontSize=13,
        leading=16,
        textColor=colors.white
    )

    style_stat_num = ParagraphStyle(
        'SNum',
        fontName=font_bld,
        fontSize=14,
        leading=16,
        textColor=colors.white,
        alignment=1
    )

    style_th = ParagraphStyle(
        'THCol',
        fontName=font_bld,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        alignment=1
    )

    style_td_center = ParagraphStyle(
        'TDCenter',
        fontName=font_bld,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1e293b'),
        alignment=1
    )

    style_td_center_reg = ParagraphStyle(
        'TDCenterReg',
        fontName=font_reg,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1e293b'),
        alignment=1
    )

    style_td_left = ParagraphStyle(
        'TDLeft',
        fontName=font_reg,
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#0f172a'),
        alignment=0
    )

    story = []

    if not weeks:
        story.append(Paragraph(f"Rapor Tarihi: {now_str}", style_date))
        story.append(Spacer(1, 15))
        story.append(Paragraph("Sistemde raporlanacak hafta veya değerlendirme testi bulunamadı.", style_td_center))
        doc.build(story)
        return buffer.getvalue()

    for w_idx, w_data in enumerate(weeks):
        if w_idx > 0:
            story.append(PageBreak())

        topics = w_data.get('topics', [])
        part_count = w_data.get('participating_students_count', 0)
        total_q_count = w_data.get('total_questions_count', sum(t.get('question_count', 0) for t in topics))
        total_topics_count = len(topics)
        specified_topic_count = w_data.get('specified_topic_count', total_topics_count)

        # 1. EN ÜSTTE TARİH (ORTALI)
        story.append(Paragraph(f"Rapor Tarihi: {now_str}", style_date))
        story.append(Spacer(1, 10))

        # 2. KOYU LACİVERT BAŞLIK KARTI
        card_content = [
            [
                Paragraph(
                    f"<b>Haftalık Değerlendirme</b><br/><font color='#cbd5e1' size='7.5'>Toplam Soru: {total_q_count} | Toplam Konu Başlığı: {specified_topic_count}</font>",
                    style_card_title
                ),
                Paragraph(
                    f"<b>{total_d2}</b><br/><font color='#a5b4fc' size='6.5'><b>D2 ÖĞRENCİ</b></font>",
                    style_stat_num
                ),
                Paragraph(
                    f"<b>{part_count}</b><br/><font color='#a5b4fc' size='6.5'><b>SINAVA GİREN</b></font>",
                    style_stat_num
                ),
                Paragraph(
                    f"<b>{total_topics_count}</b><br/><font color='#a5b4fc' size='6.5'><b>KONU SAYISI</b></font>",
                    style_stat_num
                ),
            ]
        ]
        card_table = Table(card_content, colWidths=[482, 100, 100, 100])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1a1a36')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (0, -1), 12),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 12),
        ]))
        story.append(card_table)
        story.append(Spacer(1, 10))

        if not topics:
            empty_table = Table([[Paragraph("Bu haftaya ait henüz değerlendirme testi veya soru tanımlanmamıştır.", style_td_center)]], colWidths=[782])
            empty_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('PADDING', (0, 0), (-1, -1), 15),
            ]))
            story.append(empty_table)
            continue

        # 3. KONU EKSİKLİK VE BAŞARI TABLOSU
        table_rows = [
            [
                Paragraph("<b>SIRA</b>", style_th),
                Paragraph("<b>KONU BAŞLIĞI / KAZANIM</b>", style_th),
                Paragraph("<b>SORU SAYISI</b>", style_th),
                Paragraph("<b>YANLIŞ YAPAN ÖĞRENCİ</b>", style_th),
                Paragraph("<b>TOPLAM YANLIŞ CEVAP</b>", style_th),
                Paragraph("<b>EKSİKLİK ORANI (%)</b>", style_th),
            ]
        ]

        for idx, t in enumerate(topics):
            s_color = t['status_color']
            s_label = t['status_label']

            topic_cell_html = (
                f"<b>{t['topic']}</b><br/>"
                f"<font color='{s_color}' size='6.8'><b>Durum: {s_label}</b></font>"
            )

            perc_cell_html = (
                f"<b><font color='{s_color}' size='8.5'>%{t['deficiency_percentage']}</font></b><br/>"
                f"<font color='#64748b' size='6.5'>{t['wrong_student_count']} / {part_count} Öğr.</font>"
            )

            table_rows.append([
                Paragraph(str(idx + 1), style_td_center),
                Paragraph(topic_cell_html, style_td_left),
                Paragraph(str(t['question_count']), style_td_center),
                Paragraph(f"{t['wrong_student_count']} Öğrenci", style_td_center_reg),
                Paragraph(str(t['wrong_answers_count']), style_td_center),
                Paragraph(perc_cell_html, style_td_center),
            ])

        main_table = Table(table_rows, colWidths=[42, 330, 75, 115, 105, 115], repeatRows=1)
        main_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a36')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
        ]))
        story.append(main_table)

    doc.build(story)
    return buffer.getvalue()


# =====================================================================
# MAİL GÖNDERİMİ VE 4 RAPORUN EKLENMESİ
# =====================================================================

def send_academic_report(department, week_number, trigger_type, trigger_date=None, force=False):
    """
    Belirtilen bölüm için akademisyene e-posta gönderir.
    Mail içeriğinde sadece resmi başlık ve bilgilendirme yer alır,
    panele ait 4 PDF raporu aynen ek olarak iliştirilir:
      1. Öğrenci Analizleri Raporu (14 Haftalık Genel Performans)
      2. Chatbot Analizi Raporu (Soru ve Yanıt Dökümü)
      3. Ön Değerlendirme Analizi Raporu (Ön Test & Telafi Sonuçları)
      4. Konu Eksiklik Analiz Raporu (Sınav Konu Başlıkları ve D2 Eksiklik Oranları)
    """
    if trigger_date is None:
        trigger_date = timezone.now().astimezone(ISTANBUL_TZ).date()

    teachers = User.objects.filter(is_teacher=True, is_active=True).filter(
        Q(department=department) | Q(department__isnull=True) | Q(department='')
    )

    if not teachers.exists():
        logger.warning(f"Rapor gönderilemedi: {department} bölümü için aktif akademisyen bulunamadı.")
        return {'status': 'NO_TEACHERS', 'sent_count': 0}

    dept_display = dict(User.DEPARTMENT_CHOICES).get(department, department)

    # 4 PDF RAPORUNU ÜRET
    logger.info(f"{dept_display} için 4 PDF raporu üretiliyor...")
    pdf_bulk = generate_student_analytics_bulk_pdf(department)
    pdf_chat = generate_chatbot_analytics_pdf(department)
    pdf_pretest = generate_pretest_analytics_pdf(department)
    pdf_topic = generate_topic_deficiency_analytics_pdf(department, week_number=week_number)

    fn_bulk = f"{department}_Ogrenci_Analizleri_Raporu.pdf"
    fn_chat = f"{department}_Chatbot_Analiz_Raporu.pdf"
    fn_pretest = f"{department}_On_Degerlendirme_Analiz_Raporu.pdf"
    fn_topic = f"{department}_Hafta_{week_number}_Konu_Eksiklik_Analiz_Raporu.pdf"

    subject = f"[LMS DİJİTAL] {dept_display} - Akademik Analiz Raporları (Öğrenci, Chatbot, Ön Değerlendirme, Konu Eksiklik)"

    sent_count = 0
    skipped_count = 0

    for teacher in teachers:
        recipient_email = teacher.email
        recipient_name = f"{teacher.first_name} {teacher.last_name}".strip() or teacher.username

        existing_log = AcademicReportEmailLog.objects.filter(
            department=department,
            week_number=week_number,
            recipient_email=recipient_email,
            trigger_date=trigger_date,
            status='SUCCESS'
        ).first()

        if existing_log and not force:
            logger.info(f"Rapor zaten gönderilmiş: {recipient_email} ({department}, Hafta {week_number})")
            skipped_count += 1
            continue

        log_entry = AcademicReportEmailLog.objects.create(
            department=department,
            week_number=week_number,
            trigger_type=trigger_type,
            trigger_date=trigger_date,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            pdf_filename=f"{fn_bulk}, {fn_chat}, {fn_pretest}, {fn_topic}",
            status='PENDING'
        )

        try:
            # Sade, kurumsal bilgilendirme metni (Ekstra tablo veya karmaşık içerik içermez)
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
            </head>
            <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b;">
              <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 14px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
                <div style="background: #1e3a8a; color: #ffffff; padding: 22px 25px; text-align: left;">
                  <h2 style="margin: 0; font-size: 16px; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase;">BİNGÖL ÜNİVERSİTESİ LMS DİJİTAL SINIF</h2>
                  <p style="margin: 4px 0 0 0; font-size: 12px; color: #c7d2fe;">Akademik Analiz ve İzleme Raporları</p>
                </div>
                <div style="padding: 25px; font-size: 13px; line-height: 1.6; text-align: left;">
                  <p>Sayın <b>{recipient_name}</b>,</p>
                  <p>
                    <b>{dept_display}</b> bölümüne ait <b>Kategori D2</b> grubu öğrencilerinin 
                    akademisyen panelinde yer alan güncel analiz raporları ekte bilgilerinize sunulmuştur.
                  </p>
                  
                  <div style="background: #f1f5f9; padding: 14px 18px; border-radius: 10px; margin: 18px 0; border-left: 4px solid #1e3a8a;">
                    <p style="margin: 0 0 8px 0; font-weight: 800; color: #1e3a8a; font-size: 12px; text-transform: uppercase;">
                      E-Posta Ekinde Yer Alan Raporlar (4 Adet PDF):
                    </p>
                    <p style="margin: 5px 0;">📎 <b>1. Öğrenci Analizleri Raporu:</b> 14 haftalık akademik performans, T1/T2 tamamlama yüzdeleri, çalışma süreleri ve sınav skorları.</p>
                    <p style="margin: 5px 0;">📎 <b>2. Chatbot Analiz Raporu:</b> Öğrencilerin yapay zeka chatbot ile olan soru-yanıt etkileşimleri ve haftalık dökümleri.</p>
                    <p style="margin: 5px 0;">📎 <b>3. Ön Değerlendirme Analiz Raporu:</b> Haftalık ön değerlendirme test sonuçları, tetiklenen telafi kilitleri ve telafi süreci ilerlemeleri.</p>
                    <p style="margin: 5px 0;">📎 <b>4. Konu Eksiklik Analiz Raporu:</b> {week_number}. Hafta sınav sorularına ait konu başlıkları, D2 öğrencilerinin konu bazlı eksiklik sayıları ve yüzdelik oranları.</p>
                  </div>

                  <p style="margin-top: 15px; color: #475569;">
                    Raporlara ait tüm ayrıntılı veriler ve istatistikler ekli PDF belgelerinde yer almaktadır.
                  </p>
                </div>
                <div style="background: #f8fafc; padding: 14px 25px; border-top: 1px solid #e2e8f0; font-size: 11px; color: #64748b; text-align: center;">
                  Bu e-posta LMS Dijital Sistemi tarafından otomatik olarak iletilmiştir.
                </div>
              </div>
            </body>
            </html>
            """

            msg = EmailMessage(
                subject=subject,
                body=html_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient_email]
            )
            msg.content_subtype = "html"

            # 4 PDF DOSYASINI DA EKE İLİŞTİR
            msg.attach(fn_bulk, pdf_bulk, "application/pdf")
            msg.attach(fn_chat, pdf_chat, "application/pdf")
            msg.attach(fn_pretest, pdf_pretest, "application/pdf")
            msg.attach(fn_topic, pdf_topic, "application/pdf")

            msg.send(fail_silently=False)

            log_entry.status = 'SUCCESS'
            log_entry.save(update_fields=['status'])
            sent_count += 1
            logger.info(f"4 Analiz raporu maili başarıyla gönderildi: {recipient_email} ({department})")

        except Exception as e:
            logger.error(f"Akademik rapor mail gönderim hatası ({recipient_email}): {e}", exc_info=True)
            log_entry.status = 'FAILED'
            log_entry.error_message = str(e)
            log_entry.save(update_fields=['status', 'error_message'])

    return {
        'status': 'DONE',
        'sent_count': sent_count,
        'skipped_count': skipped_count,
        'department': department,
        'week_number': week_number
    }


# --- SİSTEM CANLI ZAMANLAYICI KONTROLÜ ---

def check_and_send_due_academic_reports(force=False):
    """
    Sistem tarafından canlı ve sürekli olarak çağrılır.
    Tüm bölümleri ve haftaları tarar, vaktinde tetikler.
    """
    now = timezone.now().astimezone(ISTANBUL_TZ)
    departments = [choice[0] for choice in User.DEPARTMENT_CHOICES]
    weeks = list(WeeklyContent.objects.all().order_by('week_number'))

    results = []

    for dept in departments:
        for week in weeks:
            trigger_dt, target_date, trigger_type, reason = get_trigger_datetime_for_week(week, dept)
            if trigger_dt is None:
                continue

            is_due = False
            if force:
                is_due = True
            else:
                if now >= trigger_dt:
                    diff = now - trigger_dt
                    if diff <= timedelta(hours=24):
                        is_due = True

            if is_due:
                res = send_academic_report(
                    department=dept,
                    week_number=week.week_number,
                    trigger_type=trigger_type,
                    trigger_date=target_date,
                    force=force
                )
                results.append({
                    'department': dept,
                    'week_number': week.week_number,
                    'trigger_type': trigger_type,
                    'reason': reason,
                    'result': res
                })

    return results
