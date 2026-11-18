import datetime
from django.utils import timezone
from contents.models import (
    Badge, 
    StudentBadge, 
    WeeklyContent, 
    StudentProgress, 
    CompletedMaterial, 
    StudentQuizAttempt
)
from users.models import User

def check_and_award_badges(user):
    """
    Öğrencinin sistemdeki başarılarını analiz eder ve hak ettiği rozetleri otomatik tanımlar.
    """
    all_badges = Badge.objects.all()
    
    # 1. İlk Materyal Tamamlama Rozeti
    first_mat_badge = all_badges.filter(badge_type__icontains="İlk Materyal").first()
    if first_mat_badge:
        has_completed_any = CompletedMaterial.objects.filter(student=user).exists()
        if has_completed_any:
            StudentBadge.objects.get_or_create(student=user, badge=first_mat_badge)

    # 2. 2 Hafta Üst Üste Başarı Rozeti
    streak_badge = all_badges.filter(badge_type__icontains="2 Hafta Üst Üste").first()
    if streak_badge:
        # Öğrencinin haftalık quiz skorlarını incele
        attempts = StudentQuizAttempt.objects.filter(student=user).select_related('quiz', 'quiz__material', 'quiz__material__parent_content').order_by('completed_at')
        
        # Her hafta için en yüksek skoru tespit et
        week_scores = {}
        for att in attempts:
            parent = getattr(att.quiz.material, 'parent_content', None)
            if parent:
                w_num = parent.week_number
                week_scores[w_num] = max(week_scores.get(w_num, 0), att.score)
                
        # Art arda gelen iki hafta skoru 100 mü kontrol et
        sorted_weeks = sorted(week_scores.keys())
        has_streak = False
        for i in range(len(sorted_weeks) - 1):
            w1 = sorted_weeks[i]
            w2 = sorted_weeks[i+1]
            if w2 == w1 + 1 and week_scores[w1] == 100 and week_scores[w2] == 100:
                has_streak = True
                break
                
        if has_streak:
            StudentBadge.objects.get_or_create(student=user, badge=streak_badge)


def get_student_development_data(user):
    """
    Bireysel Gelişim Paneli için gerekli tüm analiz ve metrikleri hazırlar.
    """
    # Otomatik rozetleri kontrol et ve ver
    check_and_award_badges(user)
    
    # Bölüm eşleme
    dept_map = dict(User.DEPARTMENT_CHOICES)
    dept_key = user.department or ''
    dept_display = dept_map.get(dept_key, dept_key.upper() if dept_key else "BÖLÜM BELİRTİLMEMİŞ")

    # Haftalık içerikler ve ilerleme
    weeks = list(WeeklyContent.objects.all().order_by('week_number'))
    progress_qs = StudentProgress.objects.filter(student=user).select_related('weekly_content')
    progress_map = {p.weekly_content_id: p for p in progress_qs}

    # Quiz denemeleri
    attempts_qs = StudentQuizAttempt.objects.filter(student=user).select_related(
        'quiz', 'quiz__material', 'quiz__material__parent_content'
    ).order_by('-completed_at')
    
    latest_attempt = attempts_qs.first()
    latest_score = latest_attempt.score if latest_attempt else 0

    weekly_progress_list = []
    weekly_mastery_list = []
    total_progress_sum = 0

    # Her hafta için quiz skoru haritası
    week_quiz_scores = {}
    for att in attempts_qs:
        parent = getattr(att.quiz.material, 'parent_content', None)
        if parent:
            w_id = parent.id
            if w_id not in week_quiz_scores:
                week_quiz_scores[w_id] = att.score
            else:
                week_quiz_scores[w_id] = max(week_quiz_scores[w_id], att.score)

    for w in weeks:
        prog = progress_map.get(w.id)
        prog_pct = round(prog.completion_percentage) if prog else 0
        is_completed = prog.is_completed if prog else False
        total_progress_sum += prog_pct

        weekly_progress_list.append({
            "week_id": w.id,
            "week_number": w.week_number,
            "title": w.title,
            "progress_percentage": prog_pct,
            "is_completed": is_completed
        })

        # Ustalık Düzeyi (Varsa quiz skoru, yoksa materyal ilerleme yüzdesi)
        quiz_score = week_quiz_scores.get(w.id)
        if quiz_score is not None:
            mastery_pct = quiz_score
        else:
            mastery_pct = prog_pct

        if mastery_pct >= 100:
            status = "USTALIK SAĞLANDI"
            status_type = "mastered"
        elif mastery_pct > 0:
            status = "DEVAM EDİYOR"
            status_type = "in_progress"
        else:
            status = "BAŞLANMADI"
            status_type = "not_started"

        weekly_mastery_list.append({
            "week_id": w.id,
            "week_number": w.week_number,
            "title": w.title,
            "mastery_percentage": mastery_pct,
            "status": status,
            "status_type": status_type
        })

    # Genel ilerleme yüzdesi
    total_weeks = len(weeks)
    overall_progress = round(total_progress_sum / total_weeks) if total_weeks > 0 else 0

    # Geri bildirim mesajı
    if overall_progress >= 50:
        feedback_message = "Harika gelişim! Öğrenme hedeflerinin yarısından fazlasını tamamladın. İstikrarını sürdür!"
    elif overall_progress >= 20:
        feedback_message = "İyi bir başlangıç yaptın! Haftalık içerikleri ve değerlendirme testlerini tamamlayarak seviyeni yükseltmeye devam et."
    else:
        feedback_message = "Öğrenme yolculuğuna adım attın! Haftalık ders materyallerini takip ederek bireysel başarını hızla artırabilirsin."

    # Rozetler
    all_badges = list(Badge.objects.all().order_by('order', 'id'))
    earned_qs = StudentBadge.objects.filter(student=user).select_related('badge')
    earned_map = {eb.badge_id: eb for eb in earned_qs}

    badges_data = []
    for b in all_badges:
        eb = earned_map.get(b.id)
        is_earned = eb is not None
        earned_date_str = eb.earned_at.strftime('%d.%m.%Y') if eb else None

        badges_data.append({
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "icon_name": b.icon_name,
            "color": b.color,
            "badge_type": b.badge_type,
            "requirement_text": b.requirement_text,
            "order": b.order,
            "is_earned": is_earned,
            "earned_at": earned_date_str
        })

    return {
        "student_info": {
            "id": user.id,
            "full_name": user.get_full_name() or user.username,
            "email": user.email,
            "department": dept_key,
            "department_display": dept_display,
            "category": user.category
        },
        "summary_metrics": {
            "overall_progress": overall_progress,
            "latest_score": latest_score,
            "badges_earned_count": len(earned_qs),
            "total_badges_count": len(all_badges)
        },
        "weekly_progress_list": weekly_progress_list,
        "weekly_mastery_list": weekly_mastery_list,
        "feedback_message": feedback_message,
        "badges": badges_data
    }
