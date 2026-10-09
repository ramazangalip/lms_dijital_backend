from rest_framework import serializers
from .models import *
from django.db.models import Sum
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

# --- ALT MODELLER ---

class QuizOptionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True) 
    class Meta:
        model = QuizOption
        fields = ['id', 'option_text', 'is_correct']

class QuizQuestionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    options = QuizOptionSerializer(many=True)
    class Meta:
        model = QuizQuestion
        fields = ['id', 'question_text', 'order', 'options','explanation']

class QuizSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True) 
    questions = QuizQuestionSerializer(many=True)
    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'questions']

class MaterialSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False, allow_null=True) 
    quiz = QuizSerializer(required=False, allow_null=True)
    embed_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    duration_seconds = serializers.IntegerField(required=False, default=120, allow_null=True)
    
    class Meta:
        model = Material
        fields = ['id', 'content_type', 'embed_url', 'title', 'point_value', 'duration_seconds', 'quiz']

class FlashcardSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False, allow_null=True)
    class Meta:
        model = Flashcard
        fields = ['id', 'question', 'answer', 'order']

class WeeklyContentDepartmentScheduleSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False, allow_null=True)
    department_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WeeklyContentDepartmentSchedule
        fields = ['id', 'department', 'department_name', 'release_date', 'deactivation_date']

    def get_department_name(self, obj):
        dept_dict = dict(User.DEPARTMENT_CHOICES)
        return dept_dict.get(obj.department, obj.department)

# --- ANA SERIALIZER ---

class WeeklyContentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    materials = MaterialSerializer(many=True, required=False)
    flashcards = FlashcardSerializer(many=True, required=False)
    department_schedules = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()
    current_attempt_round = serializers.SerializerMethodField()
    is_intro_watched = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    lock_reason = serializers.SerializerMethodField()
    week_number = serializers.IntegerField(validators=[])

    class Meta:
        model = WeeklyContent
        fields = [
            'id', 'week_number', 'title', 'description', 
            'intro_title', 'intro_video_url', 'intro_description',
            'release_date', 'deactivation_date', 'department_schedules',
            'is_locked', 'lock_reason',
            'is_intro_watched', 'materials', 'flashcards', 'progress', 'is_completed', 'current_attempt_round'
        ]

    def get_department_schedules(self, obj):
        existing_schedules = {s.department: s for s in obj.department_schedules.all()}
        dept_choices = list(User.DEPARTMENT_CHOICES)
        
        # Ekstra dinamik bölümler varsa onları da listeye ekle
        for s_dept in existing_schedules.keys():
            if not any(k == s_dept for k, _ in dept_choices):
                dept_choices.append((s_dept, s_dept.replace('_', ' ').title()))
                
        result = []
        for key, name in dept_choices:
            sched = existing_schedules.get(key)
            result.append({
                'department': key,
                'department_name': name,
                'release_date': sched.release_date.isoformat() if (sched and sched.release_date) else None,
                'deactivation_date': sched.deactivation_date.isoformat() if (sched and sched.deactivation_date) else None
            })
        return result

    def _get_context_data(self):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None, False, {}, False, {}

        is_teacher = getattr(request.user, 'is_teacher', False) or request.user.is_staff
        
        if not hasattr(self, '_cached_user_id') or self._cached_user_id != request.user.id:
            if is_teacher:
                intro_watched = True
                progress_by_content = {}
                progress_by_week = {}
            else:
                intro_watched = IntroVideoCompletion.objects.filter(student=request.user, is_watched=True).exists()
                progresses = list(StudentProgress.objects.filter(student=request.user).select_related('weekly_content'))
                progress_by_content = {p.weekly_content_id: p for p in progresses}
                progress_by_week = {p.weekly_content.week_number: p for p in progresses if p.weekly_content}
                
            self._cached_user_id = request.user.id
            self._cached_is_teacher = is_teacher
            self._cached_intro_watched = intro_watched
            self._cached_progress_by_content = progress_by_content
            self._cached_progress_by_week = progress_by_week
            
        return request.user, self._cached_is_teacher, self._cached_progress_by_content, self._cached_intro_watched, self._cached_progress_by_week

    def _get_effective_dates(self, obj, user):
        """Kullanıcının bölümüne göre geçerli açılış ve pasif etme tarihlerini belirler."""
        rel_date = obj.release_date
        deact_date = obj.deactivation_date

        if user and getattr(user, 'department', None):
            # Prefetched veya doğrudan ilişki üzerinden kontrol
            sched = None
            if hasattr(obj, '_prefetched_objects_cache') and 'department_schedules' in obj._prefetched_objects_cache:
                for s in obj.department_schedules.all():
                    if s.department == user.department:
                        sched = s
                        break
            else:
                sched = obj.department_schedules.filter(department=user.department).first()

            if sched:
                if sched.release_date is not None:
                    rel_date = sched.release_date
                if sched.deactivation_date is not None:
                    deact_date = sched.deactivation_date

        return rel_date, deact_date

    def get_is_locked(self, obj):
        """Zaman (Bölüm bazlı açılış/kapanış) ve Sıralı İlerleme kontrolü yaparak haftanın kilitli olup olmadığını belirler."""
        user, is_teacher, progress_by_content, intro_watched, progress_by_week = self._get_context_data()
        if not user:
            return True
        if is_teacher:
            return False

        now = timezone.now()
        rel_date, deact_date = self._get_effective_dates(obj, user)

        # 1. Açılış tarihi henüz gelmediyse kilitli
        if rel_date and now < rel_date:
            return True

        # 2. Pasif etme tarihi geçtiyse kilitli
        if deact_date and now > deact_date:
            return True

        # 3. Sıralı ilerleme kontrolü
        if obj.week_number > 1:
            prev_progress = progress_by_week.get(obj.week_number - 1)
            if not prev_progress:
                prev_week = WeeklyContent.objects.filter(week_number=obj.week_number - 1).first()
                if prev_week:
                    prev_progress = progress_by_content.get(prev_week.id)

            if not prev_progress or not prev_progress.is_completed:
                return True
        
        return False

    def get_lock_reason(self, obj):
        """Kilit bildirimi gösterilmez."""
        return None

    def get_is_intro_watched(self, obj):
        user, is_teacher, progress_by_content, intro_watched, progress_by_week = self._get_context_data()
        if not user:
            return False
        return intro_watched

    def get_progress(self, obj):
        user, is_teacher, progress_by_content, intro_watched, progress_by_week = self._get_context_data()
        if not user:
            return 0.0
        prog = progress_by_content.get(obj.id)
        return float(prog.completion_percentage) if prog else 0.0

    def get_is_completed(self, obj):
        user, is_teacher, progress_by_content, intro_watched, progress_by_week = self._get_context_data()
        if not user:
            return False
        prog = progress_by_content.get(obj.id)
        return prog.is_completed if prog else False

    def get_current_attempt_round(self, obj):
        user, is_teacher, progress_by_content, intro_watched, progress_by_week = self._get_context_data()
        if not user:
            return 1
        prog = progress_by_content.get(obj.id)
        return prog.current_attempt_round if prog else 1

    def create(self, validated_data):
        mats_data = validated_data.pop('materials', [])
        cards_data = validated_data.pop('flashcards', [])
        w_num = validated_data.get('week_number')
        
        i_title = validated_data.get('intro_title', 'Genel Tanıtım')
        i_url = validated_data.get('intro_video_url', '')
        i_desc = validated_data.get('intro_description', '') # YENİ ALAN ALINDI
        r_date = validated_data.get('release_date', None)
        d_date = validated_data.get('deactivation_date', None)

        content, _ = WeeklyContent.objects.update_or_create(
            week_number=w_num,
            defaults={
                'title': validated_data.get('title'),
                'description': validated_data.get('description'),
                'intro_title': i_title,
                'intro_video_url': i_url,
                'intro_description': i_desc,
                'release_date': r_date,
                'deactivation_date': d_date,
            }
        )

        # Hafta 1 ise intro bilgilerini ana kilit olarak güncelle
        if w_num == 1:
            content.intro_title = i_title
            content.intro_video_url = i_url
            content.intro_description = i_desc
            content.save()

        # Bölüm bazlı tarih ayarlarını kaydet
        raw_schedules = self.initial_data.get('department_schedules') or []
        for s_item in raw_schedules:
            dept = s_item.get('department')
            if dept:
                sched_rel = s_item.get('release_date') or None
                sched_deact = s_item.get('deactivation_date') or None
                WeeklyContentDepartmentSchedule.objects.update_or_create(
                    weekly_content=content,
                    department=dept,
                    defaults={
                        'release_date': sched_rel,
                        'deactivation_date': sched_deact
                    }
                )

        raw_mats = self.initial_data.get('materials', [])
        existing_materials = list(content.materials.all())
        keep_mat_ids = []

        for idx, m_item in enumerate(mats_data):
            q_data = m_item.pop('quiz', None)
            raw_item = raw_mats[idx] if idx < len(raw_mats) else {}
            m_id = m_item.get('id') or raw_item.get('id')

            mat_obj = None
            if m_id:
                mat_obj = next((m for m in existing_materials if str(m.id) == str(m_id)), None)
                if not mat_obj and Material.objects.filter(id=m_id, parent_content=content).exists():
                    mat_obj = Material.objects.get(id=m_id, parent_content=content)
            
            # Eğer ID gönderilmemişse, aynı haftadaki aynı başlık ve tipe sahip materyali koru
            if not mat_obj:
                mat_obj = next((m for m in existing_materials if m.title == m_item.get('title') and m.content_type == m_item.get('content_type') and m.id not in keep_mat_ids), None)

            if mat_obj:
                mat_obj.title = m_item.get('title', mat_obj.title)
                mat_obj.content_type = m_item.get('content_type', mat_obj.content_type)
                mat_obj.embed_url = m_item.get('embed_url', mat_obj.embed_url)
                if 'point_value' in m_item and m_item['point_value'] is not None:
                    mat_obj.point_value = m_item['point_value']
                if 'duration_seconds' in m_item and m_item['duration_seconds'] is not None:
                    mat_obj.duration_seconds = m_item['duration_seconds']
                mat_obj.save()
            else:
                mat_obj = Material.objects.create(parent_content=content, **m_item)
            
            keep_mat_ids.append(mat_obj.id)

            if mat_obj.content_type == 'form' and q_data:
                Quiz.objects.filter(material=mat_obj).delete()
                qs_list = q_data.pop('questions', [])
                quiz_instance = Quiz.objects.create(
                    material=mat_obj, 
                    title=q_data.get('title', ''), 
                    description=q_data.get('description', '')
                )
                for q_idx, q_val in enumerate(qs_list):
                    opts_list = q_val.pop('options', [])
                    question_instance = QuizQuestion.objects.create(
                        quiz=quiz_instance, 
                        question_text=q_val.get('question_text', ''), 
                        order=q_idx
                    )
                    for o_val in opts_list:
                        QuizOption.objects.create(question=question_instance, **o_val)

        raw_cards = self.initial_data.get('flashcards', [])
        existing_cards = list(content.flashcards.all())
        keep_card_ids = []

        for idx, c_item in enumerate(cards_data):
            raw_c_item = raw_cards[idx] if idx < len(raw_cards) else {}
            c_id = c_item.get('id') or raw_c_item.get('id')

            card_obj = None
            if c_id:
                card_obj = next((c for c in existing_cards if str(c.id) == str(c_id)), None)

            if not card_obj:
                card_obj = next((c for c in existing_cards if c.question == c_item.get('question') and c.id not in keep_card_ids), None)

            if card_obj:
                card_obj.question = c_item.get('question', card_obj.question)
                card_obj.answer = c_item.get('answer', card_obj.answer)
                card_obj.order = idx
                card_obj.save()
            else:
                card_obj = Flashcard.objects.create(
                    weekly_content=content, 
                    question=c_item.get('question'), 
                    answer=c_item.get('answer'), 
                    order=idx
                )
            keep_card_ids.append(card_obj.id)

        content.materials.exclude(id__in=keep_mat_ids).delete()
        content.flashcards.exclude(id__in=keep_card_ids).delete()

        return content
    


