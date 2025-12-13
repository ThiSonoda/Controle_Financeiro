# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0021_legend'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlybudget',
            name='use_items',
            field=models.BooleanField(default=False, help_text='Se True, o valor será calculado pela soma dos itens'),
        ),
        migrations.CreateModel(
            name='BudgetItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.CharField(help_text='Descrição do item', max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, help_text='Valor do item', max_digits=14)),
                ('order', models.PositiveSmallIntegerField(default=0, help_text='Ordem de exibição do item')),
                ('budget', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='finance.monthlybudget')),
            ],
            options={
                'verbose_name': 'Item de Orçamento',
                'verbose_name_plural': 'Itens de Orçamento',
                'ordering': ['order', 'id'],
            },
        ),
    ]

