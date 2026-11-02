from django.test import TestCase
from django.urls import reverse

from catalog.forms import ProductFilterForm
from catalog.models import Category, Product, Tag
from catalog.queries import category_choices, tag_choices


class ChoiceLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categories = Category.objects.bulk_create(
            [Category(name=f"Category {index:03d}") for index in range(45)]
        )
        cls.tags = Tag.objects.bulk_create(
            [Tag(name=f"Tag {index:03d}") for index in range(45)]
        )
        cls.product = Product.objects.create(
            name="Off-window product",
            description="Selected choices beyond the initial window.",
            category=cls.categories[-1],
        )
        cls.product.tags.add(cls.tags[-1])
        cls.root = reverse("catalog:product_list")

    def test_shared_retrieval_pages_all_choices_in_fixed_windows(self):
        for retrieve, objects in (
            (category_choices, self.categories),
            (tag_choices, self.tags),
        ):
            seen = []
            for number, start, stop in (
                (1, 0, 20),
                (2, 20, 40),
                (3, 40, 45),
                (4, 45, 45),
            ):
                with self.subTest(retrieve=retrieve, page=number):
                    window = retrieve(page=number)
                    self.assertEqual(
                        window,
                        {
                            "results": [
                                {"id": item.pk, "name": item.name}
                                for item in objects[start:stop]
                            ],
                            "page": number,
                            "has_next": number < 3,
                            "has_previous": number > 1,
                        },
                    )
                    seen.extend(row["id"] for row in window["results"])
            self.assertEqual(seen, [item.pk for item in objects])

    def test_shared_search_is_trimmed_case_insensitive_and_literal(self):
        for model, retrieve, search_field, context_key in (
            (Category, category_choices, "category_search", "category_lookup"),
            (Tag, tag_choices, "tag_search", "tag_lookup"),
        ):
            literal = model.objects.create(name="Needle 100%_rated")
            model.objects.create(name="Needle 100 percent rated")
            for query in ("  nEeDlE 100%_  ", "%_", "100%"):
                with self.subTest(model=model, query=query):
                    expected = [{"id": literal.pk, "name": literal.name}]
                    self.assertEqual(retrieve(search=query)["results"], expected)
                    response = self.client.get(self.root, {search_field: query})
                    self.assertEqual(response.context[context_key]["results"], expected)

    def test_shared_retrieval_rejects_invalid_search_and_page_before_querying(self):
        for retrieve in (category_choices, tag_choices):
            for params in (
                {"search": "x" * 201},
                {"page": ""},
                {"page": "no"},
                {"page": 1.5},
                {"page": 0},
                {"page": -1},
            ):
                with (
                    self.subTest(retrieve=retrieve, params=params),
                    self.assertNumQueries(0),
                    self.assertRaises(ValueError),
                ):
                    retrieve(**params)

    def test_auxiliary_search_accepts_stripped_boundary_and_empty_windows(self):
        for model, field, context_key in (
            (Category, "category_search", "category_lookup"),
            (Tag, "tag_search", "tag_lookup"),
        ):
            boundary = model.objects.create(name="x" * 200)
            response = self.client.get(self.root, {field: " " + "x" * 200 + " "})
            self.assertFalse(response.context["form"].errors)
            self.assertEqual(
                response.context[context_key]["results"],
                [{"id": boundary.pk, "name": boundary.name}],
            )
            response = self.client.get(self.root, {field: "No matching choice"})
            self.assertEqual(
                response.context[context_key],
                {
                    "results": [],
                    "page": 1,
                    "has_next": False,
                    "has_previous": False,
                },
            )

    def test_removed_json_lookup_paths_return_not_found(self):
        for url in ("/lookups/categories/", "/lookups/tags/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_shared_retrieval_does_not_require_http_and_uses_one_lookahead_query(self):
        for retrieve, objects in (
            (category_choices, self.categories),
            (tag_choices, self.tags),
        ):
            with self.subTest(retrieve=retrieve):
                with self.assertNumQueries(1):
                    page = retrieve(page=2)
                self.assertEqual(
                    page["results"],
                    [{"id": item.pk, "name": item.name} for item in objects[20:40]],
                )
                self.assertTrue(page["has_next"])
                self.assertTrue(page["has_previous"])

    def test_off_window_selected_values_validate_and_are_pinned_with_twenty_matches(
        self,
    ):
        response = self.client.get(
            self.root,
            {"category": self.categories[-1].pk, "tags": [self.tags[-1].pk]},
        )
        self.assertEqual(list(response.context["products"]), [self.product])
        form = response.context["form"]
        self.assertEqual(form.cleaned_data["category"], self.categories[-1])
        self.assertEqual(list(form.cleaned_data["tags"]), [self.tags[-1]])
        for field, objects, context_key in (
            ("category", self.categories, "category_lookup"),
            ("tags", self.tags, "tag_lookup"),
        ):
            with self.subTest(field=field):
                choices = [
                    int(value)
                    for value, label in form.fields[field].widget.choices
                    if value != ""
                ]
                self.assertEqual(
                    choices, [objects[-1].pk] + [item.pk for item in objects[:20]]
                )
                self.assertEqual(
                    response.context[context_key]["results"],
                    [{"id": item.pk, "name": item.name} for item in objects[:20]],
                )

    def test_root_auxiliary_windows_search_and_page_without_changing_selection(self):
        response = self.client.get(
            self.root,
            {
                "category": self.categories[-1].pk,
                "tags": [self.tags[-1].pk],
                "category_search": " Category ",
                "category_page": "2",
                "tag_search": " Tag ",
                "tag_page": "2",
            },
        )
        self.assertEqual(list(response.context["products"]), [self.product])
        for key, objects in (
            ("category_lookup", self.categories),
            ("tag_lookup", self.tags),
        ):
            self.assertEqual(response.context[key]["page"], 2)
            self.assertEqual(
                response.context[key]["results"],
                [{"id": item.pk, "name": item.name} for item in objects[20:40]],
            )
        for raw in ("bad", "0", "-1", ""):
            with self.subTest(page=raw):
                response = self.client.get(
                    self.root, {"category_page": raw, "tag_page": raw}
                )
                self.assertEqual(response.context["category_lookup"]["page"], 1)
                self.assertEqual(response.context["tag_lookup"]["page"], 1)
                self.assertEqual(list(response.context["products"]), [self.product])

    def test_selected_window_rows_are_not_duplicated_and_invalid_auxiliary_search_fails_closed(
        self,
    ):
        form = ProductFilterForm(
            {"category": self.categories[0].pk, "tags": [self.tags[0].pk]}
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.set_choice_windows(category_choices(), tag_choices())
        for field in ("category", "tags"):
            values = [
                str(value)
                for value, label in form.fields[field].widget.choices
                if value != ""
            ]
            self.assertEqual(len(values), len(set(values)))
            self.assertEqual(len(values), 20)
        for field in ("category_search", "tag_search"):
            with self.subTest(field=field):
                response = self.client.get(self.root, {field: "x" * 201})
                self.assertIn(field, response.context["form"].errors)
                self.assertEqual(list(response.context["products"]), [])

    def test_huge_positive_choice_page_returns_empty_window_instead_of_overflow(self):
        number = 2**100
        for retrieve, field, context_key in (
            (category_choices, "category_page", "category_lookup"),
            (tag_choices, "tag_page", "tag_lookup"),
        ):
            with self.subTest(retrieve=retrieve):
                with self.assertNumQueries(0):
                    window = retrieve(page=number)
                self.assertEqual(
                    window,
                    {
                        "results": [],
                        "page": number,
                        "has_next": False,
                        "has_previous": True,
                    },
                )
                response = self.client.get(self.root, {field: str(number)})
                self.assertEqual(response.context[context_key], window)
                self.assertEqual(list(response.context["products"]), [self.product])

    def test_twenty_off_window_tags_are_all_pinned_without_truncating_matches(self):
        selected = self.tags[25:45]
        response = self.client.get(
            self.root, {"tags": [str(tag.pk) for tag in selected]}
        )
        form = response.context["form"]
        self.assertFalse(form.errors)
        self.assertCountEqual(form.cleaned_data["tags"], selected)
        self.assertEqual(
            [int(value) for value, label in form.fields["tags"].widget.choices],
            [tag.pk for tag in selected] + [tag.pk for tag in self.tags[:20]],
        )
