import os
import json
import time
from django.core.management.base import BaseCommand
from contents.models import QuizQuestion
import vertexai
from vertexai.generative_models import GenerativeModel
from google.oauth2 import service_account

class Command(BaseCommand):
    help = 'Boş olan tüm soru analizlerini (explanation) AI ile doldurur.'

    def init_vertex_ai(self):
        PROJECT_ID = "lmsproject-484210"
        LOCATION = "us-central1"
        # Render/Koyeb üzerindeki Environment Variable'dan veya yerel JSON'dan çeker
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        
        if creds_json:
            creds_dict = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(creds_dict)
            vertexai.init(project=PROJECT_ID, location=LOCATION, credentials=credentials)
        else:
            self.stdout.write(self.style.WARNING("UYARI: Kimlik bilgileri Environment Variable'da bulunamadı."))
            vertexai.init(project=PROJECT_ID, location=LOCATION)
        
        return GenerativeModel("gemini-2.5-pro")

    def handle(self, *args, **options):
        model = self.init_vertex_ai()
        
        # Sadece açıklaması boş olan soruları getir
        questions = QuizQuestion.objects.filter(explanation__isnull=True) | QuizQuestion.objects.filter(explanation="")
        
        count = questions.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("Tüm soruların açıklaması zaten dolu!"))
            return

        self.stdout.write(self.style.NOTICE(f"{count} soru için analiz üretiliyor..."))

        for idx, question in enumerate(questions):
            # Şıkları metin haline getir (AI'nın doğru şıkkı bilmesi için)
            options_text = "\n".join([f"- {opt.option_text} ({'DOĞRU' if opt.is_correct else 'YANLIŞ'})" for opt in question.options.all()])
            
            prompt = (
    f"Soru: {question.question_text}\n"
    f"Şıklar:\n{options_text}\n\n"
    "GÖREV: Sen bir Excel uzmanı ve samimi bir öğretmensin. "
    "Öğrenci bu soruyu yanlış yaptı. Ona 'ders notuna bak' gibi geçiştirici cümleler kurma! "
    "Bunun yerine; doğru şıkkın neden doğru olduğunu ve yanlış şıklardaki mantık hatasını "
    "maksimum 3 cümlede, 'Hadi gel bakalım,' veya 'Aslında buradaki püf noktası şu:' gibi "
    "öğrenciyi motive eden bir dille açıkla."
)

            try:
                response = model.generate_content(prompt)
                analysis_text = response.text.strip()
                
                # Veritabanına kaydet
                question.explanation = analysis_text
                question.save()

                self.stdout.write(self.style.SUCCESS(f"[{idx+1}/{count}] Tamamlandı: {question.question_text[:30]}..."))
                
                # API limitlerine takılmamak için kısa bir bekleme (opsiyonel)
                time.sleep(1) 

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Hata oluştu ({question.id}): {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"İşlem başarıyla tamamlandı. {count} soru güncellendi."))