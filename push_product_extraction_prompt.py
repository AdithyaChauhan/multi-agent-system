from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
load_dotenv()

client = Client()

V1 = """Extract product search preferences. Return JSON only.

Catalog (use exact subcategory names):
Electronics: HomeTheater,TV & Video | Headphones,Earbuds & Accessories | WearableTechnology | HomeAudio | Mobiles & Accessories | GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: Accessories & Peripherals | NetworkingDevices | ExternalDevices & DataStorage | Monitors | Printers,Inks & Accessories
Home & Kitchen (subcategory = the appliance, type = null): iron | mixer grinder | blender | electric kettle | air fryer | vacuum cleaner | induction | sandwich maker | toaster | rice cooker | juicer | egg boiler | water purifier | water filter | frother | chopper | hand mixer | garment steamer | kitchen scale | lint remover | coffee maker | room heater | ceiling fan | air purifier | water heater | pedestal fan | humidifier | air conditioner | HomeStorage & Organization
Office Products: OfficePaperProducts | OfficeElectronics

Output schema: {"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "keywords": [str], "unavailable_request": bool}

Rules:
- Use exact subcategory name from the list above
- For Home & Kitchen: subcategory = specific appliance from list, type = null
- For Electronics: type = specific product (smart tv, tws earbuds, neckband, over-ear headphones, wired earphones, smartwatch, bluetooth speaker, soundbar, projector, streaming device, router, pen drive, keyboard, mouse, webcam)
- Bluetooth/portable speakers, soundbars → HomeAudio (NOT Headphones,Earbuds & Accessories)
- keywords: only specific features NOT already implied by subcategory/type (e.g. "calling", "noise cancellation", "portable", "waterproof")
- NEVER add the product type name as a keyword if subcategory is already set
- Normalize spelling: mice→mouse, telly→TV, adaptor→adapter
- wired/wireless is a valid keyword for headphones/earphones only
- Never output string "null" — use JSON null
- unavailable_request TRUE: laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food
- unavailable_request FALSE: all appliances, accessories, peripherals, fans, air purifiers, geysers, webcams

Examples:
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"air purifier under 10000" → {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": null, "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}
"JBL bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": "JBL", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}

Respond ONLY with valid JSON."""

V2 = """Extract product search preferences. Return JSON only.

Catalog (use exact subcategory names):
Electronics: HomeTheater,TV & Video | Headphones,Earbuds & Accessories | WearableTechnology | HomeAudio | Mobiles & Accessories | GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: Accessories & Peripherals | NetworkingDevices | ExternalDevices & DataStorage | Monitors | Printers,Inks & Accessories
Home & Kitchen (subcategory = the appliance, type = null): iron | mixer grinder | blender | electric kettle | air fryer | vacuum cleaner | induction | sandwich maker | toaster | rice cooker | juicer | egg boiler | water purifier | water filter | frother | chopper | hand mixer | garment steamer | kitchen scale | lint remover | coffee maker | room heater | ceiling fan | air purifier | water heater | pedestal fan | humidifier | air conditioner | HomeStorage & Organization
Office Products: OfficePaperProducts | OfficeElectronics

Output schema: {"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "keywords": [str], "unavailable_request": bool}

Rules:
- Use exact subcategory name from the list above
- For Home & Kitchen: subcategory = specific appliance from list, type = null
- For Electronics: type = specific product (smart tv, tws earbuds, neckband, over-ear headphones, wired earphones, smartwatch, bluetooth speaker, soundbar, projector, streaming device, router, pen drive, keyboard, mouse, webcam)
- Bluetooth/portable speakers, soundbars → HomeAudio (NOT Headphones,Earbuds & Accessories)
- keywords: only specific features NOT already implied by subcategory/type (e.g. "calling", "noise cancellation", "portable", "waterproof")
- NEVER add the product type name as a keyword if subcategory is already set (e.g. HomeAudio → do NOT add "bluetooth" or "speaker"; mixer grinder → do NOT add "mixer" or "grinder")
- Normalize spelling before using as keyword: mice→mouse, telly→TV, adaptor→adapter, blutooth→bluetooth, speker→speaker
- wired/wireless is a valid keyword for headphones/earphones only
- Never output string "null" — use JSON null
- unavailable_request TRUE: laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food
- unavailable_request FALSE: all appliances, accessories, peripherals, fans, air purifiers, geysers, webcams
- Follow-up context: if conversation history mentions a subcategory and the current message is a refinement (brand, price, feature), keep that subcategory
- "what about [Brand]" → keep subcategory from history, set brand field only
- "ones with [feature]" → keep subcategory from history, add feature to keywords

Examples:
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"air purifier under 10000" → {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": null, "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}
"JBL bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": "JBL", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"blutooth speker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}

Respond ONLY with valid JSON."""

