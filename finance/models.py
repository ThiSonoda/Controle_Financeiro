# finance/models.py (resumo)
from django.db import models
from django.conf import settings
from decimal import Decimal

class Category(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    is_income = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Subcategory(models.Model):
    """Subcategoria pertencente a uma Categoria."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "Subcategories"
        ordering = ['category__name', 'name']
        unique_together = ('user', 'category', 'name')

    def __str__(self):
        return f"{self.category.name} - {self.name}"

class Account(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return self.name

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
    subcategory = models.ForeignKey('Subcategory', on_delete=models.PROTECT, related_name='transactions')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='transactions', null=True, blank=True, editable=False, help_text="Categoria identificada automaticamente através da subcategoria.")
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

    is_paid = models.BooleanField(
        default=True,
        help_text="Indica se a transação foi efetivamente paga. Para cartões de crédito, indica se a fatura foi paga."
    )

    def save(self, *args, **kwargs):
        """Preenche automaticamente o campo category baseado na subcategory."""
        if self.subcategory_id and not self.category_id:
            self.category = self.subcategory.category
        elif self.subcategory_id:
            # Atualiza category caso subcategory tenha mudado
            self.category = self.subcategory.category
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date} - {self.get_type_display()} - {self.amount}"

class MonthlyBudget(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subcategory = models.ForeignKey(Subcategory, on_delete=models.CASCADE)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ('user', 'subcategory', 'year', 'month')


class ActionLog(models.Model):
    """Modelo para registrar logs de ações dos usuários."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, help_text="Usuário que executou a ação")
    timestamp = models.DateTimeField(auto_now_add=True, help_text="Data e hora da execução da ação")
    action = models.CharField(max_length=255, help_text="Descrição da ação executada")
    details = models.TextField(blank=True, help_text="Detalhes adicionais da ação (opcional)")

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Log de Ação'
        verbose_name_plural = 'Logs de Ações'

    def __str__(self):
        username = self.user.username if self.user else 'Usuário Desconhecido'
        return f"{self.timestamp.strftime('%d/%m/%Y %H:%M:%S')} - {username} - {self.action}"
