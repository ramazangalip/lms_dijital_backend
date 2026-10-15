from django.contrib import admin
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from contents.models import RemediationCompletedMaterial
from .models import (
    StudentPreTestResult,
    StudentPreTestAnswer,
    StudentRemediationUnlock,
    RemediationMaterialRecord,
    RemediationTimeRecord
)

# --- INLINE ---

class StudentPreTestAnswerInline(admin.TabularInline):
    model = StudentPreTestAnswer
    extra = 0
    can_delete = False
    readonly_fields = ('get_question_text', 'get_selected_option', 'get_correct_option', 'is_correct_badge', 'get_target_week')
    fields = ('get_question_text', 'get_selected_option', 'get_correct_option', 'is_correct_badge', 'get_target_week')

    def get_question_text(self, obj):
        return obj.question.question_text[:80] if obj and obj.question else "-"
    get_question_text.short_description = "Soru"

    def get_selected_option(self, obj):
        return obj.selected_option.option_text if obj and obj.selected_option else "Boş"
    get_selected_option.short_description = "Öğrencinin Cevabı"

    def get_correct_option(self, obj):
        if obj and obj.question:
            corr = obj.question.options.filter(is_correct=True).first()
            return corr.option_text if corr else "-"
        return "-"
    get_correct_option.short_description = "Doğru Şık"

    def is_correct_badge(self, obj):
        if not obj: return "-"
        if obj.is_correct:
            return mark_safe('<span style="color: green; font-weight: bold;">✔ DOĞRU</span>')
        return mark_safe('<span style="color: red; font-weight: bold;">✘ YANLIŞ</span>')
    is_correct_badge.short_description = "Sonuç"

    def get_target_week(self, obj):
        if obj and obj.question:
            if not obj.is_correct:
                return format_html('<span style="color: #b45309; font-weight: bold;">{} .Hafta Kilidi Açıldı</span>', obj.question.target_week)
            return f"{obj.question.target_week}. Hafta"
        return "-"
    get_target_week.short_description = "Hedef Telafi Haftası"


# --- ADMIN MODELLERİ ---

@admin.register(StudentPreTestResult)
class StudentPreTestResultAdmin(admin.ModelAdmin):
    list_display = (
        'get_student_full_name', 'get_department', 'get_category', 
        'get_week_number', 'score_badge', 'correct_answers', 'wrong_answers', 
        'get_remediated_weeks', 'completed_at'
    )
    list_filter = (
        'pre_test__weekly_content__week_number',
        'student__department',
        'student__category',
        'completed_at'
    )
    search_fields = ('student__first_name', 'student__last_name', 'student__email')
    ordering = ('-completed_at',)
    inlines = [StudentPreTestAnswerInline]

    def get_student_full_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name} ({obj.student.email})"
    get_student_full_name.short_description = "Öğrenci"
    get_student_full_name.admin_order_field = 'student__first_name'

    def get_department(self, obj):
        return obj.student.get_department_display() if hasattr(obj.student, 'get_department_display') else obj.student.department
    get_department.short_description = "Bölüm"

    def get_category(self, obj):
        cat = getattr(obj.student, 'category', '-')
        color = '#4338ca' if cat == 'd2' else '#4b5563'
        return format_html('<span style="color: {}; font-weight: bold; text-transform: uppercase;">{}</span>', color, cat)
    get_category.short_description = "Kategori"

    def get_week_number(self, obj):
        return f"{obj.pre_test.weekly_content.week_number}. Hafta"
    get_week_number.short_description = "Ön Test Haftası"

    def score_badge(self, obj):
        color = '#15803d' if obj.score >= 70 else '#b45309'
        return format_html('<span style="color: {}; font-weight: bold; font-size: 13px;">%{}</span>', color, obj.score)
    score_badge.short_description = "Başarı Skoru"
    score_badge.admin_order_field = 'score'

    def get_remediated_weeks(self, obj):
        wrong_answers = obj.answers.filter(is_correct=False).select_related('question')
        weeks = sorted(list(set(a.question.target_week for a in wrong_answers)))
        if weeks:
            return format_html('<span style="color: #b91c1c; font-weight: bold;">Açılan Haftalar: {}</span>', ", ".join(f"{w}.H" for w in weeks))
        return mark_safe('<span style="color: #15803d;">Yok (Tam Başarı)</span>')
    get_remediated_weeks.short_description = "Tetiklenen Telafi Kilitleri"