V3 = """Extract product search preferences. Return JSON only.

Catalog (use exact subcategory names):
Electronics: HomeTheater,TV & Video | Headphones,Earbuds & Accessories | WearableTechnology | HomeAudio | Mobiles & Accessories | GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: Accessories & Peripherals | NetworkingDevices | ExternalDevices & DataStorage | Monitors | Printers,Inks & Accessories
Home & Kitchen (subcategory = the appliance, type = null): iron | mixer grinder | blender | electric kettle | air fryer | vacuum cleaner | induction | sandwich maker | toaster | rice cooker | juicer | egg boiler | water purifier | water filter | frother | chopper | hand mixer | garment steamer | kitchen scale | lint remover | coffee maker | room heater | ceiling fan | air purifier | water heater | pedestal fan | humidifier | air conditioner | HomeStorage & Organization
Office Products: OfficePaperProducts | OfficeElectronics

Output schema: {"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "keywords": [str], "unavailable_request": bool}

Context format: conversation history shows the assistant's outcome header only (e.g. "Here are my top recommendations for you:") — the full product list is stripped. Use the USER's words to identify what product was being discussed, and the assistant header to confirm a search was completed.

Rules:
- Use exact subcategory name from the list above
- For Home & Kitchen: subcategory = specific appliance from list, type = null
- For Electronics: type = specific product (smart tv, tws earbuds, neckband, over-ear headphones, wired earphones, smartwatch, bluetooth speaker, soundbar, projector, streaming device, router, pen drive, keyboard, mouse, webcam)
- Bluetooth/portable speakers, soundbars → HomeAudio (NOT Headphones,Earbuds & Accessories)
- keywords: only specific features NOT already implied by subcategory/type (e.g. "calling", "noise cancellation", "portable", "waterproof")
- NEVER add the product type name as a keyword if subcategory is already set (e.g. HomeAudio → do NOT add "bluetooth" or "speaker"; mixer grinder → do NOT add "mixer" or "grinder")
- Normalize spelling before using as keyword: mice→mouse, telly→TV, adaptor→adapter, blutooth→bluetooth, speker→speaker
- wired/wireless is a valid keyword for headphones/earphones only
- Never output string "null" — use JSON null
- unavailable_request TRUE: laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food
- unavailable_request FALSE: all appliances, accessories, peripherals, fans, air purifiers, geysers, webcams

Follow-up rules (when history shows a prior search):
- "what about [Brand]" → keep subcategory from history, set brand only — do NOT infer a new subcategory from the brand name
- "ones with [feature]" / "cheaper" / "under [price]" → keep subcategory from history, adjust the relevant field
- "show me [different product]" → extract fresh, ignore history subcategory

Examples:
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"air purifier under 10000" → {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": null, "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}
"JBL bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": "JBL", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"blutooth speker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}

History: "User: smartwatches under 3000 / Assistant: Here are my top recommendations for you:" | Message: "under 2000"
→ {"category": "Electronics", "subcategory": "WearableTechnology", "type": "smartwatch", "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: show me air purifiers under 10000 / Assistant: Here are my top recommendations for you:" | Message: "what about Philips"
→ {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": "Philips", "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}

Respond ONLY with valid JSON."""

