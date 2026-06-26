BEGIN;

-- ── OFFICE PRODUCTS ──────────────────────────────────────────────────────────
UPDATE products SET subcategory='stationery'
  WHERE subcategory='OfficePaperProducts';

UPDATE products SET subcategory='office electronics'
  WHERE subcategory='OfficeElectronics';

-- ── ELECTRONICS: Batteries & Chargers ────────────────────────────────────────
UPDATE products SET subcategory='battery'
  WHERE category='Electronics' AND subcategory='GeneralPurposeBatteries & BatteryChargers'
  AND (type='battery' OR type IS NULL);

UPDATE products SET subcategory='charger', type=NULL
  WHERE category='Electronics' AND subcategory='GeneralPurposeBatteries & BatteryChargers'
  AND type='charger';

-- ── ELECTRONICS: Cameras & Photography — move misplaced products out ──────────
UPDATE products SET category='Computers & Accessories', subcategory='webcam', type=NULL
  WHERE category='Electronics' AND subcategory='Cameras & Photography' AND type='webcam';

UPDATE products SET category='Computers & Accessories', subcategory='monitor', type=NULL
  WHERE category='Electronics' AND subcategory='Cameras & Photography' AND type='monitor';

UPDATE products SET subcategory='adapter', type=NULL
  WHERE category='Electronics' AND subcategory='Cameras & Photography' AND type='adapter';

UPDATE products SET subcategory='phone stand', type=NULL
  WHERE category='Electronics' AND subcategory='Cameras & Photography' AND type='phone stand';

UPDATE products SET subcategory='charger', type=NULL
  WHERE category='Electronics' AND subcategory='Cameras & Photography' AND type='charger';

-- security cameras with wrong type='memory card' — clear the type
UPDATE products SET type=NULL
  WHERE category='Electronics' AND subcategory='Cameras & Photography' AND type='memory card';

-- ── HOME & KITCHEN ───────────────────────────────────────────────────────────
UPDATE products SET subcategory='storage organizer'
  WHERE category='Home & Kitchen' AND subcategory='HomeStorage & Organization';

-- CraftMaterials → Office Products
UPDATE products SET category='Office Products', subcategory='art supplies'
  WHERE category='Home & Kitchen' AND subcategory='CraftMaterials';

-- Kitchen & Dining: 1 chopper, 3 measuring cup sets
UPDATE products SET subcategory='chopper'
  WHERE category='Home & Kitchen' AND subcategory='Kitchen & Dining'
  AND name ILIKE '%chopper%';

UPDATE products SET subcategory='kitchen tools'
  WHERE category='Home & Kitchen' AND subcategory='Kitchen & Dining';

-- ── COMPUTERS: Accessories — rescue misidentified products ───────────────────
UPDATE products SET subcategory='gamepad', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories'
  AND (name ILIKE '%gamepad%' OR (name ILIKE '%controller%' AND name ILIKE '%gaming%'));

UPDATE products SET subcategory='laptop bag', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories'
  AND (name ILIKE '%laptop bag%' OR name ILIKE '%sleeve%');

UPDATE products SET subcategory='drawing tablet', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories'
  AND (name ILIKE '%drawing%' OR name ILIKE '%graphics tablet%'
    OR name ILIKE '%e-writer%' OR name ILIKE '%writing pad%' OR name ILIKE '%pen tablet%');

UPDATE products SET subcategory='monitor stand', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories'
  AND (name ILIKE '%laptop stand%' OR name ILIKE '%laptop table%');

UPDATE products SET subcategory='screen protector', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories'
  AND (name ILIKE '%iPad%case%' OR name ILIKE '%tablet%cover%' OR name ILIKE '%flip stand case%');

-- USB-powered speakers in Computers → Electronics/speakers
UPDATE products SET category='Electronics', subcategory='speakers', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories'
  AND (name ILIKE '%multimedia speaker%' OR name ILIKE '%2.0 speaker%'
    OR name ILIKE '%computer speaker%');

-- ── COMPUTERS: Components → specific subcategories ───────────────────────────
UPDATE products SET subcategory='external ssd', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Components'
  AND (name ILIKE '%SSD%' OR name ILIKE '%Solid State%');

UPDATE products SET subcategory='external hdd', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Components'
  AND (name ILIKE '%Caddy%' OR name ILIKE '%HDD%' OR name ILIKE '%Hard Drive%');

-- RAM stays as Components (it's truly a component, not a peripheral)

COMMIT;
