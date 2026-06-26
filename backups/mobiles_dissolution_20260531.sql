-- Mobiles & Accessories dissolution
-- Split 151-product composite bucket into specific subcategories

BEGIN;

-- 1. Typed products: subcategory = type, clear type (type IS now the subcategory)
UPDATE products SET subcategory = type, type = NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories'
  AND type IN ('power bank', 'screen protector', 'phone stand', 'selfie stick',
               'phone case', 'charger', 'battery', 'memory card', 'pen',
               'camera accessory');

-- Cables and adapters → move to Computers & Accessories to consolidate with existing
UPDATE products SET category='Computers & Accessories', subcategory='cable', type=NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type='cable';

UPDATE products SET category='Computers & Accessories', subcategory='adapter', type=NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type='adapter';

-- tv mount → already exists as Electronics subcategory
UPDATE products SET subcategory='tv mount', type=NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type='tv mount';

-- Smartphones (typed) → subcategory='smartphone', keep category
UPDATE products SET subcategory='smartphone'
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type='smartphone';

-- 2. Null-type: assign by name pattern

-- Smartphones (most of the nulls)
UPDATE products SET subcategory='smartphone', type='smartphone'
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type IS NULL
  AND (name ILIKE '% RAM%' OR name ILIKE '% ROM%' OR name ILIKE '%5G%'
    OR name ILIKE '% SIM%' OR name ILIKE '%Helio%' OR name ILIKE '%Dimensity%'
    OR name ILIKE '%Snapdragon%' OR name ILIKE '%keypad phone%'
    OR name ILIKE '%Android%');

-- Phone stands/holders/mounts
UPDATE products SET subcategory='phone stand', type=NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type IS NULL
  AND (name ILIKE '%mobile stand%' OR name ILIKE '%phone stand%'
    OR name ILIKE '%mobile holder%' OR name ILIKE '%phone holder%'
    OR name ILIKE '%mobile mount%' OR name ILIKE '%tabletop stand%'
    OR name ILIKE '%tabletop holder%' OR name ILIKE '%Car-Vent Mobile%'
    OR name ILIKE '%Clamp%Mobile%');

-- Stylus / iPad pencil
UPDATE products SET subcategory='pen', type=NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type IS NULL
  AND (name ILIKE '%pencil%' OR name ILIKE '%stylus%');

-- Remaining nulls → generic 'Accessories'
UPDATE products SET subcategory='Accessories', type=NULL
  WHERE category='Electronics' AND subcategory='Mobiles & Accessories' AND type IS NULL;

COMMIT;
