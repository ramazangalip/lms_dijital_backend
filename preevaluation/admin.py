from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from contents.models import PreEvaluationOption
from .models import (
    PreEvaluationTestProxy,
    PreEvaluationQuestionProxy,
    PreEvaluationOptionProxy,
)

# --- INLINES ---

class PreEvaluationOptionInline(admin.TabularInline):
    model = PreEvaluationOption
    extra = 5
    max_num = 5
    fields = ('option_text', 'is_correct')
    verbose_name = "Soru Şıkkı"
    verbose_name_plural = "5 Şık (A, B, C, D, E)"


class PreEvaluationQuestionInline(admin.StackedInline):
    model = PreEvaluationQuestionProxy
    extra = 0
    fields = ('order', 'question_text', 'target_week', 'get_correct_option')
    readonly_fields = ('get_correct_option',)
    verbose_name = "Ön Test Sorusu"
    verbose_name_plural = "Ön Test Soruları"

    def get_correct_option(self, obj):
        if not obj or not obj.id:
            return "-"
        corr = obj.options.filter(is_correct=True).first()
        if corr:
            return format_html('<span style="color: green; font-weight: bold;">✔ {}</span>', corr.option_text)
        return mark_safe('<span style="color: red;">Doğru şık seçilmemiş!</span>')
    get_correct_option.short_description = "Belirlenen Doğru Cevap"


# --- ADMIN MODELLERİ ---

@admin.register(PreEvaluationTestProxy)
class PreEvaluationTestAdmin(admin.ModelAdmin):
    list_display = ('get_week_number', 'title', 'get_question_count', 'created_at')
    list_filter = ('weekly_content__week_number',)
    search_fields = ('title', 'weekly_content__title')
    ordering = ('weekly_content__week_number',)
    inlines = [PreEvaluationQuestionInline]

    def get_week_number(self, obj):
        return f"{obj.weekly_content.week_number}. Hafta"
    get_week_number.short_description = "Hafta"
    get_week_number.admin_order_field = 'weekly_content__week_number'

    def get_question_count(self, obj):
        return obj.questions.count()
    get_question_count.short_description = "Toplam Soru Sayısı"


@admin.register(PreEvaluationQuestionProxy)
class PreEvaluationQuestionAdmin(admin.ModelAdmin):
    list_display = ('get_week_number', 'order', 'short_question_text', 'get_correct_option', 'get_options_count', 'get_target_week_info')
    list_filter = ('pre_test__weekly_content__week_number', 'target_week')
    search_fields = ('question_text',)
    ordering = ('pre_test__weekly_content__week_number', 'order')
    inlines = [PreEvaluationOptionInline]

    def get_week_number(self, obj):
        return f"{obj.pre_test.weekly_content.week_number}. Hafta Ön Testi"
    get_week_number.short_description = "Hafta"

    def short_question_text(self, obj):
        return obj.question_text[:70] + "..." if len(obj.question_text) > 70 else obj.question_text
    short_question_text.short_description = "Soru Metni"

    def get_correct_option(self, obj):
        corr = obj.options.filter(is_correct=True).first()
        if corr:
            txt = corr.option_text[:50] + "..." if len(corr.option_text) > 50 else corr.option_text
            return format_html('<span style="color: #15803d; font-weight: bold;">✔ {}</span>', txt)
        return mark_safe('<span style="color: #b91c1c; font-weight: bold;">✘ Doğru Şık Yok!</span>')
    get_correct_option.short_description = "Doğru Cevap Şıkkı"

    def get_options_count(self, obj):
        cnt = obj.options.count()
        color = '#15803d' if cnt == 5 else '#b45309'
        return format_html('<span style="color: {}; font-weight: bold;">{} Şık</span>', color, cnt)
    get_options_count.short_description = "Kayıtlı Şık Sayısı"

    def get_target_week_info(self, obj):
        return f"{obj.target_week}. Hafta (Yanlışta 2 Gün Açar)"
    get_target_week_info.short_description = "Hedeflenen Telafi Haftası"


@admin.register(PreEvaluationOptionProxy)
class PreEvaluationOptionAdmin(admin.ModelAdmin):
    list_display = ('get_week_number', 'get_question_short', 'short_option_text', 'is_correct_badge', 'get_target_week')
    list_filter = ('question__pre_test__weekly_content__week_number', 'is_correct', 'question__target_week')
    search_fields = ('option_text', 'question__question_text')
    ordering = ('question__pre_test__weekly_content__week_number', 'question__order', '-is_correct')

    def get_week_number(self, obj):
        return f"{obj.question.pre_test.weekly_content.week_number}. Hafta"
    get_week_number.short_description = "Hafta"

    def get_question_short(self, obj):
        return f"Soru {obj.question.order + 1}: {obj.question.question_text[:40]}..."
    get_question_short.short_description = "Ait Olduğu Soru"

    def short_option_text(self, obj):
        return obj.option_text[:80] + "..." if len(obj.option_text) > 80 else obj.option_text
    short_option_text.short_description = "Cevap Şıkkı Metni"

    def is_correct_badge(self, obj):
        if obj.is_correct:
            return mark_safe('<span style="background-color: #dcfce7; color: #15803d; padding: 3px 8px; border-radius: 6px; font-weight: bold;">✔ DOĞRU CEVAP</span>')
        return mark_safe('<span style="color: #6b7280;">Yanlış Şık</span>')
    is_correct_badge.short_description = "Doğru Şık mı?"

    def get_target_week(self, obj):
        return f"{obj.question.target_week}. Hafta"
    get_target_week.short_description = "Açılacak Hafta"
