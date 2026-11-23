#!/usr/bin/env python3
"""Make a copy of the baseline database with every category name changed (Phase 0 robustness check).

Real catalogs get re-organised: "mouse" becomes "Mice & Pointing Devices". Search that only works
with today's exact category names is fragile. This script copies the source database and renames
every category, subcategory and type, so eval/run_retrieval.py can measure how much search drops.
Product ids, names, prices and ratings stay the same, so the labels in eval/product_queries.json
still apply.

Since Phase 1, search reads types from the product_types table, so that table's names and
categories are renamed too (the old text columns on products are renamed as before). Synonyms,
kinds, attributes and brands stay: they are shopping words and product facts that survive a
reorganisation. Types we don't sell and the hidden "other ..." types keep their names.

    python scripts/make_renamed_catalog_db.py            # multi_agent_baseline -> multi_agent_renamed

Copying needs no other open connections to the source database: stop evals and baseline runs
first. Only a target database whose name ends in "_renamed" is ever dropped and recreated.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.run_baseline import DEFAULT_DB  # noqa: E402

CATEGORY = {
    "Electronics": "Consumer Tech",
    "Home & Kitchen": "Household Appliances",
    "Computers & Accessories": "PC & Peripherals",
    "Office Products": "Stationery & Office",
}
# Realistic alternative names for the larger subcategories; the rest get a generic rewrite.
SUBCATEGORY = {
    "cable": "Charging & Data Leads",
    "tv": "Televisions",
    "headphones": "Personal Audio",
    "smartwatch": "Wearables",
    "room heater": "Space Heating",
    "water heater": "Geysers & Boilers",
    "mixer grinder": "Food Processors",
    "mouse": "Pointing Devices",
    "electric kettle": "Hot Beverage Appliances",
    "iron": "Garment Care",
    "stationery": "Writing Supplies",
    "adapter": "Power Adapters",
    "lint remover": "Fabric Care",
    "vacuum cleaner": "Floor Care",
    "tv remote": "Remote Controls",
    "keyboard": "Input Devices",
    "blender": "Blending",
    "monitor stand": "Desk Ergonomics",
    "wifi adapter": "Network Dongles",
    "water purifier": "Drinking Water Systems",
    "phone stand": "Device Holders",
    "storage organizer": "Home Organisation",
    "speakers": "Home Audio",
    "screen protector": "Display Guards",
    "battery": "Cells & Power",
    "kitchen scale": "Kitchen Measuring",
    "set top box": "TV Receivers",
    "egg boiler": "Egg Cookers",
    "drawing tablet": "Writing Pads",
    "ceiling fan": "Air Circulation",
    "pen drive": "Portable Storage",
    "power bank": "Portable Power",
    "induction": "Cooktops",
}
TYPE = {
    "smart tv": "Connected Television",
    "smartwatch": "Wrist Wearable",
    "cable": "Lead",
    "wired earphones": "Corded In-Ear",
    "tws earbuds": "True Wireless In-Ear",
    "tv remote": "Handset Controller",
    "over-ear headphones": "Around-Ear Audio",
    "neckband": "Behind-Neck Wireless",
    "set top box": "Satellite Receiver",
    "bluetooth speaker": "Portable Audio",
    "soundbar": "Bar Audio",
    "home theatre": "Surround System",
}
# product_types.name (Phase 1 types): what another shop might call the same section.
TYPE_NAME = {
    "cable": "Charging & Data Leads",
    "mouse": "Pointing Devices",
    "keyboard": "Input Devices",
    "adapter": "Connectivity Dongles",
    "laptop stand": "Desk Ergonomics",
    "networking": "Wi-Fi & Routers",
    "storage": "Data Storage Devices",
    "drawing tablet": "Digital Sketch Pads",
    "printer": "Print & Scan",
    "laptop bag": "Computer Carry Cases",
    "webcam": "Video Calling Cameras",
    "tv": "Televisions",
    "headphones": "Personal Audio",
    "smartwatch": "Wearables",
    "speaker": "Home Audio",
    "tv remote": "Remote Controls",
    "tv accessory": "Television Add-ons",
    "set top box": "TV Receivers",
    "power bank": "Portable Power",
    "charger": "Wall Chargers",
    "battery": "Cells & Power",
    "phone holder": "Device Mounts",
    "screen protector": "Display Guards",
    "camera": "Imaging",
    "stylus": "Touch Pens",
    "room heater": "Space Heating",
    "water heater": "Geysers & Boilers",
    "mixer grinder": "Food Processors",
    "electric kettle": "Hot Beverage Appliances",
    "iron": "Garment Care",
    "lint remover": "Fabric Care",
    "vacuum cleaner": "Floor Care",
    "blender": "Blending",
    "water purifier": "Drinking Water Systems",
    "fan": "Air Circulation",
    "kitchen scale": "Kitchen Measuring",
    "cooking appliance": "Countertop Cooking",
    "home appliance": "Household Gadgets",
    "laundry basket": "Laundry Storage",
    "stationery": "Writing Supplies",
    "art supplies": "Craft & Drawing",
}
NOT_SOLD = {"smartphone", "laptop", "laptops", "tablet", "tablets"}  # keep these: the app must still exclude them


def renamed(value, mapping: dict, generic: str):
    if value is None or value.lower() in NOT_SOLD:
        return value
    return mapping.get(value) or mapping.get(value.lower()) or generic.format(value.title())


def renamed_type(name: str, category: str, served: bool) -> tuple:
    """(new name, new category) for a product_types row. Types we don't sell keep their name, so
    refusals are still tested; "other ..." types keep theirs because the model never sees them."""
    new_category = CATEGORY.get(category, category)
    if not served or name.startswith("other "):
        return name, new_category
    return TYPE_NAME.get(name) or f"{name.title()} Range", new_category


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-url", default=os.getenv("BASELINE_DATABASE_URL", DEFAULT_DB))
    parser.add_argument("--target", default="multi_agent_renamed")
    args = parser.parse_args()
    if not args.target.endswith("_renamed"):
        print("refusing: the target database name must end with _renamed")
        return 1

    src = urlparse(args.source_url)
    source = src.path.lstrip("/")
    admin = create_engine(urlunparse(src._replace(path="/postgres")), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{args.target}"'))
        conn.execute(text(f'CREATE DATABASE "{args.target}" TEMPLATE "{source}"'))
    admin.dispose()

    target = create_engine(urlunparse(src._replace(path=f"/{args.target}")))
    with target.begin() as conn:
        for column, mapping, generic in (
            ("category", CATEGORY, "{} Department"),
            ("subcategory", SUBCATEGORY, "{} Range"),
            ("type", TYPE, "{} Line"),
        ):
            values = [r[0] for r in conn.execute(text(f"SELECT DISTINCT {column} FROM products"))]
            for value in values:
                new = renamed(value, mapping, generic)
                if new != value:
                    conn.execute(
                        text(f"UPDATE products SET {column} = :new WHERE {column} = :old"), {"new": new, "old": value}
                    )
        type_rows = conn.execute(text("SELECT id, name, category, served FROM product_types")).all()
        renamed_types = 0
        for tid, name, category, served in type_rows:
            new_name, new_category = renamed_type(name, category, served)
            renamed_types += new_name != name
            conn.execute(
                text("UPDATE product_types SET name = :n, category = :c WHERE id = :id"),
                {"n": new_name, "c": new_category, "id": tid},
            )
        counts = conn.execute(
            text("SELECT count(DISTINCT category), count(DISTINCT subcategory), count(*) FROM products")
        ).one()
    print(
        f"created {args.target} from {source}: {counts[2]} products, {counts[0]} categories, "
        f"{counts[1]} subcategories, {renamed_types} of {len(type_rows)} product types renamed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
