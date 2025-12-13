from django.contrib import admin
from .models import Category, Subcategory, Account, Transaction, MonthlyBudget, BudgetItem, ActionLog, CreditCard, BudgetTemplate, BudgetTemplateItem, BudgetTemplateItemItem, Legend

admin.site.register(Category)
admin.site.register(Subcategory)
admin.site.register(Account)

class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'type', 'subcategory', 'category', 'description', 'amount', 'credit_card', 'is_paid', 'is_installment')
    list_display_links = ('date', 'type', 'subcategory', 'description', 'amount', 'credit_card')
    list_filter = ('type', 'subcategory', 'category', 'account', 'credit_card', 'is_paid', 'is_installment')
    search_fields = ('description',)
    list_editable = ('is_paid', 'is_installment')
    list_per_page = 10

admin.site.register(Transaction, TransactionAdmin)
admin.site.register(MonthlyBudget)

class BudgetItemAdmin(admin.ModelAdmin):
    list_display = ('budget', 'description', 'amount', 'order')
    list_display_links = ('description',)
    list_filter = ('budget__year', 'budget__month', 'budget__subcategory')
    search_fields = ('description', 'budget__subcategory__name')
    list_editable = ('amount', 'order')
    list_per_page = 20

admin.site.register(BudgetItem, BudgetItemAdmin)

class ActionLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'details')
    list_display_links = ('timestamp', 'user', 'action')
    list_filter = ('user', 'timestamp')
    search_fields = ('action', 'details', 'user__username')
    readonly_fields = ('timestamp',)
    list_per_page = 50
    ordering = ('-timestamp',)

admin.site.register(ActionLog, ActionLogAdmin)
admin.site.register(CreditCard)

class BudgetTemplateItemInline(admin.TabularInline):
    model = BudgetTemplateItem
    extra = 1
    fields = ('subcategory', 'amount')

class BudgetTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'user', 'created_at', 'updated_at')
    list_display_links = ('name',)
    list_filter = ('created_at', 'updated_at', 'user')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [BudgetTemplateItemInline]

admin.site.register(BudgetTemplate, BudgetTemplateAdmin)

class LegendAdmin(admin.ModelAdmin):
    list_display = ('description', 'translation', 'user', 'created_at', 'updated_at')
    list_display_links = ('description', 'translation')
    list_filter = ('created_at', 'updated_at', 'user')
    search_fields = ('description', 'translation')
    readonly_fields = ('created_at', 'updated_at')

admin.site.register(Legend, LegendAdmin)