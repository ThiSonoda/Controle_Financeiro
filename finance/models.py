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


class CreditCardRefund(models.Model):
    """Modelo para armazenar estornos de cartão de crédito."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    credit_card = models.ForeignKey(CreditCard, on_delete=models.CASCADE, related_name='refunds')
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Valor do estorno")
    description = models.TextField(help_text="Descrição do estorno")
    refund_date = models.DateField(help_text="Data do estorno")
    invoice_year = models.PositiveSmallIntegerField(help_text="Ano da fatura")
    invoice_month = models.PositiveSmallIntegerField(help_text="Mês da fatura")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-refund_date', '-created_at']
        verbose_name = 'Estorno de Cartão'
        verbose_name_plural = 'Estornos de Cartão'

    def __str__(self):
        return f"{self.credit_card.name} - R$ {self.amount} - {self.invoice_month}/{self.invoice_year}"


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
    comment = models.TextField(blank=True, help_text="Comentário opcional sobre o lançamento")
    created_at = models.DateTimeField(auto_now_add=True)

    installment_group = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Identificador do grupo de parcelas, se for uma compra parcelada."
    )

    is_installment = models.BooleanField(
        default=False,
        help_text="Indica se o lançamento é parte de uma compra parcelada."
    )

    credit_card = models.ForeignKey(
        'CreditCard',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Cartão de crédito utilizado (se aplicável). A payment_date será ajustada para a data de vencimento da fatura."
    )

    OWNER_THI = 'Thi'
    OWNER_THA = 'Tha'
    OWNER_CHOICES = [
        (OWNER_THI, 'Thiago'),
        (OWNER_THA, 'Thaís'),
    ]

    owner_tag = models.CharField(
        max_length=3,
        choices=OWNER_CHOICES,
        blank=True,
        null=True,
        help_text="Tag do proprietário (obrigatório para cartão Bradesco): Thi (Thiago) ou Tha (Thaís)"
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
    comment = models.TextField(blank=True, null=True, help_text="Comentário opcional sobre o orçamento")
    use_items = models.BooleanField(default=False, help_text="Se True, o valor será calculado pela soma dos itens")

    class Meta:
        unique_together = ('user', 'subcategory', 'year', 'month')


class BudgetItem(models.Model):
    """Item individual que compõe um orçamento mensal."""
    budget = models.ForeignKey(MonthlyBudget, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255, help_text="Descrição do item")
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Valor do item")
    order = models.PositiveSmallIntegerField(default=0, help_text="Ordem de exibição do item")

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Item de Orçamento'
        verbose_name_plural = 'Itens de Orçamento'

    def __str__(self):
        return f"{self.budget.subcategory.name} - {self.description}: R$ {self.amount}"


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


class BudgetTemplate(models.Model):
    """Template de orçamento com valores pré-definidos por subcategoria."""
    name = models.CharField(max_length=200, help_text="Nome do template")
    description = models.TextField(blank=True, null=True, help_text="Descrição opcional do template")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, help_text="Usuário que criou o template (para rastreamento, mas templates são globais)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Template de Orçamento'
        verbose_name_plural = 'Templates de Orçamento'

    def __str__(self):
        return self.name


class BudgetTemplateItem(models.Model):
    """Item de um template de orçamento, contendo o valor para uma subcategoria específica."""
    template = models.ForeignKey(BudgetTemplate, on_delete=models.CASCADE, related_name='items')
    subcategory = models.ForeignKey(Subcategory, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Valor do orçamento para esta subcategoria")
    comment = models.TextField(blank=True, null=True, help_text="Comentário opcional sobre o orçamento desta subcategoria")
    use_items = models.BooleanField(default=False, help_text="Se True, o valor será calculado pela soma dos itens")

    class Meta:
        unique_together = ('template', 'subcategory')
        verbose_name = 'Item do Template'
        verbose_name_plural = 'Itens do Template'

    def __str__(self):
        return f"{self.template.name} - {self.subcategory.name}: R$ {self.amount}"


class BudgetTemplateItemItem(models.Model):
    """Item individual que compõe um item de template de orçamento."""
    template_item = models.ForeignKey(BudgetTemplateItem, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255, help_text="Descrição do item")
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Valor do item")
    order = models.PositiveSmallIntegerField(default=0, help_text="Ordem de exibição do item")

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Item do Item de Template'
        verbose_name_plural = 'Itens do Item de Template'

    def __str__(self):
        return f"{self.template_item.subcategory.name} - {self.description}: R$ {self.amount}"


class Legend(models.Model):
    """Legendas para traduzir descrições de cartão de crédito."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    description = models.CharField(max_length=200, help_text="Descrição como aparece no cartão de crédito")
    translation = models.CharField(max_length=200, help_text="Tradução/Descrição amigável")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Legenda'
        verbose_name_plural = 'Legendas'
        ordering = ['description']
        unique_together = ('user', 'description')

    def __str__(self):
        return f"{self.description} → {self.translation}"
