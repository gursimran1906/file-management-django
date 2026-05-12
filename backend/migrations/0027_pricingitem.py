from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0026_matterfilereview_user_links'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PricingItem',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('category', models.CharField(choices=[('conveyancing', 'Conveyancing'), ('wills', 'Wills'), ('lpa', 'LPA'), ('probate', 'Probate'), ('divorce_family', 'Divorce and Family'), ('veriphy', 'Veriphy Checks'), ('searches', 'Searches'), ('disbursements', 'Disbursements'), ('general', 'General'), ('other', 'Other')], default='general', max_length=30)),
                ('name', models.CharField(max_length=255)),
                ('pricing_type', models.CharField(choices=[('fixed', 'Fixed price'), ('range', 'Range')], default='fixed', max_length=10)),
                ('price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('minimum_price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('maximum_price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('manager_only', models.BooleanField(default=True)),
                ('is_active', models.BooleanField(default=True)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pricing_item_created_by', to=settings.AUTH_USER_MODEL)),
                ('matter_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pricing', to='backend.mattertype')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pricing_item_updated_by', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Pricing item',
                'verbose_name_plural': 'Pricing items',
                'ordering': ['category', 'matter_type__type', 'name'],
            },
        ),
    ]
