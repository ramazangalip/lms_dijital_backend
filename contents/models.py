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
    

    intro_title = models.CharField(max_length=255, default="Genel Tanıtım", verbose_name="Tanıtım Başlığı")
    intro_video_url = models.URLField(blank=True, null=True, verbose_name="Tanıtım Videosu (Embed Link)")

    class Meta:
        verbose_name = "Haftalık İçerik"
        verbose_name_plural = "Haftalık İçerikler"
        ordering = ['week_number']

    def __str__(self):
        return f"Hafta {self.week_number} - {self.title}"

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

    def __str__(self):
        status = "Tamamladı" if self.is_watched else "Tamamlamadı"
        return f"{self.student.email} - {status}"

class Material(models.Model):
    CONTENT_TYPES = (
        ('video', 'Video'),
        ('podcast', 'Podcast'),
        ('form', 'Bilgi Testi'),
        ('pdf', 'Ders Notu (PDF)'),
    )
    parent_content = models.ForeignKey(
        WeeklyContent, 
        related_name='materials', 
        on_delete=models.CASCADE
    )
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPES)
    embed_url = models.URLField(verbose_name="Materyal Linki", help_text="Video/Podcast embed kodu veya OneDrive PDF indirme linki.")
    title = models.CharField(max_length=200, verbose_name="Materyal Başlığı")
    
   
    point_value = models.PositiveIntegerField(default=0, verbose_name="Tamamlama Puanı")

    def __str__(self):
        return f"{self.get_content_type_display()} - {self.title}"
    


class StudentProgress(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE)
    is_completed = models.BooleanField(default=False)
    completion_percentage = models.FloatField(default=0.0) 
    last_accessed = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('student', 'weekly_content')
        verbose_name = "Öğrenci İlerlemesi"
        verbose_name_plural = "Öğrenci İlerlemeleri"

class TimeTracking(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE)
    duration_seconds = models.PositiveIntegerField(default=0)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.email} - Hafta {self.weekly_content.week_number} - {self.duration_seconds}s"
    
class CompletedMaterial(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'material')

class StudentQuestion(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    weekly_content = models.ForeignKey(WeeklyContent, on_delete=models.CASCADE)
    question_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.first_name} - Hafta {self.weekly_content.week_number}"

class Quiz(models.Model):
    """Her bir test materyali için ana başlık"""
    material = models.OneToOneField('Material', on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Test: {self.title} (Hafta {self.material.parent_content.week_number})"

class QuizQuestion(models.Model):
    """Sınavın içindeki her bir soru"""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.question_text[:50]

class QuizOption(models.Model):
    """Soruların şıkları (A, B, C, D...)"""
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.option_text

class StudentQuizAttempt(models.Model):
    """Öğrencinin genel sınav sonucu"""
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField() 
    correct_answers = models.IntegerField()
    wrong_answers = models.IntegerField()
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.first_name} - {self.quiz.title} - %{self.score}"

class StudentAnswer(models.Model):
    """Öğrencinin her bir soruya verdiği spesifik cevap"""
    attempt = models.ForeignKey(StudentQuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(QuizOption, on_delete=models.CASCADE)
    is_correct = models.BooleanField()

class Flashcard(models.Model):
    weekly_content = models.ForeignKey(
        WeeklyContent, 
        related_name='flashcards', 
        on_delete=models.CASCADE
    )
    question = models.TextField()
    answer = models.TextField()
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']