from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import *
from .serializers import *
from django.utils import timezone
from datetime import date, timedelta
from rest_framework.permissions import IsAdminUser
from django.db.models import Sum
from django.conf import settings
from django.shortcuts import get_object_or_404
import google as genai
from google.cloud import aiplatform
import requests
from google.auth import default
from google.auth.transport.requests import Request as AuthRequest
import vertexai
from vertexai.generative_models import GenerativeModel
from google.oauth2 import service_account
import os
import json

# --- YARDIMCI FONKSİYONLAR ---

def init_vertex_ai():
    """Vertex AI bağlantısını merkezi olarak yönetir."""
    PROJECT_ID = "lmsproject-484210"
    LOCATION = "us-central1"
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    
    if creds_json:
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        vertexai.init(project=PROJECT_ID, location=LOCATION, credentials=credentials)
    else:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
    
    # Endpoint yerine doğrudan modeli döndürelim
    return GenerativeModel("gemini-1.5-flash") # En hızlı ve verimli genel model

# --- ANA İÇERİK VIEW ---

class WeeklyContentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        week_number = request.query_params.get('week_number')
        if week_number:
            content = WeeklyContent.objects.filter(week_number=week_number).first()
            if content:
                week_one = WeeklyContent.objects.filter(week_number=1).first()
                # context={'request': request} eklemek Serializer'daki is_locked metodunun 
                # kullanıcıyı (request.user) tanıması için ZORUNLUDUR.
                serializer = WeeklyContentSerializer(content, context={'request': request})
                data = serializer.data
                
                if week_one:
                    data['intro_video_url'] = week_one.intro_video_url
                    data['intro_title'] = week_one.intro_title
                return Response(data, status=status.HTTP_200_OK)
            return Response({"detail": "Bu hafta henüz boş."}, status=status.HTTP_404_NOT_FOUND)
            
        contents = WeeklyContent.objects.all().order_by('week_number')
        # Liste görünümünde de context verilmeli ki her hafta için kilit hesabı yapılabilsin
        serializer = WeeklyContentSerializer(contents, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        if not getattr(request.user, 'is_teacher', False):
            return Response({"error": "İçerik ekleme yetkiniz bulunmamaktadır."}, status=status.HTTP_403_FORBIDDEN)

        intro_url = request.data.get('intro_video_url')
        intro_title = request.data.get('intro_title')
        # release_date artık request.data içinde gelecek, Serializer bunu otomatik karşılayacak

        serializer = WeeklyContentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_instance = serializer.save()
            
            if intro_url:
                WeeklyContent.objects.filter(week_number=1).update(
                    intro_video_url=intro_url,
                    intro_title=intro_title if intro_title else "Genel Tanıtım"
                )
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CompleteIntroVideoView(APIView):
    """Öğrenci genel tanıtım videosunu bitirdiğinde tüm haftaların kilidi açılır."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # OneToOneField sayesinde her öğrenci için tek bir "izledi" kaydı tutulur
        completion, created = IntroVideoCompletion.objects.get_or_create(student=request.user)
        completion.is_watched = True
        completion.save()
        
        return Response({
            "status": "success", 
            "message": "Genel tanıtım tamamlandı. Sistem kilidi açıldı."
        })

class ContentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, week_number):
        content = WeeklyContent.objects.filter(week_number=week_number).first()
        if not content:
            return Response({"error": f"{week_number}. hafta içeriği bulunamadı."}, status=status.HTTP_404_NOT_FOUND)
        serializer = WeeklyContentSerializer(content, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

# --- TAKİP VE İLERLEME SİSTEMİ ---

class TrackActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ActivityTrackSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        weekly_content_id = serializer.validated_data.get('weekly_content_id')
        seconds = serializer.validated_data.get('seconds', 30)
        
        try:
            weekly_content = WeeklyContent.objects.get(id=weekly_content_id)
            tracking, _ = TimeTracking.objects.get_or_create(
                student=request.user,
                weekly_content=weekly_content,
                date=date.today()
            )
            tracking.duration_seconds += seconds
            tracking.save()

            StudentProgress.objects.get_or_create(student=request.user, weekly_content=weekly_content)
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except WeeklyContent.DoesNotExist:
            return Response({"error": "Haftalık içerik bulunamadı."}, status=status.HTTP_404_NOT_FOUND)

class CompleteMaterialView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CompleteMaterialSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        material_id = serializer.validated_data.get('material_id')
        material = get_object_or_404(Material, id=material_id)
        weekly_content = material.parent_content
        
        CompletedMaterial.objects.get_or_create(student=request.user, material=material)

        total_materials = weekly_content.materials.count()
        completed_count = CompletedMaterial.objects.filter(student=request.user, material__parent_content=weekly_content).count()

        percentage = (completed_count / total_materials) * 100 if total_materials > 0 else 0
        progress, _ = StudentProgress.objects.get_or_create(student=request.user, weekly_content=weekly_content)
        progress.completion_percentage = round(percentage, 2)
        progress.is_completed = (percentage >= 100)
        progress.save()

        return Response({"status": "success", "current_percentage": progress.completion_percentage}, status=status.HTTP_200_OK)

class CompletedMaterialIdsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        completed_ids = CompletedMaterial.objects.filter(student=request.user).values_list('material_id', flat=True)
        return Response(list(completed_ids))

class StudentProgressListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        progresses = StudentProgress.objects.filter(student=request.user).order_by('weekly_content__week_number')
        serializer = StudentProgressSerializer(progresses, many=True)
        return Response(serializer.data)

# --- HOCA PANELİ VE ANALİTİKLER ---

class TeacherAnalyticsView(APIView):
    permission_classes = [IsAdminUser] 

    def get(self, request, student_id=None):
        if student_id:
            try:
                student = User.objects.get(id=student_id)
                one_week_ago = timezone.now().date() - timedelta(days=7)
                time_stats = TimeTracking.objects.filter(student=student, date__gte=one_week_ago).values('weekly_content__title', 'weekly_content__week_number').annotate(total_seconds=Sum('duration_seconds')).order_by('weekly_content__week_number')
                progress_stats = StudentProgress.objects.filter(student=student).values('weekly_content__title', 'completion_percentage', 'is_completed')
                return Response({"student_info": f"{student.first_name} {student.last_name}", "weekly_analysis": list(time_stats), "progress_analysis": list(progress_stats)})
            except User.DoesNotExist: return Response({"error": "Öğrenci bulunamadı."}, status=404)
        else:
            students = User.objects.filter(is_staff=False)
            serializer = StudentAnalyticsSerializer(students, many=True)
            return Response(serializer.data)

class StudentAnalyticsView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        students = User.objects.filter(is_staff=False)
        serializer = StudentAnalyticsSerializer(students, many=True)
        return Response(serializer.data)

# --- YAPAY ZEKA SOHBET ---

class AIChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_message = request.data.get("message")
        week_id = request.data.get("weekly_content_id")
        
        if not user_message: 
            return Response({"error": "Mesaj boş olamaz."}, status=400)

        try:
            # Genel modelimizi başlatalım
            model = init_vertex_ai()
            
            # Öğrencinin sorusunu genel zekaya gönderiyoruz
            # Ders içeriğine sadık kalmasını istersen prompt'un başına ekleme yapabilirsin
            response = model.generate_content(user_message)
            ai_response_text = response.text

            # Soruyu veritabanına kaydetmeye devam edelim (Hoca panelinde görmek için)
            if week_id:
                try:
                    weekly_content = WeeklyContent.objects.get(id=week_id)
                    StudentQuestion.objects.create(
                        student=request.user, 
                        weekly_content=weekly_content, 
                        question_text=user_message
                    )
                except: pass
                
            return Response({"response": ai_response_text}, status=200)
            
        except Exception as e: 
            return Response({"response": "Asistan şu an cevap veremiyor."}, status=500)

# --- QUIZ (SINAV) SİSTEMİ ---

class QuizSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)
        if StudentQuizAttempt.objects.filter(student=request.user, quiz=quiz).exists():
            return Response({"error": "Bu testi zaten çözdünüz."}, status=403)

        answers_data = request.data.get('answers', [])
        correct_count, wrong_count = 0, 0
        attempt = StudentQuizAttempt.objects.create(student=request.user, quiz=quiz, score=0, correct_answers=0, wrong_answers=0)

        for ans in answers_data:
            question = get_object_or_404(QuizQuestion, id=ans.get('question_id'), quiz=quiz)
            option = get_object_or_404(QuizOption, id=ans.get('option_id'), question=question)
            if option.is_correct: correct_count += 1
            else: wrong_count += 1
            StudentAnswer.objects.create(attempt=attempt, question=question, selected_option=option, is_correct=option.is_correct)

        total = quiz.questions.count()
        attempt.score = round((correct_count / total) * 100) if total > 0 else 0
        attempt.correct_answers, attempt.wrong_answers = correct_count, (total - correct_count)
        attempt.save()

        CompletedMaterial.objects.get_or_create(student=request.user, material=quiz.material)
        
        # İlerleme Güncelleme
        weekly_content = quiz.material.parent_content
        total_mats = weekly_content.materials.count()
        done_mats = CompletedMaterial.objects.filter(student=request.user, material__parent_content=weekly_content).count()
        perc = (done_mats / total_mats) * 100 if total_mats > 0 else 0
        prog, _ = StudentProgress.objects.get_or_create(student=request.user, weekly_content=weekly_content)
        prog.completion_percentage, prog.is_completed = round(perc, 2), (perc >= 100)
        prog.save()

        return Response({"attempt_id": attempt.id, "score": attempt.score, "correct": correct_count, "wrong": (total - correct_count)}, status=201)

class QuizLastAttemptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, quiz_id):
        attempt = StudentQuizAttempt.objects.filter(student=request.user, quiz_id=quiz_id).order_by('-completed_at').first()
        if attempt:
            return Response({
                "id": attempt.id,
                "score": attempt.score,
                "correct_answers": attempt.correct_answers,
                "wrong_answers": attempt.wrong_answers
            }, status=200)
        return Response({"detail": "Henüz çözülmedi"}, status=404)

class QuizAIAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        try:
            attempt = StudentQuizAttempt.objects.get(id=attempt_id, student=request.user)
            wrong_answers = StudentAnswer.objects.filter(attempt=attempt, is_correct=False)
            user_name = request.user.first_name if request.user.first_name else request.user.username
            
            details = ""
            for ans in wrong_answers:
                correct_opt = QuizOption.objects.filter(question=ans.question, is_correct=True).first()
                details += (f"Soru: {ans.question.question_text}\n"
                           f"Öğrencinin Yanlış Cevabı: {ans.selected_option.option_text}\n"
                           f"Doğru Cevap: {correct_opt.option_text if correct_opt else '?'}\n\n")

            # Analiz için genel zekaya detaylı bir "prompt" gönderiyoruz
            prompt = (
                f"Bir eğitim danışmanı olarak, öğrencim {user_name} için '{attempt.quiz.title}' sınavındaki "
                f"%{attempt.score} başarısını analiz et. Hataları:\n{details}\n"
                f"Lütfen mesaja direkt '{user_name}, merhaba!' veya 'Selam {user_name}!' gibi samimi bir girişle başla. "
                f"Hatalarını nazikçe açıkla, moral ver ve gelişim için ne yapması gerektiğini söyle."
            )
            
            model = init_vertex_ai()
            response = model.generate_content(prompt)
            
            return Response({"ai_feedback": response.text}, status=200)
            
        except Exception as e: 
            return Response({"error": "Genel analiz şu an oluşturulamadı."}, status=500)