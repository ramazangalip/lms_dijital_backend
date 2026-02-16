from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, EmailOTP

class CustomUserAdmin(UserAdmin):
    model = User
    
    # 1. Liste ekranında görünecek sütunlar (Puan ve Bölüm eklendi)
    list_display = ['email', 'username', 'department', 'total_points', 'is_teacher', 'is_student', 'is_staff']
    
    # 2. Liste ekranında bu alanlara göre filtreleme yapabilme
    list_filter = UserAdmin.list_filter + ('department', 'is_teacher', 'is_student')
    
    # 3. Kullanıcı düzenleme sayfasında (Detay) bu alanları görebilme ve değiştirme
    fieldsets = UserAdmin.fieldsets + (
        ('LMS Bilgileri ve Yetkileri', {
            'fields': ('department', 'total_points', 'is_teacher', 'is_student')
        }),
    )
    
    # 4. Yeni kullanıcı oluştururken bu alanları doldurabilme
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('LMS Bilgileri', {
            'fields': ('department', 'total_points', 'is_teacher', 'is_student')
        }),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(EmailOTP)