from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, EmailOTP

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        token['email'] = user.email
        token['is_teacher'] = user.is_teacher
        token['is_student'] = user.is_student
        token['full_name'] = f"{user.first_name} {user.last_name}"
        
        return token

class RegisterSerializer(serializers.ModelSerializer):
    code = serializers.CharField(write_only=True, required=True)
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    
    class Meta:
        model = User
        fields = ['email', 'password', 'first_name', 'last_name', 'code']

    def validate_email(self, value):
        if not value.endswith('@bingol.edu.tr'):
            raise serializers.ValidationError("Sadece @bingol.edu.tr uzantılı adresler kayıt olabilir.")
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Bu e-posta adresi zaten kullanımda.")
        return value

    def validate(self, data):
        email = data.get('email')
        code = data.get('code')
        
        otp_record = EmailOTP.objects.filter(email=email, code=code).first()
        if not otp_record:
            raise serializers.ValidationError({"code": "Doğrulama kodu geçersiz veya hatalı."})
        
        return data

    def create(self, validated_data):
        # Kullanılan OTP kodunu temizle
        EmailOTP.objects.filter(email=validated_data['email']).delete()
        
        user = User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_student=True,
            is_teacher=False
        )
        return user

class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True, 
        validators=[validate_password], 
        style={'input_type': 'password'}
    )

    def validate_email(self, value):
        # 1. Uzantı Kontrolü
        if not value.endswith('@bingol.edu.tr'):
            raise serializers.ValidationError("Sadece @bingol.edu.tr uzantılı adresler şifre sıfırlayabilir.")
        
        
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Bu e-posta adresiyle kayıtlı bir kullanıcı bulunamadı.")
        
        return value

    def validate(self, data):
        email = data.get('email')
        code = data.get('code')

        otp_record = EmailOTP.objects.filter(email=email, code=code).first()
        if not otp_record:
            raise serializers.ValidationError({"code": "Doğrulama kodu geçersiz veya hatalı."})

        
        return data

    def save(self):
        email = self.validated_data['email']
        new_password = self.validated_data['new_password']
        user = User.objects.get(email=email)
        user.set_password(new_password)
        user.save()

        EmailOTP.objects.filter(email=email).delete()
        
        return user