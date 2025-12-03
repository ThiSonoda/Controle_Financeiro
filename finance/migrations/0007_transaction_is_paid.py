# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0006_make_payment_date_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='is_paid',
            field=models.BooleanField(
                default=False,
                help_text='Indica se a transação foi efetivamente paga. Para cartões de crédito, indica se a fatura foi paga.'
            ),
        ),
    ]