# --- DİĞER SERIALIZERLAR ---

class IntroCompleteSerializer(serializers.Serializer):
    weekly_content_id = serializers.IntegerField(required=False)
class ActivityTrackSerializer(serializers.Serializer):
    weekly_content_id = serializers.CharField() 
    seconds = serializers.IntegerField(default=30)

class StudentAnalyticsSerializer(serializers.ModelSerializer):
    total_time_spent = serializers.SerializerMethodField()
    overall_progress = serializers.SerializerMethodField()
    weekly_breakdown = serializers.SerializerMethodField()
    # Bölümün ismini (display name) çekmek için choice metodunu kullanıyoruz
    department_name = serializers.CharField(source='get_department_display', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'email', 
            'department', 'department_name', 'total_points', 
            'total_time_spent', 'overall_progress', 'weekly_breakdown'
        ]

    def _get_precomputed_data(self, obj):
        if not hasattr(self, '_cached_analytics_student_id') or self._cached_analytics_student_id != obj.id:
            from collections import defaultdict

            weeks = list(WeeklyContent.objects.all().order_by('week_number'))
            all_materials = list(Material.objects.all().select_related('parent_content'))
            total_materials_count = len(all_materials)

            materials_by_week = defaultdict(list)
            for m in all_materials:
                materials_by_week[m.parent_content_id].append(m)

            # Student progress
            progress_list = list(StudentProgress.objects.filter(student=obj))
            progress_by_week = {p.weekly_content_id: p for p in progress_list}

            # Completed materials
            completed_materials = list(CompletedMaterial.objects.filter(student=obj).values('material_id', 'attempt_round'))
            completed_set = {(cm['material_id'], cm['attempt_round']) for cm in completed_materials}

            # Overall progress calculation
            current_completed_count = 0
            for prog in progress_list:
                for m in materials_by_week.get(prog.weekly_content_id, []):
                    if (m.id, prog.current_attempt_round) in completed_set:
                        current_completed_count += 1
            
            overall_progress = 0.0
            if total_materials_count > 0:
                overall_progress = round(min((current_completed_count / total_materials_count) * 100, 100), 2)

            # Time trackings
            trackings = list(TimeTracking.objects.filter(student=obj).values('weekly_content_id', 'material_id', 'attempt_round', 'duration_seconds'))
            total_seconds = sum(t['duration_seconds'] for t in trackings)
            
            time_by_week_round = defaultdict(int) # (week_id, attempt_round) -> sec
            time_by_material = defaultdict(int) # material_id -> sec
            for t in trackings:
                w_id = t['weekly_content_id']
                m_id = t['material_id']
                ar = t['attempt_round']
                dur = t['duration_seconds']
                time_by_week_round[(w_id, ar)] += dur
                if m_id:
                    time_by_material[m_id] += dur

            # Quiz Attempts
            attempts = list(
                StudentQuizAttempt.objects.filter(student=obj)
                .select_related('quiz__material')
                .order_by('completed_at')
            )
            quiz_by_week_round = {} # (week_id, round) -> attempt
            latest_attempt_by_week = {} # week_id -> attempt
            for att in attempts:
                if att.quiz and att.quiz.material and att.quiz.material.parent_content_id:
                    w_id = att.quiz.material.parent_content_id
                    quiz_by_week_round[(w_id, att.attempt_round)] = att
                    latest_attempt_by_week[w_id] = att

            # AI Questions
            questions_qs = list(StudentQuestion.objects.filter(student=obj).values('weekly_content_id', 'question_text'))
            questions_by_week = defaultdict(list)
            for q in questions_qs:
                questions_by_week[q['weekly_content_id']].append(q['question_text'])

            # Quiz Results for latest attempts
            quiz_results_by_week = defaultdict(list)
            last_attempt_ids = [att.id for att in latest_attempt_by_week.values()]
            if last_attempt_ids:
                answers = list(
                    StudentAnswer.objects.filter(attempt_id__in=last_attempt_ids)
                    .select_related('question', 'selected_option', 'attempt__quiz__material')
                    .order_by('id')
                )
                
                # Fetch correct options for all questions involved
                question_ids = list({ans.question_id for ans in answers})
                correct_options_map = {
                    opt.question_id: opt.option_text 
                    for opt in QuizOption.objects.filter(question_id__in=question_ids, is_correct=True)
                }

                for ans in answers:
                    w_id = ans.attempt.quiz.material.parent_content_id
                    quiz_results_by_week[w_id].append({
                        "question_text": ans.question.question_text if ans.question else "",
                        "selected_option": ans.selected_option.option_text if ans.selected_option else "",
                        "correct_option": correct_options_map.get(ans.question_id, "Belirtilmemiş"),
                        "is_correct": ans.is_correct
                    })

            # Build breakdown
            breakdown = []
            for week in weeks:
                total_sec_1 = time_by_week_round.get((week.id, 1), 0)
                total_sec_2 = time_by_week_round.get((week.id, 2), 0)
                
                quiz_1 = quiz_by_week_round.get((week.id, 1))
                quiz_2 = quiz_by_week_round.get((week.id, 2))
                prog_obj = progress_by_week.get(week.id)
                current_round = prog_obj.current_attempt_round if prog_obj else 1

                w_mats = materials_by_week.get(week.id, [])
                total_w_mats = len(w_mats)
                w_mat_ids = {m.id for m in w_mats}
                
                done_count_1 = len([cm for cm in completed_materials if cm['material_id'] in w_mat_ids and cm['attempt_round'] == 1])
                prog_1 = round((done_count_1 / total_w_mats) * 100) if total_w_mats > 0 else 0

                done_count_2 = len([cm for cm in completed_materials if cm['material_id'] in w_mat_ids and cm['attempt_round'] == 2])
                prog_2 = round((done_count_2 / total_w_mats) * 100) if total_w_mats > 0 else 0

                material_details = []
                for m in w_mats:
                    material_details.append({
                        "title": m.title,
                        "content_type": m.content_type,
                        "duration_seconds": time_by_material.get(m.id, 0)
                    })

                breakdown.append({
                    "week_number": week.week_number,
                    "progress": prog_1,
                    "progress_1": prog_1,
                    "progress_2": prog_2,
                    "current_round": current_round,
                    "duration": total_sec_1 + total_sec_2,
                    "duration_seconds": total_sec_1 + total_sec_2,
                    "material_details": material_details,
                    "questions": questions_by_week.get(week.id, []),
                    "quiz_results": quiz_results_by_week.get(week.id, []),
                    
                    # Tur 1 Detayları
                    "duration_1": total_sec_1,
                    "score_1": quiz_1.score if quiz_1 else 0,
                    "predicted_1": quiz_1.predicted_score if quiz_1 else 0,
                    "diff_1": quiz_1.score_difference if quiz_1 else 0,
                    "correct_1": quiz_1.correct_answers if quiz_1 else 0,
                    "wrong_1": quiz_1.wrong_answers if quiz_1 else 0,

                    # Tur 2 Detayları
                    "duration_2": total_sec_2,
                    "score_2": quiz_2.score if quiz_2 else 0,
                    "predicted_2": quiz_2.predicted_score if quiz_2 else 0,
                    "diff_2": quiz_2.score_difference if quiz_2 else 0,
                    "correct_2": quiz_2.correct_answers if quiz_2 else 0,
                    "wrong_2": quiz_2.wrong_answers if quiz_2 else 0,
                })

            self._cached_analytics_student_id = obj.id
            self._cached_total_time_spent = f"{total_seconds // 3600} saat {(total_seconds % 3600) // 60} dakika"
            self._cached_overall_progress = overall_progress
            self._cached_weekly_breakdown = breakdown

    def get_total_time_spent(self, obj):
        self._get_precomputed_data(obj)
        return self._cached_total_time_spent

    def get_overall_progress(self, obj):
        self._get_precomputed_data(obj)
        return self._cached_overall_progress

    def get_weekly_breakdown(self, obj):
        self._get_precomputed_data(obj)
        return self._cached_weekly_breakdown

