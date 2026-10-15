from contents.models import (
    PreEvaluationTest,
    PreEvaluationQuestion,
    PreEvaluationOption,
)

class PreEvaluationTestProxy(PreEvaluationTest):
    class Meta:
        proxy = True
        verbose_name = "Ön Değerlendirme Testi"
        verbose_name_plural = "1. Ön Değerlendirme Testleri"


class PreEvaluationQuestionProxy(PreEvaluationQuestion):
    class Meta:
        proxy = True
        verbose_name = "Ön Test Sorusu"
        verbose_name_plural = "2. Ön Test Soruları"


class PreEvaluationOptionProxy(PreEvaluationOption):
    class Meta:
        proxy = True
        verbose_name = "Ön Test Soru Şıkkı / Cevabı"
        verbose_name_plural = "3. Ön Test Soru Şıkları (Cevap Şıkları)"
