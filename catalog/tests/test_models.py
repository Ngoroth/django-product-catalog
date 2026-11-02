from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from catalog.models import Category, Product, Tag


class ProductRelationshipTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Tools")
        self.product = Product.objects.create(
            name="Claw hammer",
            description="A steel hammer for framing.",
            category=self.category,
        )

    def test_category_in_use_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.category.delete()

        self.product.refresh_from_db()
        self.assertEqual(self.product.category, self.category)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_deleting_tag_keeps_product_and_other_tags(self):
        removed_tag = Tag.objects.create(name="Steel")
        remaining_tag = Tag.objects.create(name="Hand tool")
        self.product.tags.add(removed_tag, remaining_tag)

        removed_tag.delete()

        self.product.refresh_from_db()
        self.assertEqual(self.product.category, self.category)
        self.assertSequenceEqual(list(self.product.tags.all()), [remaining_tag])

    def test_description_accepts_2000_characters_and_rejects_2001(self):
        self.product.description = "x" * 2000
        self.product.full_clean()
        self.product.save(update_fields=["description"])
        self.product.description += "x"
        with self.assertRaises(ValidationError) as raised:
            self.product.full_clean()
        self.assertEqual(
            raised.exception.error_dict["description"][0].code, "max_length"
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.description, "x" * 2000)
