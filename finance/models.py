# finance/models.py (resumo)
from django.db import models
from django.conf import settings
from decimal import Decimal

class Category(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    is_income = models.BooleanField(default=False)

    def __str__(self):
        return self.name

class Account(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

class CreditCard(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, help_text="Nome do cartão de crédito")
    closing_day = models.PositiveSmallIntegerField(
        help_text="Dia do mês em que a fatura fecha (1-31)"
    )
    due_day = models.PositiveSmallIntegerField(
        help_text="Dia do mês em que a fatura vence (1-31)"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class Transaction(models.Model):
    TYPE_INCOME = 'IN'
    TYPE_EXPENSE = 'EX'
    TYPE_CHOICES = [
        (TYPE_INCOME, 'Receita'),
        (TYPE_EXPENSE, 'Despesa'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    date = models.DateField(help_text="Data de lançamento (data em que a transação foi registrada)")
    payment_date = models.DateField(help_text="Data de pagamento (data em que o pagamento aconteceu ou acontecerá)")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    type = models.CharField(max_length=2, choices=TYPE_CHOICES)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    installment_group = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Identificador do grupo de parcelas, se for uma compra parcelada."
    )

    credit_card = models.ForeignKey(
        'CreditCard',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Cartão de crédito utilizado (se aplicável). A payment_date será ajustada para a data de vencimento da fatura."
    )

    def __str__(self):
        return f"{self.date} - {self.get_type_display()} - {self.amount}"

class MonthlyBudget(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ('user', 'category', 'year', 'month')
