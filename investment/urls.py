from django.urls import path
from . import views

app_name = 'investment'

urlpatterns = [
    path('investments/', views.investments_view, name='investments'),
]

