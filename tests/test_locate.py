import pytest

from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.locate import LocatorError, by_help, by_title, label, right_of_label


def test_order_cust_ref_field_is_right_of_its_label(ax_snapshot):
    field = right_of_label(ax_snapshot("order_editor"), "Cust.Ref.")
    assert field.role is Role.TEXT_FIELD
    assert field.help.startswith("Customer's reference")


def test_debtor_first_and_last_name_share_one_label(ax_snapshot):
    elements = ax_snapshot("debtor_editor")
    first = right_of_label(elements, "First Name Last Name", nth=0)
    last = right_of_label(elements, "First Name Last Name", nth=1)
    assert first.rect.x < last.rect.x
    assert first.rect.y == last.rect.y


def test_debtor_zip_and_city_stop_before_the_next_labelled_column(ax_snapshot):
    elements = ax_snapshot("debtor_editor")
    zip_field = right_of_label(elements, "ZIP - City", nth=0)
    city = right_of_label(elements, "ZIP - City", nth=1)
    assert zip_field.rect.width < city.rect.width
    with pytest.raises(LocatorError, match="ZIP - City"):
        right_of_label(elements, "ZIP - City", nth=2)  # the Telefax field belongs to its own label


def test_debtor_street_has_one_field_not_the_email_column(ax_snapshot):
    elements = ax_snapshot("debtor_editor")
    street = right_of_label(elements, "Street")
    email = right_of_label(elements, "E-Mail")
    assert street.rect.right < email.rect.x
    with pytest.raises(LocatorError):
        right_of_label(elements, "Street", nth=1)


def test_debtor_country_is_a_popup(ax_snapshot):
    country = right_of_label(ax_snapshot("debtor_editor"), "Country", role=Role.POPUP)
    assert country.value == "Egypt"


@pytest.mark.parametrize(
    ("snapshot", "text", "role", "value"),
    [
        ("vat_editor", "Value", Role.TEXT_FIELD, "0%"),
        ("product_editor", "Price (gross)", Role.TEXT_FIELD, "0,00 €"),
        ("product_editor", "VAT", Role.POPUP, "Free of Tax"),
        ("product_editor", "Stock", Role.TEXT_FIELD, "0.00"),
        ("payment_editor", "Net Days", Role.TEXT_FIELD, "0"),
    ],
)
def test_fields_found_by_label_in_each_editor(ax_snapshot, snapshot, text, role, value):
    assert right_of_label(ax_snapshot(snapshot), text, role=role).value == value


def test_label_must_be_unique(ax_snapshot):
    with pytest.raises(LocatorError, match="2 labels 'VAT'"):
        label(ax_snapshot("order_editor"), "VAT")


def test_missing_label_is_reported(ax_snapshot):
    with pytest.raises(LocatorError, match="no label 'Nope'"):
        label(ax_snapshot("vat_editor"), "Nope")


def test_label_text_ignores_extra_whitespace():
    elements = (Element(Role.LABEL, Rect(0, 0, 10, 10), value="  ZIP  -   City "),)
    assert label(elements, "ZIP - City") is elements[0]


def test_field_too_far_from_its_label_is_not_taken():
    elements = (
        Element(Role.LABEL, Rect(0, 0, 50, 16), value="Name"),
        Element(Role.TEXT_FIELD, Rect(200, 0, 100, 16)),
    )
    with pytest.raises(LocatorError, match="no text_field right of label 'Name'"):
        right_of_label(elements, "Name")


def test_icons_found_by_help_text(ax_snapshot):
    picker = by_help(ax_snapshot("order_editor"), Role.IMAGE, "Pick an address from the list of all contacts")
    assert picker.rect.width == 22


def test_help_must_match_exactly_one(ax_snapshot):
    with pytest.raises(LocatorError, match="2 label"):
        by_help(ax_snapshot("vat_editor"), Role.LABEL, "Name of the tax rate")


def test_buttons_found_by_title(ax_snapshot):
    add = by_title(ax_snapshot("debtor_editor"), Role.BUTTON, "+")
    assert add.help == "add a new address for this contact"
    with pytest.raises(LocatorError, match="no button titled 'Save'"):
        by_title(ax_snapshot("debtor_editor"), Role.BUTTON, "Save")
