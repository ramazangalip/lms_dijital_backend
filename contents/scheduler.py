import time
import threading
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

_scheduler_started = False
_scheduler_lock = threading.Lock()

def _scheduler_loop():
    """
    Canlı arka plan döngüsü:
    Her 60 saniyede bir çalışarak bölüm bazlı haftalık akademik raporların
    gönderim zamanının gelip gelmediğini kontrol eder.
    """
    logger.info("Akademik Rapor Canlı Zamanlayıcısı (Scheduler) başlatıldı.")
    
    # Sunucu ilk açıldığında 10 saniye bekle (DB bağlantılarının tam oturması için)
    time.sleep(10)

    while True:
        try:
            from contents.services.academic_report_service import check_and_send_due_academic_reports
            results = check_and_send_due_academic_reports(force=False)
            if results:
                logger.info(f"Akademik rapor zamanlayıcı kontrolü tamamlandı: {len(results)} işlem yapıldı.")
        except Exception as e:
            logger.error(f"Akademik rapor zamanlayıcı döngüsünde hata: {e}", exc_info=True)

        # 60 saniye uyu
        time.sleep(60)


def start_report_scheduler():
    """
    Arka plan zamanlayıcı thread'ini tek bir defa güvenli şekilde başlatır.
    """
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        
        thread = threading.Thread(
            target=_scheduler_loop,
            name="AcademicReportSchedulerThread",
            daemon=True
        )
        thread.start()
        _scheduler_started = True
        logger.info("AcademicReportSchedulerThread daemon thread olarak devreye alındı.")
