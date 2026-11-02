# Django Product Catalog

A Django product catalog with name/description search, one category filter, and **ALL selected tags** matching.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). It manages the pinned Python **3.14.10**; `uv.lock` supplies Django **6.1.2** and Ruff. SQLite comes with Python. No frontend build or JavaScript dependency is needed.

Start from a project directory with **no existing `db.sqlite3`**:

```sh
uv sync --locked
uv run python manage.py migrate
uv run python manage.py loaddata catalog_demo
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/admin/. Choose your own admin credentials; no account is shipped. The admin supports editing categories, tags, and products, product search, category/tag filters, and a two-pane tag selector.

### Choose exactly one fixture

| Fixture | Categories | Tags | Products |
| --- | ---: | ---: | ---: |
| `catalog_demo` | 5 | 10 | 60 |
| `catalog_large` | 200 | 300 | 1000 |

For the larger dataset, **replace** the `loaddata catalog_demo` step with `uv run python manage.py loaddata catalog_large`. Skip fixture loading for an empty catalog. Each fixture is independently loadable into a fresh migrated database; **never load both or overlay either onto existing data**. Explicit primary keys can overwrite records. To try the other dataset, use a separate project copy without the original database, environment, or secrets, and repeat setup there; preserve any database you care about.

The demo preserves the original 5 categories, 10 tags, and 20 products entered through Django admin, plus 40 synthetic products. The large fixture is entirely synthetic. Both contain catalog records only, not accounts or admin history.

## Behavior and decisions

- Search matches a **substring of name OR description**, with surrounding whitespace stripped. SQLite ignores case for ASCII letters, but not for Cyrillic or Unicode in general.
- Category and tags combine with search using **AND**. Every selected tag must match; extra product tags are allowed. Without tag restrictions, untagged products remain eligible. Results are unique, ordered by name then primary key.
- Invalid or deleted category/tag IDs show errors and no products. Search is limited to **200 characters after stripping**; at most **20 distinct tags** may be selected. Excess input is rejected, not truncated.
- Results have **20 products per page**. Previous/next links retain all filters; submitting the filter form restarts product results at page 1.
- GET URLs preserve filters and selections; clearing filters returns to the unfiltered first page. There is **no price** because it is not required by the assignment; checkout and customer accounts are also out of scope.

### Using filters

- Use **Find categories** above the native category radio list or **Find tags** above the tag checkboxes to search names. Each search accepts at most **200 stripped characters** and shows **20 matching choices**; ordinary previous/next buttons replace the choice window.
- The selected category stays available alongside matches; choose **All categories** to remove that condition. Up to **20 selected tags** remain checked in a separate group across searches/pages. Each tag appears once; uncheck it to remove it.
- **Every submit reloads the page and applies all current product filters**, including finding or paging category/tag choices and **Apply filters**. All checked tags travel with the form, and product results restart at page 1. Finding choices resets that choice window to page 1 without resetting the other window. **Clear filters** returns to the bare catalog URL.
- The public catalog uses **no JavaScript**. Use native browser keyboard controls: Tab/Shift-Tab between fields/actions, arrows or Space to choose one category, Space on tag checkboxes, and Enter/Space on submit buttons.

Examples with `catalog_demo`:

- `precision` → **Precision Driver** (name-only match).
- `drill` → **Cordless Drill**, **Outdoor Drill**, **Precision Driver** (the last matches its description).
- `drill` + **Tools** + **Cordless**, **Outdoor** → only **Outdoor Drill**, with its additional tags displayed.
- Clear filters → all 60 products across three pages, including untagged **Cable Clips**.

## Technical choices and limits

Products have a required description/category and optional many-to-many tags. Descriptions allow at most **2000 characters** through Django model validation (`full_clean`) and admin forms; excess text is rejected, not truncated. Direct `save`, bulk operations and SQL do not automatically run this validation, and SQLite has no new length constraint. Category/tag names are unique. In-use categories are protected from deletion; deleting a tag preserves its products.

`catalog/models.py` owns reusable product query rules; `catalog/queries.py` retrieves category/tag choices. Forms validate input, views coordinate filtering/pagination, and templates render HTML. Product relationships are fetched together to avoid per-product queries. There is no separate API or frontend build.

**Deliberate coupling:** templates receive Django model instances directly for simplicity. The browser receives HTML with category/tag IDs in GET parameters and product IDs in element identifiers. These IDs are not secrets or authorization; forms validate selections, and admin changes require authenticated permissions. A future API would need an explicit representation and access policy.

**Indexes:** `catalog_product_name_id_idx(name, id)` and `catalog_product_cat_name_idx(category, name, id)` support global/category ordered retrieval, alongside Django's normal relationship indexes. SQLite `EXPLAIN` tests check actual planner use for representative ordered queries, not every possible filter combination.

**No text-search index:** ordinary B-trees do not solve arbitrary name/description substring search. FTS5 was considered but rejected: no measured representative need justifies synchronization triggers, extra write/migration complexity, and reduced database portability. Token-based full-text search is not automatically equivalent to substring matching. Pagination bounds rendered data, not SQL work: substring scans, ALL-tag aggregation, `COUNT`, and deep `OFFSET` can still be costly. These fixtures demonstrate behavior, not production capacity or a throughput guarantee; profile a real workload before adding search infrastructure.

## Local-only security

Development settings enable DEBUG, restrict hosts to localhost, and use console email; they are **not production deployment settings**. Public hosting needs separately reviewed settings, a production server, HTTPS/secure cookies, a stable private secret, and admin/login-abuse controls; Django does not provide login rate limiting by default. `manage.py check` is not a deployment-security certification.

A new secret is generated per process unless `DJANGO_SECRET_KEY` is set externally, so admin sessions normally expire on server restart. For stable sessions, generate a private value with `uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` and set `DJANGO_SECRET_KEY` in your shell before starting Django. No `.env` loader is installed. Never commit secrets or credentials; local databases and environments are ignored.

## Checks

```sh
uv run python manage.py test
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
uv run ruff format --check .
```

Tests cover filtering, relationships/deletion rules, description validation, invalid input, native form submissions, choice/product pagination, escaping, safe HTTP methods, page-local loading, fixtures, and representative ordering-index use.

## AI-assisted development

This project was developed with AI assistance, using **GPT-6.1 Sol as the primary model**, [oh-my-pi (omp)](https://github.com/can1357/oh-my-pi), [Orca](https://github.com/stablyai/orca), and the author's [Ghost in the Tools workflow skills](https://github.com/Ngoroth/ghost-in-the-tools). Django development also used the [django-expert skill](https://github.com/vintasoftware/django-ai-plugins/tree/main/skills/django-expert).

All code was reviewed and modified by the human author, who made the final product and technical decisions and remains responsible for the result. AI-assisted independent plan/code reviews and goal validation complemented, rather than replaced, that human review.
