# Generated manually
from django.db import migrations


def populate_is_installment_true(apps, schema_editor):
    """
    Define todos os lançamentos existentes como is_installment=True
    """
    Transaction = apps.get_model('finance', 'Transaction')
    
    # Atualizar todas as transações para is_installment=True
    Transaction.objects.all().update(is_installment=True)


def reverse_populate_is_installment_true(apps, schema_editor):
    """
    Reverte a população - não faz nada pois o campo já tem default=True
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0017_add_is_installment_to_transaction'),
    ]

    operations = [
        migrations.RunPython(populate_is_installment_true, reverse_populate_is_installment_true),
    ]

