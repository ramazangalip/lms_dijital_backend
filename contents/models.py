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
    option_text = models.CharField(max_length=255)
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