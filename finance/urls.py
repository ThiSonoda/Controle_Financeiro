# finance/urls.py
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name = 'finance'

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='finance/login.html'), name='login'),
    path('transactions/', views.transactions_view, name='transactions'),
    path('transactions/<int:transaction_id>/edit/', views.edit_transaction_view, name='edit_transaction'),
    path('transactions/<int:transaction_id>/delete/', views.delete_transaction_view, name='delete_transaction'),
    path('budget/', views.budget_view, name='budget'),
    path('report/', views.report_view, name='report'),
    path('credit-cards/', views.credit_cards_view, name='credit_cards'),
]
