from contents.models import (
    PreEvaluationAttempt,
    PreEvaluationAnswer,
    TemporaryWeekUnlock,
    RemediationCompletedMaterial,
    RemediationTimeTracking
)

class StudentPreTestResult(PreEvaluationAttempt):
    class Meta:
        proxy = True
        verbose_name = "Öğrenci Ön Test Sonucu"
        verbose_name_plural = "1. Öğrenci Ön Test Sonuçları & Skorları"


class StudentPreTestAnswer(PreEvaluationAnswer):
    class Meta:
        proxy = True
        verbose_name = "Öğrenci Soru Yanıtı"
        verbose_name_plural = "2. Öğrenci Soru Yanıtları & Seçenekleri"


class StudentRemediationUnlock(TemporaryWeekUnlock):
    class Meta:
        proxy = True
        verbose_name = "2 Günlük Telafi Kilit Açması"
        verbose_name_plural = "3. 2 Günlük Telafi Kilit Açmaları & İlerlemeler"


class RemediationMaterialRecord(RemediationCompletedMaterial):
    class Meta:
        proxy = True
        verbose_name = "Telafi Tamamlanan Materyal"
        verbose_name_plural = "4. Telafi Kapsamında Tamamlanan Materyaller"


class RemediationTimeRecord(RemediationTimeTracking):
    class Meta:
        proxy = True
        verbose_name = "Telafi Süre Takibi"
        verbose_name_plural = "5. Telafi Süre Takip Kayıtları (İzole)"

