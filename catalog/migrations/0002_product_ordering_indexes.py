from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["name", "id"], name="catalog_product_name_id_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(
                fields=["category", "name", "id"],
                name="catalog_product_cat_name_idx",
            ),
        ),
    ]