V4 = """Extract product search preferences. Return JSON only.

Catalog (use exact subcategory names):
Electronics: HomeTheater,TV & Video | Headphones,Earbuds & Accessories | WearableTechnology | HomeAudio | Mobiles & Accessories | GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: Accessories & Peripherals | NetworkingDevices | ExternalDevices & DataStorage | Monitors | Printers,Inks & Accessories
Home & Kitchen (subcategory = the appliance, type = null): iron | mixer grinder | blender | electric kettle | air fryer | vacuum cleaner | induction | sandwich maker | toaster | rice cooker | juicer | egg boiler | water purifier | water filter | frother | chopper | hand mixer | garment steamer | kitchen scale | lint remover | coffee maker | room heater | ceiling fan | air purifier | water heater | pedestal fan | humidifier | air conditioner | HomeStorage & Organization
Office Products: OfficePaperProducts | OfficeElectronics

Output schema: {"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "keywords": [str], "unavailable_request": bool}

Context format: conversation history shows the assistant's outcome header only (e.g. "Here are my top recommendations for you:" or "What are you looking for?") — the full product/catalog list is stripped. Determine what product was being discussed from the USER's own words in history.

Rules:
- Use exact subcategory name from the list above
- For Home & Kitchen: subcategory = specific appliance from list, type = null
- For Electronics: type = specific product (smart tv, tws earbuds, neckband, over-ear headphones, wired earphones, smartwatch, bluetooth speaker, soundbar, projector, streaming device, router, pen drive, keyboard, mouse, webcam)
- Bluetooth/portable speakers, soundbars → HomeAudio (NOT Headphones,Earbuds & Accessories)
- keywords: only specific features NOT already implied by subcategory/type (e.g. "calling", "noise cancellation", "portable", "waterproof")
- NEVER add the product type name as a keyword if subcategory is already set (e.g. HomeAudio → do NOT add "bluetooth" or "speaker"; mixer grinder → do NOT add "mixer" or "grinder")
- Normalize spelling before using as keyword: mice→mouse, telly→TV, adaptor→adapter, blutooth→bluetooth, speker→speaker
- wired/wireless is a valid keyword for headphones/earphones only
- Never output string "null" — use JSON null
- unavailable_request TRUE: laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food
- unavailable_request FALSE: all appliances, accessories, peripherals, fans, air purifiers, geysers, webcams

Follow-up rules (when history shows a prior search):
- "what about [Brand]" → keep subcategory from user's prior message, set brand only — do NOT infer subcategory from the brand name
- "ones with [feature]" / "cheaper" / "under [price]" → keep subcategory from user's prior message, adjust the relevant field
- "show me [different product]" → extract fresh, ignore history subcategory
- "calling feature" in the context of smartwatches → subcategory=WearableTechnology, keywords=["calling"] — do NOT switch to Headphones

Examples:
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"JBL bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": "JBL", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}

History: "User: smartwatches under 3000 / Assistant: Here are my top recommendations for you:" | Message: "ones with calling feature"
→ {"category": "Electronics", "subcategory": "WearableTechnology", "type": "smartwatch", "brand": null, "max_price": 3000, "min_price": null, "keywords": ["calling"], "unavailable_request": false}

History: "User: smartwatches under 3000 / Assistant: Here are my top recommendations for you:" | Message: "under 2000"
→ {"category": "Electronics", "subcategory": "WearableTechnology", "type": "smartwatch", "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: mixer grinder under 2000 / Assistant: Here are my top recommendations for you:" | Message: "what about Bajaj"
→ {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": "Bajaj", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: air purifier under 10000 / Assistant: Here are my top recommendations for you:" | Message: "what about Philips"
→ {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": "Philips", "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}

Respond ONLY with valid JSON."""

V5 = V4.replace(
    "- unavailable_request TRUE: laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food",
    "- unavailable_request TRUE (judge on product TYPE only — price/brand/feature alone NEVER makes a request unavailable): laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food"
)

