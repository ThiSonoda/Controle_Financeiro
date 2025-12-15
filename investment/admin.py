from django.contrib import admin
from .models import Broker, InvestmentType, Investment, InvestmentTransaction, PendingInvestment


@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']
    search_fields = ['name']
    ordering = ['name']


@admin.register(InvestmentType)
class InvestmentTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name']
    ordering = ['name']


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ['broker', 'investment_type', 'name', 'status', 'current_balance', 'total_contributed', 'created_at']
    list_filter = ['status', 'broker', 'investment_type']
    search_fields = ['name', 'broker__name']
    ordering = ['broker__name', 'name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(InvestmentTransaction)
class InvestmentTransactionAdmin(admin.ModelAdmin):
    list_display = ['investment', 'amount', 'transaction_date', 'is_contribution', 'is_redemption', 'account', 'created_at']
    list_filter = ['is_contribution', 'is_redemption', 'transaction_date']
    search_fields = ['investment__name', 'investment__broker__name']
    ordering = ['-transaction_date', '-created_at']
    readonly_fields = ['created_at']


@admin.register(PendingInvestment)
class PendingInvestmentAdmin(admin.ModelAdmin):
    list_display = ['transaction', 'amount', 'amount_allocated', 'created_at']
    list_filter = ['created_at']
    search_fields = ['transaction__description']
    ordering = ['created_at']
    readonly_fields = ['created_at']
