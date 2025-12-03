# Generated manually

from django.db import migrations


def populate_is_paid(apps, schema_editor):
    """
    Popula is_paid para todas as transações existentes.
    - Transações sem cartão de crédito: is_paid = True (já foram pagas)
    - Transações com cartão de crédito: is_paid = False (ainda não foram pagas)
    """
    Transaction = apps.get_model('finance', 'Transaction')
    
    # Transações sem cartão de crédito = pagas
    Transaction.objects.filter(credit_card__isnull=True).update(is_paid=True)
    
    # Transações com cartão de crédito = não pagas (podem ser pagas depois)
    Transaction.objects.filter(credit_card__isnull=False).update(is_paid=False)


def reverse_populate_is_paid(apps, schema_editor):
    """Função reversa - define is_paid como False"""
    Transaction = apps.get_model('finance', 'Transaction')
    Transaction.objects.all().update(is_paid=False)


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0007_transaction_is_paid'),
    ]

    operations = [
        migrations.RunPython(populate_is_paid, reverse_populate_is_paid),
    ]

