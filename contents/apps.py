import os
import sys
from django.apps import AppConfig


class ContentsConfig(AppConfig):
    name = 'contents'

    def ready(self):
        # Sadece web sunucusu (runserver, gunicorn, uwsgi vb.) çalışırken başlat
        # migrate, makemigrations veya diğer tek seferlik yönetim komutlarında başlatma
        is_server = any(cmd in sys.argv for cmd in ['runserver', 'gunicorn', 'uwsgi', 'daphne'])
        is_main_process = os.environ.get('RUN_MAIN') == 'true' or not any('runserver' in arg for arg in sys.argv)

        if is_server and is_main_process:
            from .scheduler import start_report_scheduler
            start_report_scheduler()
