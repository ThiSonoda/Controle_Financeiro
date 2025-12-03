from django.contrib import admin
from .models import Category, Subcategory, Account, Transaction, MonthlyBudget, ActionLog

admin.site.register(Category)
admin.site.register(Subcategory)
admin.site.register(Account)

class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'type', 'subcategory', 'category', 'description', 'amount', 'credit_card', 'is_paid')
    list_display_links = ('date', 'type', 'subcategory', 'description', 'amount', 'credit_card')
    list_filter = ('type', 'subcategory', 'category', 'account', 'credit_card', 'is_paid')
    search_fields = ('description',)
    list_editable = ('is_paid',)
    list_per_page = 10

admin.site.register(Transaction, TransactionAdmin)
admin.site.register(MonthlyBudget)

class ActionLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'details')
    list_display_links = ('timestamp', 'user', 'action')
    list_filter = ('user', 'timestamp')
    search_fields = ('action', 'details', 'user__username')
    readonly_fields = ('timestamp',)
    list_per_page = 50
    ordering = ('-timestamp',)

admin.site.register(ActionLog, ActionLogAdmin)
