from typing import ClassVar

from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Count, Q

_DESCRIPTION_MAX_LENGTH = 2000


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name", "pk"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name", "pk"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def matching(self, *, query="", category_id=None, tag_ids=()):
        """Match text, one category, and every unique selected tag ID."""
        products = self
        query = query.strip()
        if query:
            products = products.filter(
                Q(name__icontains=query) | Q(description__icontains=query)
            )
        if category_id is not None:
            products = products.filter(category_id=category_id)

        selected_tag_ids = set(tag_ids)
        if selected_tag_ids:
            # Count only selected tags; additional product tags remain eligible.
            products = (
                products.filter(tags__pk__in=selected_tag_ids)
                .alias(matched_tag_count=Count("tags", distinct=True))
                .filter(matched_tag_count=len(selected_tag_ids))
            )
        return products.order_by("name", "pk")

    def with_relationships(self):
        """Fetch the category and all tags with bounded query cost."""
        return self.select_related("category").prefetch_related("tags")


class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(
        max_length=_DESCRIPTION_MAX_LENGTH,
        validators=[MaxLengthValidator(_DESCRIPTION_MAX_LENGTH)],
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering: ClassVar[list[str]] = ["name", "pk"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["name", "id"], name="catalog_product_name_id_idx"),
            models.Index(
                fields=["category", "name", "id"], name="catalog_product_cat_name_idx"
            ),
        ]

    def __str__(self):
        return self.name
