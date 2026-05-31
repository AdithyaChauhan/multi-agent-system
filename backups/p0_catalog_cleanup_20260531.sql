-- P0 catalog cleanup — 2026-05-31
-- Silent-miss fixes: move stranded earbuds, TVs, and accessories
-- out of legacy composite buckets into proper subcategories.
-- All changes are targeted product_id UPDATEs; no schema changes.
--
-- BEFORE:
--   Headphones,Earbuds & Accessories / None        = 11 rows (earbuds missing from search)
--   Headphones,Earbuds & Accessories / battery     =  2 rows (real earphones mistagged)
--   Headphones,Earbuds & Accessories / cable       =  3 rows (2 wired earphones + 1 splitter)
--   HomeTheater,TV & Video / None                  = 11 rows (2 real TVs missing from search)
--   smartwatch / screen_protector                  =  1 row  (watch case cover polluting bucket)
--   smartwatch (charger, type=null)                =  1 row  (smartwatch charger polluting bucket)
--
-- ROLLBACK: set subcategory/type back to previous values per product_id

BEGIN;

-- ── TVs → tv/smart tv ────────────────────────────────────────────────────────
UPDATE products SET subcategory='tv', type='smart tv'
WHERE product_id IN (
  'B0B9XN9S3W',  -- Acer 32" N Series HD Ready TV
  'B087JWLZ2K'   -- AmazonBasics 43" Fire TV
);

-- ── TWS earbuds → headphones/tws earbuds ─────────────────────────────────────
UPDATE products SET subcategory='headphones', type='tws earbuds'
WHERE product_id IN (
  'B0B31BYXQQ',  -- Boult Airbass Z20 True Wireless
  'B0B31FR4Y2',  -- Boult Omega True Wireless
  'B0B5GJRTHB',  -- Wecool Moonwalk M1 ENC True Wireless
  'B0B2931FCV',  -- ZEBRONICS Zeb-Sound Bomb N1 True Wireless
  'B08JQN8DGZ',  -- boAt Airdopes 121v2
  'B09PL79D2X',  -- boAt Airdopes 181
  'B09X76VL5L',  -- boAt Airdopes 191G
  'B086WMSCN3'   -- boAt Airdopes 171 (was mistagged type='battery')
);

-- ── Neckband/BT earphones → headphones/neckband ──────────────────────────────
UPDATE products SET subcategory='headphones', type='neckband'
WHERE product_id IN (
  'B07LG59NPV',  -- Boult Probass Curve Bluetooth Wireless
  'B09NR6G588',  -- Boult ZCharge Bluetooth Wireless
  'B08FB2LNSZ',  -- JBL Tune 215BT
  'B09YLFHFDW'   -- Sony WI-C100 (was mistagged type='battery')
);

-- ── Wired earphones mistagged type='cable' → headphones/wired earphones ──────
UPDATE products SET subcategory='headphones', type='wired earphones'
WHERE product_id IN (
  'B09SGGRKV8',  -- ZEBRONICS Zeb-Buds 30 wired in-ear
  'B08VRMK55F'   -- Zebronics Zeb Buds C2 Type-C wired
);

-- ── Non-earphone leftovers in legacy bucket → neutralise ─────────────────────
UPDATE products SET subcategory='cable', type='cable'
WHERE product_id='B08BCKN299';  -- Sounce 3.5mm headphone splitter (audio cable)

UPDATE products SET subcategory='Accessories'
WHERE product_id IN (
  'B07DKZCZ89',  -- Gizga Earphone Carrying Case
  'B08X77LM8C'   -- Silicone Rubber Earbuds Tips
);

-- ── Smartwatch accessories out of smartwatch bucket ───────────────────────────
UPDATE products SET subcategory='cable', type='cable'
WHERE product_id='B0BMM7R92G';  -- Noise smartwatch magnetic charger

UPDATE products SET subcategory='screen protector', type=NULL
WHERE product_id='B0B298D54H';  -- Prolet Galaxy Watch 4 case cover

COMMIT;

-- RESULT:
--   headphones / neckband            7 → 11 (+4)
--   headphones / tws earbuds         9 → 17 (+8)
--   headphones / wired earphones    22 → 24 (+2)
--   Headphones,Earbuds & Accessories  17 → 0 (fully dissolved)
--   tv / smart tv                   81 → 83 (+2)
--   HomeTheater,TV & Video / None   11 → 9  (-2 TVs)
--   smartwatch / *                  62 → 60 (-2 accessories)
