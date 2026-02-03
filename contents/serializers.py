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
        fields = ['id', 'question_text', 'order', 'options']

class QuizSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True) 
    questions = QuizQuestionSerializer(many=True)
    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'questions']

class MaterialSerializer(serializers.ModelSerializer):
    
    id = serializers.CharField(read_only=True) 
    quiz = QuizSerializer(required=False, allow_null=True)
    embed_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
    class Meta:
        model = Material
        fields = ['id', 'content_type', 'embed_url', 'title', 'quiz']
        extra_kwargs = {'id': {'read_only': False, 'required': False}}

class FlashcardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flashcard
        fields = ['id', 'question', 'answer', 'order']
        extra_kwargs = {'id': {'read_only': False, 'required': False}}

# --- ANA SERIALIZER ---

class WeeklyContentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    materials = MaterialSerializer(many=True, required=False)
    flashcards = FlashcardSerializer(many=True, required=False)
    progress = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()
    is_intro_watched = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    lock_reason = serializers.SerializerMethodField()
    week_number = serializers.IntegerField(validators=[])

    class Meta:
        model = WeeklyContent
        fields = [
            'id', 'week_number', 'title', 'description', 
            'intro_title', 'intro_video_url', 'release_date',
            'is_locked', 'lock_reason',
            'is_intro_watched', 'materials', 'flashcards', 'progress', 'is_completed'
        ]

    def get_is_locked(self, obj):
        """Zaman ve Sıralı İlerleme kontrolü yaparak haftanın kilitli olup olmadığını belirler."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return True
        if getattr(request.user, 'is_teacher', False) or request.user.is_staff:
            return False

        now = timezone.now()
        if obj.release_date:
            if now < obj.release_date:
                return True
        if obj.week_number > 1:
            previous_week = WeeklyContent.objects.filter(week_number=obj.week_number - 1).first()
            if previous_week:
                prev_progress = StudentProgress.objects.filter(
                    student=request.user, 
                    weekly_content=previous_week
                ).first()
                
                if not prev_progress or not prev_progress.is_completed:
                    return True
        
        return False

    def get_lock_reason(self, obj):
        """Öğrenciye kilit sebebini GG.AA.YYYY formatında döner."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or getattr(request.user, 'is_teacher', False):
            return None

        now = timezone.now()

        if obj.release_date and now < obj.release_date:
            formatted_date = obj.release_date.strftime('%d.%m.%Y')
            return f"Bu içerik {formatted_date} tarihinde erişime açılacaktır."

        if obj.week_number > 1:
            previous_week = WeeklyContent.objects.filter(week_number=obj.week_number - 1).first()
            if previous_week:
                prev_progress = StudentProgress.objects.filter(student=request.user, weekly_content=previous_week).first()
                if not prev_progress or not prev_progress.is_completed:
                    return f"Bu haftayı açmak için lütfen {obj.week_number - 1}. haftayı %100 tamamlayın."
            
        return None

    def get_is_intro_watched(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if getattr(request.user, 'is_teacher', False):
                return True
            completion = IntroVideoCompletion.objects.filter(student=request.user).first()
            return completion.is_watched if completion else False
        return False

    def get_progress(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            progress_obj = StudentProgress.objects.filter(student=request.user, weekly_content=obj).first()
            return float(progress_obj.completion_percentage) if progress_obj else 0.0
        return 0.0

    def get_is_completed(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            progress_obj = StudentProgress.objects.filter(student=request.user, weekly_content=obj).first()
            return progress_obj.is_completed if progress_obj else False
        return False

    def create(self, validated_data):
        mats_data = validated_data.pop('materials', [])
        cards_data = validated_data.pop('flashcards', [])
        w_num = validated_data.get('week_number')
        
        i_title = validated_data.get('intro_title', 'Genel Tanıtım')
        i_url = validated_data.get('intro_video_url', '')
        r_date = validated_data.get('release_date', None)

        content, _ = WeeklyContent.objects.update_or_create(
            week_number=w_num,
            defaults={
                'title': validated_data.get('title'),
                'description': validated_data.get('description'),
                'intro_title': i_title,
                'intro_video_url': i_url,
                'release_date': r_date,
            }
        )

        if w_num == 1:
            content.intro_title = i_title
            content.intro_video_url = i_url
            content.save()

        keep_mat_ids = []
        for m_item in mats_data:
            q_data = m_item.pop('quiz', None)
            m_id = m_item.get('id')

            if m_id and Material.objects.filter(id=m_id).exists():
                mat_obj = Material.objects.get(id=m_id)
                mat_obj.title = m_item.get('title', mat_obj.title)
                mat_obj.content_type = m_item.get('content_type', mat_obj.content_type)
                mat_obj.embed_url = m_item.get('embed_url', mat_obj.embed_url)
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
                for idx, q_val in enumerate(qs_list):
                    opts_list = q_val.pop('options', [])
                    question_instance = QuizQuestion.objects.create(
                        quiz=quiz_instance, 
                        question_text=q_val.get('question_text', ''), 
                        order=idx
                    )
                    for o_val in opts_list:
                        QuizOption.objects.create(question=question_instance, **o_val)

        keep_card_ids = []
        for idx, c_item in enumerate(cards_data):
            c_id = c_item.get('id')
            if c_id and Flashcard.objects.filter(id=c_id).exists():
                card_obj = Flashcard.objects.get(id=c_id)
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

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'total_time_spent', 'overall_progress', 'weekly_breakdown']

    def get_total_time_spent(self, obj):
        total_seconds = TimeTracking.objects.filter(student=obj).aggregate(total=Sum('duration_seconds'))['total'] or 0
        return f"{total_seconds // 3600} saat {(total_seconds % 3600) // 60} dakika"

    def get_overall_progress(self, obj):
        total_materials = Material.objects.count()
        if total_materials == 0: return 0
        completed_count = CompletedMaterial.objects.filter(student=obj).count()
        return round((completed_count / total_materials) * 100, 2)

    def get_weekly_breakdown(self, obj):
        weeks = WeeklyContent.objects.all().order_by('week_number')
        breakdown = []
        for week in weeks:
            progress_obj = StudentProgress.objects.filter(student=obj, weekly_content=week).first()
            total_sec = TimeTracking.objects.filter(student=obj, weekly_content=week).aggregate(total=Sum('duration_seconds'))['total'] or 0
            questions = StudentQuestion.objects.filter(student=obj, weekly_content=week).values_list('question_text', flat=True)
            quiz_results = []
            attempts = StudentQuizAttempt.objects.filter(student=obj, quiz__material__parent_content=week).select_related('quiz').prefetch_related('answers__question', 'answers__selected_option')
            for attempt in attempts:
                for ans in attempt.answers.all():
                    correct_opt = ans.question.options.filter(is_correct=True).first()
                    quiz_results.append({
                        "question_text": ans.question.question_text,
                        "selected_option": ans.selected_option.option_text if ans.selected_option else "Cevapsız",
                        "correct_option": correct_opt.option_text if correct_opt else "Belirlenmemiş",
                        "is_correct": ans.is_correct
                    })
            breakdown.append({
                "week_number": week.week_number,
                "progress": progress_obj.completion_percentage if progress_obj else 0,
                "duration": f"{total_sec // 60} dk",
                "questions": list(questions),
                "quiz_results": quiz_results
            })
        return breakdown

class CompleteMaterialSerializer(serializers.Serializer):
    material_id = serializers.CharField()

class StudentProgressSerializer(serializers.ModelSerializer):
    weekly_content = serializers.CharField(source='weekly_content.id')
    week_number = serializers.ReadOnlyField(source='weekly_content.week_number')
    week_title = serializers.ReadOnlyField(source='weekly_content.title')
    
    class Meta:
        model = StudentProgress
        fields = ['id', 'weekly_content', 'week_number', 'week_title', 'is_completed', 'completion_percentage', 'last_accessed']

class AIChatSerializer(serializers.Serializer):
    message = serializers.CharField(required=True, min_length=1)

class QuizAIAnalysisSerializer(serializers.Serializer):
    attempt_id = serializers.CharField(read_only=True) 
    ai_feedback = serializers.CharField()
    score = serializers.IntegerField()
    correct_answers = serializers.IntegerField()
    wrong_answers = serializers.IntegerField()



class BulkWeeklyStatSerializer(serializers.Serializer):
    """Her bir haftanın durumunu temsil eder"""
    week = serializers.IntegerField()
    progress = serializers.FloatField()
    duration_seconds = serializers.IntegerField()
    correct = serializers.IntegerField() # Eklendi
    wrong = serializers.IntegerField()   # Eklendi
    has_quiz = serializers.BooleanField() # Eklendi

class BulkAcademicReportSerializer(serializers.Serializer):
    """Tüm öğrenci verisini paketler"""
    id = serializers.CharField() 
    full_name = serializers.CharField()
    email = serializers.EmailField()
    total_time = serializers.IntegerField()
    weekly_breakdown = BulkWeeklyStatSerializer(many=True)