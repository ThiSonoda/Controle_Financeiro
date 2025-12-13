# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0022_budgetitem_monthlybudget_use_items'),
    ]

    operations = [
        migrations.AddField(
            model_name='budgettemplateitem',
            name='use_items',
            field=models.BooleanField(default=False, help_text='Se True, o valor será calculado pela soma dos itens'),
        ),
        migrations.CreateModel(
            name='BudgetTemplateItemItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.CharField(help_text='Descrição do item', max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, help_text='Valor do item', max_digits=14)),
                ('order', models.PositiveSmallIntegerField(default=0, help_text='Ordem de exibição do item')),
                ('template_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='finance.budgettemplateitem')),
            ],
            options={
                'verbose_name': 'Item do Item de Template',
                'verbose_name_plural': 'Itens do Item de Template',
                'ordering': ['order', 'id'],
            },
        ),
    ]
