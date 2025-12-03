# Generated manually to populate Transaction subcategory and make it required
import django.db.models.deletion
from django.db import migrations, models


def populate_transaction_subcategory(apps, schema_editor):
    """
    Popula a subcategoria "Subcategoria Despesa Teste" em todas as transações
    que não têm subcategoria definida.
    """
    Transaction = apps.get_model('finance', 'Transaction')
    Subcategory = apps.get_model('finance', 'Subcategory')
    Category = apps.get_model('finance', 'Category')
    
    # Buscar todas as transações sem subcategoria
    transactions_without_subcategory = Transaction.objects.filter(subcategory__isnull=True)
    
    # Agrupar por usuário para criar subcategorias por usuário
    user_ids = transactions_without_subcategory.values_list('user_id', flat=True).distinct()
    
    for user_id in user_ids:
        # Buscar ou criar uma categoria padrão "Despesa" para o usuário
        category, created = Category.objects.get_or_create(
            user_id=user_id,
            name='Despesa',
            defaults={'is_income': False}
        )
        
        # Buscar ou criar a subcategoria "Subcategoria Despesa Teste" para o usuário
        subcategory, created = Subcategory.objects.get_or_create(
            user_id=user_id,
            category=category,
            name='Subcategoria Despesa Teste',
            defaults={'name': 'Subcategoria Despesa Teste'}
        )
        
        # Atualizar todas as transações desse usuário que não têm subcategoria
        Transaction.objects.filter(
            user_id=user_id,
            subcategory__isnull=True
        ).update(subcategory=subcategory)


def reverse_populate(apps, schema_editor):
    """
    Reverte a migração: remove a subcategoria das transações.
    """
    Transaction = apps.get_model('finance', 'Transaction')
    # Não fazemos nada na reversão, apenas permitimos que o campo seja nullable novamente
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0011_alter_monthlybudget_subcategory'),
    ]

    operations = [
        # 1. Popular subcategorias em todas as transações que não têm
        migrations.RunPython(populate_transaction_subcategory, reverse_populate),
        
        # 2. Tornar o campo subcategory obrigatório (remover null=True, blank=True)
        migrations.AlterField(
            model_name='transaction',
            name='subcategory',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='transactions',
                to='finance.subcategory'
            ),
        ),
    ]
