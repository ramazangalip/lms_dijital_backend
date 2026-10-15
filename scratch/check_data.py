import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')
import django
django.setup()

from contents.models import Material, WeeklyContent, User

print("WeeklyContents:")
for wc in WeeklyContent.objects.all().order_by('week_number'):
    print(f"  Week {wc.week_number}: {wc.title} - {wc.materials.count()} materials")

print("\nStudents in turkdiliveedebiyati (d2):")
for u in User.objects.filter(department='turkdiliveedebiyati', category='d2'):
    print(f"  {u.first_name} {u.last_name} ({u.email}) - pts: {u.total_points}")
