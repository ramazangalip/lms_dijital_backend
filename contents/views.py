
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
            content = WeeklyContent.objects.filter(week_number=week_number).first()
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
            
        contents = WeeklyContent.objects.all().order_by('week_number')
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
                    StudentQuestion.objects.create(student=request.user, weekly_content_id=week_id, question_text=user_message)
                except: pass
                
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
        correct_count = 0
        
        # 4. Sınav denemesini (Attempt) aktif tura göre oluştur
        attempt = StudentQuizAttempt.objects.create(
            student=request.user, 
            quiz=quiz, 
            score=0, 
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
        attempt.correct_answers = correct_count
        attempt.wrong_answers = total_questions - correct_count
        attempt.save()

        # 7. Sınav materyalini BU TUR için tamamlandı işaretle
        CompletedMaterial.objects.get_or_create(
            student=request.user, 
            material=quiz.material,
            attempt_round=current_round
        )
        
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
            "correct": attempt.correct_answers,
            "wrong": attempt.wrong_answers,
            "current_round": current_round,
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
    renderer_classes = [PlainTextRenderer]

    def get(self, request, attempt_id):
        try:
            attempt = get_object_or_404(StudentQuizAttempt, id=str(attempt_id), student=request.user)
            wrong_answers = StudentAnswer.objects.filter(attempt=attempt, is_correct=False).select_related('question')
            user_name = request.user.first_name or request.user.username
            
            details = "".join([f"Soru: {ans.question.question_text}\nYanlış: {ans.selected_option.option_text}\n\n" for ans in wrong_answers])
            prompt = (
                f"Sen uzman bir eğitim danışmanısın. Öğrencin {user_name}, '{attempt.quiz.title}' sınavında %{attempt.score} başarı sağladı. "
                f"Hatalı sorular ve detayları şunlar:\n{details}\n\n"
                f"TALİMATLAR:\n"
                f"1. Direkt '{user_name}, merhaba!' diyerek başla.\n"
                f"2. Skoru değerlendir ve moral verici bir giriş yap.\n"
                f"3. Hataları maddeler halinde, teknik terimlerden kaçınarak, anlaşılır şekilde açıkla.\n"
                f"4. Gelişim için 2 spesifik tavsiye ver.\n"
                f"5. Gereksiz giriş-çıkış cümlelerinden kaçın, doğrudan konuya odaklan ki yanıt hızlı üretilsin."
            )

            # Round 2 Mantığı (Streaming öncesi durum kontrolü)
            weekly_content = attempt.quiz.material.parent_content
            progress = StudentProgress.objects.get(student=request.user, weekly_content=weekly_content)
            if attempt.wrong_answers > 0 and progress.current_attempt_round == 1:
                progress.current_attempt_round = 2
                progress.completion_percentage = 0
                progress.save()

            def stream_generator():
                config = init_vertex_ai()
                # generateContent yerine streamGenerateContent kullanıyoruz
                url = f"https://{config['location']}-aiplatform.googleapis.com/v1/projects/{config['project_id']}/locations/{config['location']}/publishers/google/models/{config['model_id']}:streamGenerateContent"
                
                headers = {"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json"}
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.7} # İstediğin limit korundu
                }

                response = requests.post(url, headers=headers, json=payload, timeout=500, stream=True)
                
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8').strip()
                        # Google Stream formatı bazen '[, {' ile başlar, temizliyoruz
                        if decoded_line.startswith(','): decoded_line = decoded_line[1:].strip()
                        if decoded_line.startswith('['): decoded_line = decoded_line[1:].strip()
                        if decoded_line.endswith(']'): decoded_line = decoded_line[:-1].strip()
                        
                        try:
                            chunk = json.loads(decoded_line)
                            if 'candidates' in chunk:
                                text_part = chunk['candidates'][0]['content']['parts'][0].get('text', '')
                                yield text_part
                        except:
                            continue

            return StreamingHttpResponse(stream_generator(), content_type='text/plain')

        except Exception as e:
            return Response({"error": "Sistemsel bir hata oluştu."}, status=500)

