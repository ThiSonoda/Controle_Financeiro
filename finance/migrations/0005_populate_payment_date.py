# Generated manually

from django.db import migrations


def populate_payment_date(apps, schema_editor):
    """
    Popula payment_date com o valor de date para todas as transações existentes.
    Para transações com cartão de crédito, também calcula a data de vencimento.
    """
    Transaction = apps.get_model('finance', 'Transaction')
    CreditCard = apps.get_model('finance', 'CreditCard')
    
    from datetime import date
    import calendar
    
    def calculate_invoice_due_date(transaction_date, closing_day, due_day):
        """Calcula a data de vencimento da fatura"""
        year = transaction_date.year
        month = transaction_date.month
        
        # Identificar o mês em que a fatura fecha
        if transaction_date.day <= closing_day:
            closing_month = month
            closing_year = year
        else:
            closing_month = month + 1
            closing_year = year
            if closing_month > 12:
                closing_month = 1
                closing_year = year + 1
        
        # Calcular a data de vencimento
        if due_day >= closing_day:
            due_month = closing_month
            due_year = closing_year
        else:
            due_month = closing_month + 1
            due_year = closing_year
            if due_month > 12:
                due_month = 1
                due_year = closing_year + 1
        
        max_day = calendar.monthrange(due_year, due_month)[1]
        final_due_day = min(due_day, max_day)
        
        return date(due_year, due_month, final_due_day)
    
    # Atualizar todas as transações
    for transaction in Transaction.objects.all():
        if transaction.payment_date is None:
            if transaction.credit_card:
                # Se tem cartão de crédito, calcular a data de vencimento
                transaction.payment_date = calculate_invoice_due_date(
                    transaction.date,
                    transaction.credit_card.closing_day,
                    transaction.credit_card.due_day
                )
            else:
                # Se não tem cartão, usar a mesma data
                transaction.payment_date = transaction.date
            transaction.save()


def reverse_populate_payment_date(apps, schema_editor):
    """Função reversa - define payment_date como None"""
    Transaction = apps.get_model('finance', 'Transaction')
    Transaction.objects.all().update(payment_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0004_transaction_payment_date_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_payment_date, reverse_populate_payment_date),
    ]

