from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .forms import ProductFilterForm
from .models import Product
from .queries import PRODUCT_PAGE_SIZE, category_choices, tag_choices


def _window_page(value):
    try:
        return max(1, int(value))
    except TypeError, ValueError, OverflowError:
        return 1


@require_safe
def product_list(request):
    form = ProductFilterForm(request.GET)
    products = Product.objects.none()
    if form.is_valid():
        category = form.cleaned_data["category"]
        products = Product.objects.matching(
            query=form.cleaned_data["q"],
            category_id=category.pk if category is not None else None,
            tag_ids=(tag.pk for tag in form.cleaned_data["tags"]),
        ).with_relationships()
    page_obj = Paginator(products, PRODUCT_PAGE_SIZE).get_page(request.GET.get("page"))
    category_lookup = category_choices(
        search=form.cleaned_data.get("category_search", ""),
        page=_window_page(request.GET.get("category_page")),
    )
    tag_lookup = tag_choices(
        search=form.cleaned_data.get("tag_search", ""),
        page=_window_page(request.GET.get("tag_page")),
    )
    form.set_choice_windows(category_lookup, tag_lookup)
    return render(
        request,
        "catalog/product_list.html",
        {
            "form": form,
            "products": page_obj.object_list,
            "page_obj": page_obj,
            "category_lookup": category_lookup,
            "tag_lookup": tag_lookup,
        },
    )
