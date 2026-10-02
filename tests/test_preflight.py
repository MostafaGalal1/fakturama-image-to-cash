import json

import pytest

from image_to_cash.drive.preflight import check_currency, currency_locale, load_order
from image_to_cash.errors import NeedsReview
from image_to_cash.normalized import normalize
from image_to_cash.outputs import write_order

PREFS = "eclipse.preferences.version=1\nCONTACT_USE_COUNTRY=true\nPREFERENCE_CURRENCY_LOCALE={locale}\n"


def test_order_json_round_trips(tmp_path, sample_order):
    normalized = normalize(sample_order)
    path = write_order(normalized, tmp_path)
    assert load_order(path) == normalized


def test_edited_order_json_is_revalidated_without_echoing_values(tmp_path, sample_order):
    payload = json.loads(normalize(sample_order).model_dump_json())
    payload["lines"][0]["vat_percent"] = "7"  # no longer matches its product
    path = tmp_path / "order.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid order.json") as raised:
        load_order(path)
    assert sample_order.customer.email not in str(raised.value)


def test_missing_order_json_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        load_order(tmp_path / "order.json")


@pytest.mark.parametrize(("text", "locale"), [(PREFS.format(locale="de/DE"), "de/DE"), ("A=1\n", None), ("# PREFERENCE_CURRENCY_LOCALE=de/DE\n", None)])
def test_currency_locale_is_read_from_the_preferences(text, locale):
    assert currency_locale(text) == locale


def test_escaped_property_values_are_unescaped():
    assert currency_locale("PREFERENCE_CURRENCY_LOCALE=de\\/DE\n") == "de/DE"


@pytest.mark.parametrize("locale", ["de/DE", "fr/FR", "de/AT"])
def test_euro_locales_pass(tmp_path, locale):
    prefs = tmp_path / "rcp.prefs"
    prefs.write_text(PREFS.format(locale=locale), encoding="utf-8")
    assert check_currency(prefs) == locale


@pytest.mark.parametrize(("text", "shown"), [(PREFS.format(locale="ar/EG"), "ar/EG"), ("A=1\n", "unset")])
def test_other_currencies_stop_before_touching_fakturama(tmp_path, text, shown):
    prefs = tmp_path / "rcp.prefs"
    prefs.write_text(text, encoding="utf-8")
    with pytest.raises(NeedsReview, match=f"fakturama_currency_not_eur: currency_locale={shown}"):
        check_currency(prefs)


def test_missing_preferences_file_means_the_currency_is_unknown(tmp_path):
    with pytest.raises(NeedsReview, match="currency_locale=unset"):
        check_currency(tmp_path / "missing.prefs")
