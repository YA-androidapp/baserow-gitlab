# Generated by Django 2.2.24 on 2021-08-12 16:15

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("database", "0036_createdonfield_lastmodifiedfield"),
    ]

    operations = [
        migrations.CreateModel(
            name="FormulaField",
            fields=[
                (
                    "field_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="database.Field",
                    ),
                ),
                ("formula", models.TextField()),
            ],
            options={
                "abstract": False,
            },
            bases=("database.field",),
        ),
    ]