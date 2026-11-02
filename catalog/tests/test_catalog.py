from html.parser import HTMLParser

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.forms import ProductFilterForm
from catalog.models import Category, Product, Tag


class CatalogData(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tools = Category.objects.create(name="Tools")
        cls.safety = Category.objects.create(name="Safety")
        cls.portable = Tag.objects.create(name="Portable")
        cls.steel = Tag.objects.create(name="Steel")
        cls.rated = Tag.objects.create(name="Rated")
        cls.hammer = Product.objects.create(
            name="Hammer", description="A framing tool.", category=cls.tools
        )
        cls.extra = Product.objects.create(
            name="Grip", description="A HAMMER alternative.", category=cls.tools
        )
        cls.partial = Product.objects.create(
            name="Hammer partial", description="Compact tool.", category=cls.tools
        )
        cls.wrong_category = Product.objects.create(
            name="Hammer safety", description="Protective cover.", category=cls.safety
        )
        cls.wrong_tags = Product.objects.create(
            name="Hammer polymer", description="Nonmetallic tool.", category=cls.tools
        )
        cls.unrelated = Product.objects.create(
            name="Wrench", description="Turns bolts.", category=cls.tools
        )
        cls.untagged = Product.objects.create(
            name="Brush", description="Cleans work surfaces.", category=cls.tools
        )
        for product in (cls.hammer, cls.extra, cls.wrong_category, cls.unrelated):
            product.tags.add(cls.portable, cls.steel)
        cls.extra.tags.add(cls.rated)
        cls.partial.tags.add(cls.portable)
        cls.wrong_tags.tags.add(cls.rated)

    def assertProducts(self, products, expected):
        self.assertEqual(
            [product.pk for product in products], [product.pk for product in expected]
        )


class ProductQueryTests(CatalogData):
    def test_search_matches_name_or_description_case_insensitively_and_trims(self):
        self.assertProducts(
            Product.objects.matching(query="  hAmMeR  "),
            [
                self.extra,
                self.hammer,
                self.partial,
                self.wrong_tags,
                self.wrong_category,
            ],
        )

    def test_search_and_category_and_all_tags_restrict_both_text_branches(self):
        wrong_category_description = Product.objects.create(
            name="Safety grip",
            description="A hammer accessory.",
            category=self.safety,
        )
        wrong_category_description.tags.add(self.portable, self.steel)
        self.assertProducts(
            Product.objects.matching(
                query="hammer",
                category_id=self.tools.pk,
                tag_ids=[self.portable.pk, self.steel.pk],
            ),
            [self.extra, self.hammer],
        )

    def test_all_tags_allows_extra_tags_excludes_partial_and_avoids_duplicates(self):
        self.assertProducts(
            Product.objects.matching(
                tag_ids=[self.portable.pk, self.steel.pk, self.portable.pk]
            ),
            [self.extra, self.hammer, self.wrong_category, self.unrelated],
        )

    def test_no_filter_includes_untagged_and_whitespace_does_not_restrict(self):
        expected = [
            self.untagged,
            self.extra,
            self.hammer,
            self.partial,
            self.wrong_tags,
            self.wrong_category,
            self.unrelated,
        ]
        self.assertProducts(Product.objects.matching(), expected)
        self.assertProducts(Product.objects.matching(query=" \t "), expected)

    def test_category_without_tags_keeps_untagged_product(self):
        self.assertProducts(
            Product.objects.matching(category_id=self.tools.pk),
            [
                self.untagged,
                self.extra,
                self.hammer,
                self.partial,
                self.wrong_tags,
                self.unrelated,
            ],
        )

    def test_substring_search_treats_percent_and_underscore_literally(self):
        for query, literal_name, other_name in (
            ("%", "100% guide", "100 percent guide"),
            ("_", "Bit_set", "Bit set"),
        ):
            with self.subTest(query=query):
                literal = Product.objects.create(
                    name=literal_name, description="Reference.", category=self.tools
                )
                Product.objects.create(
                    name=other_name, description="Reference.", category=self.tools
                )
                self.assertProducts(Product.objects.matching(query=query), [literal])

    def test_matching_is_lazy_and_same_names_use_primary_key_order(self):
        first = Product.objects.create(
            name="Equal name", description="First.", category=self.tools
        )
        second = Product.objects.create(
            name="Equal name", description="Second.", category=self.tools
        )
        with self.assertNumQueries(0):
            products = Product.objects.matching(query="Equal name")
        self.assertProducts(products, [first, second])

    def test_relationship_queries_stay_bounded_for_different_product_counts(self):
        expected = {
            self.untagged.pk: ("Tools", ()),
            self.extra.pk: ("Tools", ("Portable", "Rated", "Steel")),
            self.hammer.pk: ("Tools", ("Portable", "Steel")),
            self.partial.pk: ("Tools", ("Portable",)),
            self.wrong_tags.pk: ("Tools", ("Rated",)),
            self.wrong_category.pk: ("Safety", ("Portable", "Steel")),
            self.unrelated.pk: ("Tools", ("Portable", "Steel")),
        }
        query_counts = []
        for selected_ids in ([self.extra.pk, self.hammer.pk], list(expected)):
            with self.subTest(product_count=len(selected_ids)):
                with CaptureQueriesContext(connection) as queries:
                    relationships = {
                        product.pk: (
                            product.category.name,
                            tuple(tag.name for tag in product.tags.all()),
                        )
                        for product in Product.objects.filter(pk__in=selected_ids)
                        .matching()
                        .with_relationships()
                    }
                self.assertEqual(
                    relationships, {pk: expected[pk] for pk in selected_ids}
                )
                self.assertLessEqual(len(queries), 2)
                query_counts.append(len(queries))
        self.assertEqual(query_counts[0], query_counts[1])


class PageControls(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.inputs = []
        self.checked_categories = []
        self.clear_url = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            self.inputs.append(attrs)
            if (
                attrs.get("type") == "radio"
                and attrs.get("name") == "category"
                and "checked" in attrs
            ):
                self.checked_categories.append(attrs.get("value", ""))
        elif tag == "a" and "data-filter-clear" in attrs:
            self.clear_url = attrs.get("href")


class ProductPageTests(CatalogData):
    def setUp(self):
        self.url = reverse("catalog:product_list")

    def test_unfiltered_page_and_unknown_parameters_show_full_catalog(self):
        expected = list(Product.objects.order_by("name", "pk"))
        for params in ({}, {"unrelated": "ignored"}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200)
                self.assertProducts(response.context["products"], expected)

    def test_combined_get_filters_preserve_controls_and_reloadable_url(self):
        params = {
            "q": " HaMmEr ",
            "category": str(self.tools.pk),
            "tags": [str(self.portable.pk), str(self.steel.pk), str(self.portable.pk)],
        }
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        self.assertProducts(response.context["products"], [self.extra, self.hammer])
        form = response.context["form"]
        self.assertEqual(form.cleaned_data["q"], "HaMmEr")
        self.assertEqual(form.cleaned_data["category"], self.tools)
        self.assertCountEqual(form.cleaned_data["tags"], [self.portable, self.steel])

        controls = PageControls(response.content.decode())
        query_input = next(item for item in controls.inputs if item.get("name") == "q")
        self.assertEqual(query_input["value"], params["q"])
        self.assertEqual(controls.checked_categories, [str(self.tools.pk)])
        self.assertCountEqual(
            [
                item["value"]
                for item in controls.inputs
                if item.get("name") == "tags" and "checked" in item
            ],
            [str(self.portable.pk), str(self.steel.pk)],
        )

        reloaded = self.client.get(response.wsgi_request.get_full_path())
        self.assertProducts(reloaded.context["products"], [self.extra, self.hammer])

    def test_invalid_or_deleted_selections_show_errors_and_no_products(self):
        deleted_category = Category.objects.create(name="Deleted category")
        deleted_category_id = deleted_category.pk
        deleted_category.delete()
        deleted_tag = Tag.objects.create(name="Deleted tag")
        deleted_tag_id = deleted_tag.pk
        deleted_tag.delete()
        for field, value in (
            ("category", "not-an-id"),
            ("category", str(deleted_category_id)),
            ("tags", "not-an-id"),
            ("tags", str(deleted_tag_id)),
        ):
            with self.subTest(field=field, value=value):
                params = {"q": "Hammer", field: value}
                if field == "tags":
                    params[field] = [str(self.portable.pk), value]
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertProducts(response.context["products"], [])
                self.assertTrue(response.context["form"].is_bound)

    def test_no_matches_and_reset_returns_unfiltered_products(self):
        response = self.client.get(
            self.url,
            {"q": "No matching product", "category": str(self.tools.pk)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertProducts(response.context["products"], [])
        clear_url = PageControls(response.content.decode()).clear_url
        self.assertEqual(clear_url, self.url)
        reset_response = self.client.get(clear_url)
        self.assertProducts(
            reset_response.context["products"], list(Product.objects.all())
        )

    def test_optional_form_fields_accept_an_empty_selection(self):
        form = ProductFilterForm({"q": "   ", "category": "", "tags": []})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["q"], "")
        self.assertIsNone(form.cleaned_data["category"])
        self.assertEqual(list(form.cleaned_data["tags"]), [])


class FilterLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Tools")
        cls.tags = Tag.objects.bulk_create(
            [Tag(name=f"Selected tag {index:02d}") for index in range(21)]
        )
        cls.complete = Product.objects.create(
            name="Complete kit",
            description="All twenty selected tags.",
            category=cls.category,
        )
        cls.complete.tags.add(*cls.tags[:20])
        cls.partial = Product.objects.create(
            name="Partial kit",
            description="Only nineteen selected tags.",
            category=cls.category,
        )
        cls.partial.tags.add(*cls.tags[:19])
        cls.url = reverse("catalog:product_list")

    def test_search_limit_applies_after_stripping_without_truncating(self):
        product = Product.objects.create(
            name="x" * 200, description="Boundary match.", category=self.category
        )
        response = self.client.get(self.url, {"q": " " + "x" * 200 + " "})
        self.assertEqual(list(response.context["products"]), [product])
        self.assertEqual(response.context["form"].cleaned_data["q"], "x" * 200)
        response = self.client.get(self.url, {"q": "x" * 201})
        self.assertIn("q", response.context["form"].errors)
        self.assertEqual(list(response.context["products"]), [])

    def test_twenty_distinct_tags_allow_canonical_duplicates_and_preserve_all_semantics(
        self,
    ):
        ids = [str(tag.pk) for tag in self.tags[:20]]
        params = {
            "tags": ids + [f"{self.tags[0].pk:06d}", f" +{self.tags[0].pk} ", ids[0]],
        }
        response = self.client.get(self.url, params)
        form = response.context["form"]
        self.assertFalse(form.errors)
        self.assertCountEqual(form.cleaned_data["tags"], self.tags[:20])
        self.assertEqual(list(response.context["products"]), [self.complete])
        controls = PageControls(response.content.decode())
        self.assertCountEqual(
            [
                item["value"]
                for item in controls.inputs
                if item.get("name") == "tags" and "checked" in item
            ],
            ids,
        )

    def test_twenty_one_unique_tags_are_rejected_before_any_selected_tag_query(self):
        form = ProductFilterForm({"tags": [str(tag.pk) for tag in self.tags]})
        with self.assertNumQueries(0):
            self.assertFalse(form.is_valid())
        self.assertEqual(form.errors.as_data()["tags"][0].code, "too_many_tags")
        response = self.client.get(
            self.url, {"tags": [str(tag.pk) for tag in self.tags]}
        )
        self.assertIn("tags", response.context["form"].errors)
        self.assertEqual(list(response.context["products"]), [])

    def test_malformed_tag_is_rejected_without_hydrating_other_selected_tags(self):
        form = ProductFilterForm({"tags": [str(self.tags[0].pk), "not-an-integer"]})
        with self.assertNumQueries(0):
            self.assertFalse(form.is_valid())
        self.assertIn("tags", form.errors)

    def test_integer_aliases_keep_selected_category_and_tags_checked(self):
        response = self.client.get(
            self.url,
            {
                "category": f"{self.category.pk:06d}",
                "tags": [f"{self.tags[0].pk:06d}", str(self.tags[0].pk)],
            },
        )
        self.assertFalse(response.context["form"].errors)
        self.assertEqual(
            list(response.context["products"]), [self.complete, self.partial]
        )
        controls = PageControls(response.content.decode())
        self.assertEqual(controls.checked_categories, [str(self.category.pk)])
        self.assertEqual(
            [
                item["value"]
                for item in controls.inputs
                if item.get("name") == "tags" and "checked" in item
            ],
            [str(self.tags[0].pk)],
        )
