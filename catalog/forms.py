from django import forms

from .models import Category, Tag
from .queries import MAX_SELECTED_TAGS, SEARCH_MAX_LENGTH


class LimitedTagChoiceField(forms.ModelMultipleChoiceField):
    def clean(self, value):
        if not value:
            return super().clean(value)
        if not isinstance(value, (list, tuple)):
            raise forms.ValidationError(
                self.error_messages["invalid_list"], code="invalid_list"
            )
        normalized = set()
        for raw_id in value:
            try:
                normalized.add(int(raw_id))
            except TypeError, ValueError, OverflowError:
                raise forms.ValidationError(
                    self.error_messages["invalid_pk_value"],
                    code="invalid_pk_value",
                    params={"pk": raw_id},
                ) from None
            if len(normalized) > MAX_SELECTED_TAGS:
                raise forms.ValidationError(
                    "Select at most %(limit)s distinct tags.",
                    code="too_many_tags",
                    params={"limit": MAX_SELECTED_TAGS},
                )
        # Reject the oversized set before Django builds or hydrates its query.
        return super().clean([str(pk) for pk in sorted(normalized)])


class ProductFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        strip=True,
        max_length=SEARCH_MAX_LENGTH,
        label="Search",
        help_text="Search product names and descriptions.",
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        empty_label="All categories",
        widget=forms.RadioSelect,
        blank=True,
    )
    tags = LimitedTagChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Products must have every selected tag.",
    )
    category_search = forms.CharField(
        required=False,
        strip=True,
        max_length=SEARCH_MAX_LENGTH,
        label="Find categories",
    )
    tag_search = forms.CharField(
        required=False, strip=True, max_length=SEARCH_MAX_LENGTH, label="Find tags"
    )

    def clean(self):
        cleaned = super().clean()
        # Canonical IDs must also be reflected by the bound native controls.
        data = self.data.copy()
        if "category" in cleaned and cleaned["category"] is not None:
            data["category"] = str(cleaned["category"].pk)
        if "tags" in cleaned:
            values = [str(tag.pk) for tag in cleaned["tags"]]
            if hasattr(data, "setlist"):
                data.setlist("tags", values)
            else:
                data["tags"] = values
        self.data = data
        return cleaned

    def set_choice_windows(self, category_lookup, tag_lookup):
        """Bound presentation only; validation always uses complete querysets."""
        selected_category = self.cleaned_data.get("category")
        category_rows = (
            [(selected_category.pk, selected_category.name)]
            if selected_category is not None
            else []
        )
        tag_rows = [(tag.pk, tag.name) for tag in self.cleaned_data.get("tags", ())]
        for field_name, selected, lookup in (
            ("category", category_rows, category_lookup),
            ("tags", tag_rows, tag_lookup),
        ):
            choices = dict(selected)
            choices.update((row["id"], row["name"]) for row in lookup["results"])
            rows = list(choices.items())
            if field_name == "category":
                rows.insert(0, ("", self.fields["category"].empty_label))
            self.fields[field_name].widget.choices = rows