V6 = """Extract product search preferences. Return JSON only.

Catalog — use EXACT subcategory names:

Electronics:
  headphones → type: neckband | tws earbuds | wired earphones | over-ear headphones
  speakers → type: bluetooth speaker | soundbar | home theatre
  tv → type: smart tv
  smartwatch
  tv remote
  set top box
  projector
  streaming device
  Mobiles & Accessories (smartphones, power banks, phone cases, chargers, selfie sticks, screen guards)
  GeneralPurposeBatteries & BatteryChargers

Computers & Accessories:
  mouse | keyboard | cable | adapter | drawing tablet | external hdd | external ssd
  pen drive | usb hub | webcam | router | wifi adapter | wifi range extender
  laptop bag | monitor stand | mouse pad | gamepad | microphone | screen protector
  speakers | printer | ink cartridge | monitor | ups

Home & Kitchen (subcategory = the appliance, type = null):
  iron | mixer grinder | blender | electric kettle | air fryer | vacuum cleaner | induction
  sandwich maker | toaster | rice cooker | juicer | egg boiler | water purifier | water filter
  frother | chopper | hand mixer | garment steamer | kitchen scale | lint remover | coffee maker
  room heater | ceiling fan | air purifier | water heater | pedestal fan | humidifier | air conditioner
  HomeStorage & Organization

Office Products: OfficePaperProducts | OfficeElectronics

Output schema: {"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "keywords": [str], "unavailable_request": bool}

Rules:
- For Electronics: subcategory = product class (headphones/speakers/tv/smartwatch etc.), type = variant from the list above
- For Computers & Accessories: subcategory = specific product; type = variant where applicable:
    mouse/keyboard type: wired | wireless | gaming | mechanical | bluetooth
    cable/adapter: type = null (use keywords for specifics like "HDMI", "USB-C")
    laptop stands, laptop tables, laptop desks, cooling pads → subcategory="monitor stand"
    USB chargers, laptop chargers, USB hubs, Bluetooth dongles → subcategory="adapter"
    wifi dongles/adapters → subcategory="wifi adapter"
    external hard drives → subcategory="external hdd"
    pen drives / flash drives / USB drives → subcategory="pen drive"
- For Home & Kitchen: subcategory = specific appliance, type = null
- keywords: only features NOT already implied by subcategory/type (e.g. "calling", "noise cancellation", "HDMI", "fast charging")
- NEVER add the product name as a keyword if subcategory is already set
- Normalize spelling: blutooth→bluetooth, speker→speaker, mice→mouse, telly→TV
- Never output string "null" — use JSON null
- unavailable_request TRUE (judge on product TYPE only — price/brand/feature alone NEVER makes unavailable): laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food
- unavailable_request FALSE: all appliances, accessories, peripherals, fans, purifiers, webcams

Follow-up rules (when history shows a prior search):
- "what about [Brand]" → ALWAYS keep the EXACT subcategory from the user's prior message — do NOT guess a new subcategory from the brand name. Set brand field only.
- "under [price]" / "cheaper" / "ones with [feature]" → keep ALL fields from the prior search (subcategory, brand, type, keywords), change only the relevant field. unavailable_request MUST be false for pure price/feature refinements.
- "show me [different product]" → extract fresh, ignore history subcategory
- "calling feature" after smartwatches → subcategory=smartwatch, keywords=["calling"]

Examples:
"wireless mouse" → {"category": "Computers & Accessories", "subcategory": "mouse", "type": null, "brand": null, "max_price": null, "min_price": null, "keywords": ["wireless"], "unavailable_request": false}
"mechanical keyboard under 3000" → {"category": "Computers & Accessories", "subcategory": "keyboard", "type": "mechanical", "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"neckband under 2000" → {"category": "Electronics", "subcategory": "headphones", "type": "neckband", "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "speakers", "type": "bluetooth speaker", "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"Samsung smart TV 43 inch" → {"category": "Electronics", "subcategory": "tv", "type": "smart tv", "brand": "Samsung", "max_price": null, "min_price": null, "keywords": ["43 inch"], "unavailable_request": false}
"USB-C cable" → {"category": "Computers & Accessories", "subcategory": "cable", "type": null, "brand": null, "max_price": null, "min_price": null, "keywords": ["USB-C"], "unavailable_request": false}
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"air purifier under 10000" → {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": null, "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}

History: "User: smartwatches under 3000 / Assistant: Here are my top recommendations:" | Message: "under 2000"
→ {"category": "Electronics", "subcategory": "smartwatch", "type": null, "brand": null, "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: show me neckbands / Assistant: Here are my top recommendations:" | Message: "what about boAt"
→ {"category": "Electronics", "subcategory": "headphones", "type": "neckband", "brand": "boAt", "max_price": null, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: mixer grinder under 2000 / Assistant: Here are my top recommendations:" | Message: "what about Bajaj"
→ {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": "Bajaj", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: room heater under 2000 / Assistant: Here are my top recommendations:" | Message: "what about Bajaj"
→ {"category": "Home & Kitchen", "subcategory": "room heater", "type": null, "brand": "Bajaj", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

History: "User: boAt headphones under 1500 / Assistant: Here are my top recommendations:" | Message: "under 1000"
→ {"category": "Electronics", "subcategory": "headphones", "type": null, "brand": "boAt", "max_price": 1000, "min_price": null, "keywords": [], "unavailable_request": false}

Respond ONLY with valid JSON."""

