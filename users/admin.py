from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, EmailOTP


class CustomUserAdmin(UserAdmin):
    model = User
    # Listeleme ekranından department kaldırıldı
    list_display = ['email', 'username', 'is_teacher', 'is_student', 'is_staff']
    
    # Düzenleme ekranından department alanı kaldırıldı
    fieldsets = UserAdmin.fieldsets + (
        ('LMS Yetkileri', {'fields': ('is_teacher', 'is_student')}),
    )
    
    # Yeni kullanıcı ekleme ekranından department alanı kaldırıldı
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('LMS Yetkileri', {'fields': ('is_teacher', 'is_student')}),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(EmailOTP)