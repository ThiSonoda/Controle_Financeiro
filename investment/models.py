from django.db import models
from django.conf import settings
from decimal import Decimal
from finance.models import Transaction, Account


class Broker(models.Model):
    """Corretora onde os investimentos estão alocados."""
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Corretora'
        verbose_name_plural = 'Corretoras'

    def __str__(self):
        return self.name


class InvestmentType(models.Model):
    """Modalidade de investimento (Tesouro Direto, Ações, FII, etc)."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Modalidade de Investimento'
        verbose_name_plural = 'Modalidades de Investimento'

    def __str__(self):
        return self.name


class Investment(models.Model):
    """Investimento individual."""
    STATUS_CHOICES = [
        ('ativo', 'Ativo'),
        ('resgatado', 'Resgatado'),
    ]

    broker = models.ForeignKey(Broker, on_delete=models.PROTECT)
    investment_type = models.ForeignKey(InvestmentType, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ativo')
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_contributed = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('broker', 'name')
        ordering = ['broker__name', 'name']
        verbose_name = 'Investimento'
        verbose_name_plural = 'Investimentos'

    def get_return_amount(self):
        """Retorna o rendimento absoluto (current_balance - total_contributed)."""
        return self.current_balance - self.total_contributed

    def get_return_percentage(self):
        """Retorna o percentual de rendimento."""
        if self.total_contributed > 0:
            return ((self.current_balance / self.total_contributed - 1) * 100)
        return Decimal('0.00')

    def __str__(self):
        return f"{self.broker.name} - {self.name}"


class InvestmentTransaction(models.Model):
    """Transação de investimento (alocação, aporte, atualização de saldo, resgate)."""
    investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_date = models.DateField()
    is_contribution = models.BooleanField(default=True)
    is_redemption = models.BooleanField(default=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        verbose_name = 'Transação de Investimento'
        verbose_name_plural = 'Transações de Investimento'

    def __str__(self):
        return f"{self.investment} - R$ {self.amount} - {self.transaction_date}"


class PendingInvestment(models.Model):
    """Valores em análise (pendentes de alocação)."""
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    amount_allocated = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Investimento Pendente'
        verbose_name_plural = 'Investimentos Pendentes'

    def get_available_amount(self):
        """Retorna o valor disponível para alocação."""
        return self.amount - self.amount_allocated

    def is_fully_allocated(self):
        """Retorna True se o valor já foi totalmente alocado."""
        return self.amount_allocated >= self.amount

    def __str__(self):
        return f"{self.transaction} - R$ {self.get_available_amount()} disponível"