@admin.register(StudentPreTestAnswer)
class StudentPreTestAnswerAdmin(admin.ModelAdmin):
    list_display = ('get_student', 'get_department', 'get_week_number', 'short_question', 'get_selected', 'get_correct_choice', 'is_correct_badge', 'get_target_week')
    list_filter = ('is_correct', 'attempt__pre_test__weekly_content__week_number', 'attempt__student__department', 'attempt__student__category')
    search_fields = ('attempt__student__first_name', 'attempt__student__last_name', 'attempt__student__email', 'question__question_text')
    ordering = ('-attempt__completed_at',)

    def get_student(self, obj):
        return f"{obj.attempt.student.first_name} {obj.attempt.student.last_name}"
    get_student.short_description = "Öğrenci"

    def get_department(self, obj):
        stu = obj.attempt.student
        return stu.get_department_display() if hasattr(stu, 'get_department_display') else stu.department
    get_department.short_description = "Bölüm"

    def get_week_number(self, obj):
        return f"{obj.attempt.pre_test.weekly_content.week_number}. Hafta"
    get_week_number.short_description = "Ön Test"

    def short_question(self, obj):
        return obj.question.question_text[:50] + "..." if len(obj.question.question_text) > 50 else obj.question.question_text
    short_question.short_description = "Soru"

    def get_selected(self, obj):
        return obj.selected_option.option_text if obj.selected_option else "Boş"
    get_selected.short_description = "Verilen Cevap"

    def get_correct_choice(self, obj):
        if obj.question:
            corr = obj.question.options.filter(is_correct=True).first()
            return corr.option_text if corr else "-"
        return "-"
    get_correct_choice.short_description = "Doğru Şık"

    def is_correct_badge(self, obj):
        if obj.is_correct:
            return mark_safe('<span style="color: green; font-weight: bold;">✔ Doğru</span>')
        return mark_safe('<span style="color: red; font-weight: bold;">✘ Yanlış</span>')
    is_correct_badge.short_description = "Doğruluk"

    def get_target_week(self, obj):
        if not obj.is_correct:
            return format_html('<span style="color: #b45309; font-weight: bold;">{} .Hafta Kilidi Açıldı</span>', obj.question.target_week)
        return "-"
    get_target_week.short_description = "Açılan Kilit"


class RemediationCompletedMaterialInline(admin.TabularInline):
    model = RemediationCompletedMaterial
    extra = 0
    can_delete = False
    readonly_fields = ('get_material_title', 'get_content_type', 'completed_at')
    fields = ('get_material_title', 'get_content_type', 'completed_at')

    def get_material_title(self, obj):
        return obj.material.title if obj and obj.material else "-"
    get_material_title.short_description = "Materyal Başlığı"

    def get_content_type(self, obj):
        return obj.material.content_type if obj and obj.material else "-"
    get_content_type.short_description = "Tür"


