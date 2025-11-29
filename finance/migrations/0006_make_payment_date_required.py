# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_populate_payment_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='payment_date',
            field=models.DateField(help_text='Data de pagamento (data em que o pagamento aconteceu ou acontecerá)'),
        ),
    ]