class BulkAcademicReportView(APIView):
    """
    Akademisyen Paneli için toplu PDF raporu verisi sağlar.
    Her haftanın altında o haftaya ait TÜM materyallerin detaylı sürelerini raporlar.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        # 1. Filtre parametresini al
        department_filter = request.query_params.get('department', 'all')
        
        # 2. Sadece öğrencileri getir (Hocalar ve adminler hariç)
        students = User.objects.filter(is_staff=False, is_teacher=False)

        if department_filter and department_filter != 'all':
            students = students.filter(department=department_filter)
        
        students = students.order_by('first_name')
        
        report_data = []

        for student in students:
            weekly_stats = []
            
            # Öğrencinin sistemdeki tüm zaman kaydı (Genel Toplam)
            overall_total_seconds = TimeTracking.objects.filter(
                student=student
            ).aggregate(total=Sum('duration_seconds'))['total'] or 0
            
            # 14 Haftalık döngü
            for i in range(1, 15):
                # O haftanın içerik nesnesini bul
                week_content = WeeklyContent.objects.filter(week_number=i).first()
                
                # --- TUR 1 VERİLERİ ---
                duration_1 = TimeTracking.objects.filter(
                    student=student, 
                    weekly_content=week_content,
                    attempt_round=1
                ).aggregate(total=Sum('duration_seconds'))['total'] or 0
                
                attempt_1 = StudentQuizAttempt.objects.filter(
                    student=student, 
                    quiz__material__parent_content=week_content,
                    attempt_round=1
                ).first()

                # --- TUR 2 VERİLERİ ---
                duration_2 = TimeTracking.objects.filter(
                    student=student, 
                    weekly_content=week_content,
                    attempt_round=2
                ).aggregate(total=Sum('duration_seconds'))['total'] or 0
                
                attempt_2 = StudentQuizAttempt.objects.filter(
                    student=student, 
                    quiz__material__parent_content=week_content,
                    attempt_round=2
                ).first()
                
                # --- MATERYAL BAZLI DETAYLI SÜRELER ---
                material_details = []
                if week_content:
                    # Haftaya ait tüm materyalleri (Video, PDF, Ödev vb.) al
                    mats = week_content.materials.all()
                    for m in mats:
                        # Bu öğrencinin bu spesifik materyalde harcadığı süre
                        m_duration = TimeTracking.objects.filter(
                            student=student,
                            material=m
                        ).aggregate(total=Sum('duration_seconds'))['total'] or 0
                        
                        material_details.append({
                            "title": m.title,
                            "content_type": m.content_type,
                            "duration_seconds": m_duration
                        })

                # Mevcut ilerleme durumu
                progress_record = StudentProgress.objects.filter(
                    student=student, 
                    weekly_content=week_content
                ).first()
                progress_value = progress_record.completion_percentage if progress_record else 0

                weekly_stats.append({
                    "week": i,
                    "progress": float(progress_value),
                    
                    # Materyal detay listesi
                    "material_details": material_details,
                    
                    # Tur 1
                    "duration_seconds": duration_1,
                    "correct": attempt_1.correct_answers if attempt_1 else 0,
                    "wrong": attempt_1.wrong_answers if attempt_1 else 0,
                    "score_1": attempt_1.score if attempt_1 else 0,
                    
                    # Tur 2
                    "duration_seconds_2": duration_2,
                    "correct_2": attempt_2.correct_answers if attempt_2 else 0,
                    "wrong_2": attempt_2.wrong_answers if attempt_2 else 0,
                    "score_2": attempt_2.score if attempt_2 else 0,
                    
                    "has_quiz": True if (attempt_1 or attempt_2) else False,
                    "is_round_2_started": True if (duration_2 > 0 or attempt_2) else False
                })

            # Öğrenci paketini oluştur
            report_data.append({
                "id": str(student.id),
                "full_name": f"{student.first_name} {student.last_name}".upper(),
                "email": student.email,
                "department": student.department,
                "total_points": getattr(student, 'total_points', 0),
                "total_time": overall_total_seconds,
                "weekly_breakdown": weekly_stats
            })

        return Response(report_data, status=status.HTTP_200_OK)
 