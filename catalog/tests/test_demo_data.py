from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product, Tag


class ProductArticles(HTMLParser):
    """Read product content without mistaking filter labels for relationships."""

    def __init__(self, response):
        super().__init__(convert_charrefs=True)
        self.articles = []
        self.current = None
        self.heading = False
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.current = {"name": [], "text": []}
        elif tag == "h3" and self.current is not None:
            self.heading = True

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)
            if self.heading:
                self.current["name"].append(data)

    def handle_endtag(self, tag):
        if tag == "h3":
            self.heading = False
        elif tag == "article" and self.current is not None:
            self.articles.append(
                (
                    "".join(self.current["name"]),
                    " ".join(" ".join(self.current["text"]).split()),
                )
            )
            self.current = None


class DemoFixtureTests(TestCase):
    fixtures = ("catalog_demo",)

    def test_documented_name_and_description_search_examples_remain_reproducible(self):
        for query, names in (
            ("  pReCiSiOn  ", ["Precision Driver"]),
            ("drill", ["Cordless Drill", "Outdoor Drill", "Precision Driver"]),
        ):
            with self.subTest(query=query):
                response = self.client.get(
                    reverse("catalog:product_list"), {"q": query}
                )
                self.assertEqual(response.status_code, 200)
                articles = ProductArticles(response).articles
                self.assertEqual([name for name, _ in articles], names)
                driver = dict(articles)["Precision Driver"]
                self.assertIn("A lightweight drill driver for indoor repairs.", driver)

    def test_documented_combination_displays_all_relationships_not_just_filter_tags(
        self,
    ):
        response = self.client.get(
            reverse("catalog:product_list"),
            {
                "q": "drill",
                "category": Category.objects.get(name="Tools").pk,
                "tags": [
                    Tag.objects.get(name="Cordless").pk,
                    Tag.objects.get(name="Outdoor").pk,
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        articles = ProductArticles(response).articles
        self.assertEqual([name for name, _ in articles], ["Outdoor Drill"])
        for relationship in (
            "Tools",
            "Cordless",
            "Outdoor",
            "Professional",
            "Weather Resistant",
        ):
            self.assertIn(relationship, articles[0][1])

    def test_synthetic_addition_and_original_untagged_product_are_browsable(self):
        electrical = Category.objects.get(name="Electrical")
        for query, name, relationships in (
            ("power outages", "Battery Lantern", ("Cordless", "Outdoor", "Portable")),
            ("routing electrical cable", "Cable Clips", ()),
        ):
            with self.subTest(product=name):
                response = self.client.get(
                    reverse("catalog:product_list"),
                    {"q": query, "category": electrical.pk},
                )
                self.assertEqual(response.status_code, 200)
                articles = ProductArticles(response).articles
                self.assertEqual([title for title, _ in articles], [name])
                for relationship in ("Electrical", *relationships):
                    self.assertIn(relationship, articles[0][1])


class LargeFixtureTests(TestCase):
    fixtures = ("catalog_large",)

    def test_all_tags_excludes_partial_matches_and_allows_additional_tags(self):
        category = Category.objects.get(name="Carpentry Measuring Tools")
        professional = Tag.objects.get(name="Professional")
        heavy_duty = Tag.objects.get(name="Heavy Duty")
        products = Product.objects.matching(
            query="checking workpiece dimensions",
            category_id=category.pk,
            tag_ids=[professional.pk, heavy_duty.pk, professional.pk],
        )
        self.assertEqual(
            list(products.values_list("name", flat=True)),
            [
                "Carpentry Professional Measuring Tape",
                "Carpentry Workshop Measuring Tape",
            ],
        )

    def test_off_window_category_and_tags_render_matching_product_and_extra_tags(self):
        response = self.client.get(
            reverse("catalog:product_list"),
            {
                "q": "  MEASURING TAPE  ",
                "category": Category.objects.get(name="Welding Measuring Tools").pk,
                "tags": [
                    Tag.objects.get(name="Outdoor").pk,
                    Tag.objects.get(name="Professional").pk,
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        articles = ProductArticles(response).articles
        self.assertEqual(
            [name for name, _ in articles], ["Welding Outdoor Measuring Tape"]
        )
        for relationship in (
            "Welding Measuring Tools",
            "Outdoor",
            "Professional",
            "Weather Resistant",
            "Welding Inspection",
            "Welding Site Work",
        ):
            self.assertIn(relationship, articles[0][1])

    def test_untagged_product_is_included_until_a_tag_is_required(self):
        params = {
            "q": "Utility Measuring Tape",
            "category": Category.objects.get(name="Carpentry Measuring Tools").pk,
        }
        url = reverse("catalog:product_list")
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        articles = ProductArticles(response).articles
        self.assertEqual(
            [name for name, _ in articles], ["Carpentry Utility Measuring Tape"]
        )
        self.assertIn("Carpentry Measuring Tools", articles[0][1])

        response = self.client.get(
            url, {**params, "tags": [Tag.objects.get(name="Professional").pk]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductArticles(response).articles, [])
        self.assertEqual(list(response.context["products"]), [])
