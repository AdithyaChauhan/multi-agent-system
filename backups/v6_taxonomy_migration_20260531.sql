-- V6 Taxonomy Migration
-- Converts old composite subcategory bucket names to clean, specific subcategory names
-- Matches the 821c8d1 + 5fba422 taxonomy changes applied to the host DB

BEGIN;

-- ================================================================
-- ELECTRONICS
-- ================================================================

-- 1. HomeTheater,TV & Video → split by type
UPDATE products SET subcategory='tv'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='smart tv';

UPDATE products SET subcategory='cable'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='cable';

UPDATE products SET subcategory='tv remote'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='tv remote';

UPDATE products SET subcategory='set top box'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='set top box';

UPDATE products SET subcategory='projector'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='projector';

UPDATE products SET subcategory='streaming device'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='streaming device';

UPDATE products SET subcategory='adapter'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='adapter';

UPDATE products SET subcategory='tv mount'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='tv mount';

UPDATE products SET subcategory='tv stand'
  WHERE category='Electronics' AND subcategory='HomeTheater,TV & Video' AND type='tv stand';

-- null-type HomeTheater: handle individually based on product names
UPDATE products SET subcategory='tv', type='smart tv'
  WHERE product_id IN ('B0B9XN9S3W', 'B087JWLZ2K');  -- Acer 32", AmazonBasics 43"

UPDATE products SET subcategory='tv remote'
  WHERE product_id IN ('B09P8M18QM', 'B00RFWNJMC', 'B071VMP1Z4', 'B01N90RZ4M');  -- Fire TV / DTH / Sony / Tata Sky remotes

UPDATE products SET subcategory='set top box'
  WHERE product_id='B07YZG8PPY';  -- Tata Sky DTH connection

UPDATE products SET subcategory='cable'
  WHERE product_id='B006LW0WDQ';  -- AmazonBasics Speaker Wire

UPDATE products SET subcategory='streaming device'
  WHERE product_id='B097JVLW3L';  -- Irusu VR headset (closest match)

UPDATE products SET subcategory='Accessories'
  WHERE product_id IN ('B098LCVYPW', 'B09BW334ML');  -- Fire TV Stick remote cases


-- 2. Headphones,Earbuds & Accessories → headphones (known headphone types)
UPDATE products SET subcategory='headphones'
  WHERE category='Electronics' AND subcategory='Headphones,Earbuds & Accessories'
  AND type IN ('wired earphones', 'over-ear headphones', 'tws earbuds', 'neckband');

-- null-type earbuds (exact product_ids from p0 cleanup analysis)
UPDATE products SET subcategory='headphones', type='tws earbuds'
  WHERE product_id IN (
    'B0B31BYXQQ', 'B0B31FR4Y2', 'B0B5GJRTHB', 'B0B2931FCV',
    'B08JQN8DGZ', 'B09PL79D2X', 'B09X76VL5L'
  );

UPDATE products SET subcategory='headphones', type='neckband'
  WHERE product_id IN ('B07LG59NPV', 'B09NR6G588', 'B08FB2LNSZ');

-- non-headphone products stranded in the bucket
UPDATE products SET subcategory='cable'
  WHERE category='Electronics' AND subcategory='Headphones,Earbuds & Accessories' AND type='cable';

UPDATE products SET subcategory='Accessories'
  WHERE category='Electronics' AND subcategory='Headphones,Earbuds & Accessories' AND type='battery';

UPDATE products SET subcategory='pen drive', category='Computers & Accessories'
  WHERE category='Electronics' AND subcategory='Headphones,Earbuds & Accessories' AND type='pen drive';

-- Silicone earbuds tips (not a headphone)
UPDATE products SET subcategory='Accessories'
  WHERE product_id='B08X77LM8C';

-- Fix mistagged battery/cable types on real earphones (from p0 cleanup)
UPDATE products SET subcategory='headphones', type='neckband'
  WHERE product_id='B09YLFHFDW';  -- Sony WI-C100 (was type=battery)

UPDATE products SET subcategory='headphones', type='tws earbuds'
  WHERE product_id='B086WMSCN3';  -- boAt Airdopes 171 (was type=battery)

UPDATE products SET subcategory='headphones', type='wired earphones'
  WHERE product_id IN ('B09SGGRKV8', 'B08VRMK55F');  -- Zeb-Buds 30, Zeb Buds C2 (were type=cable)

-- audio cable splitter (genuinely a cable)
UPDATE products SET subcategory='cable', type='cable'
  WHERE product_id='B08BCKN299';


-- 3. WearableTechnology → smartwatch
UPDATE products SET subcategory='smartwatch'
  WHERE category='Electronics' AND subcategory='WearableTechnology'
  AND (type='smartwatch' OR type IS NULL);

UPDATE products SET subcategory='headphones'
  WHERE category='Electronics' AND subcategory='WearableTechnology' AND type='tws earbuds';