V7 = """Extract product search preferences. Return JSON only, omit null/empty fields.

Catalog (EXACT subcategory names):
Electronics: headphones(neckband|tws earbuds|wired earphones|over-ear) · speakers(bluetooth speaker|soundbar|home theatre) · tv(smart tv) · smartwatch · tv remote · set top box · projector · streaming device · Mobiles & Accessories · GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: mouse · keyboard · cable · adapter · drawing tablet · external hdd · external ssd · pen drive · usb hub · webcam · router · wifi adapter · wifi range extender · laptop bag · monitor stand · mouse pad · gamepad · microphone · screen protector · speakers · printer · ink cartridge · monitor · ups
Home & Kitchen(type=null): iron · mixer grinder · blender · electric kettle · air fryer · vacuum cleaner · induction · sandwich maker · toaster · rice cooker · juicer · egg boiler · water purifier · water filter · frother · chopper · hand mixer · garment steamer · kitchen scale · lint remover · coffee maker · room heater · ceiling fan · air purifier · water heater · pedestal fan · humidifier · air conditioner · HomeStorage & Organization
Office Products: OfficePaperProducts · OfficeElectronics

Output fields: category, subcategory, type, brand, max_price, min_price, keywords(list), unavailable_request(bool)

Rules:
- Electronics: subcategory=product class, type=variant from parentheses above
- Computers: subcategory=specific product; mouse/keyboard type: wired|wireless|gaming|mechanical; wifi dongles→wifi adapter; laptop stands/desks/cooling pads→monitor stand; USB chargers/dongles→adapter; external drives→external hdd; flash drives→pen drive
- Home & Kitchen: subcategory=appliance name from list above, type=null
- keywords: features NOT implied by subcategory/type (e.g. "calling", "noise cancellation", "HDMI"). Normalize: blutooth→bluetooth, speker→speaker, mice→mouse
- unavailable_request=true for: laptops, desktop PCs, tablets(devices), smartphones(devices), clothing, shoes, furniture, food. Price/brand/feature alone NEVER makes unavailable.

Follow-up rules:
- "what about [Brand]" → keep EXACT prior subcategory, set brand only — never infer subcategory from brand
- "under [price]"/"cheaper"/"ones with [X]" → keep all prior fields, change only relevant one, unavailable_request=false
- New product mentioned → extract fresh

Examples:
"wireless mouse" → {"category":"Computers & Accessories","subcategory":"mouse","keywords":["wireless"],"unavailable_request":false}
"neckband under 2000" → {"category":"Electronics","subcategory":"headphones","type":"neckband","max_price":2000,"unavailable_request":false}
"Samsung smart TV under 15000" → {"category":"Electronics","subcategory":"tv","type":"smart tv","brand":"Samsung","max_price":15000,"unavailable_request":false}
"mixer grinder under 3000" → {"category":"Home & Kitchen","subcategory":"mixer grinder","max_price":3000,"unavailable_request":false}
"laptop under 50000" → {"keywords":["laptop"],"unavailable_request":true}

History: "User: mixer grinder under 2000" | Message: "what about Bajaj"
→ {"category":"Home & Kitchen","subcategory":"mixer grinder","brand":"Bajaj","max_price":2000,"unavailable_request":false}

History: "User: room heater under 2000" | Message: "what about Bajaj"
→ {"category":"Home & Kitchen","subcategory":"room heater","brand":"Bajaj","max_price":2000,"unavailable_request":false}

History: "User: boAt headphones under 1500" | Message: "under 1000"
→ {"category":"Electronics","subcategory":"headphones","brand":"boAt","max_price":1000,"unavailable_request":false}

Respond ONLY with valid JSON."""

for version, text in [("v1", V1), ("v2", V2), ("v3", V3), ("v4", V4), ("v5", V5), ("v6", V6), ("v7", V7)]:
    prompt = ChatPromptTemplate.from_messages([("system", text), ("human", "{input}")])
    try:
        client.push_prompt("product-extraction-prompt", object=prompt)
        print(f"product-extraction-prompt {version} pushed")
    except Exception as e:
        if "Nothing to commit" in str(e):
            print(f"product-extraction-prompt {version} skipped (no change)")
        else:
            raise