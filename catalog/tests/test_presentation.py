from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

from django.middleware.csrf import get_token
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from catalog.models import Category, Product, Tag


class PageMarkup(HTMLParser):
    """Read browser-visible elements and submit successful native GET controls."""

    def __init__(self, response):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.stack = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        element = {
            "tag": tag,
            "attrs": dict(attrs),
            "text": "",
            "parent": self.stack[-1] if self.stack else None,
        }
        self.elements.append(element)
        if tag not in {"input", "link", "meta", "br", "hr", "img"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        for element in self.stack:
            element["text"] += data

    def find(self, tag=None, **attrs):
        return [
            element
            for element in self.elements
            if (tag is None or element["tag"] == tag)
            and all(
                key in element["attrs"] and element["attrs"][key] == value
                for key, value in attrs.items()
            )
        ]

    def checked_tags(self):
        return {
            element["attrs"]["value"]
            for element in self.find("input", name="tags")
            if "checked" in element["attrs"]
        }

    def choice_button(self, kind, action):
        labels = {
            "search": f"Find {'categories' if kind == 'category' else 'tags'}",
            "previous": f"Previous {'categories' if kind == 'category' else 'tags'}",
            "next": f"Next {'categories' if kind == 'category' else 'tags'}",
        }
        return next(
            button
            for button in self.find("button", name=f"{kind}_page")
            if button["text"].strip() == labels[action]
        )

    def native_query(self, button=None, changes=None):
        pairs = []
        for element in self.find("input"):
            attrs = element["attrs"]
            if not attrs.get("name") or "disabled" in attrs:
                continue
            if attrs.get("type") in {"checkbox", "radio"} and "checked" not in attrs:
                continue
            pairs.append((attrs["name"], attrs.get("value", "")))
        if changes:
            pairs = [(name, value) for name, value in pairs if name not in changes]
            for name, values in changes.items():
                for value in values if isinstance(values, (list, tuple)) else [values]:
                    pairs.append((name, value))
        if button:
            attrs = button["attrs"]
            if attrs.get("name"):
                pairs.append((attrs["name"], attrs.get("value", "")))
        return urlencode(pairs)


class PresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categories = [
            Category.objects.create(name=f"Category {index:02}") for index in range(45)
        ]
        cls.tags = [Tag.objects.create(name=f"Tag {index:02}") for index in range(45)]
        cls.selected_category = cls.categories[44]
        cls.selected_tags = [cls.tags[42], cls.tags[44]]
        for index in range(25):
            product = Product.objects.create(
                name=f"Cordless drill {index:02}",
                description="Drives screws.\nIncludes a battery.",
                category=cls.selected_category,
            )
            product.tags.add(*cls.selected_tags)
        Product.objects.create(
            name="Excluded saw", description="Cuts wood.", category=cls.categories[0]
        )

    def setUp(self):
        self.url = reverse("catalog:product_list")
        self.filters = {
            "q": "drill",
            "category": str(self.selected_category.pk),
            "tags": [str(tag.pk) for tag in self.selected_tags],
        }

    def test_rendered_products_include_relationships_and_exclude_nonmatches(self):
        page = PageMarkup(self.client.get(self.url, self.filters))
        articles = page.find("article")
        self.assertEqual(len(articles), 20)
        first = articles[0]["text"]
        for value in (
            "Cordless drill 00",
            "Drives screws.",
            "Includes a battery.",
            self.selected_category.name,
            *(tag.name for tag in self.selected_tags),
        ):
            self.assertIn(value, first)
        self.assertFalse(any("Excluded saw" in item["text"] for item in articles))
        self.assertFalse(any("Cordless drill 24" in item["text"] for item in articles))

    def test_product_page_links_keep_repeated_tags_and_apply_resets_product_page(self):
        choice_state = {
            "category_search": "Category",
            "category_page": "2",
            "tag_search": "Tag",
            "tag_page": "2",
        }
        page = PageMarkup(self.client.get(self.url, {**self.filters, **choice_state}))
        next_link = page.find("a", rel="next")[0]["attrs"]["href"]
        params = parse_qs(urlsplit(next_link).query)
        self.assertEqual(params["tags"], self.filters["tags"])
        self.assertEqual(params["q"], ["drill"])
        self.assertEqual(params["category"], [str(self.selected_category.pk)])
        for name, value in choice_state.items():
            self.assertEqual(params[name], [value])
        second = PageMarkup(self.client.get(next_link))
        self.assertIn("Cordless drill 24", second.find("article")[-1]["text"])
        self.assertEqual(len(second.find("article")), 5)
        apply_buttons = second.find("button", **{"data-filter-apply": None})
        self.assertEqual(len(apply_buttons), 1)
        query = second.native_query(button=apply_buttons[0])
        self.assertNotIn("page", parse_qs(query))
        restarted = PageMarkup(self.client.get(f"{self.url}?{query}"))
        self.assertIn("Cordless drill 00", restarted.find("article")[0]["text"])

    def test_native_choice_paging_preserves_off_window_selections(self):
        response = self.client.get(self.url, self.filters)
        for name in ("tag_page", "category_page"):
            page = PageMarkup(response)
            button = page.choice_button(name.removesuffix("_page"), "next")
            self.assertNotIn("disabled", button["attrs"])
            response = self.client.get(f"{self.url}?{page.native_query(button=button)}")
            updated = PageMarkup(response)
            self.assertEqual(updated.checked_tags(), set(self.filters["tags"]))
            selected = updated.find("input", name="category", checked=None)
            self.assertIn(
                str(self.selected_category.pk),
                [item["attrs"]["value"] for item in selected],
            )
            self.assertLessEqual(len(updated.find("input", name="tags")), 22)
            self.assertLessEqual(len(updated.find("input", name="category")), 22)
            self.assertIn("Cordless drill 00", updated.find("article")[0]["text"])

    def test_every_native_choice_is_reachable_without_javascript(self):
        for field, page_name, expected in (
            ("tags", "tag_page", {str(tag.pk) for tag in self.tags}),
            (
                "category",
                "category_page",
                {str(category.pk) for category in self.categories},
            ),
        ):
            with self.subTest(field=field):
                response = self.client.get(self.url)
                seen = set()
                for _ in range(3):
                    page = PageMarkup(response)
                    controls = page.find("input", name=field)
                    seen.update(item["attrs"].get("value") for item in controls)
                    button = page.choice_button(page_name.removesuffix("_page"), "next")
                    if "disabled" in button["attrs"]:
                        break
                    response = self.client.get(
                        f"{self.url}?{page.native_query(button=button)}"
                    )
                self.assertEqual(seen - {""}, expected)
                self.assertIn("disabled", button["attrs"])
                for _ in range(2):
                    previous = page.choice_button(
                        page_name.removesuffix("_page"), "previous"
                    )
                    self.assertNotIn("disabled", previous["attrs"])
                    response = self.client.get(
                        f"{self.url}?{page.native_query(button=previous)}"
                    )
                    page = PageMarkup(response)
                self.assertIn(
                    "disabled",
                    page.choice_button(page_name.removesuffix("_page"), "previous")[
                        "attrs"
                    ],
                )

    def test_native_choice_search_keeps_selected_values_and_finds_late_choices(self):
        page = PageMarkup(self.client.get(self.url, self.filters))
        button = page.choice_button("tag", "search")
        query = page.native_query(button=button, changes={"tag_search": "Tag 31"})
        searched = PageMarkup(self.client.get(f"{self.url}?{query}"))
        self.assertEqual(searched.checked_tags(), set(self.filters["tags"]))
        values = {
            item["attrs"]["value"] for item in searched.find("input", name="tags")
        }
        self.assertEqual(values, {*self.filters["tags"], str(self.tags[31].pk)})
        self.assertIn("Cordless drill 00", searched.find("article")[0]["text"])

    def test_native_category_search_finds_and_selects_an_off_window_category(self):
        matching = Product.objects.create(
            name="Late category drill",
            description="A drill in a category outside the first choice window.",
            category=self.categories[31],
        )
        matching.tags.add(*self.selected_tags)
        partial = Product.objects.create(
            name="Partial category drill",
            description="Missing one required tag.",
            category=self.categories[31],
        )
        partial.tags.add(self.selected_tags[0])
        page = PageMarkup(self.client.get(self.url, self.filters))
        self.assertFalse(
            page.find("input", name="category", value=str(self.categories[31].pk))
        )
        button = page.choice_button("category", "search")
        query = page.native_query(
            button=button, changes={"category_search": "Category 31"}
        )
        searched = PageMarkup(self.client.get(f"{self.url}?{query}"))
        self.assertEqual(
            {
                item["attrs"]["value"]
                for item in searched.find("input", name="category")
            },
            {"", str(self.categories[31].pk), str(self.selected_category.pk)},
        )
        self.assertEqual(searched.checked_tags(), set(self.filters["tags"]))
        self.assertEqual(
            [
                item["attrs"]["value"]
                for item in searched.find("input", name="category", checked=None)
            ],
            [str(self.selected_category.pk)],
        )
        query = searched.native_query(
            button=searched.find("button", **{"data-filter-apply": None})[0],
            changes={"category": str(self.categories[31].pk)},
        )
        selected = PageMarkup(self.client.get(f"{self.url}?{query}"))
        articles = selected.find("article")
        self.assertEqual(len(articles), 1)
        self.assertIn(matching.name, articles[0]["text"])
        self.assertNotIn(partial.name, articles[0]["text"])
        self.assertIn(self.categories[31].name, articles[0]["text"])
        self.assertEqual(selected.checked_tags(), set(self.filters["tags"]))

    def test_native_apply_submits_one_canonical_category_and_each_selected_tag_once(
        self,
    ):
        page = PageMarkup(
            self.client.get(
                self.url,
                {
                    **self.filters,
                    "category": f"{self.selected_category.pk:06d}",
                    "tags": [
                        f"{self.selected_tags[0].pk:06d}",
                        *self.filters["tags"],
                        self.filters["tags"][1],
                    ],
                },
            )
        )
        query = page.native_query(
            button=page.find("button", **{"data-filter-apply": None})[0]
        )
        params = parse_qs(query)
        self.assertEqual(params["category"], [str(self.selected_category.pk)])
        self.assertCountEqual(params["tags"], self.filters["tags"])
        submitted = PageMarkup(self.client.get(f"{self.url}?{query}"))
        self.assertEqual(
            [
                heading["text"]
                for heading in submitted.find("h3")
                if heading["parent"]["tag"] == "article"
            ],
            [f"Cordless drill {index:02}" for index in range(20)],
        )
        self.assertEqual(submitted.checked_tags(), set(self.filters["tags"]))

    def test_errors_are_visible_linked_and_descriptions_resolve(self):
        page = PageMarkup(
            self.client.get(self.url, {"q": "x" * 201, "tags": "missing"})
        )
        self.assertEqual(page.find("article"), [])
        ids = {item["attrs"]["id"] for item in page.elements if "id" in item["attrs"]}
        query = page.find("input", name="q")[0]
        self.assertIn("id_q_helptext", query["attrs"]["aria-describedby"].split())
        tags = page.find("fieldset", id="id_tags")[0]
        self.assertIn("id_tags_error", tags["attrs"]["aria-describedby"].split())
        self.assertEqual(tags["attrs"]["aria-invalid"], "true")
        for item in page.elements:
            for target in item["attrs"].get("aria-describedby", "").split():
                self.assertIn(target, ids)
        self.assertTrue(page.find("a", href="#id_tags"))
        self.assertTrue(page.find("ul", id="id_tags_error")[0]["text"].strip())

    def test_invalid_choice_search_errors_link_to_the_corresponding_inputs(self):
        for field_name in ("category_search", "tag_search"):
            with self.subTest(field=field_name):
                invalid_value = "x" * 201
                response = self.client.get(
                    self.url, {**self.filters, field_name: invalid_value}
                )
                self.assertEqual(response.status_code, 200)
                page = PageMarkup(response)
                self.assertEqual(page.find("article"), [])
                search = page.find("input", name=field_name)[0]
                self.assertEqual(search["attrs"]["value"], invalid_value)
                error_links = page.find("a", href=f"#{search['attrs']['id']}")
                self.assertTrue(error_links)
                self.assertTrue(page.find("label", **{"for": search["attrs"]["id"]}))

    def test_empty_state_has_clear_link_to_bare_catalog_url(self):
        page = PageMarkup(self.client.get(self.url, {"q": "No such catalog product"}))
        self.assertEqual(page.find("article"), [])
        self.assertTrue(page.find("li", **{"class": "empty-state"}))
        clear_links = page.find("a", **{"data-filter-clear": None})
        self.assertEqual(len(clear_links), 1)
        self.assertEqual(clear_links[0]["attrs"]["href"], self.url)
        reset = PageMarkup(self.client.get(clear_links[0]["attrs"]["href"]))
        self.assertIn("Cordless drill 00", reset.find("article")[0]["text"])

    def test_hostile_catalog_content_is_text_not_executable_markup(self):
        category = Category.objects.create(name='<img src=x onerror="alert(1)">')
        tag = Tag.objects.create(name='<svg onload="alert(2)">')
        product = Product.objects.create(
            name='<script>alert("name")</script>',
            description='<img src=x onerror="alert(3)">\n<script>alert("description")</script>',
            category=category,
        )
        product.tags.add(tag)
        page = PageMarkup(
            self.client.get(self.url, {"category": category.pk, "tags": [tag.pk]})
        )
        article = page.find("article")[0]
        for value in (
            product.name,
            category.name,
            tag.name,
            '<script>alert("description")</script>',
        ):
            self.assertIn(value, article["text"])
        self.assertEqual(page.find("img"), [])
        self.assertEqual(page.find("svg"), [])
        self.assertEqual(page.find("script"), [])
        self.assertFalse(
            any(key.startswith("on") for item in page.elements for key in item["attrs"])
        )

    def test_root_rejects_post_with_csrf_and_head_has_no_body(self):
        strict = Client(enforce_csrf_checks=True)
        request = RequestFactory().get(self.url)
        token = get_token(request)
        self.assertEqual(strict.post(self.url).status_code, 403)
        strict.cookies["csrftoken"] = request.META["CSRF_COOKIE"]
        rejected = strict.post(self.url, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(rejected.status_code, 405)
        self.assertEqual(
            set(rejected.headers["Allow"].replace(" ", "").split(",")),
            {"GET", "HEAD"},
        )
        head = strict.head(self.url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")

    def test_all_choice_submits_apply_current_filters_and_reset_product_page(self):
        pending_tags = [self.tags[30], self.selected_tags[0]]
        pending_products = []
        for index in range(25):
            product = Product.objects.create(
                name=f"Pending drill {index:02}",
                description="New filters applied during choice navigation.",
                category=self.categories[31],
            )
            product.tags.add(*pending_tags)
            pending_products.append(product)
        partial = Product.objects.create(
            name="Pending partial drill",
            description="Missing a pending tag.",
            category=self.categories[31],
        )
        partial.tags.add(pending_tags[0])
        current = {
            **self.filters,
            "page": "2",
            "category_search": "Category",
            "category_page": "2",
            "tag_search": "Tag",
            "tag_page": "2",
        }
        for kind in ("category", "tag"):
            for action, expected_page in (("search", 1), ("previous", 1), ("next", 3)):
                with self.subTest(kind=kind, action=action):
                    response = self.client.get(self.url, current)
                    self.assertEqual(response.context["page_obj"].number, 2)
                    page = PageMarkup(response)
                    changes = {
                        "q": "Pending",
                        "category": str(self.categories[31].pk),
                        "tags": [str(tag.pk) for tag in pending_tags],
                    }
                    if action == "search":
                        changes[f"{kind}_search"] = (
                            "Category 03" if kind == "category" else "Tag 03"
                        )
                    query = page.native_query(
                        button=page.choice_button(kind, action), changes=changes
                    )
                    params = parse_qs(query)
                    self.assertNotIn("page", params)
                    self.assertEqual(params["tags"], changes["tags"])
                    self.assertEqual(params[f"{kind}_page"], ["2", str(expected_page)])
                    other = "tag" if kind == "category" else "category"
                    self.assertEqual(params[f"{other}_page"], ["2"])
                    self.assertEqual(
                        params[f"{other}_search"], [current[f"{other}_search"]]
                    )
                    submitted = self.client.get(f"{self.url}?{query}")
                    self.assertFalse(submitted.context["form"].errors)
                    self.assertEqual(submitted.context["page_obj"].number, 1)
                    self.assertEqual(
                        list(submitted.context["products"]), pending_products[:20]
                    )
                    self.assertEqual(
                        submitted.context[f"{kind}_lookup"]["page"], expected_page
                    )
                    self.assertEqual(submitted.context[f"{other}_lookup"]["page"], 2)
                    self.assertEqual(
                        PageMarkup(submitted).checked_tags(), set(changes["tags"])
                    )

    def test_twenty_off_window_selected_tags_and_twenty_matches_render_once(self):
        selected = self.tags[25:45]
        page = PageMarkup(
            self.client.get(self.url, {"tags": [str(tag.pk) for tag in selected]})
        )
        controls = page.find("input", name="tags")
        values = [item["attrs"]["value"] for item in controls]
        self.assertCountEqual(
            values, [str(tag.pk) for tag in [*selected, *self.tags[:20]]]
        )
        self.assertEqual(page.checked_tags(), {str(tag.pk) for tag in selected})
        for control in controls:
            ancestor = control["parent"]
            container_ids = set()
            while ancestor is not None:
                container_ids.add(ancestor["attrs"].get("id"))
                ancestor = ancestor["parent"]
            group = (
                "selected-tags" if "checked" in control["attrs"] else "matching-tags"
            )
            self.assertIn(group, container_ids)
        query = page.native_query(
            button=page.find("button", **{"data-filter-apply": None})[0]
        )
        self.assertCountEqual(
            parse_qs(query)["tags"], [str(tag.pk) for tag in selected]
        )

    def test_matching_tags_render_once_and_unchecking_and_all_categories_apply(self):
        remaining_tag = self.selected_tags[0]
        matching = Product.objects.create(
            name="A remaining-tag drill",
            description="Visible after removing the other selected tag.",
            category=self.selected_category,
        )
        matching.tags.add(remaining_tag)
        other_category = Product.objects.create(
            name="Another category drill",
            description="Visible after choosing all categories.",
            category=self.categories[0],
        )
        other_category.tags.add(remaining_tag)
        page = PageMarkup(
            self.client.get(self.url, {**self.filters, "tag_search": "Tag 4"})
        )
        for tag in self.selected_tags:
            self.assertEqual(len(page.find("input", name="tags", value=str(tag.pk))), 1)
        removed = page.find("input", name="tags", value=str(self.selected_tags[1].pk))[
            0
        ]
        del removed["attrs"]["checked"]
        query = page.native_query(
            button=page.find("button", **{"data-filter-apply": None})[0]
        )
        self.assertEqual(parse_qs(query)["tags"], [str(remaining_tag.pk)])
        response = self.client.get(f"{self.url}?{query}")
        self.assertIn(matching, response.context["products"])
        self.assertNotIn(other_category, response.context["products"])
        page = PageMarkup(response)
        all_categories = page.find("input", name="category", value="")[0]
        self.assertEqual(all_categories["parent"]["text"].strip(), "All categories")
        query = page.native_query(
            button=page.find("button", **{"data-filter-apply": None})[0],
            changes={"category": ""},
        )
        response = self.client.get(f"{self.url}?{query}")
        self.assertIn(other_category, response.context["products"])
        self.assertEqual(PageMarkup(response).checked_tags(), {str(remaining_tag.pk)})
        self.assertEqual(
            PageMarkup(response).find("input", name="category", checked=None)[0][
                "attrs"
            ]["value"],
            "",
        )

    def test_invalid_ids_and_excess_tags_have_visible_resolvable_error_links(self):
        stale_category = Category.objects.create(name="Deleted category")
        stale_category_id = stale_category.pk
        stale_category.delete()
        stale_tag = Tag.objects.create(name="Deleted tag")
        stale_tag_id = stale_tag.pk
        stale_tag.delete()
        for field, value, target in (
            ("category", "missing", "id_category"),
            ("category", str(stale_category_id), "id_category"),
            ("tags", ["missing"], "id_tags"),
            ("tags", [str(stale_tag_id)], "id_tags"),
            ("tags", [str(tag.pk) for tag in self.tags[:21]], "id_tags"),
        ):
            with self.subTest(field=field, value=value):
                response = self.client.get(self.url, {field: value})
                page = PageMarkup(response)
                self.assertEqual(page.find("article"), [])
                self.assertIn(field, response.context["form"].errors)
                self.assertTrue(page.find("a", href=f"#{target}"))
                control = page.find(id=target)[0]
                self.assertEqual(control["attrs"]["aria-invalid"], "true")
                ids = {
                    item["attrs"]["id"]
                    for item in page.elements
                    if "id" in item["attrs"]
                }
                for describedby in control["attrs"]["aria-describedby"].split():
                    self.assertIn(describedby, ids)
                error = page.find(id=f"{target}_error")[0]
                self.assertTrue(error["text"].strip())