UPDATE products SET subcategory='cable', type='cable'
  WHERE category='Electronics' AND subcategory='WearableTechnology' AND type='cable';

UPDATE products SET subcategory='screen protector'
  WHERE category='Electronics' AND subcategory='WearableTechnology' AND type='screen protector';

UPDATE products SET subcategory='Accessories'
  WHERE category='Electronics' AND subcategory='WearableTechnology'
  AND type IN ('battery', 'smartphone');


-- 4. HomeAudio → speakers
UPDATE products SET subcategory='speakers'
  WHERE category='Electronics' AND subcategory='HomeAudio'
  AND (type IN ('bluetooth speaker', 'home theatre', 'soundbar') OR type IS NULL);

UPDATE products SET subcategory='cable'
  WHERE category='Electronics' AND subcategory='HomeAudio' AND type='cable';


-- 5. PowerAccessories (1 product, type=cable) → cable
UPDATE products SET subcategory='cable'
  WHERE category='Electronics' AND subcategory='PowerAccessories';


-- ================================================================
-- COMPUTERS & ACCESSORIES
-- ================================================================

-- 1. Accessories & Peripherals → subcategory = old type value, clear type
--    (old type IS now the product class; v6 uses type for variant like wired/wireless/gaming)
UPDATE products
  SET subcategory = type, type = NULL
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals'
  AND type IN (
    'cable', 'mouse', 'keyboard', 'drawing tablet', 'monitor stand',
    'adapter', 'usb hub', 'webcam', 'laptop bag', 'screen protector',
    'ups', 'wifi adapter', 'external hdd', 'pen'
  );

-- null-type Accessories & Peripherals: assign by name pattern
UPDATE products SET subcategory='mouse'
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals' AND type IS NULL
  AND (name ILIKE '%mouse%' OR name ILIKE '%optical%gaming%');

UPDATE products SET subcategory='mouse pad'
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals' AND type IS NULL
  AND (name ILIKE '%mousepad%' OR name ILIKE '%mouse pad%');

UPDATE products SET subcategory='gamepad'
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals' AND type IS NULL
  AND (name ILIKE '%gamepad%' OR name ILIKE '%controller%' AND name ILIKE '%gaming%');

UPDATE products SET subcategory='monitor stand'
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals' AND type IS NULL
  AND (name ILIKE '%laptop stand%' OR name ILIKE '%tablet stand%'
    OR name ILIKE '%laptop table%' OR name ILIKE '%lapdesk%'
    OR name ILIKE '%laptop cooling%' OR name ILIKE '%bed study table%'
    OR name ILIKE '%tabletop%laptop%' OR name ILIKE '%tabletop%tablet%');

UPDATE products SET subcategory='microphone'
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals' AND type IS NULL
  AND (name ILIKE '%microphone%' OR name ILIKE '%lavalier%' OR name ILIKE '%lapel mic%');

-- remaining null-type Accessories & Peripherals → generic Accessories
UPDATE products SET subcategory='Accessories'
  WHERE category='Computers & Accessories' AND subcategory='Accessories & Peripherals' AND type IS NULL;


-- 2. NetworkingDevices → split by type, clear type
UPDATE products SET subcategory='router', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='NetworkingDevices' AND type='router';

UPDATE products SET subcategory='wifi adapter', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='NetworkingDevices' AND type='adapter';

UPDATE products SET subcategory='wifi range extender', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='NetworkingDevices' AND type='range extender';

UPDATE products SET subcategory='cable', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='NetworkingDevices' AND type='cable';

UPDATE products SET subcategory='router', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='NetworkingDevices' AND type IS NULL;


-- 3. ExternalDevices & DataStorage → split by type, clear type
UPDATE products SET subcategory='pen drive', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='ExternalDevices & DataStorage' AND type='pen drive';

UPDATE products SET subcategory='external hdd', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='ExternalDevices & DataStorage' AND type='external hdd';

UPDATE products SET subcategory='external ssd', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='ExternalDevices & DataStorage' AND type='external ssd';

UPDATE products SET subcategory='cable', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='ExternalDevices & DataStorage' AND type='cable';

UPDATE products SET subcategory='memory card', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='ExternalDevices & DataStorage' AND type='memory card';

UPDATE products SET subcategory='external hdd', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='ExternalDevices & DataStorage' AND type IS NULL;


-- 4. Monitors → monitor, clear type
UPDATE products SET subcategory='monitor', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Monitors';


-- 5. Printers,Inks & Accessories → split by type, clear type
UPDATE products SET subcategory='printer', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Printers,Inks & Accessories' AND type='printer';

UPDATE products SET subcategory='ink cartridge', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Printers,Inks & Accessories' AND type='ink cartridge';

UPDATE products SET subcategory='printer', type=NULL
  WHERE category='Computers & Accessories' AND subcategory='Printers,Inks & Accessories' AND type IS NULL;


COMMIT;
