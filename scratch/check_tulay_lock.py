import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from contents.models import WeeklyContent, WeeklyContentDepartmentSchedule, StudentProgress, TemporaryWeekUnlock
from contents.serializers import WeeklyContentSerializer
from rest_framework.test import APIRequestFactory

User = get_user_model()
u = User.objects.get(id=1217885619385466881)
print(f"Student: {u.first_name} {u.last_name} ({u.email}) - Dept: {u.department}")
print(f"Current time (now): {timezone.now()}")

factory = APIRequestFactory()
request = factory.get('/contents/list/')
request.user = u

weeks = list(WeeklyContent.objects.all().order_by('week_number'))
serializer = WeeklyContentSerializer(weeks, many=True, context={'request': request})
for w in serializer.data:
    wn = w['week_number']
    wc = next(x for x in weeks if x.week_number == wn)
    sched = WeeklyContentDepartmentSchedule.objects.filter(weekly_content=wc, department=u.department).first()
    print(f"\n--- Week {wn} ({wc.title}) ---")
    print(f"  is_locked: {w['is_locked']}")
    print(f"  is_intro_watched: {w['is_intro_watched']}")
    print(f"  WC default release_date: {wc.release_date}, deactivation_date: {wc.deactivation_date}")
    if sched:
        print(f"  Dept Schedule ({u.department}): rel={sched.release_date}, deact={sched.deactivation_date}")
    else:
        print(f"  Dept Schedule: NONE")
    
    prog = StudentProgress.objects.filter(student=u, weekly_content=wc).first()
    if prog:
        print(f"  StudentProgress: %{prog.completion_percentage}, completed={prog.is_completed}")
    else:
        print(f"  StudentProgress: None")
