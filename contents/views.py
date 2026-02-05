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

# views.py başındaki importları ve init_vertex_ai kısmını şu şekilde güncelleyin:

def init_vertex_ai():
    """Vertex AI bağlantısını merkezi olarak yönetir ve modeli döndürer."""
    PROJECT_ID = "lmsproject-484210"
    LOCATION = "us-central1"
    
    # Kimlik bilgileri kontrolü
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    
    if creds_json:
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        vertexai.init(project=PROJECT_ID, location=LOCATION, credentials=credentials)
    else:
        # Local geliştirme için default kimlikleri kullanır
        vertexai.init(project=PROJECT_ID, location=LOCATION)
    
    # Modeli sistem yönergesi (system instruction) ile başlatarak "Genel AI" yapıyoruz
    model = GenerativeModel(
        model_name="gemini-2.5-pro",
        system_instruction="Sen BÜ-LMS akıllı eğitim asistanısın. Öğrencilere her konuda yardımcı olabilirsin."
    )
    return model

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
            # SADECE SÜREYİ KAYDET (İlerlemeye dokunma!)
            tracking, _ = TimeTracking.objects.get_or_create(
                student=request.user,
                weekly_content=weekly_content,
                date=date.today()
            )
            tracking.duration_seconds += seconds
            tracking.save()
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except WeeklyContent.DoesNotExist:
            return Response({"error": "İçerik bulunamadı."}, status=status.HTTP_404_NOT_FOUND)

class CompleteMaterialView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        print("\n" + "="*60)
        print(f"DEBUG: [CompleteMaterialView] POST BAŞLADI")
        
        serializer = CompleteMaterialSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        material_id_raw = serializer.validated_data.get('material_id')

        # 1. Materyal var mı kontrolü
        try:
            material = Material.objects.get(id=material_id_raw)
        except Material.DoesNotExist:
            return Response({"error": "Materyal bulunamadı"}, status=status.HTTP_404_NOT_FOUND)

        # 2. Daha önce tamamlanmış mı kontrolü (PUAN İÇİN KRİTİK)
        # Eğer kayıt varsa created=False döner
        completed_record, created = CompletedMaterial.objects.get_or_create(
            student=request.user, 
            material=material
        )

        new_points = 0
        if created:
            # ÖĞRENCİ BU MATERYALİ İLK KEZ TAMAMLIYOR
            # Materyal modelindeki point_value kadar puan ekle
            new_points = material.point_value
            request.user.total_points += new_points
            request.user.save()
            print(f"DEBUG: Öğrenci {new_points} puan kazandı. Yeni Toplam: {request.user.total_points}")
        else:
            print("DEBUG: Bu materyal zaten tamamlanmış, puan eklenmedi.")

        # 3. İlerleme Hesaplama (Mevcut kodunuzdaki mantık)
        weekly_content = material.parent_content
        total_mats = weekly_content.materials.count()
        done_mats = CompletedMaterial.objects.filter(
            student=request.user, 
            material__parent_content=weekly_content
        ).count()

        percentage = (done_mats / total_mats) * 100 if total_mats > 0 else 0
        
        progress, _ = StudentProgress.objects.get_or_create(
            student=request.user, 
            weekly_content=weekly_content
        )
        progress.completion_percentage = round(percentage, 2)
        progress.is_completed = (percentage >= 100)
        progress.save()

        print(f"DEBUG: İşlem Başarılı. Yeni Yüzde: %{progress.completion_percentage}")
        print("="*60 + "\n")

        # Frontend'e "new_points_earned" bilgisini gönderiyoruz ki bildirim çıkabilsin
        return Response({
            "status": "success", 
            "current_percentage": progress.completion_percentage,
            "material_id": str(material.id),
            "new_points_earned": new_points,
            "total_points": request.user.total_points
        }, status=status.HTTP_200_OK)

class CompletedMaterialIdsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Tüm ID'leri string olarak dönüyoruz
        completed_ids = CompletedMaterial.objects.filter(
            student=request.user
        ).values_list('material_id', flat=True)
        
        string_ids = [str(m_id) for m_id in completed_ids]
        print(f"DEBUG: CompletedMaterialIdsView -> {len(string_ids)} adet ID gönderildi.")
        return Response(string_ids)

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
    permission_classes = [IsAuthenticated]
    authentication_classes = []
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
            model = init_vertex_ai()
            response = model.generate_content(user_message)

            if response and response.candidates:
                try:
                 
                    ai_response_text = "".join([part.text for part in response.candidates[0].content.parts])
                except (AttributeError, IndexError, Exception):
               
                    ai_response_text = "Üzgünüm, bu içeriği şu an işleyemiyorum."
            else:
                ai_response_text = "Üzgünüm, bu soruya şu an yanıt veremiyorum."

            if week_id:
                try:
                    weekly_content = WeeklyContent.objects.get(id=week_id)
                    StudentQuestion.objects.create(
                        student=request.user, 
                        weekly_content=weekly_content, 
                        question_text=user_message
                    )
                except: 
                    pass
                
            return Response({"response": ai_response_text}, status=200)
            
        except Exception as e: 
            print(f"AI Chat Error Detailed: {str(e)}")
            return Response({"response": "Şu an genel bilgi havuzuna erişim sağlanamıyor, lütfen birazdan tekrar deneyin."}, status=500)

# --- QUIZ (SINAV) SİSTEMİ ---


class QuizSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, quiz_id):
       
        quiz = get_object_or_404(Quiz, id=str(quiz_id))
        
        if StudentQuizAttempt.objects.filter(student=request.user, quiz=quiz).exists():
            return Response({"error": "Bu testi zaten çözdünüz."}, status=403)

        answers_data = request.data.get('answers', [])
        correct_count, wrong_count = 0, 0
        attempt = StudentQuizAttempt.objects.create(
            student=request.user, quiz=quiz, score=0, correct_answers=0, wrong_answers=0
        )

        for ans in answers_data:
            
            q_id = str(ans.get('question_id'))
            o_id = str(ans.get('option_id'))
            
            try:
                question = get_object_or_404(QuizQuestion, id=q_id, quiz=quiz)
                option = get_object_or_404(QuizOption, id=o_id, question=question)
                
                if option.is_correct:
                    correct_count += 1
                else:
                    wrong_count += 1
                
                StudentAnswer.objects.create(
                    attempt=attempt, question=question, 
                    selected_option=option, is_correct=option.is_correct
                )
            except Exception as e:
                print(f"DEBUG: Quiz ID Eşleşme Hatası -> {str(e)}")
          

        total = quiz.questions.count()
        attempt.score = round((correct_count / total) * 100) if total > 0 else 0
        attempt.correct_answers = correct_count
        attempt.wrong_answers = (total - correct_count)
        attempt.save()

        
        CompletedMaterial.objects.get_or_create(student=request.user, material=quiz.material)
        
        
        weekly_content = quiz.material.parent_content
        total_mats = weekly_content.materials.count()
        done_mats = CompletedMaterial.objects.filter(
            student=request.user, material__parent_content=weekly_content
        ).count()
        
        perc = (done_mats / total_mats) * 100 if total_mats > 0 else 0
        prog, _ = StudentProgress.objects.get_or_create(student=request.user, weekly_content=weekly_content)
        prog.completion_percentage = round(perc, 2)
        prog.is_completed = (perc >= 100)
        prog.save()

        return Response({
            "attempt_id": str(attempt.id),  
            "score": attempt.score, 
            "correct": correct_count, 
            "wrong": (total - correct_count)
        }, status=201)
class QuizLastAttemptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, quiz_id):
        
        attempt = StudentQuizAttempt.objects.filter(student=request.user, quiz_id=str(quiz_id)).order_by('-completed_at').first()
        if attempt:
            return Response({
                "id": str(attempt.id), 
                "score": attempt.score,
                "correct": attempt.correct_answers,
                "wrong": attempt.wrong_answers,     
                "correct_answers": attempt.correct_answers,
                "wrong_answers": attempt.wrong_answers 
            }, status=200)

class QuizAIAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        print("\n" + "="*60)
        print(f"DEBUG: [QuizAIAnalysisView] Analiz İsteği Geldi. ID: {attempt_id}")
        
        try:
            try:
                attempt = StudentQuizAttempt.objects.get(id=str(attempt_id), student=request.user)
                print(f"DEBUG: Sınav Kaydı Bulundu -> {attempt.quiz.title}")
            except StudentQuizAttempt.DoesNotExist:
                print(f"DEBUG: !!! HATA: ID {attempt_id} ile eşleşen sınav kaydı BULUNAMADI !!!")
                return Response({"error": "Sınav verisi bulunamadı. Lütfen sayfayı yenileyip tekrar deneyin."}, status=404)

            wrong_answers = StudentAnswer.objects.filter(attempt=attempt, is_correct=False).select_related('question')
            user_name = request.user.first_name if request.user.first_name else request.user.username
            
            details = ""
            for ans in wrong_answers:
                correct_opt = QuizOption.objects.filter(question=ans.question, is_correct=True).first()
                details += (f"Soru: {ans.question.question_text}\n"
                           f"Öğrencinin Yanlış Cevabı: {ans.selected_option.option_text}\n"
                           f"Doğru Cevap: {correct_opt.option_text if correct_opt else '?'}\n\n")

   
            prompt = (
                f"Bir eğitim danışmanı olarak, öğrencim {user_name} için '{attempt.quiz.title}' sınavındaki "
                f"%{attempt.score} başarısını analiz et. Hataları:\n{details}\n"
                f"Lütfen mesaja direkt '{user_name}, merhaba!' veya 'Selam {user_name}!' gibi samimi bir girişle başla. "
                f"Hatalarını nazikçe açıkla, moral ver ve gelişim için ne yapması gerektiğini söyle."
            )
            
            print("DEBUG: Vertex AI İsteği Gönderiliyor...")
            model = init_vertex_ai()
            response = model.generate_content(prompt)
            
            
            if not response or not response.text:
                print("DEBUG: AI Modelinden boş yanıt döndü.")
                return Response({"ai_feedback": "Tebrikler, sınavı tamamladın! Şu an detaylı analiz oluşturulamıyor ama başarılarının devamını dilerim."}, status=200)

            print("DEBUG: Analiz Başarıyla Oluşturuldu.")
            print("="*60 + "\n")
            return Response({"ai_feedback": response.text}, status=200)
            
        except Exception as e: 
            print(f"DEBUG: !!! BEKLENMEDİK HATA !!! -> {str(e)}")
            return Response({"error": f"Sistemsel bir hata oluştu: {str(e)}"}, status=500)

class BulkAcademicReportView(APIView):
    """
    Akademisyen Paneli için toplu PDF raporu verisi sağlar.
    Bölüm filtrelemesi ve puan sistemini destekler.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        # 1. Filtre parametresini al (Frontend: selectedDepartment)
        department_filter = request.query_params.get('department', 'all')
        
        # 2. Sadece öğrencileri getir (Staff/Teacher hariç)
        students = User.objects.filter(is_staff=False, is_teacher=False)

        # 3. Eğer spesifik bir bölüm seçildiyse filtrele
        if department_filter and department_filter != 'all':
            students = students.filter(department=department_filter)
        
        students = students.order_by('first_name')
        
        report_data = []

        for student in students:
            weekly_stats = []
            
            # Toplam çalışma süresini hesapla
            overall_total_seconds = TimeTracking.objects.filter(
                student=student
            ).aggregate(Sum('duration_seconds'))['duration_seconds__sum'] or 0
            
            # 14 Haftalık döngü
            for i in range(1, 15):
                # Haftalık süre
                duration = TimeTracking.objects.filter(
                    student=student, 
                    weekly_content__week_number=i
                ).aggregate(Sum('duration_seconds'))['duration_seconds__sum'] or 0
                
                # Haftalık ilerleme yüzdesi
                progress_record = StudentProgress.objects.filter(
                    student=student, 
                    weekly_content__week_number=i
                ).first()
                progress_value = progress_record.completion_percentage if progress_record else 0

                # Haftalık sınav sonucu
                attempt = StudentQuizAttempt.objects.filter(
                    student=student, 
                    quiz__material__parent_content__week_number=i
                ).first()

                weekly_stats.append({
                    "week": i,
                    "progress": float(progress_value), 
                    "duration_seconds": duration,
                    "correct": attempt.correct_answers if attempt else 0,
                    "wrong": attempt.wrong_answers if attempt else 0,
                    "has_quiz": True if attempt else False
                })

            # Öğrenci verisini paketle (Puan ve Bölüm dahil)
            report_data.append({
                "id": str(student.id),
                "full_name": f"{student.first_name} {student.last_name}".upper(),
                "email": student.email,
                "department": student.department, # Filtreleme ve PDF başlığı için
                "total_points": getattr(student, 'total_points', 0), # Kazanılan kümülatif puan
                "total_time": overall_total_seconds,
                "weekly_breakdown": weekly_stats
            })

        return Response(report_data, status=status.HTTP_200_OK)