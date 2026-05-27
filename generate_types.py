"""
Rule-based type populator for products.
Populates the 'type' column based on product name patterns.
Run once: python generate_types.py
"""

import os
import sys
sys.path.insert(0, '/home/admin1/project/multi-agent-system')
os.chdir('/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv
load_dotenv()

from app.db.database import SessionLocal
from app.models.product import Product

# ─── TYPE RULES (order matters — first match wins) ───────────────────────────

TYPE_RULES = [

    # ── Heating,Cooling & AirQuality ─────────────────────────────────────────
    ("air purifier",    ["air purifier"]),
    ("humidifier",      ["humidifier"]),
    ("room heater",     ["room heater", "halogen heater", "heat convector",
                         "oil filled heater", "fan heater", "radiant heater"]),
    ("water heater",    ["water heater", "geyser", "instant water heater",
                         "storage water heater", "immersion rod"]),
    ("ceiling fan",     ["ceiling fan"]),
    ("pedestal fan",    ["pedestal fan", "table fan", "wall fan",
                         "tower fan", "exhaust fan"]),

    # ── Kitchen & HomeAppliances ──────────────────────────────────────────────
    ("mixer grinder",   ["mixer grinder", "mixer, grinder", "juicer mixer"]),
    ("juicer",          ["juicer"]),
    ("blender",         ["blender", "smoothie maker"]),
    ("iron",            ["dry iron", "steam iron", "iron,"]),
    ("induction",       ["induction cooktop", "induction cook"]),
    ("air fryer",       ["air fryer"]),
    ("sandwich maker",  ["sandwich maker", "sandwich griller"]),
    ("electric kettle", ["electric kettle", "kettle"]),
    ("egg boiler",      ["egg boiler"]),
    ("vacuum cleaner",  ["vacuum cleaner"]),
    ("water purifier",  ["water purifier"]),
    ("microwave",       ["microwave"]),
    ("toaster",         ["toaster", "pop-up toaster"]),
    ("hand mixer",      ["hand mixer"]),
    ("lint remover",    ["lint remover", "fabric shaver"]),
    ("kitchen scale",   ["weighing scale", "kitchen scale", "weight machine"]),
    ("frother",         ["milk frother", "coffee foamer", "cappuccino frother"]),
    ("garment steamer", ["garment steamer", "steamer"]),
    ("pressure washer", ["pressure washer"]),
    ("chopper",         ["electric chopper", "mini chopper"]),
    ("rice cooker",     ["rice cooker"]),
    ("water filter",    ["water cartridge", "water filter", "water purifier"]),

    # ── Accessories & Peripherals ─────────────────────────────────────────────
    ("keyboard",        ["keyboard"]),
    ("mouse",           ["mouse,"]),
    ("usb hub",         ["usb hub", "usb ports hub"]),
    ("laptop bag",      ["laptop bag", "laptop sleeve", "laptop case"]),
    ("ups",             ["ups system", "back-ups", "uninterruptible"]),
    ("cable",           ["cable", "charging cable", "data cable"]),
    ("adapter",         ["adapter", "adaptor", "converter"]),
    ("power bank",      ["power bank"]),
    ("webcam",          ["webcam", "web camera"]),
    ("monitor stand",   ["monitor stand", "laptop stand", "laptop table"]),
    ("drawing tablet",  ["drawing tablet", "lcd writing", "graphics tablet"]),

    # ── HomeTheater,TV & Video ────────────────────────────────────────────────
    ("smart tv", ["smart tv", "smart led tv", "smart android tv",
              "smart google tv", "smart oled", "android led tv",
              "android tv", "google tv", "led tv"]),
    ("set top box", ["setup box", "set top box", "dth box"]),
    ("tv stand",        ["tv stand", "tv unit", "tv cabinet"]),
    ("tv mount",        ["wall mount", "tv mount", "swivel tilt"]),
    ("tv remote",       ["remote control", "remote compatible"]),
    ("projector",       ["projector"]),
    ("streaming device", ["fire stick", "firestick", "streaming stick", "chromecast"]),

    # ── Mobiles & Accessories ─────────────────────────────────────────────────
    ("phone case",      ["back cover", "phone case", "mobile cover",
                         "phone cover", "back case"]),
    ("screen protector",["tempered glass", "screen protector", "screen guard"]),
    ("phone stand",     ["phone stand", "phone holder", "mobile stand"]),
    ("selfie stick",    ["selfie stick"]),
    ("smartphone", ["samsung galaxy", "oppo a", "redmi note", "realme"]),

    # ── GeneralPurposeBatteries & BatteryChargers ─────────────────────────────
    ("power bank",      ["power bank"]),
    ("charger",         ["charger", "charging adapter", "travel adapter",
                         "wall charger", "car charger"]),
    ("battery",         ["battery,"]),

    # ── Headphones,Earbuds & Accessories ─────────────────────────────────────
    ("tws earbuds",     ["truly wireless", "tws"]),
    ("neckband",        ["neckband", "wireless neckband"]),
    ("over-ear headphones", ["over ear", "over-ear", "on-ear", "on ear"]),
    ("wired earphones", ["wired earphones", "wired in ear", "wired headphones"]),
    ("headphone stand", ["headphone stand", "headphone hanger"]),

    # ── WearableTechnology ────────────────────────────────────────────────────
    ("smartwatch",      ["smart watch", "smartwatch", "fitness watch"]),
    ("fitness band",    ["fitness band", "fitness tracker", "smart band"]),

    # ── HomeAudio ─────────────────────────────────────────────────────────────
    ("bluetooth speaker",["bluetooth speaker", "wireless speaker", "portable speaker"]),
    ("soundbar",        ["soundbar", "sound bar"]),
    ("home theatre",    ["home theatre", "home theater"]),

    # ── Cameras & Photography ─────────────────────────────────────────────────
    ("action camera",   ["action camera", "action cam"]),
    ("camera accessory",["camera bag", "camera strap", "lens cap", "tripod"]),

    # ── NetworkingDevices ─────────────────────────────────────────────────────
    ("wifi adapter",    ["wifi adapter", "wireless adapter", "usb wifi",
                         "wireless usb"]),
    ("router",          ["router", "wifi router"]),
    ("range extender",  ["range extender", "wifi extender", "signal booster"]),

    # ── ExternalDevices & DataStorage ─────────────────────────────────────────
    ("external ssd",    ["portable ssd", "external ssd"]),
    ("external hdd",    ["portable hdd", "external hdd", "hard disk",
                         "hard drive"]),
    ("pen drive",       ["pen drive", "flash drive", "usb drive"]),
    ("memory card",     ["memory card", "microsd", "sd card"]),

    # ── Monitors ─────────────────────────────────────────────────────────────
    ("monitor",         ["monitor,"]),

    # ── Office Products ───────────────────────────────────────────────────────
    ("printer",         ["printer"]),
    ("ink cartridge",   ["ink cartridge", "toner"]),
    ("paper",           ["paper,"]),
    ("pen",             ["pen,"]),
    ("stapler",         ["stapler"]),
]


def extract_type(product: Product) -> str:
    """Extract product type from name using rule-based matching."""
    name = (product.name or "").lower()

    for product_type, patterns in TYPE_RULES:
        for pattern in patterns:
            if pattern.lower() in name:
                return product_type

    return None


def main():
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        total = len(products)
        print(f"Processing {total} products...")

        updated = 0
        skipped = 0
        type_counts = {}

        for product in products:
            product_type = extract_type(product)
            if product_type:
                product.type = product_type
                updated += 1
                type_counts[product_type] = type_counts.get(product_type, 0) + 1
            else:
                skipped += 1

        db.commit()
        print(f"\n✅ Updated: {updated} products")
        print(f"⚠️  Skipped (no type found): {skipped} products")

        print("\nType distribution:")
        for t, count in sorted(type_counts.items(), key=lambda x: -x[1])[:30]:
            print(f"  {t}: {count}")

        # Verify air purifier fix
        print("\n=== Air purifier check ===")
        from sqlalchemy import func
        purifiers = db.query(Product).filter(
            Product.type == 'air purifier'
        ).count()
        geysers = db.query(Product).filter(
            Product.type == 'water heater'
        ).count()
        print(f"Air purifiers typed: {purifiers}")
        print(f"Water heaters typed: {geysers}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
