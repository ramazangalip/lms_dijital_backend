from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class WeeklyContent(models.Model):
    week_number = models.IntegerField(unique=True, verbose_name="Hafta")
    title = models.CharField(max_length=200, verbose_name="Hafta Başlığı")
    description = models.TextField(blank=True, verbose_name="Ders Notları")

    release_date = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Erişime Açılma Tarihi",
        help_text="Bu tarih gelmeden öğrenci içeriğe erişemez."
    )
    deactivation_date = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Pasif Etme / Kapanma Tarihi",
        help_text="Bu tarih geçtikten sonra öğrenci içeriğe erişemez."
    )
    

    intro_title = models.CharField(max_length=255, default="Genel Tanıtım", verbose_name="Tanıtım Başlığı")
    intro_video_url = models.URLField(blank=True, null=True, verbose_name="Tanıtım Videosu (Embed Link)")
    intro_description = models.TextField(blank=True, null=True, verbose_name="Tanıtım Metni/Açıklaması")
    is_pretest_active = models.BooleanField(
        default=False, 
        verbose_name="Ön Değerlendirme Testi Aktif mi?",
        help_text="2. haftadan itibaren aktif edildiğinde, öğrenci bu testi tamamlamadan haftalık materyallere erişemez."
    )

    class Meta:
        verbose_name = "Haftalık İçerik"
        verbose_name_plural = "Haftalık İçerikler"
        ordering = ['week_number']
        indexes = [
            models.Index(fields=['week_number']),
            models.Index(fields=['release_date']),
            models.Index(fields=['deactivation_date']),
        ]

    def __str__(self):
        return f"Hafta {self.week_number} - {self.title}"

class WeeklyContentDepartmentSchedule(models.Model):
    """
    Bölüm Bazlı Hafta Erişim ve Pasif Etme Tarihleri
    Her haftanın her bölüm için ayrı açılış ve kapanış tarihleri olabilir.
    """
    weekly_content = models.ForeignKey(
        WeeklyContent, 
        related_name='department_schedules', 
        on_delete=models.CASCADE,
        verbose_name="Haftalık İçerik"
    )
    department = models.CharField(
        max_length=50, 
        choices=User.DEPARTMENT_CHOICES, 
        verbose_name="Bölüm"
    )
    release_date = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Erişime Açılma Tarihi",
        help_text="Bu tarih gelmeden ilgili bölümdeki öğrenci içeriğe erişemez."
    )
    deactivation_date = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Pasif Etme / Kapanma Tarihi",
        help_text="Bu tarih geçtikten sonra ilgili bölümdeki öğrenci içeriğe erişemez."
    )

    class Meta:
        verbose_name = "Bölüm Bazlı Hafta Tarih Ayarı"
        verbose_name_plural = "Bölüm Bazlı Hafta Tarih Ayarları"
        unique_together = ('weekly_content', 'department')
        indexes = [
            models.Index(fields=['weekly_content', 'department']),
            models.Index(fields=['department', 'release_date', 'deactivation_date']),
        ]

    def __str__(self):
        return f"{self.weekly_content.week_number}. Hafta - {self.get_department_display()} ({self.release_date} - {self.deactivation_date})"

class IntroVideoCompletion(models.Model):
    """
    SİSTEM GENELİ TEK TANITIM VİDEOSU TAKİBİ
    Öğrenci Hafta 1'deki videoyu bir kez izlediğinde OneToOneField sayesinde
    tüm haftaların kilidini açan global bir anahtar görevi görür.
    """
    student = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='intro_status',
        verbose_name="Öğrenci"
    )
    is_watched = models.BooleanField(default=False, verbose_name="İzledi mi?")
    watched_at = models.DateTimeField(auto_now_add=True, verbose_name="İzleme Tarihi")

    class Meta:
        verbose_name = "Genel Tanıtım Tamamlama"
        verbose_name_plural = "Genel Tanıtım Tamamlamaları"
        indexes = [
            models.Index(fields=['student', 'is_watched']),
        ]

    def __str__(self):
        status = "Tamamladı" if self.is_watched else "Tamamlamadı"
        return f"{self.student.email} - {status}"

