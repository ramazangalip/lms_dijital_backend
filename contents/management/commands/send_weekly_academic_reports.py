from django.core.management.base import BaseCommand
from django.utils import timezone
from zoneinfo import ZoneInfo
from users.models import User
from contents.models import WeeklyContent
from contents.services.academic_report_service import (
    check_and_send_due_academic_reports,
    send_academic_report,
    get_trigger_datetime_for_week,
    ISTANBUL_TZ
)

import sys

class Command(BaseCommand):
    help = "Bölüm bazlı haftalık D2 öğrenci analitiği raporlarını akademisyenlere gönderir."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Tarih ve saat kontrollerini atlayarak seçili/tüm raporları hemen gönderir.'
        )
        parser.add_argument(
            '--week',
            type=int,
            help='Sadece belirtilen hafta için rapor gönderir (örn: --week 1).'
        )
        parser.add_argument(
            '--department',
            type=str,
            help='Sadece belirtilen bölüm için rapor gönderir (örn: --department matematik).'
        )
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='Mail göndermeden sadece tetikleme durumlarını listeler.'
        )

    def handle(self, *args, **options):
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
        now = timezone.now().astimezone(ISTANBUL_TZ)
        self.stdout.write(self.style.SUCCESS(f"=== Akademik Rapor Gönderim Kontrolü ({now.strftime('%d.%m.%Y %H:%M:%S')}) ==="))

        force = options['force']
        week_param = options['week']
        dept_param = options['department']
        check_only = options['check_only']

        departments = [dept_param] if dept_param else [c[0] for c in User.DEPARTMENT_CHOICES]
        weeks_qs = WeeklyContent.objects.all().order_by('week_number')
        if week_param:
            weeks_qs = weeks_qs.filter(week_number=week_param)

        weeks = list(weeks_qs)

        for dept in departments:
            for w in weeks:
                trigger_dt, target_date, trigger_type, reason = get_trigger_datetime_for_week(w, dept)
                if not trigger_dt:
                    self.stdout.write(f"[{dept}] Hafta {w.week_number}: {reason}")
                    continue

                diff = now - trigger_dt
                is_due = (diff.total_seconds() >= 0 and diff.total_seconds() <= 86400) or force

                status_tag = self.style.SUCCESS("GÖNDERİLECEK (DUE)") if is_due else self.style.WARNING("BEKLİYOR (NOT DUE)")
                self.stdout.write(f"[{dept}] Hafta {w.week_number}: {status_tag} | Tetik: {trigger_dt.strftime('%d.%m.%Y %H:%M')} ({reason})")

                if is_due and not check_only:
                    self.stdout.write(f"  -> Mail gönderimi başlatılıyor...")
                    res = send_academic_report(
                        department=dept,
                        week_number=w.week_number,
                        trigger_type=trigger_type,
                        trigger_date=target_date,
                        force=force
                    )
                    self.stdout.write(self.style.SUCCESS(f"  -> Sonuç: {res}"))

        self.stdout.write(self.style.SUCCESS("=== Tamamlandı ==="))
