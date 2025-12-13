# finance/urls.py
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name = 'finance'

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='finance/login.html'), name='login'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('transactions/', views.transactions_view, name='transactions'),
    path('transactions/<int:transaction_id>/edit/', views.edit_transaction_view, name='edit_transaction'),
    path('transactions/<int:transaction_id>/delete/', views.delete_transaction_view, name='delete_transaction'),
    path('transactions/bulk-delete/', views.bulk_delete_transactions_view, name='bulk_delete_transactions'),
    path('credit-cards/<int:card_id>/pay/<int:year>/<int:month>/', views.pay_credit_card_invoice_view, name='pay_invoice'),
    path('credit-cards/<int:card_id>/reopen/<int:year>/<int:month>/', views.reopen_credit_card_invoice_view, name='reopen_invoice'),
    path('budget/', views.budget_view, name='budget'),
    path('report/', views.report_view, name='report'),
    path('all-transactions/', views.all_transactions_view, name='all_transactions'),
    path('all-logs/', views.all_logs_view, name='all_logs'),
    path('budget-templates/list/', views.budget_template_list_view, name='budget_template_list'),
    path('budget-templates/create/', views.budget_template_create_view, name='budget_template_create'),
    path('budget-templates/<int:template_id>/edit/', views.budget_template_edit_view, name='budget_template_edit'),
    path('budget-templates/<int:template_id>/delete/', views.budget_template_delete_view, name='budget_template_delete'),
    path('budget-templates/apply/', views.budget_template_apply_view, name='budget_template_apply'),
    path('budget-templates/save-current/', views.budget_template_save_current_view, name='budget_template_save_current'),
    path('legends/', views.legends_view, name='legends'),
    path('subcategory-budget-info/', views.subcategory_budget_info_view, name='subcategory_budget_info'),
    path('subcategory-transactions/', views.subcategory_transactions_view, name='subcategory_transactions'),
    path('credit-card-refunds/', views.credit_card_refunds_view, name='credit_card_refunds'),
    path('credit-card-refunds/create/', views.create_credit_card_refund_view, name='create_credit_card_refund'),
    path('credit-card-refunds/<int:refund_id>/edit/', views.edit_credit_card_refund_view, name='edit_credit_card_refund'),
    path('credit-card-refunds/<int:refund_id>/delete/', views.delete_credit_card_refund_view, name='delete_credit_card_refund'),
    # path('credit-cards/', views.credit_cards_view, name='credit_cards'),
]