class Material(models.Model):
    CONTENT_TYPES = (
        ('video', 'Video'),
        ('podcast', 'Podcast'),
        ('form', 'Bilgi Testi'),
        ('pdf', 'Ders Notu (PDF)'),
        ('assignment', 'Ödev (Microsoft Form)'),
    )
    parent_content = models.ForeignKey(
        WeeklyContent, 
        related_name='materials', 
        on_delete=models.CASCADE
    )
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPES)
    embed_url = models.URLField(verbose_name="Materyal Linki", help_text="Video/Podcast embed kodu veya OneDrive PDF indirme linki.")
    title = models.CharField(max_length=200, verbose_name="Materyal Başlığı")
    
   
    point_value = models.PositiveIntegerField(default=1, verbose_name="Tamamlama Puanı")
    duration_seconds = models.PositiveIntegerField(default=120, null=True, blank=True, verbose_name="Tamamlama Süresi (Saniye)")

    class Meta:
        verbose_name = "Materyal"
        verbose_name_plural = "Materyaller"
        indexes = [
            models.Index(fields=['parent_content', 'content_type']),
        ]

    def __str__(self):
        return f"{self.get_content_type_display()} - {self.title}"
    


class StudentProgress(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE)
    is_completed = models.BooleanField(default=False)
    completion_percentage = models.FloatField(default=0.0) 
    last_accessed = models.DateTimeField(auto_now=True)
    
    # YENİ ALAN: Öğrenci şu an hangi turda? (1 veya 2)
    current_attempt_round = models.PositiveIntegerField(default=1, verbose_name="Aktif Deneme Turu")

    class Meta:
        unique_together = ('student', 'weekly_content')
        verbose_name = "Öğrenci İlerlemesi"
        verbose_name_plural = "Öğrenci İlerlemeleri"
        indexes = [
            models.Index(fields=['student', 'weekly_content']),
            models.Index(fields=['student', 'is_completed']),
            models.Index(fields=['student', 'current_attempt_round']),
            models.Index(fields=['weekly_content', 'is_completed']),
        ]