@admin.register(StudentRemediationUnlock)
class StudentRemediationUnlockAdmin(admin.ModelAdmin):
    list_display = (
        'get_student_full_name', 'get_department', 'get_category', 
        'get_week_number', 'completion_badge', 'duration_badge', 
        'unlocked_at', 'expires_at', 'status_badge', 'hours_remaining'
    )
    list_filter = ('weekly_content__week_number', 'student__department', 'student__category', 'is_completed')
    search_fields = ('student__first_name', 'student__last_name', 'student__email')
    ordering = ('-expires_at',)
    inlines = [RemediationCompletedMaterialInline]

    def get_student_full_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name} ({obj.student.email})"
    get_student_full_name.short_description = "Öğrenci"

    def get_department(self, obj):
        return obj.student.get_department_display() if hasattr(obj.student, 'get_department_display') else obj.student.department
    get_department.short_description = "Bölüm"

    def get_category(self, obj):
        cat = getattr(obj.student, 'category', '-')
        color = '#4338ca' if cat == 'd2' else '#4b5563'
        return format_html('<span style="color: {}; font-weight: bold; text-transform: uppercase;">{}</span>', color, cat)
    get_category.short_description = "Kategori"

    def get_week_number(self, obj):
        return f"{obj.weekly_content.week_number}. Hafta Kilidi"
    get_week_number.short_description = "Telafi Haftası"

    def completion_badge(self, obj):
        color = '#15803d' if obj.completion_percentage >= 100 else '#b45309'
        return format_html('<span style="color: {}; font-weight: bold; font-size: 13px;">%{}</span>', color, round(obj.completion_percentage, 1))
    completion_badge.short_description = "Telafi İlerlemesi"
    completion_badge.admin_order_field = 'completion_percentage'

    def duration_badge(self, obj):
        mins = obj.total_duration_seconds // 60
        secs = obj.total_duration_seconds % 60
        return f"{mins} dk {secs} sn"
    duration_badge.short_description = "Harcanan Süre"
    duration_badge.admin_order_field = 'total_duration_seconds'

    def status_badge(self, obj):
        if obj.expires_at > timezone.now():
            return mark_safe('<span style="background-color: #fef3c7; color: #92400e; padding: 3px 8px; border-radius: 6px; font-weight: bold;">⚡ 2 GÜN KİLİT AKTİF</span>')
        return mark_safe('<span style="color: #9ca3af; font-weight: bold;">Süre Doldu</span>')
    status_badge.short_description = "Durum"

    def hours_remaining(self, obj):
        diff = (obj.expires_at - timezone.now()).total_seconds()
        if diff > 0:
            hrs = int(diff // 3600)
            mins = int((diff % 3600) // 60)
            return f"{hrs} saat {mins} dk kaldı"
        return "0 dk (Kapandı)"
    hours_remaining.short_description = "Kalan Süre"


@admin.register(RemediationMaterialRecord)
class RemediationMaterialRecordAdmin(admin.ModelAdmin):
    list_display = ('get_student', 'get_department', 'get_week', 'get_material', 'completed_at')
    list_filter = ('temporary_unlock__weekly_content__week_number', 'student__department', 'completed_at')
    search_fields = ('student__first_name', 'student__last_name', 'student__email', 'material__title')
    ordering = ('-completed_at',)

    def get_student(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"
    get_student.short_description = "Öğrenci"

    def get_department(self, obj):
        return obj.student.get_department_display() if hasattr(obj.student, 'get_department_display') else obj.student.department
    get_department.short_description = "Bölüm"

    def get_week(self, obj):
        return f"{obj.temporary_unlock.weekly_content.week_number}. Hafta" if obj.temporary_unlock else "-"
    get_week.short_description = "Telafi Haftası"

    def get_material(self, obj):
        return obj.material.title if obj.material else "-"
    get_material.short_description = "Tamamlanan Materyal"


@admin.register(RemediationTimeRecord)
class RemediationTimeRecordAdmin(admin.ModelAdmin):
    list_display = ('get_student', 'get_department', 'get_week', 'get_material', 'duration_display', 'date')
    list_filter = ('weekly_content__week_number', 'student__department', 'date')
    search_fields = ('student__first_name', 'student__last_name', 'student__email')
    ordering = ('-date',)

    def get_student(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"
    get_student.short_description = "Öğrenci"

    def get_department(self, obj):
        return obj.student.get_department_display() if hasattr(obj.student, 'get_department_display') else obj.student.department
    get_department.short_description = "Bölüm"

    def get_week(self, obj):
        return f"{obj.weekly_content.week_number}. Hafta"
    get_week.short_description = "Telafi Haftası"

    def get_material(self, obj):
        return obj.material.title if obj.material else "Genel"
    get_material.short_description = "Materyal"

    def duration_display(self, obj):
        mins = obj.duration_seconds // 60
        secs = obj.duration_seconds % 60
        return f"{mins} dk {secs} sn"
    duration_display.short_description = "Harcanan Süre"