class CompleteMaterialSerializer(serializers.Serializer):
    material_id = serializers.CharField()

class StudentProgressSerializer(serializers.ModelSerializer):
    weekly_content = serializers.CharField(source='weekly_content.id')
    week_number = serializers.ReadOnlyField(source='weekly_content.week_number')
    week_title = serializers.ReadOnlyField(source='weekly_content.title')
    
    class Meta:
        model = StudentProgress
        fields = ['id', 'weekly_content', 'week_number', 'week_title', 'is_completed', 'completion_percentage', 'current_attempt_round', 'last_accessed']

class AIChatSerializer(serializers.Serializer):
    message = serializers.CharField(required=True, min_length=1)

class QuizAIAnalysisSerializer(serializers.Serializer):
    attempt_id = serializers.CharField(read_only=True) 
    ai_feedback = serializers.CharField()
    score = serializers.IntegerField()
    correct_answers = serializers.IntegerField()
    wrong_answers = serializers.IntegerField()



class BulkWeeklyStatSerializer(serializers.Serializer):
    week = serializers.IntegerField()
    progress = serializers.FloatField()
    
    # Tur 1
    duration_seconds = serializers.IntegerField()
    correct = serializers.IntegerField()
    wrong = serializers.IntegerField()
    score_1 = serializers.IntegerField(required=False)
    predicted_1 = serializers.IntegerField(required=False)
    diff_1 = serializers.IntegerField(required=False)
    
    # Tur 2
    duration_seconds_2 = serializers.IntegerField()
    correct_2 = serializers.IntegerField()
    wrong_2 = serializers.IntegerField()
    score_2 = serializers.IntegerField(required=False)
    predicted_2 = serializers.IntegerField(required=False)
    diff_2 = serializers.IntegerField(required=False)
    
    has_quiz = serializers.BooleanField()
    is_round_2_started = serializers.BooleanField()

class BulkAcademicReportSerializer(serializers.Serializer):
    """PDF Raporu için tüm öğrenci verisini paketler"""
    id = serializers.CharField() 
    full_name = serializers.CharField()
    email = serializers.EmailField()
    department = serializers.CharField() 
    total_points = serializers.IntegerField()
    total_time = serializers.IntegerField()
    avg_predicted = serializers.FloatField(required=False)
    avg_actual = serializers.FloatField(required=False)
    avg_diff = serializers.FloatField(required=False)
    weekly_breakdown = BulkWeeklyStatSerializer(many=True)