class TimeTracking(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE)
    material = models.ForeignKey(Material, on_delete=models.CASCADE, null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    date = models.DateField(auto_now_add=True)
    
    # YENİ ALAN: Bu süre hangi turda harcandı?
    attempt_round = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Zaman Takibi"
        verbose_name_plural = "Zaman Takip Kayıtları"
        indexes = [
            models.Index(fields=['student', 'weekly_content', 'attempt_round']),
            models.Index(fields=['student', 'material', 'attempt_round']),
            models.Index(fields=['student', 'date']),
            models.Index(fields=['weekly_content', 'attempt_round']),
            models.Index(fields=['material', 'attempt_round']),
        ]

    def __str__(self):
        return f"{self.student.email} - Tur {self.attempt_round} - {self.duration_seconds}s"
    
class CompletedMaterial(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    completed_at = models.DateTimeField(auto_now_add=True)
    
    # YENİ ALAN: Hangi turda tamamlandı?
    attempt_round = models.PositiveIntegerField(default=1)

    class Meta:
        # Artık bir öğrenci bir materyali farklı turlarda tamamlayabilir
        unique_together = ('student', 'material', 'attempt_round')
        verbose_name = "Tamamlanan Materyal"
        verbose_name_plural = "Tamamlanan Materyaller"
        indexes = [
            models.Index(fields=['student', 'attempt_round']),
            models.Index(fields=['material', 'attempt_round']),
            models.Index(fields=['student', 'material', 'attempt_round']),
        ]

class StudentQuestion(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE)
    question_text = models.TextField()
    response_text = models.TextField(blank=True, null=True, verbose_name="Yapay Zeka Yanıtı")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Öğrenci Sorusu"
        verbose_name_plural = "Öğrenci Soruları"
        indexes = [
            models.Index(fields=['student', 'weekly_content']),
            models.Index(fields=['weekly_content', '-created_at']),
            models.Index(fields=['student', '-created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.student.first_name} - Hafta {self.weekly_content.week_number}"

class Quiz(models.Model):
    """Her bir test materyali için ana başlık"""
    material = models.OneToOneField('Material', on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sınav"
        verbose_name_plural = "Sınavlar"

    def __str__(self):
        return f"Test: {self.title} (Hafta {self.material.parent_content.week_number})"

class QuizQuestion(models.Model):
    """Sınavın içindeki her bir soru"""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    order = models.PositiveIntegerField(default=0)
    explanation = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Soru Analizi / Açıklaması",
        help_text="Öğrenci bu soruyu yanlış yaptığında gösterilecek hazır yapay zeka veya hoca analizi."
    )
    class Meta:
        ordering = ['order']
        verbose_name = "Sınav Sorusu"
        verbose_name_plural = "Sınav Soruları"
        indexes = [
            models.Index(fields=['quiz', 'order']),
        ]

    def __str__(self):
        return self.question_text[:50]

class QuizOption(models.Model):
    """Soruların şıkları (A, B, C, D...)"""
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='options')
    option_text = models.TextField(verbose_name="Şık Metni")
    is_correct = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Sınav Şıkkı"
        verbose_name_plural = "Sınav Şıkları"
        indexes = [
            models.Index(fields=['question', 'is_correct']),
        ]

    def __str__(self):
        return self.option_text

class StudentQuizAttempt(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField() 
    predicted_score = models.IntegerField(default=0, verbose_name="Tahmin Edilen Skor")
    score_difference = models.IntegerField(default=0, verbose_name="Skor Farkı (Gerçek - Tahmin)")
    correct_answers = models.IntegerField()
    wrong_answers = models.IntegerField()
    completed_at = models.DateTimeField(auto_now_add=True)
    
    # YENİ ALAN: AI analizi öncesi (1) veya sonrası (2) deneme
    attempt_round = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Sınav Denemesi"
        verbose_name_plural = "Sınav Denemeleri"
        indexes = [
            models.Index(fields=['student', 'quiz', 'attempt_round']),
            models.Index(fields=['student', '-completed_at']),
            models.Index(fields=['quiz', 'attempt_round']),
        ]

    def __str__(self):
        return f"{self.student.first_name} - Tur {self.attempt_round} - %{self.score}"

class StudentAnswer(models.Model):
    """Öğrencinin her bir soruya verdiği spesifik cevap"""
    attempt = models.ForeignKey(StudentQuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(QuizOption, on_delete=models.CASCADE)
    is_correct = models.BooleanField()

    class Meta:
        verbose_name = "Öğrenci Cevabı"
        verbose_name_plural = "Öğrenci Cevapları"
        indexes = [
            models.Index(fields=['attempt', 'is_correct']),
            models.Index(fields=['question', 'is_correct']),
        ]

# ... Diğer modellerin (WeeklyContent, Material vb.) aynı kalıyor ...

class Flashcard(models.Model):
    """
    Flashcard'ları 'Haftalık Kaynaklar' olarak güncelliyoruz.
    question -> Kaynağın Başlığı (Örn: Haftalık Özet PDF)
    answer   -> OneDrive Linki
    """
    weekly_content = models.ForeignKey(
        WeeklyContent, 
        related_name='flashcards', 
        on_delete=models.CASCADE
    )
    # Alan isimlerini veritabanını bozmamak için aynı tutuyoruz 
    # ama açıklama ve verbose_name'leri güncelliyoruz.
    question = models.TextField(verbose_name="Kaynak Başlığı")
    answer = models.TextField(verbose_name="OneDrive Linki") 
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = "Haftalık Kaynak"
        verbose_name_plural = "Haftalık Kaynaklar"
        indexes = [
            models.Index(fields=['weekly_content', 'order']),
        ]

    def __str__(self):
        return f"{self.weekly_content.week_number}. Hafta - {self.question}"


# ==============================================================================
# HAFTALIK ÖN DEĞERLENDİRME TESTİ MODELLERİ (2. HAFTADAN İTİBAREN)
# ==============================================================================

class PreEvaluationTest(models.Model):
    """
    Her hafta için isteğe bağlı (varsayılan kapalı) Ön Değerlendirme Testi.
    2. haftadan itibaren aktif edilebilir.
    """
    weekly_content = models.OneToOneField(
        WeeklyContent, 
        on_delete=models.CASCADE, 
        related_name='pre_test',
        verbose_name="Haftalık İçerik"
    )
    title = models.CharField(max_length=255, default="Haftalık Ön Değerlendirme Testi", verbose_name="Ön Test Başlığı")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ön Değerlendirme Testi"
        verbose_name_plural = "Ön Değerlendirme Testleri"

    def __str__(self):
        return f"Ön Test: Hafta {self.weekly_content.week_number} - {self.title}"


class PreEvaluationQuestion(models.Model):
    """
    Ön değerlendirme testi sorusu.
    Her soru 5 şıklıdır ve yanlış yapıldığında hangi önceki haftanın kilidinin 
    2 günlüğüne telafi amaçlı açılacağını belirleyen 'target_week' bilgisine sahiptir.
    Önemli: target_week bilgisi öğrenciye asla gösterilmez.
    """
    pre_test = models.ForeignKey(PreEvaluationTest, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField(verbose_name="Soru Metni")
    order = models.PositiveIntegerField(default=0, verbose_name="Soru Sırası")
    target_week = models.IntegerField(
        default=1, 
        verbose_name="Yanlış Yapıldığında Kilidi Açılacak Hafta",
        help_text="Öğrenci bu soruyu yanlış yaparsa kilidi 2 günlüğüne açılacak olan önceki hafta numarası"
    )

    class Meta:
        ordering = ['order']
        verbose_name = "Ön Test Sorusu"
        verbose_name_plural = "Ön Test Soruları"
        indexes = [
            models.Index(fields=['pre_test', 'order']),
        ]

    def __str__(self):
        return f"Soru {self.order + 1} (Hedef: Hafta {self.target_week}): {self.question_text[:50]}"


class PreEvaluationOption(models.Model):
    """
    Soruların 5 şıkkı (A, B, C, D, E).
    """
    question = models.ForeignKey(PreEvaluationQuestion, on_delete=models.CASCADE, related_name='options')
    option_text = models.TextField(verbose_name="Şık Metni")
    is_correct = models.BooleanField(default=False, verbose_name="Doğru Şık mı?")

    class Meta:
        verbose_name = "Ön Test Şıkkı"
        verbose_name_plural = "Ön Test Şıkları"
        indexes = [
            models.Index(fields=['question', 'is_correct']),
        ]

    def __str__(self):
        return f"{self.option_text} ({'Doğru' if self.is_correct else 'Yanlış'})"


class PreEvaluationAttempt(models.Model):
    """
    Öğrencinin haftalık ön değerlendirme testi çözme denemesi ve skoru.
    """
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pre_evaluation_attempts')
    pre_test = models.ForeignKey(PreEvaluationTest, on_delete=models.CASCADE, related_name='attempts')
    score = models.IntegerField(default=0, verbose_name="Skor (%)")
    correct_answers = models.IntegerField(default=0, verbose_name="Doğru Sayısı")
    wrong_answers = models.IntegerField(default=0, verbose_name="Yanlış Sayısı")
    completed_at = models.DateTimeField(auto_now_add=True, verbose_name="Tamamlanma Tarihi")

    class Meta:
        verbose_name = "Ön Test Denemesi"
        verbose_name_plural = "Ön Test Denemeleri"
        indexes = [
            models.Index(fields=['student', 'pre_test']),
            models.Index(fields=['completed_at']),
        ]

    def __str__(self):
        return f"{self.student.get_full_name()} - Hafta {self.pre_test.weekly_content.week_number} Ön Test (%{self.score})"


class PreEvaluationAnswer(models.Model):
    """
    Öğrencinin ön testteki her bir soruya verdiği yanıt.
    """
    attempt = models.ForeignKey(PreEvaluationAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(PreEvaluationQuestion, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(PreEvaluationOption, on_delete=models.CASCADE, null=True, blank=True)
    is_correct = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Ön Test Öğrenci Cevabı"
        verbose_name_plural = "Ön Test Öğrenci Cevapları"
        indexes = [
            models.Index(fields=['attempt', 'is_correct']),
        ]


class TemporaryWeekUnlock(models.Model):
    """
    Ön değerlendirme testinde yanlış yapılan sorular sonucu,
    ilgili önceki haftanın öğrenci için 2 GÜNLÜĞÜNE telafi ve inceleme amaçlı açılması.
    
    ÖNEMLİ KURAL:
    Bu geçici açılış süresince o haftanın hiçbir ilerleme yüzdesi, materyal tamamlaması,
    test sonucu DB'de sıfırlanmaz veya yeni puan/tamamlama kaydedilmez (Salt-okunur / İnceleme modu).
    """
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='temporary_week_unlocks')
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE, related_name='temporary_unlocks')
    unlocked_at = models.DateTimeField(auto_now_add=True, verbose_name="Kilit Açılma Tarihi")
    expires_at = models.DateTimeField(verbose_name="Geçerlilik Bitiş Tarihi (2 Gün)")
    source_pre_test = models.ForeignKey(PreEvaluationTest, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kaynak Ön Test")
    
    # TELAFİ SÜRECİNE ÖZEL İLERLEME VE SÜRE TAKİBİ (Normal T1/T2 ve 1/2. tur verilerini ASLA etkilemez)
    completion_percentage = models.FloatField(default=0.0, verbose_name="Telafi Tamamlama Yüzdesi")
    total_duration_seconds = models.PositiveIntegerField(default=0, verbose_name="Telafi Toplam Süre (sn)")
    is_completed = models.BooleanField(default=False, verbose_name="Telafi Tamamlandı mı?")

    class Meta:
        verbose_name = "Geçici Hafta Telafi Kilidi Açma"
        verbose_name_plural = "Geçici Hafta Telafi Kilit Açmaları"
        indexes = [
            models.Index(fields=['student', 'weekly_content']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"{self.student.email} - Hafta {self.weekly_content.week_number} Geçici Açık (Bitiş: {self.expires_at})"


class RemediationCompletedMaterial(models.Model):
    """
    Telafi kilidi aktif iken öğrencinin tamamladığı materyalleri ayrı tutan model.
    Normal CompletedMaterial (1. ve 2. Tur) kayıtlarını ASLA etkilemez.
    """
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='remediation_completed_materials')
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='remediation_completions')
    temporary_unlock = models.ForeignKey(TemporaryWeekUnlock, on_delete=models.CASCADE, related_name='completed_records', null=True, blank=True)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'material', 'temporary_unlock')
        verbose_name = "Telafi Tamamlanan Materyal"
        verbose_name_plural = "Telafi Tamamlanan Materyaller"
        indexes = [
            models.Index(fields=['student', 'material']),
            models.Index(fields=['temporary_unlock']),
        ]

    def __str__(self):
        return f"{self.student.email} - Telafi: {self.material.title}"


class RemediationTimeTracking(models.Model):
    """
    Telafi kilidi aktif iken materyallerde geçirilen süreleri ayrı tutan model.
    Normal TimeTracking (T1 ve T2 süreleri) tablosunu ASLA kirletmez veya etkilemez.
    """
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='remediation_time_trackings')
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE, related_name='remediation_trackings')
    material = models.ForeignKey(Material, on_delete=models.CASCADE, null=True, blank=True, related_name='remediation_time_records')
    temporary_unlock = models.ForeignKey(TemporaryWeekUnlock, on_delete=models.CASCADE, related_name='time_records', null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    date = models.DateField(auto_now_add=True)

    class Meta:
        verbose_name = "Telafi Zaman Takibi"
        verbose_name_plural = "Telafi Zaman Takip Kayıtları"
        indexes = [
            models.Index(fields=['student', 'weekly_content']),
            models.Index(fields=['temporary_unlock']),
            models.Index(fields=['student', 'date']),
        ]

    def __str__(self):
        return f"{self.student.email} - Telafi {self.duration_seconds}s"


class AcademicReportEmailLog(models.Model):
    """
    Bölüm bazlı haftalık D2 öğrenci analitiği raporlarının akademisyenlere
    gönderim kayıtlarını tutan ve mükerrer gönderimleri engelleyen model.
    """
    TRIGGER_CHOICES = [
        ('NEXT_WEEK_MINUS_ONE_DAY', 'Sonraki Hafta Açılışından 1 Gün Önce (20:00)'),
        ('CURRENT_WEEK_DEACTIVATION_DAY', 'Mevcut Hafta Kapanış Günü (20:00)'),
        ('MANUAL', 'Manuel Tetikleme'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'İşleniyor'),
        ('SUCCESS', 'Başarılı'),
        ('FAILED', 'Başarısız'),
    ]

    department = models.CharField(
        max_length=50, 
        choices=User.DEPARTMENT_CHOICES, 
        verbose_name="Bölüm"
    )
    week_number = models.IntegerField(verbose_name="Raporlanan Hafta")
    trigger_type = models.CharField(
        max_length=50, 
        choices=TRIGGER_CHOICES, 
        verbose_name="Tetikleme Tipi"
    )
    trigger_date = models.DateField(verbose_name="Tetikleme Tarihi")
    recipient_email = models.EmailField(verbose_name="Alıcı E-posta")
    recipient_name = models.CharField(max_length=255, blank=True, verbose_name="Alıcı Adı")
    pdf_filename = models.CharField(max_length=255, blank=True, verbose_name="PDF Dosya Adı")
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="Gönderim Zamanı")
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='PENDING', 
        verbose_name="Durum"
    )
    error_message = models.TextField(blank=True, null=True, verbose_name="Hata Mesajı")

    class Meta:
        verbose_name = "Akademik Rapor Mail Gönderim Kaydı"
        verbose_name_plural = "Akademik Rapor Mail Gönderim Kayıtları"
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['department', 'week_number', 'recipient_email', 'status']),
            models.Index(fields=['trigger_date', 'status']),
        ]

    def __str__(self):
        return f"{self.get_department_display()} - Hafta {self.week_number} -> {self.recipient_email} [{self.status}]"
