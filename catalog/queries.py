"""Bounded catalog choice retrieval, independent of HTTP and widgets."""

from .models import Category, Tag

SEARCH_MAX_LENGTH = 200
MAX_SELECTED_TAGS = 20
CHOICE_PAGE_SIZE = 20
PRODUCT_PAGE_SIZE = 20


def _choice_page(queryset, *, search="", page=1):
    search = search.strip()
    if len(search) > SEARCH_MAX_LENGTH:
        raise ValueError("Search must be at most 200 characters.")
    if not isinstance(page, int) or page < 1:
        raise ValueError("Page must be a positive integer.")
    if search:
        queryset = queryset.filter(name__icontains=search)
    start = (page - 1) * CHOICE_PAGE_SIZE
    # SQLite offsets are signed 64-bit values. Beyond that, no row can exist.
    if start > 2**63 - 1 - CHOICE_PAGE_SIZE:
        rows = []
    else:
        rows = list(
            queryset.order_by("name", "pk").values("id", "name")[
                start : start + CHOICE_PAGE_SIZE + 1
            ]
        )
    return {
        "results": rows[:CHOICE_PAGE_SIZE],
        "page": page,
        "has_next": len(rows) > CHOICE_PAGE_SIZE,
        "has_previous": page > 1,
    }


def category_choices(*, search="", page=1):
    return _choice_page(Category.objects.all(), search=search, page=page)


def tag_choices(*, search="", page=1):
    return _choice_page(Tag.objects.all(), search=search, page=page)
