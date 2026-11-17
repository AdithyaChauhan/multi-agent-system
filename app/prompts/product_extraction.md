Extract product search preferences. Return JSON only.

Catalog:
{catalog}

Schema: {"category":str|null,"subcategory":str|null,"type":str|null,"brand":str|null,"max_price":int|null,"min_price":int|null,"min_rating":float|null,"keywords":[str],"unavailable_request":bool}

Types (Electronics only; null if unspecified):
headphones: neckband|tws earbuds|wired earphones|over-ear headphones
speakers: bluetooth speaker|soundbar|home theatre  tv: smart tv
mouse/keyboard: wired|wireless|gaming|mechanical|bluetooth
cable/adapter/H&K: type=null, use keywords for HDMI/USB-C/lightning specifics

Rules:
- Exact catalog subcategory names only
- mice→mouse; earbuds/earphones→headphones+type; telly→tv; adaptor→adapter; geyser→water heater; AC→air conditioner
- pencil/pen/highlighter/eraser/ruler/marker/sketch pad→stationery; paintbrush/canvas/palette→art supplies
- phone/mobile charger→sub:charger, keywords:["USB"]
- keywords: features beyond subcategory/type (calling, noise cancellation, 4K, wireless)
- best/highly/top rated→min_rating:4.0; "4.5 stars"→4.5; "4 stars and above"→4.0; null otherwise
- Category-only browse: subcategory null, keywords []
- Vague browse (show products/what do you have): category null, unavailable_request false
- unavailable_request true ONLY for absent types (laptops, phones, tablets, clothing, food, furniture) — not for brands, specs, or features
- JSON null only, never string "null"
- Navigation phrases before a product name ("show me", "find me", "get me") are filler — extract the product name as subcategory, not keyword.
- When a message ends with "type" or "ones" after a product qualifier (e.g. "gaming type", "neckband type", "wireless ones", "bluetooth ones"), set type to the qualifier word directly, set subcategory to null, and set unavailable_request to false — even if the qualifier is not an exact catalog type name.
- Need/goal queries: when the user describes a problem, activity, or desired outcome rather than naming a specific product, infer the catalog subcategory that best enables it. This applies to multi-word intent phrases ("something to keep warm", "for the gym"), NOT to bare single nouns that are product names ("table", "chair", "book") — treat those as direct product searches.
- If the user names a product type not in the catalog (furniture, food, clothing, books, toys), set unavailable_request: true.

Examples:
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}
"best rated JBL bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "speakers", "type": "bluetooth speaker", "brand": "JBL", "max_price": 2000, "min_price": null, "min_rating": 4.0, "keywords": [], "unavailable_request": false}
"top rated neckband under 2000" → {"category": "Electronics", "subcategory": "headphones", "type": "neckband", "brand": null, "max_price": 2000, "min_price": null, "min_rating": 4.0, "keywords": [], "unavailable_request": false}
"wireless mouse" → {"category": "Computers & Accessories", "subcategory": "mouse", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["wireless"], "unavailable_request": false}
"4.5 star and above air fryer" → {"category": "Home & Kitchen", "subcategory": "air fryer", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": 4.5, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "min_rating": null, "keywords": ["laptop"], "unavailable_request": true}
"geyser under 5000" → {"category": "Home & Kitchen", "subcategory": "water heater", "type": null, "brand": null, "max_price": 5000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}
"4K monitor" → {"category": "Computers & Accessories", "subcategory": "monitor", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["4K"], "unavailable_request": false}
"USB hub with ethernet" → {"category": "Computers & Accessories", "subcategory": "usb hub", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["ethernet"], "unavailable_request": false}
"Sony headphones under 5000" → {"category": "Electronics", "subcategory": "headphones", "type": null, "brand": "Sony", "max_price": 5000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}
"affordable headphones" → {"category": "Electronics", "subcategory": "headphones", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}

Respond ONLY with valid JSON.
