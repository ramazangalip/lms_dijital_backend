from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    DEPARTMENT_CHOICES = [
        ('ilahiyat', 'İlahiyat'),
        ('isg', 'İş Sağlığı Ve Güvenliği'),
        ('beslenmevediyetetik', 'Beslenme Ve Diyetetik'),
        ('hemsirelik', 'Hemşirelik'),
        ('saglikyonetimi', 'Sağlık Yönetimi'),
        ('webtasarimvekodlama', 'Web Tasarım Ve Kodlama'),

        
    ]

    email = models.EmailField(unique=True, verbose_name="E-posta Adresi")
    is_teacher = models.BooleanField(default=False, verbose_name="Akademisyen mi?")
    is_student = models.BooleanField(default=False, verbose_name="Öğrenci mi?")
    

    department = models.CharField(
        max_length=50, 
        choices=DEPARTMENT_CHOICES, 
        null=True, 
        blank=True, 
        verbose_name="Bölüm"
    )
    total_points = models.PositiveIntegerField(default=0, verbose_name="Toplam Puan")
    
    is_staff = models.BooleanField(default=False)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']


    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"

    class Meta:
        verbose_name = "Kullanıcı"
        verbose_name_plural = "Kullanıcılar"


class EmailOTP(models.Model):
    """
    Kayıt öncesi mail doğrulaması için geçici kodları tutan tablo.
    """
    email = models.EmailField(unique=True, verbose_name="E-posta")
    code = models.CharField(max_length=6, verbose_name="Doğrulama Kodu")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")

    def __str__(self):
        return f"{self.email} - {self.code}"

    class Meta:
        verbose_name = "E-posta Doğrulama Kodu"
        verbose_name_plural = "E-posta Doğrulama Kodları"