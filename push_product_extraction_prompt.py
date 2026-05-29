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

for version, text in [("v1", V1), ("v2", V2), ("v3", V3), ("v4", V4)]:
    prompt = ChatPromptTemplate.from_messages([("system", text), ("human", "{input}")])
    try:
        client.push_prompt("product-extraction-prompt", object=prompt)
        print(f"product-extraction-prompt {version} pushed")
    except Exception as e:
        if "Nothing to commit" in str(e):
            print(f"product-extraction-prompt {version} skipped (no change)")
        else:
            raise