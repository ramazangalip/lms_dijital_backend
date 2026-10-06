
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import *
from .serializers import *
from django.utils import timezone
from datetime import date, timedelta
from rest_framework.permissions import IsAdminUser
from django.db.models import Sum, Count, Avg, F, Q, FloatField
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
from rest_framework.renderers import BaseRenderer
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

# --- YARDIMCI FONKSİYONLAR ---

# views.py başındaki importları ve init_vertex_ai kısmını şu şekilde güncelleyin:

def init_vertex_ai():
    """Vertex AI için sadece Erişim Token'ı hazırlar. RAM ve Süre dostudur."""
    import os, json
    from django.conf import settings
    from google.oauth2 import service_account
    import google.auth.transport.requests

    PROJECT_ID = "lmsproject-484210"
    LOCATION = "us-central1"
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    
    try:
        if creds_json:
            creds_dict = json.loads(creds_json.strip())
            credentials = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        else:
            local_path = os.path.join(settings.BASE_DIR, "google_creds.json")
            credentials = service_account.Credentials.from_service_account_file(
                local_path, scopes=['https://www.googleapis.com/auth/cloud-platform']
            )

        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        
        return {
            "token": credentials.token,
            "project_id": PROJECT_ID,
            "location": LOCATION,
            "model_id": "gemini-2.5-pro"
        }
    except Exception as e:
        print(f"DEBUG: Kimlik Hatası -> {str(e)}")
        raise e

# --- ANA İÇERİK VIEW ---

class WeeklyContentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        week_number = request.query_params.get('week_number')
        if week_number:
            content = WeeklyContent.objects.filter(week_number=week_number).prefetch_related(
                'materials__quiz__questions__options',
                'flashcards'
            ).first()
            if content:
                # 1. haftayı buluyoruz (intro bilgilerini oradan kopyalamak için)
                week_one = WeeklyContent.objects.filter(week_number=1).first()
                
                # context={'request': request} eklemek Serializer'daki is_locked metodunun 
                # kullanıcıyı (request.user) tanıması için ZORUNLUDUR.
                serializer = WeeklyContentSerializer(content, context={'request': request})
                data = serializer.data
                
                # Eğer 1. hafta varsa, güncel intro bilgilerini (URL, Başlık, Metin) her hafta talebine ekle
                if week_one:
                    data['intro_video_url'] = week_one.intro_video_url
                    data['intro_title'] = week_one.intro_title
                    data['intro_description'] = week_one.intro_description # YENİ: Metin desteği eklendi
                
                return Response(data, status=status.HTTP_200_OK)
            return Response({"detail": "Bu hafta henüz boş."}, status=status.HTTP_404_NOT_FOUND)
            
        contents = WeeklyContent.objects.prefetch_related(
            'materials__quiz__questions__options',
            'flashcards'
        ).order_by('week_number')
        # Liste görünümünde de context verilmeli ki her hafta için kilit hesabı yapılabilsin
        serializer = WeeklyContentSerializer(contents, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        if not getattr(request.user, 'is_teacher', False):
            return Response({"error": "İçerik ekleme yetkiniz bulunmamaktadır."}, status=status.HTTP_403_FORBIDDEN)

        # Frontend'den gelen verileri yakala
        intro_url = request.data.get('intro_video_url')
        intro_title = request.data.get('intro_title')
        intro_desc = request.data.get('intro_description') # YENİ: Metin bilgisini al

        serializer = WeeklyContentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            content_instance = serializer.save()
            
            # Eğer bir intro bilgisi gönderilmişse, sistem genelinde 1. haftanın intro alanlarını güncelle
            if intro_url or intro_desc:
                WeeklyContent.objects.filter(week_number=1).update(
                    intro_video_url=intro_url,
                    intro_title=intro_title if intro_title else "Genel Tanıtım",
                    intro_description=intro_desc # YENİ: Veritabanına metni kaydet
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
        # YENİ: Frontend'den gelen material_id'yi alıyoruz
        material_id = request.data.get('material_id') 

        try:
            weekly_content = WeeklyContent.objects.get(id=weekly_content_id)
            progress, _ = StudentProgress.objects.get_or_create(
                student=request.user, 
                weekly_content=weekly_content
            )
            current_round = progress.current_attempt_round

            # KRİTİK DEĞİŞİKLİK: 
            # get_or_create içine 'material' alanını ekliyoruz.
            # Böylece her materyal için ayrı bir satır oluşur.
            tracking, _ = TimeTracking.objects.get_or_create(
                student=request.user,
                weekly_content=weekly_content,
                material_id=material_id, # Materyal bazlı satır
                attempt_round=current_round,
                date=date.today()
            )
            tracking.duration_seconds += seconds
            tracking.save()
            
            return Response({
                "status": "success", 
                "material": tracking.material.title if tracking.material else "Genel",
                "total_seconds_in_material": tracking.duration_seconds
            }, status=status.HTTP_200_OK)
            
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

        weekly_content = material.parent_content

        # 2. Öğrencinin aktif deneme turunu (Round) tespit et
        progress, _ = StudentProgress.objects.get_or_create(
            student=request.user, 
            weekly_content=weekly_content
        )
        current_round = progress.current_attempt_round
        print(f"DEBUG: Öğrenci {weekly_content.week_number}. Hafta için {current_round}. turda.")

        # 3. Materyali BU TUR için tamamlanmış olarak kaydet
        completed_record, created = CompletedMaterial.objects.get_or_create(
            student=request.user, 
            material=material,
            attempt_round=current_round # Tur bilgisi ile kaydediyoruz
        )

        new_points = 0
        # Puan Mantığı: Sadece 1. turda materyal bitirince puan verilir
        if created and current_round == 1:
            # --- GÜNCELLEME BURADA ---
            # Eğer puan 10 ise veya 0 ise (girilmemişse) 1 puan ver, değilse tanımlı puanı ver.
            actual_point = material.point_value
            if actual_point == 10 or actual_point == 0:
                new_points = 1
            else:
                new_points = actual_point
            # -------------------------

            request.user.total_points += new_points
            request.user.save()
            print(f"DEBUG: 1. Tur tamamlaması. {new_points} puan kazandı.")
        else:
            print(f"DEBUG: {current_round}. tur kaydı zaten var veya 2. tur olduğu için puan verilmedi.")

        # 4. İlerleme Hesaplama (Sadece aktif olan turdaki materyallere göre)
        total_mats = weekly_content.materials.count()
        done_mats_in_current_round = CompletedMaterial.objects.filter(
            student=request.user, 
            material__parent_content=weekly_content,
            attempt_round=current_round # Filtreleme sadece mevcut tura göre yapılır
        ).count()

        percentage = (done_mats_in_current_round / total_mats) * 100 if total_mats > 0 else 0
        
        progress.completion_percentage = round(percentage, 2)
        # Eğer yüzde 100 ise o tur için tamamlandı olarak işaretle
        progress.is_completed = (percentage >= 100)
        progress.save()

        print(f"DEBUG: {current_round}. Tur İlerlemesi: %{progress.completion_percentage}")
        print("="*60 + "\n")

        return Response({
            "status": "success", 
            "round": current_round,
            "current_percentage": progress.completion_percentage,
            "material_id": str(material.id),
            "new_points_earned": new_points,
            "total_points": request.user.total_points
        }, status=status.HTTP_200_OK)

class CompletedMaterialIdsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Q
        
        # 1. Öğrencinin haftalık tur bilgilerini al
        student_progresses = StudentProgress.objects.filter(student=request.user)
        
        # 2. Dinamik bir filtre oluştur (Hafta X'te Tur Y verilerini getir)
        query = Q()
        for prog in student_progresses:
            query |= Q(
                material__parent_content=prog.weekly_content, 
                attempt_round=prog.current_attempt_round
            )
        
        if not query:
            return Response([])

        # 3. Sadece aktif tura ait olan tamamlanmış materyal ID'lerini çek
        completed_ids = CompletedMaterial.objects.filter(
            query,
            student=request.user
        ).values_list('material_id', flat=True)
        
        return Response([str(m_id) for m_id in completed_ids])

class StudentProgressListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        progresses = StudentProgress.objects.filter(student=request.user).select_related('weekly_content').order_by('weekly_content__week_number')
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
    """
    Hem Öğrenci hem de Akademisyen Paneli için veri sağlar.
    Öğrenci gelse sadece kendi temel verisini, Hoca gelirse tüm listeyi döner.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 1. İstek atan kullanıcı Akademisyen mi?
        is_teacher = getattr(request.user, 'is_teacher', False) or request.user.is_staff
        student_id_param = request.query_params.get('student_id')

        # --- DURUM A: ÖĞRENCİ KENDİ PANELİNE GİRİYOR ---
        if not is_teacher:
            # Öğrenci için tüm sınıfın dökümünü hesaplama! Sadece kendi puanını dön.
            # Bu kısım saniyeler süren çökme riskini 1 milisaniyeye indirir.
            return Response({
                "id": request.user.id,
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "total_points": getattr(request.user, 'total_points', 0),
                "overall_progress": 0,
                "weekly_breakdown": [] # Öğrenci paneli için detay gerekmiyor
            }, status=200)

        # --- DURUM B: HOCA, BİR ÖĞRENCİNİN KARNESİNE BAKIYOR (MODAL) ---
        if student_id_param:
            student = get_object_or_404(User, id=student_id_param)
            # Sadece tek bir öğrenci olduğu için Serializer kullanımı burada güvenlidir.
            serializer = StudentAnalyticsSerializer(student)
            return Response(serializer.data, status=200)

        total_weeks_count = WeeklyContent.objects.count()
        
        # Eğer henüz hiç hafta eklenmemişse hata oluşmaması için kontrol
        if total_weeks_count == 0:
            total_weeks_count = 1 

        dept_param = request.query_params.get('department')

        students = User.objects.filter(is_staff=False, is_teacher=False)
        if dept_param and dept_param != 'all':
            students = students.filter(department=dept_param)

        students = students.prefetch_related(
            'studentprogress_set',
            'timetracking_set',
            'studentquizattempt_set'
        ).order_by('first_name')

        analytics_data = []
        for s in students:
            progresses = list(s.studentprogress_set.all())
            trackings = list(s.timetracking_set.all())
            attempts = list(s.studentquizattempt_set.all())
            
            total_seconds = sum(t.duration_seconds for t in trackings)
            
            # 2. HESAPLAMA: Toplam ilerlemeyi dinamik hafta sayısına böl
            total_progress_sum = sum(p.completion_percentage for p in progresses)
            avg_progress = total_progress_sum / total_weeks_count
            
            avg_progress = min(avg_progress, 100.0)

            # Sınav Tahmin ve Gerçekleşen Skor Analizleri
            if attempts:
                avg_pred = round(sum(a.predicted_score for a in attempts) / len(attempts), 1)
                avg_act = round(sum(a.score for a in attempts) / len(attempts), 1)
                avg_diff = round(sum(a.score_difference for a in attempts) / len(attempts), 1)
            else:
                avg_pred = 0
                avg_act = 0
                avg_diff = 0

            analytics_data.append({
                "id": str(s.id),
                "first_name": s.first_name,
                "last_name": s.last_name,
                "department": s.department,
                "total_points": getattr(s, 'total_points', 0),
                "total_time_spent": total_seconds,
                "overall_progress": round(avg_progress, 1),
                "avg_predicted": avg_pred,
                "avg_actual": avg_act,
                "avg_diff": avg_diff,
                "total_quizzes_taken": len(attempts),
                "weekly_breakdown": []
            })

        return Response(analytics_data, status=200)

# --- YAPAY ZEKA SOHBET ---

class AIChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_message = request.data.get("message")
        week_id = request.data.get("weekly_content_id")
        if not user_message: return Response({"error": "Mesaj boş."}, status=400)

        try:
            config = init_vertex_ai()
            url = f"https://{config['location']}-aiplatform.googleapis.com/v1/projects/{config['project_id']}/locations/{config['location']}/publishers/google/models/{config['model_id']}:generateContent"
            
            headers = {"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json"}
            payload = {
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.7}
            }

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            res_json = response.json()

            if 'candidates' in res_json:
                parts = res_json['candidates'][0]['content']['parts']
                ai_response_text = "".join([p.get('text', '') for p in parts])
            else:
                ai_response_text = "Üzgünüm, şu an yanıt veremiyorum."

            # Kayıt mantığı
            if week_id:
                try:
                    WeeklyContent.objects.filter(id=week_id).exists()
                    StudentQuestion.objects.create(
                        student=request.user, 
                        weekly_content_id=week_id, 
                        question_text=user_message,
                        response_text=ai_response_text
                    )
                except Exception as ex: 
                    print(f"DEBUG: Chat Soru Kayıt Hatası -> {str(ex)}")
                
            return Response({"response": ai_response_text}, status=200)
        except Exception as e:
            return Response({"response": "Sistem yoğunluğu var."}, status=500)

# --- QUIZ (SINAV) SİSTEMİ ---


class QuizSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, quiz_id):
        # 1. Temel nesneleri al
        quiz = get_object_or_404(Quiz, id=str(quiz_id))
        weekly_content = quiz.material.parent_content
        
        # 2. Mevcut tur (round) bilgisini al
        progress, _ = StudentProgress.objects.get_or_create(
            student=request.user, 
            weekly_content=weekly_content
        )
        current_round = progress.current_attempt_round

        # 3. Aynı tur içinde mükerrer sınav çözümünü engelle
        if StudentQuizAttempt.objects.filter(
            student=request.user, 
            quiz=quiz, 
            attempt_round=current_round
        ).exists():
            return Response(
                {"error": f"Bu haftanın testini {current_round}. tur için zaten çözdünüz."}, 
                status=status.HTTP_403_FORBIDDEN
            )

        answers_data = request.data.get('answers', [])
        predicted_score_val = request.data.get('predicted_score', 0)
        try:
            predicted_score_val = max(0, min(100, int(predicted_score_val)))
        except (ValueError, TypeError):
            predicted_score_val = 0

        correct_count = 0
        
        # 4. Sınav denemesini (Attempt) aktif tura göre oluştur
        attempt = StudentQuizAttempt.objects.create(
            student=request.user, 
            quiz=quiz, 
            score=0, 
            predicted_score=predicted_score_val,
            score_difference=0,
            correct_answers=0, 
            wrong_answers=0,
            attempt_round=current_round # Hangi turda olduğu kaydediliyor
        )

        # 5. Cevapları işle
        for ans in answers_data:
            q_id = str(ans.get('question_id'))
            o_id = str(ans.get('option_id'))
            
            try:
                question = get_object_or_404(QuizQuestion, id=q_id, quiz=quiz)
                option = get_object_or_404(QuizOption, id=o_id, question=question)
                
                if option.is_correct:
                    correct_count += 1
                
                StudentAnswer.objects.create(
                    attempt=attempt, 
                    question=question, 
                    selected_option=option, 
                    is_correct=option.is_correct
                )
            except Exception as e:
                print(f"DEBUG: Quiz Soru/Cevap Hatası -> {str(e)}")

        # 6. Skor hesapla ve kaydet
        total_questions = quiz.questions.count()
        attempt.score = round((correct_count / total_questions) * 100) if total_questions > 0 else 0
        attempt.score_difference = attempt.score - attempt.predicted_score
        attempt.correct_answers = correct_count
        attempt.wrong_answers = total_questions - correct_count
        attempt.save()

        # 7. Sınav materyalini BU TUR için tamamlandı işaretle
        comp_mat, comp_created = CompletedMaterial.objects.get_or_create(
            student=request.user, 
            material=quiz.material,
            attempt_round=current_round
        )

        points_earned = 0
        if comp_created and current_round == 1:
            actual_point = quiz.material.point_value
            if actual_point == 10 or actual_point == 0:
                points_earned = 1
            else:
                points_earned = actual_point
            request.user.total_points += points_earned
            request.user.save()
        
        # 8. İlerleme durumunu güncelle (Round yükseltme BURADA YAPILMIYOR)
        total_mats = weekly_content.materials.count()
        done_mats = CompletedMaterial.objects.filter(
            student=request.user, 
            material__parent_content=weekly_content,
            attempt_round=current_round
        ).count()
        
        perc = (done_mats / total_mats) * 100 if total_mats > 0 else 0
        progress.completion_percentage = round(perc, 2)
        progress.is_completed = (perc >= 100)
        progress.save()

        return Response({
            "attempt_id": str(attempt.id),
            "score": attempt.score,
            "predicted_score": attempt.predicted_score,
            "score_difference": attempt.score_difference,
            "correct": attempt.correct_answers,
            "wrong": attempt.wrong_answers,
            "current_round": current_round,
            "points_earned": points_earned,
            "total_points": request.user.total_points,
            "is_completed": progress.is_completed
        }, status=status.HTTP_201_CREATED)
class QuizLastAttemptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, quiz_id):
        
        attempt = StudentQuizAttempt.objects.filter(student=request.user, quiz_id=str(quiz_id)).order_by('-completed_at').first()
        if attempt:
            return Response({
                "id": str(attempt.id), 
                "score": attempt.score,
                "predicted_score": attempt.predicted_score,
                "score_difference": attempt.score_difference,
                "correct": attempt.correct_answers,
                "wrong": attempt.wrong_answers,     
                "correct_answers": attempt.correct_answers,
                "wrong_answers": attempt.wrong_answers 
            }, status=200)

class PlainTextRenderer(BaseRenderer):
    media_type = 'text/plain'
    format = 'txt'
    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data

from django.http import StreamingHttpResponse
import json

class QuizAIAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attempt_id):
        try:
            # 1. Sınav denemesini bul
            attempt = get_object_or_404(StudentQuizAttempt, id=attempt_id, student=request.user)
            
            # 2. Haftalık içerik ve ilerleme kaydına ulaş
            weekly_content = attempt.quiz.material.parent_content
            progress = StudentProgress.objects.get(student=request.user, weekly_content=weekly_content)
            
            # --- 2. TUR TETİKLEME MANTIĞI (Aynı kalıyor) ---
            if attempt.wrong_answers > 0 and progress.current_attempt_round == 1:
                progress.current_attempt_round = 2
                progress.completion_percentage = 0  
                progress.save()

            # 3. VERİTABANINDAN HAZIR ANALİZLERİ TOPLA
            # Öğrencinin yanlış cevapladığı soruları çekiyoruz
            wrong_answers = StudentAnswer.objects.filter(
                attempt=attempt, 
                is_correct=False
            ).select_related('question')

            combined_analysis = ""
            user_name = request.user.first_name if request.user.first_name else request.user.username
            
            pred = attempt.predicted_score
            actual = attempt.score
            diff = attempt.score_difference
            diff_sign = f"+{diff}" if diff > 0 else f"{diff}"

            combined_analysis += f"Merhaba {user_name}, bu testteki performansını senin için analiz ettim:\n\n"
            combined_analysis += f"🎯 Hedef/Tahmin Skorun: %{pred}\n"
            combined_analysis += f"📊 Gerçekleşen Skorun: %{actual}\n"
            combined_analysis += f"⚡ Skor Sapması / Fark: {diff_sign} Puan\n\n"

            for ans in wrong_answers:
                # Soru bazlı hazır açıklamayı (explanation) çekiyoruz
                q_text = ans.question.question_text
                # Eğer explanation boşsa bir fallback metni koyuyoruz
                q_analysis = ans.question.explanation if ans.question.explanation else "Bu konuyla ilgili ders notlarını tekrar gözden geçirmelisin."
                
                combined_analysis += f"• SORU: {q_text}\n"
                combined_analysis += f"• ANALİZ: {q_analysis}\n\n"

            combined_analysis += "\nŞimdi 2. tura geçerek bu eksiklerini tamamlayabilirsin. Başarılar!"

            return Response({
                "ai_feedback": combined_analysis, # İsim aynı kalsın ki frontend kırılmasın
                "current_round": progress.current_attempt_round,
                "score": attempt.score,
                "predicted_score": attempt.predicted_score,
                "score_difference": attempt.score_difference
            }, status=200)
            
        except Exception as e: 
            return Response({"error": "Analiz verisi alınamadı."}, status=500)

User = get_user_model()

class BulkAcademicReportView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        department_filter = request.query_params.get('department')
        
        if not department_filter or department_filter == 'all':
            return Response({"detail": "Bölüm seçiniz."}, status=400)

        # 1. ADIM: İhtiyacımız olan tüm öğrencileri ve ilişkili verileri TEK SEFERDE çek
        students = User.objects.filter(
            is_staff=False, is_teacher=False, department=department_filter
        ).prefetch_related(
            'timetracking_set', 
            'studentquizattempt_set__quiz__material__parent_content',
            'studentprogress_set'
        ).order_by('first_name')

        # 2. ADIM: Tüm haftalık içerikleri ve materyalleri hafızaya al
        all_weeks = list(WeeklyContent.objects.all().prefetch_related('materials'))
        week_map = {w.week_number: w for w in all_weeks}
        
        report_data = []

        # 3. ADIM: Hafızadaki veriler üzerinden dön (Veritabanına bir daha gidilmez)
        for student in students:
            # Öğrenciye ait tüm kayıtları listeye çevir (RAM'de süzmek için)
            student_trackings = list(student.timetracking_set.all())
            student_attempts = list(student.studentquizattempt_set.all())
            student_progresses = list(student.studentprogress_set.all())

            weekly_stats = []
            overall_total_seconds_1 = sum(t.duration_seconds for t in student_trackings if t.attempt_round == 1)
            overall_total_seconds_2 = sum(t.duration_seconds for t in student_trackings if t.attempt_round == 2)
            overall_total_seconds = overall_total_seconds_1 + overall_total_seconds_2
            
            for i in range(1, 15):
                week_content = week_map.get(i)
                w_id = week_content.id if week_content else None
                
                # --- TUR 1 & 2 VERİLERİ (Hafızadan Filtrele) ---
                duration_1 = sum(t.duration_seconds for t in student_trackings if t.weekly_content_id == w_id and t.attempt_round == 1)
                duration_2 = sum(t.duration_seconds for t in student_trackings if t.weekly_content_id == w_id and t.attempt_round == 2)
                
                attempt_1 = next((a for a in student_attempts if a.quiz.material.parent_content_id == w_id and a.attempt_round == 1), None)
                attempt_2 = next((a for a in student_attempts if a.quiz.material.parent_content_id == w_id and a.attempt_round == 2), None)
                
                # --- MATERYAL DETAYLARI (Hafızadan Filtrele - T1 ve T2 Ayrımıyla) ---
                material_details = []
                if week_content:
                    for m in week_content.materials.all():
                        m_duration_1 = sum(t.duration_seconds for t in student_trackings if t.material_id == m.id and t.attempt_round == 1)
                        m_duration_2 = sum(t.duration_seconds for t in student_trackings if t.material_id == m.id and t.attempt_round == 2)
                        material_details.append({
                            "title": m.title,
                            "content_type": m.content_type,
                            "duration_seconds_1": m_duration_1,
                            "duration_seconds_2": m_duration_2,
                            "duration_seconds": m_duration_1 + m_duration_2
                        })

                # --- İLERLEME (Hafızadan Filtrele) ---
                progress_record = next((p for p in student_progresses if p.weekly_content_id == w_id), None)
                progress_value = progress_record.completion_percentage if progress_record else 0

                weekly_stats.append({
                    "week": i,
                    "progress": float(progress_value),
                    "material_details": material_details,
                    "duration_seconds": duration_1,
                    "correct": attempt_1.correct_answers if attempt_1 else 0,
                    "wrong": attempt_1.wrong_answers if attempt_1 else 0,
                    "score_1": attempt_1.score if attempt_1 else 0,
                    "predicted_1": attempt_1.predicted_score if attempt_1 else 0,
                    "diff_1": attempt_1.score_difference if attempt_1 else 0,
                    "duration_seconds_2": duration_2,
                    "correct_2": attempt_2.correct_answers if attempt_2 else 0,
                    "wrong_2": attempt_2.wrong_answers if attempt_2 else 0,
                    "score_2": attempt_2.score if attempt_2 else 0,
                    "predicted_2": attempt_2.predicted_score if attempt_2 else 0,
                    "diff_2": attempt_2.score_difference if attempt_2 else 0,
                    "has_quiz": True if (attempt_1 or attempt_2) else False,
                    "is_round_2_started": True if (duration_2 > 0 or attempt_2) else False
                })

            if student_attempts:
                stu_avg_pred = round(sum(a.predicted_score for a in student_attempts) / len(student_attempts), 1)
                stu_avg_act = round(sum(a.score for a in student_attempts) / len(student_attempts), 1)
                stu_avg_diff = round(sum(a.score_difference for a in student_attempts) / len(student_attempts), 1)
            else:
                stu_avg_pred = 0
                stu_avg_act = 0
                stu_avg_diff = 0

            report_data.append({
                "id": str(student.id),
                "full_name": f"{student.first_name} {student.last_name}".upper(),
                "email": student.email,
                "department": student.department,
                "total_points": getattr(student, 'total_points', 0),
                "total_time_1": overall_total_seconds_1,
                "total_time_2": overall_total_seconds_2,
                "total_time": overall_total_seconds,
                "avg_predicted": stu_avg_pred,
                "avg_actual": stu_avg_act,
                "avg_diff": stu_avg_diff,
                "weekly_breakdown": weekly_stats
            })

        return Response(report_data, status=200)
 
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import permissions
from django.db.models import Sum, Value, CharField, FloatField
from django.db.models.functions import Concat, Cast
from .models import TimeTracking

class SystemTimeAnalyticsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        dept = request.query_params.get('department')
        
        # Ana sorgu kalkanı
        logs = TimeTracking.objects.all()
        if dept:
            logs = logs.filter(student__department=dept)

        # 1. Genel Öğrenci Bazında Toplam Süreleri Hesapla
        student_totals = logs.values('student').annotate(
            full_name=Concat(
                'student__first_name', Value(' '), 'student__last_name',
                output_field=CharField()
            ),
            total_hours=Sum(Cast('duration_seconds', FloatField())) / 3600.0
        ).order_by('-total_hours')

        # Varsayılan genel değerler
        max_student = {"student": "Veri Yok", "time": "0 Saat"}
        min_student = {"student": "Veri Yok", "time": "0 Saat"}

        if student_totals.exists():
            most_active = student_totals.first()
            least_active = student_totals.last()
            
            max_student = {
                "student": most_active['full_name'] if most_active['full_name'].strip() else "Bilinmeyen Öğrenci",
                "time": f"{round(most_active['total_hours'], 2)} Saat"
            }
            min_student = {
                "student": least_active['full_name'] if least_active['full_name'].strip() else "Bilinmeyen Öğrenci",
                "time": f"{round(least_active['total_hours'], 2)} Saat"
            }

        # 2. Genel Etkinlik Türlerine Göre Zaman Dağılımı
        activity_totals = logs.values('material__content_type').annotate(
            total_hours=Sum(Cast('duration_seconds', FloatField())) / 3600.0
        ).order_by('-total_hours')

        type_mapping = {
            'video': 'Video İzleme',
            'podcast': 'Podcast Dinleme',
            'form': 'Bilgi Testi (Quiz)',
            'pdf': 'Ders Notu Okuma (PDF)',
            'assignment': 'Ödev Çözme'
        }

        activity_distribution = []
        for act in activity_totals:
            raw_type = act['material__content_type']
            if raw_type:
                activity_distribution.append({
                    "type": type_mapping.get(raw_type, raw_type.upper()),
                    "hours": round(act['total_hours'], 2)
                })

        # ----------------------------------------------------------------
        # 3. HAFTA HAFTA AKADEMİK KIRILIM VE ÖĞRENCİ SIRALAMA ANALİZLERİ
        # ----------------------------------------------------------------
        weekly_totals = logs.values('weekly_content__week_number').annotate(
            total_hours=Sum(Cast('duration_seconds', FloatField())) / 3600.0
        ).order_by('weekly_content__week_number')

        weekly_analysis = []
        for week_data in weekly_totals:
            w_num = week_data['weekly_content__week_number']
            if w_num is None:
                continue

            # O haftaya ait özel filtreleme kalkanı
            week_logs = logs.filter(weekly_content__week_number=w_num)

            # Hafta bazında tüm öğrencilerin sürelerini hesapla ve sırala
            week_student_totals = week_logs.values('student').annotate(
                full_name=Concat('student__first_name', Value(' '), 'student__last_name', output_field=CharField()),
                hours=Sum(Cast('duration_seconds', FloatField())) / 3600.0
            ).order_by('-hours')

            w_max = {"student": "Veri Yok", "time": "0 Saat"}
            w_min = {"student": "Veri Yok", "time": "0 Saat"}

            if week_student_totals.exists():
                w_most = week_student_totals.first()
                w_least = week_student_totals.last()
                w_max = {
                    "student": w_most['full_name'] if w_most['full_name'].strip() else "Bilinmeyen Öğrenci",
                    "time": f"{round(w_most['hours'], 2)} Saat"
                }
                w_min = {
                    "student": w_least['full_name'] if w_least['full_name'].strip() else "Bilinmeyen Öğrenci",
                    "time": f"{round(w_least['hours'], 2)} Saat"
                }

            # Hafta bazında etkinlik dağılımını hesapla
            week_activity_totals = week_logs.values('material__content_type').annotate(
                hours=Sum(Cast('duration_seconds', FloatField())) / 3600.0
            ).order_by('-hours')

            w_activity_dist = []
            for w_act in week_activity_totals:
                w_raw_type = w_act['material__content_type']
                if w_raw_type:
                    w_activity_dist.append({
                        "type": type_mapping.get(w_raw_type, w_raw_type.upper()),
                        "hours": round(w_act['hours'], 2)
                    })

            # EKSTRA İSTEK: O haftanın ilk 15 öğrenci sıralama listesini oluşturuyoruz
            w_student_list = [
                {
                    "rank": idx + 1,
                    "student": s['full_name'] if s['full_name'].strip() else "Bilinmeyen Öğrenci",
                    "time": f"{round(s['hours'], 2)} Saat"
                } for idx, s in enumerate(week_student_totals[:15])
            ]

            weekly_analysis.append({
                "week_number": w_num,
                "total_hours": f"{round(week_data['total_hours'], 2)} Saat",
                "max_engagement": w_max,
                "min_engagement": w_min,
                "activity_distribution": w_activity_dist,
                "student_list": w_student_list # Haftalık sıralama listesi backend'e eklendi
            })

        return Response({
            "max_engagement": max_student,
            "min_engagement": min_student,
            "activity_distribution": activity_distribution,
            "weekly_analysis": weekly_analysis,
            "raw_student_list": [
                {
                    "rank": idx + 1,
                    "student": s['full_name'] if s['full_name'].strip() else "Bilinmeyen Öğrenci",
                    "time": f"{round(s['total_hours'], 2)} Saat"
                } for idx, s in enumerate(student_totals[:15])
            ]
        })


class ChatbotAnalyticsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        dept = request.query_params.get('department')
        
        # 1. İlgili öğrencileri çek
        students = User.objects.filter(is_staff=False, is_teacher=False)
        if dept and dept != 'all':
            students = students.filter(department=dept)
        
        students = students.order_by('first_name', 'last_name')
        
        # 2. Bu öğrencilere ait soru kayıtlarını çek
        questions = StudentQuestion.objects.filter(
            student__in=students
        ).select_related('student', 'weekly_content').order_by('-created_at')
        
        total_questions = questions.count()
        active_users_count = questions.values('student').distinct().count()
        total_users_count = students.count()
        
        # 3. Öğrenci bazında soruları grupla
        questions_by_student = {}
        for q in questions:
            s_id = str(q.student_id)
            if s_id not in questions_by_student:
                questions_by_student[s_id] = []
            
            created_str = q.created_at.strftime("%d.%m.%Y / %H:%M") if q.created_at else ""
            questions_by_student[s_id].append({
                "id": q.id,
                "week_number": q.weekly_content.week_number if q.weekly_content else 1,
                "week_title": q.weekly_content.title if q.weekly_content else "",
                "question_text": q.question_text,
                "response_text": q.response_text or "Henüz yanıt kaydedilmemiş.",
                "created_at": created_str,
                "created_at_iso": q.created_at.isoformat() if q.created_at else ""
            })
            
        students_data = []
        for s in students:
            s_id = str(s.id)
            s_questions = questions_by_student.get(s_id, [])
            students_data.append({
                "id": s_id,
                "first_name": s.first_name,
                "last_name": s.last_name,
                "department": s.department,
                "question_count": len(s_questions),
                "questions": s_questions
            })
            
        # Çok soru sorandan aza doğru sıralayalım
        students_data.sort(key=lambda x: (-x['question_count'], x['first_name']))

        return Response({
            "total_questions": total_questions,
            "active_users_count": active_users_count,
            "total_users_count": total_users_count,
            "students": students_data
        }, status=200)


class DepartmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        counts = dict(
            User.objects.filter(is_staff=False, is_teacher=False, department__isnull=False)
            .values('department')
            .annotate(count=Count('id'))
            .values_list('department', 'count')
        )
        
        dept_choices = dict(User.DEPARTMENT_CHOICES)
        result = []
        for key, name in User.DEPARTMENT_CHOICES:
            result.append({
                "key": key,
                "name": name,
                "student_count": counts.get(key, 0)
            })
            
        for key, count in counts.items():
            if key and key not in dept_choices:
                result.append({
                    "key": key,
                    "name": key.replace('_', ' ').title(),
                    "student_count": count
                })
                
        return Response(result, status=200)