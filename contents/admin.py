from django.contrib import admin
from .models import *

# --- INLINES ---

class MaterialInline(admin.TabularInline):
    """Haftalık içeriklerin altına video/podcast/test eklemeyi sağlar."""
    model = Material
    extra = 1
    fields = ('content_type', 'title', 'embed_url')

# --- MODELLER ---

@admin.register(WeeklyContent)
class WeeklyContentAdmin(admin.ModelAdmin):
    list_display = ('week_number', 'title', 'has_global_intro')
    list_filter = ('week_number',)
    search_fields = ('title', 'description')
    ordering = ('week_number',)
    inlines = [MaterialInline]

    fieldsets = (
        ('Haftalık Ders Bilgileri', {
            'fields': ('week_number', 'title', 'description')
        }),
        ('Merkezi Tanıtım Videosu (Sadece Hafta 1 İçin Doldurun)', {
            'description': (
                "Öğrencilerin tüm sistemi açmak için izlemesi gereken tek videodur. "
                "Hafta 1'e eklenen video global kilit görevi görür."
            ),
            'fields': ('intro_title', 'intro_video_url'),
            'classes': ('collapse',) # Varsayılan olarak kapalı durur, Hafta 1'de açılabilir
        }),
    )

    def has_global_intro(self, obj):
        return bool(obj.intro_video_url)
    has_global_intro.boolean = True
    has_global_intro.short_description = "Tanıtım Videosu Var"

    def formfield_for_dbfield(self, db_field, **kwargs):
        field = super().formfield_for_dbfield(db_field, **kwargs)
        if db_field.name == 'description':
            field.widget.attrs['rows'] = 5
            field.widget.attrs['style'] = 'width: 85%;'
        return field

@admin.register(IntroVideoCompletion)
class IntroVideoCompletionAdmin(admin.ModelAdmin):
    """Öğrencilerin global tanıtım videosunu bitirip bitirmediğini takip eder."""
    list_display = ('student', 'is_watched', 'watched_at')
    list_filter = ('is_watched', 'watched_at')
    search_fields = ('student__email', 'student__first_name', 'student__last_name')
    readonly_fields = ('watched_at',)

# --- TAKİP VE ANALİZ MODELLERİ ---

@admin.register(StudentProgress)
class StudentProgressAdmin(admin.ModelAdmin):
    list_display = ('student', 'weekly_content', 'get_progress', 'is_completed', 'last_accessed')
    list_filter = ('weekly_content', 'is_completed')
    search_fields = ('student__email', 'weekly_content__title')

    def get_progress(self, obj):
        return f"%{obj.completion_percentage}"
    get_progress.short_description = "İlerleme"

@admin.register(TimeTracking)
class TimeTrackingAdmin(admin.ModelAdmin):
    list_display = ('student', 'weekly_content', 'formatted_duration', 'date')
    list_filter = ('date', 'weekly_content')
    search_fields = ('student__email',)

    def formatted_duration(self, obj):
        mins = obj.duration_seconds // 60
        if mins < 60: return f"{mins} dk"
        return f"{mins // 60} sa {mins % 60} dk"
    formatted_duration.short_description = "Süre"

@admin.register(StudentQuestion)
class StudentQuestionAdmin(admin.ModelAdmin):
    list_display = ('student', 'get_week', 'short_question', 'created_at')
    list_filter = ('weekly_content', 'created_at')
    search_fields = ('student__email', 'question_text')

    def get_week(self, obj):
        return f"Hafta {obj.weekly_content.week_number}"
    
    def short_question(self, obj):
        return obj.question_text[:50] + "..." if len(obj.question_text) > 50 else obj.question_text

# --- SINAV (QUIZ) SİSTEMİ ---

class StudentAnswerInline(admin.TabularInline):
    model = StudentAnswer
    extra = 0
    readonly_fields = ('question', 'selected_option', 'is_correct')
    can_delete = False

@admin.register(StudentQuizAttempt)
class StudentQuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('student', 'quiz', 'score', 'correct_answers', 'wrong_answers', 'completed_at')
    list_filter = ('quiz', 'completed_at')
    search_fields = ('student__email', 'quiz__title')
    inlines = [StudentAnswerInline]

class QuizOptionInline(admin.TabularInline):
    model = QuizOption
    extra = 4

@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ('question_text', 'quiz')
    inlines = [QuizOptionInline]

@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'material')

# Tekil kayıtlar
admin.site.register(Material)
@admin.register(CompletedMaterial)
class CompletedMaterialAdmin(admin.ModelAdmin):
    # list_display: Tablo sütunlarında nelerin görüneceğini belirler
    list_display = ('get_student_full_name', 'get_department', 'get_material_name', 'completed_at')
    
    # Filtreleme seçenekleri
    list_filter = ('completed_at', 'student__department', 'material__content_type')
    
    # Arama çubuğu (Öğrenci adı, e-postası veya materyal başlığına göre)
    search_fields = ('student__first_name', 'student__last_name', 'student__email', 'material__title')

    # 1. Öğrenci Adı ve Soyadı
    def get_student_full_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"
    get_student_full_name.short_description = 'Öğrenci Adı Soyadı'
    get_student_full_name.admin_order_field = 'student__first_name'

    # 2. Bölüm Bilgisi
    def get_department(self, obj):
        # User modelindeki department alanını çeker (get_department_display seçeneği varsa onu kullanır)
        return obj.student.get_department_display() if hasattr(obj.student, 'get_department_display') else obj.student.department
    get_department.short_description = 'Bölüm'

    # 3. Materyal İsmi
    def get_material_name(self, obj):
        return obj.material.title
    get_material_name.short_description = 'Tamamlanan İçerik'
admin.site.register(Flashcard)