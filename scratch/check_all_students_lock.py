import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from contents.models import WeeklyContent, StudentProgress
from contents.serializers import WeeklyContentSerializer
from rest_framework.test import APIRequestFactory

User = get_user_model()
students = User.objects.filter(department='siyasetbilimivekamuyonetimi', category='d2')

weeks = list(WeeklyContent.objects.all().order_by('week_number'))
factory = APIRequestFactory()
request = factory.get('/contents/list/')

print(f"{'Student':<25} | {'W1 Prog':<10} | {'W1 Lock':<10} | {'W2 Prog':<10} | {'W2 Lock':<10}")
print("-" * 75)

for s in students:
    request.user = s
    serializer = WeeklyContentSerializer(weeks, many=True, context={'request': request})
    w_data = {w['week_number']: w for w in serializer.data}
    
    p1 = StudentProgress.objects.filter(student=s, weekly_content__week_number=1).first()
    p2 = StudentProgress.objects.filter(student=s, weekly_content__week_number=2).first()
    
    prog1_str = f"{p1.completion_percentage}% ({p1.is_completed})" if p1 else "None"
    prog2_str = f"{p2.completion_percentage}% ({p2.is_completed})" if p2 else "None"
    
    lock1 = w_data[1]['is_locked']
    lock2 = w_data[2]['is_locked']
    
    print(f"{s.first_name + ' ' + s.last_name:<25} | {prog1_str:<10} | {str(lock1):<10} | {prog2_str:<10} | {str(lock2):<10}")
