from unittest import skipUnless

from django.db import connection
from django.test import TestCase

from catalog.models import Category, Product


@skipUnless(connection.vendor == "sqlite", "SQLite query-plan regression coverage")
class ProductOrderingIndexTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categories = Category.objects.bulk_create(
            [Category(name=f"Category {index}") for index in range(6)]
        )
        cls.products = Product.objects.bulk_create(
            [
                Product(
                    name=f"Product {index // 3:04d}",
                    description=f"Representative item {index}.",
                    category=cls.categories[index % len(cls.categories)],
                )
                for index in range(600)
            ]
        )

    def test_global_ordered_page_uses_name_id_index(self):
        products = Product.objects.matching().with_relationships()[:20]
        plan = products.explain()
        self.assertIn("catalog_product_name_id_idx", plan)
        self.assertNotIn("TEMP B-TREE FOR ORDER BY", plan.upper())
        self.assertEqual(list(products), self.products[:20])

    def test_category_ordered_page_uses_category_name_id_index(self):
        selected_category = self.categories[2]
        products = Product.objects.matching(
            category_id=selected_category.pk
        ).with_relationships()[:20]
        plan = products.explain()
        self.assertIn("catalog_product_cat_name_idx", plan)
        self.assertNotIn("TEMP B-TREE FOR ORDER BY", plan.upper())
        self.assertEqual(
            list(products),
            [
                product
                for product in self.products
                if product.category_id == selected_category.pk
            ][:20],
        )
