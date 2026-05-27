"""
Rule-based tag extractor for product catalog.
Reads products from DB, extracts tags from name + description,
stores back as JSONB tags column.

Run once: python generate_tags.py
"""

import os
import sys
import json
import re

sys.path.insert(0, '/home/admin1/project/multi-agent-system')
os.chdir('/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv
load_dotenv()

from app.db.database import SessionLocal
from app.models.product import Product

# ─── KEYWORD DICTIONARY (grounded in actual catalog language) ─────────────────

TAGS_BY_SUBCATEGORY = {

    "WearableTechnology": [
        "bluetooth calling", "calling", "bluetooth",
        "amoled", "oled",
        "spo2", "blood oxygen",
        "heart rate",
        "ip68", "ip67", "waterproof", "water resistant",
        "sports modes", "fitness",
        "sleep monitor", "sleep tracking",
        "voice assistant", "alexa",
        "gps",
        "always on display",
        "tws connection",
        "stress monitor",
        "fast charging",
        "long battery",
    ],

    "Headphones,Earbuds & Accessories": [
        "bluetooth", "wireless",
        "noise cancelling", "noise cancellation", "anc", "enc",
        "bass",
        "mic", "microphone",
        "ipx4", "ipx5", "ipx7", "water resistant", "waterproof",
        "neckband",
        "tws", "truly wireless",
        "gaming",
        "fast charging", "asap charge",
        "long playback", "playtime",
        "dual pairing",
        "voice assistant",
        "surround sound",
    ],

    "HomeTheater,TV & Video": [
        "smart tv", "android tv", "google tv",
        "4k", "uhd", "ultra hd", "full hd", "hd ready",
        "hdmi",
        "wifi", "voice control", "alexa",
        "dolby",
        "bezel less",
    ],

    "HomeAudio": [
        "bluetooth", "wireless",
        "bass",
        "waterproof", "ipx",
        "stereo",
        "surround sound",
        "aux", "optical",
        "multiroom",
        "alexa", "voice assistant",
    ],

    "Accessories & Peripherals": [
        "fast charging", "quick charging", "pd charging", "gan",
        "braided", "nylon braided",
        "type-c","type c" "usb-c",
        "lightning", "mfi certified",
        "micro usb",
        "data sync", "data transfer", "480mbps",
        "wireless",
        "gaming",
        "mechanical",
        "rgb", "backlit",
        "silent", "noise reduction",
        "ergonomic",
        "dpi",
        "multi device",
        "long battery",
    ],

    "NetworkingDevices": [
        "wifi", "wireless",
        "dual band",
        "5ghz", "2.4ghz",
        "usb adapter",
        "bluetooth",
        "range extender",
    ],

    "ExternalDevices & DataStorage": [
        "portable",
        "ssd",
        "usb 3.0",
        "encryption",
        "password protection",
        "high speed",
        "backup",
    ],

    "Heating,Cooling & AirQuality": [
        "hepa filter", "true hepa",
        "air purifier",
        "pm2.5",
        "wifi", "voice control", "alexa",
        "auto mode",
        "silent", "quiet",
        "coverage area",
        "filter life",
        "bacteria", "virus",
    ],

    "Kitchen & HomeAppliances": [
        "mixer grinder", "grinder",
        "induction",
        "steam iron", "dry iron",
        "auto shut off",
        "stainless steel",
        "electric kettle",
        "non stick",
        "overload protection",
        "juicer",
        "blender",
    ],

    "GeneralPurposeBatteries & BatteryChargers": [
        "power bank",
        "fast charging", "pd charging",
        "20000mah", "10000mah",
        "type-c",
        "multiple ports",
        "lightweight", "compact",
        "led indicator",
    ],

    "Monitors": [
        "full hd", "4k", "uhd",
        "ips", "va", "tn",
        "144hz", "165hz", "75hz",
        "amd freesync", "g-sync",
        "bezel less",
        "eye care", "flicker free",
        "hdmi", "displayport",
        "gaming",
    ],

}

# Universal tags extracted from any product
UNIVERSAL_KEYWORDS = [
    "wireless", "bluetooth",
    "waterproof", "water resistant",
    "fast charging",
    "gaming",
    "rgb",
    "alexa", "voice assistant",
]


def extract_tags(product: Product) -> list:
    """Extract tags from product name + description."""
    text = ""
    if product.name:
        text += product.name.lower() + " "
    if product.description:
        text += product.description.lower()

    tags = set()

    # Subcategory-specific keywords
    subcategory_keywords = TAGS_BY_SUBCATEGORY.get(product.subcategory, [])
    for keyword in subcategory_keywords:
        if keyword.lower() in text:
            tags.add(keyword.lower())

    # Universal keywords
    for keyword in UNIVERSAL_KEYWORDS:
        if keyword.lower() in text:
            tags.add(keyword.lower())

    return sorted(list(tags))


def main():
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        total = len(products)
        print(f"Processing {total} products...")

        updated = 0
        tag_counts = {}

        for i, product in enumerate(products):
            tags = extract_tags(product)
            product.tags = tags
            updated += 1

            # Track tag frequency
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

            if (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{total}...")

        db.commit()
        print(f"\n✅ Updated {updated} products with tags")

        # Show top tags
        print("\nTop 20 most common tags:")
        for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  {tag}: {count} products")

        # Show sample
        sample = db.query(Product).filter(
            Product.subcategory == 'WearableTechnology'
        ).first()
        if sample:
            print(f"\nSample (WearableTechnology):")
            print(f"  Name: {sample.name[:60]}")
            print(f"  Tags: {sample.tags}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
