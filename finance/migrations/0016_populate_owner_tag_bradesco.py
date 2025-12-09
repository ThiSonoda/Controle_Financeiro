# Generated manually
from django.db import migrations


def populate_owner_tag_bradesco(apps, schema_editor):
    """
    Marca todos os lançamentos existentes do cartão Bradesco com owner_tag='Thi'
    """
    Transaction = apps.get_model('finance', 'Transaction')
    CreditCard = apps.get_model('finance', 'CreditCard')
    
    # Buscar cartão Bradesco (pode ter diferentes variações de nome)
    bradesco_cards = CreditCard.objects.filter(name__icontains='Bradesco')
    
    for card in bradesco_cards:
        # Atualizar todas as transações desse cartão para ter owner_tag='Thi'
        Transaction.objects.filter(credit_card=card, owner_tag__isnull=True).update(owner_tag='Thi')


def reverse_populate_owner_tag_bradesco(apps, schema_editor):
    """
    Reverte a população - remove a tag dos lançamentos do Bradesco
    """
    Transaction = apps.get_model('finance', 'Transaction')
    CreditCard = apps.get_model('finance', 'CreditCard')
    
    bradesco_cards = CreditCard.objects.filter(name__icontains='Bradesco')
    
    for card in bradesco_cards:
        Transaction.objects.filter(credit_card=card, owner_tag='Thi').update(owner_tag=None)


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0015_add_owner_tag_to_transaction'),
    ]

    operations = [
        migrations.RunPython(populate_owner_tag_bradesco, reverse_populate_owner_tag_bradesco),
    ]

