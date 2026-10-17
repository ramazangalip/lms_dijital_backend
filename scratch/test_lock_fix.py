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
u = User.objects.get(id=1217885619385466881) # Tülay Bazencir

print(f"Testing for Tülay Bazencir ({u.email}):")
factory = APIRequestFactory()
request = factory.get('/contents/list/')
request.user = u

weeks = list(WeeklyContent.objects.all().order_by('week_number'))
serializer = WeeklyContentSerializer(weeks, many=True, context={'request': request})
for w in serializer.data:
    print(f"Week {w['week_number']}: is_locked={w['is_locked']}, is_intro_watched={w['is_intro_watched']}")
