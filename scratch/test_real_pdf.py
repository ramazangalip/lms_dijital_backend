import os
import sys
from io import BytesIO

# Setup django
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
from reportlab.pdfgen import canvas

User = get_user_model()

# Register Arial
pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
font_reg = 'Arial'
font_bld = 'Arial-Bold'

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

data = fetch_bulk_data('turkdiliveedebiyati')
print(f"Fetched {len(data)} students for turkdiliveedebiyati")
for s in data[:2]:
    print("Student:", s['full_name'], s['email'])
    w4 = s['weekly_breakdown'][3]
    print(f"  W4: prog1={w4['progress_1']} dur1={w4['duration_seconds']} score1={w4['score_1']} r2={w4['is_round_2_started']} mats={len(w4['material_details'])}")
