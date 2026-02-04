# Generated manually to fix MonthlyBudget category to subcategory migration
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.state import StateApps


def migrate_category_to_subcategory(apps, schema_editor):
    """
    Migra os dados de category_id para subcategory_id.
    Para cada MonthlyBudget existente, cria uma subcategoria padrão "Geral" 
    para a categoria associada, se não existir.
    """
    MonthlyBudget = apps.get_model('finance', 'MonthlyBudget')
    Subcategory = apps.get_model('finance', 'Subcategory')
    Category = apps.get_model('finance', 'Category')
    
    # Para cada MonthlyBudget existente
    for budget in MonthlyBudget.objects.all():
        if hasattr(budget, 'category_id') and budget.category_id:
            # Busca ou cria uma subcategoria padrão "Geral" para a categoria
            subcategory, created = Subcategory.objects.get_or_create(
                user_id=budget.user_id,
                category_id=budget.category_id,
                name='Geral',
                defaults={'name': 'Geral'}
            )
            budget.subcategory_id = subcategory.id
            budget.save()


def reverse_migrate(apps, schema_editor):
    """
    Reverte a migração: copia subcategory.category_id para category_id.
    """
    MonthlyBudget = apps.get_model('finance', 'MonthlyBudget')
    
    for budget in MonthlyBudget.objects.all():
        if hasattr(budget, 'subcategory_id') and budget.subcategory_id:
            budget.category_id = budget.subcategory.category_id
            budget.save()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0009_alter_category_options_alter_transaction_category_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Adiciona o campo subcategory (temporariamente nullable)
        migrations.AddField(
            model_name='monthlybudget',
            name='subcategory',
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='budgets',
                to='finance.subcategory'
            ),
        ),
        
        # 2. Migra os dados de category para subcategory
        migrations.RunPython(migrate_category_to_subcategory, reverse_migrate),
        
        # 3. Remove o campo category usando SeparateDatabaseAndState
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # SQLite: remover todos os índices que usam category_id antes de dropar a coluna
                # 1. Índice do unique_together (user, category, year, month)
                migrations.RunSQL(
                    sql="DROP INDEX IF EXISTS finance_monthlybudget_user_id_category_id_year_month_eebf948d_uniq;",
                    reverse_sql="CREATE UNIQUE INDEX finance_monthlybudget_user_id_category_id_year_month_eebf948d_uniq ON finance_monthlybudget (user_id, category_id, year, month);",
                ),
                # 2. Índice da ForeignKey category (criado automaticamente pelo Django)
                migrations.RunSQL(
                    sql="DROP INDEX IF EXISTS finance_monthlybudget_category_id_e0ca7c00;",
                    reverse_sql="CREATE INDEX finance_monthlybudget_category_id_e0ca7c00 ON finance_monthlybudget (category_id);",
                ),
                # 3. Operação no banco: remove a coluna category_id
                migrations.RunSQL(
                    sql="ALTER TABLE finance_monthlybudget DROP COLUMN category_id;",
                    reverse_sql="ALTER TABLE finance_monthlybudget ADD COLUMN category_id INTEGER REFERENCES finance_category(id);",
                ),
            ],
            state_operations=[
                # Operação no estado do modelo: remove o campo category
                migrations.RemoveField(
                    model_name='monthlybudget',
                    name='category',
                ),
                # Atualiza unique_together no estado para evitar referência a 'category' no passo 4
                migrations.AlterUniqueTogether(
                    name='monthlybudget',
                    unique_together={('user', 'subcategory', 'year', 'month')},
                ),
            ],
        ),
        
        # 4. Torna subcategory obrigatório (não nullable)
        migrations.AlterField(
            model_name='monthlybudget',
            name='subcategory',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='budgets',
                to='finance.subcategory'
            ),
        ),
        
        # 5. Atualiza unique_together para usar subcategory
        migrations.AlterUniqueTogether(
            name='monthlybudget',
            unique_together={('user', 'subcategory', 'year', 'month')},
        ),
    ]

