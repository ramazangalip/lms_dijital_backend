import random
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.core.mail import send_mail
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User, EmailOTP
from .serializers import *

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer

class SendOTPView(APIView):
    """Kayıt için OTP gönderir (Email sistemde olmamalı)"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get('email')
        if not email or not email.endswith('@bingol.edu.tr'):
            return Response({"error": "Geçerli bir kurum adresi giriniz."}, status=400)

        if User.objects.filter(email=email).exists():
            return Response({"error": "Bu e-posta zaten kayıtlı."}, status=400)

        return self.send_otp(email, "Kayıt Doğrulama")

    def send_otp(self, email, subject_text):
        otp_code = str(random.randint(100000, 999999))
        EmailOTP.objects.update_or_create(email=email, defaults={'code': otp_code})
        
        try:
            send_mail(
                subject=f'LMS {subject_text} Kodu',
                message=f'İşleminiz için doğrulama kodunuz: {otp_code}',
                from_email='ramazansaidgalip@gmail.com',
                recipient_list=[email],
                fail_silently=False,
            )
            return Response({"message": "Kod gönderildi."}, status=200)
        except:
            return Response({"error": "E-posta hatası."}, status=500)

class SendResetOTPView(SendOTPView):
    authentication_classes = []
    """Şifre sıfırlama için OTP gönderir (Email sistemde kayıtlı olmalı)"""
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "E-posta gerekli."}, status=400)

        if not User.objects.filter(email=email).exists():
            return Response({"error": "Bu e-posta adresiyle kayıtlı bir kullanıcı bulunamadı."}, status=404)

        return self.send_otp(email, "Şifre Sıfırlama")

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

class PasswordResetConfirmView(APIView):
    """Kodu ve yeni şifreyi alır, doğrularsa şifreyi günceller."""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Şifreniz başarıyla sıfırlandı."}, status=200)
        return Response(serializer.errors, status=400)