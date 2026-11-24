"""The renamed-catalog copy (Phase 3 gate) renames the product types search reads, nothing else."""

from pathlib import Path

import yaml

from scripts.make_renamed_catalog_db import TYPE_NAME, renamed_type

TYPES = yaml.safe_load((Path(__file__).resolve().parent.parent / "data/catalog/product_types.yaml").read_text("utf-8"))


def test_served_type_gets_a_new_name_and_category():
    assert renamed_type("tv", "Electronics", True) == ("Televisions", "Consumer Tech")


def test_unmapped_served_type_gets_a_generic_name():
    assert renamed_type("air fryer", "Home & Kitchen", True) == ("Air Fryer Range", "Household Appliances")


def test_types_we_dont_sell_keep_their_name():
    assert renamed_type("phone", "Electronics", False) == ("phone", "Consumer Tech")


def test_hidden_other_types_keep_their_name():
    assert renamed_type("other home & kitchen", "Home & Kitchen", True)[0] == "other home & kitchen"


def test_every_served_type_is_renamed_to_a_unique_name():
    served = [t for t in TYPES["types"] if t.get("served", True) and not t["name"].startswith("other ")]
    new_names = [renamed_type(t["name"], t["category"], True)[0] for t in served]
    assert all(new != t["name"] for new, t in zip(new_names, served))
    assert len(set(n.lower() for n in new_names)) == len(new_names)
    assert set(TYPE_NAME) <= {t["name"] for t in served}
