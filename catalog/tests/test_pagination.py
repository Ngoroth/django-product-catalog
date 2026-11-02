from django.db.models.signals import post_init
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product, Tag


class ProductPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Tools")
        cls.other_category = Category.objects.create(name="Safety")
        cls.products = Product.objects.bulk_create(
            [
                Product(
                    name=f"Product {index // 2:03d}",
                    description=f"Item {index} description.",
                    category=cls.category if index < 42 else cls.other_category,
                )
                for index in range(45)
            ]
        )
        cls.tags = Tag.objects.bulk_create(
            [Tag(name=f"Tag {index:03d}") for index in range(45)]
        )
        Product.tags.through.objects.bulk_create(
            [
                Product.tags.through(product_id=product.pk, tag_id=tag.pk)
                for product, tag in zip(cls.products, cls.tags, strict=True)
            ]
        )
        cls.url = reverse("catalog:product_list")

    def test_pages_partition_catalog_in_name_then_primary_key_order(self):
        expected = list(
            Product.objects.order_by("name", "pk").values_list("pk", flat=True)
        )
        seen = []
        for number, start, stop in ((1, 0, 20), (2, 20, 40), (3, 40, 45)):
            with self.subTest(page=number):
                response = self.client.get(self.url, {"page": number})
                self.assertEqual(response.status_code, 200)
                page = response.context["page_obj"]
                ids = [product.pk for product in response.context["products"]]
                self.assertEqual(ids, expected[start:stop])
                self.assertEqual(page.number, number)
                self.assertEqual(page.paginator.count, 45)
                self.assertEqual(page.paginator.num_pages, 3)
                self.assertEqual(page.has_previous(), number > 1)
                self.assertEqual(page.has_next(), number < 3)
                seen.extend(ids)
        self.assertEqual(seen, expected)

    def test_get_page_policy_handles_invalid_and_out_of_range_values(self):
        for raw, expected_page in (("nonnumeric", 1), ("0", 3), ("-1", 3), ("999", 3)):
            with self.subTest(page=raw):
                response = self.client.get(self.url, {"page": raw})
                self.assertEqual(response.context["page_obj"].number, expected_page)
                expected = (
                    self.products[:20] if expected_page == 1 else self.products[40:]
                )
                self.assertEqual(list(response.context["products"]), expected)

    def test_category_filter_applies_before_pagination(self):
        response = self.client.get(self.url, {"category": self.category.pk, "page": 3})
        self.assertEqual(list(response.context["products"]), self.products[40:42])
        self.assertEqual(response.context["page_obj"].paginator.count, 42)
        reset = self.client.get(self.url, {"category": self.other_category.pk})
        self.assertEqual(reset.context["page_obj"].number, 1)
        self.assertEqual(list(reset.context["products"]), self.products[42:])

    def test_empty_and_invalid_filters_have_empty_page_one(self):
        for params in ({"q": "absent", "page": 7}, {"tags": ["stale"], "page": 7}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                page = response.context["page_obj"]
                self.assertEqual(page.number, 1)
                self.assertEqual(page.paginator.num_pages, 1)
                self.assertEqual(page.paginator.count, 0)
                self.assertEqual(list(response.context["products"]), [])
                self.assertFalse(page.has_next())
                self.assertFalse(page.has_previous())

    def test_only_current_page_products_and_relationships_are_hydrated(self):
        hydrated_products = []
        hydrated_tags = []

        def record_product(sender, instance, **kwargs):
            hydrated_products.append(instance.pk)

        def record_tag(sender, instance, **kwargs):
            hydrated_tags.append(instance.pk)

        post_init.connect(record_product, sender=Product, weak=False)
        post_init.connect(record_tag, sender=Tag, weak=False)
        try:
            response = self.client.get(self.url, {"page": 2})
            products = list(response.context["products"])
            with self.assertNumQueries(0):
                relationships = [
                    (product.category.name, [tag.pk for tag in product.tags.all()])
                    for product in products
                ]
        finally:
            post_init.disconnect(record_product, sender=Product)
            post_init.disconnect(record_tag, sender=Tag)
        self.assertEqual(
            hydrated_products, [product.pk for product in self.products[20:40]]
        )
        self.assertCountEqual(hydrated_tags, [tag.pk for tag in self.tags[20:40]])
        self.assertEqual(
            relationships,
            [("Tools", [tag.pk]) for tag in self.tags[20:40]],
        )
