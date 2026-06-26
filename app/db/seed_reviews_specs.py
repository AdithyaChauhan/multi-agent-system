from app.db.database import SessionLocal
from app.models.review import Review
from app.models.spec import Spec
from app.core.logger import get_logger

logger = get_logger("app.db.seed_reviews_specs")

DEMO_REVIEWS = [
    # CLO-001 / CLO-002 — Classic Cotton T-Shirt
    {
        "review_id": "REV-001",
        "product_id": "CLO-001",
        "rating": 4.5,
        "reviewer": "Rahul M",
        "review_text": "Great quality cotton, very comfortable for daily wear.",
    },
    {
        "review_id": "REV-002",
        "product_id": "CLO-001",
        "rating": 4.0,
        "reviewer": "Arjun S",
        "review_text": "Good fit, washes well. Slightly thin material.",
    },
    {
        "review_id": "REV-003",
        "product_id": "CLO-002",
        "rating": 4.5,
        "reviewer": "Vikram P",
        "review_text": "Perfect size L fit. Highly recommend.",
    },
    # CLO-003 / CLO-004 — Slim Fit Denim Jeans
    {
        "review_id": "REV-004",
        "product_id": "CLO-003",
        "rating": 4.8,
        "reviewer": "Karan T",
        "review_text": "Best jeans I have owned. Slim fit is perfect.",
    },
    {
        "review_id": "REV-005",
        "product_id": "CLO-004",
        "rating": 4.3,
        "reviewer": "Rohit G",
        "review_text": "Good denim quality. XL fits well.",
    },
    # CLO-005 / CLO-006 — Floral Print Blouse
    {
        "review_id": "REV-006",
        "product_id": "CLO-005",
        "rating": 4.2,
        "reviewer": "Priya K",
        "review_text": "Beautiful print, lightweight fabric. Perfect for summer.",
    },
    {
        "review_id": "REV-007",
        "product_id": "CLO-006",
        "rating": 4.0,
        "reviewer": "Sneha R",
        "review_text": "Lovely blouse, true to size.",
    },
    # CLO-007 / CLO-008 — High Waist Jeans
    {
        "review_id": "REV-008",
        "product_id": "CLO-007",
        "rating": 4.5,
        "reviewer": "Ananya B",
        "review_text": "High waist fit is amazing. Very stylish.",
    },
    {
        "review_id": "REV-009",
        "product_id": "CLO-008",
        "rating": 4.3,
        "reviewer": "Divya M",
        "review_text": "Good quality denim, comfortable fit.",
    },
    # CLO-009 / CLO-010 — Unisex Oversized Hoodie
    {
        "review_id": "REV-010",
        "product_id": "CLO-009",
        "rating": 4.8,
        "reviewer": "Aditya N",
        "review_text": "Super comfortable hoodie. Oversized fits great.",
    },
    {
        "review_id": "REV-011",
        "product_id": "CLO-010",
        "rating": 4.5,
        "reviewer": "Meera S",
        "review_text": "Loved the quality. XL is very roomy.",
    },
    # CLO-011 / CLO-012 — Joggers
    {
        "review_id": "REV-012",
        "product_id": "CLO-011",
        "rating": 4.2,
        "reviewer": "Suresh V",
        "review_text": "Comfortable for gym and daily use.",
    },
    {
        "review_id": "REV-013",
        "product_id": "CLO-012",
        "rating": 4.0,
        "reviewer": "Ramesh K",
        "review_text": "Good quality, XXL fits perfectly.",
    },
    # LAP-001 — MacBook Air M3
    {
        "review_id": "REV-014",
        "product_id": "LAP-001",
        "rating": 4.9,
        "reviewer": "Nikhil A",
        "review_text": "Incredibly lightweight and fast. Best laptop for everyday use.",
    },
    {
        "review_id": "REV-015",
        "product_id": "LAP-001",
        "rating": 4.8,
        "reviewer": "Pooja R",
        "review_text": "All-day battery life is amazing. Highly recommend.",
    },
    # LAP-002 — MacBook Pro 14 M3
    {
        "review_id": "REV-016",
        "product_id": "LAP-002",
        "rating": 4.9,
        "reviewer": "Vivek S",
        "review_text": "Absolute beast for development work. Worth every rupee.",
    },
    {
        "review_id": "REV-017",
        "product_id": "LAP-002",
        "rating": 4.8,
        "reviewer": "Anjali T",
        "review_text": "Best laptop I have ever used. Display is stunning.",
    },
    # LAP-003 — XPS 13
    {
        "review_id": "REV-018",
        "product_id": "LAP-003",
        "rating": 4.6,
        "reviewer": "Siddharth M",
        "review_text": "Premium build quality. InfinityEdge display is gorgeous.",
    },
    {
        "review_id": "REV-019",
        "product_id": "LAP-003",
        "rating": 4.4,
        "reviewer": "Kavya P",
        "review_text": "Lightweight and powerful. Great for travel.",
    },
    # LAP-004 — Inspiron 15
    {
        "review_id": "REV-020",
        "product_id": "LAP-004",
        "rating": 4.0,
        "reviewer": "Manish B",
        "review_text": "Reliable everyday laptop. Good value for money.",
    },
    {
        "review_id": "REV-021",
        "product_id": "LAP-004",
        "rating": 4.2,
        "reviewer": "Ravi K",
        "review_text": "Decent performance for the price.",
    },
    # LAP-005 — ThinkPad X1 Carbon
    {
        "review_id": "REV-022",
        "product_id": "LAP-005",
        "rating": 4.8,
        "reviewer": "Amit G",
        "review_text": "Legendary ThinkPad keyboard. Excellent build quality.",
    },
    {
        "review_id": "REV-023",
        "product_id": "LAP-005",
        "rating": 4.6,
        "reviewer": "Neha S",
        "review_text": "Best business laptop. Battery lasts all day.",
    },
    # LAP-006 — IdeaPad Slim 5
    {
        "review_id": "REV-024",
        "product_id": "LAP-006",
        "rating": 4.3,
        "reviewer": "Prateek V",
        "review_text": "Great value. Slim design and good battery.",
    },
    {
        "review_id": "REV-025",
        "product_id": "LAP-006",
        "rating": 4.1,
        "reviewer": "Shruti M",
        "review_text": "Good everyday laptop. Does everything I need.",
    },
    # LAP-007 — Pavilion 14
    {
        "review_id": "REV-026",
        "product_id": "LAP-007",
        "rating": 3.9,
        "reviewer": "Deepak R",
        "review_text": "Decent laptop for the price. Gets warm under load.",
    },
    {
        "review_id": "REV-027",
        "product_id": "LAP-007",
        "rating": 4.1,
        "reviewer": "Gaurav N",
        "review_text": "Good for office work. Battery could be better.",
    },
    # LAP-008 — Spectre x360
    {
        "review_id": "REV-028",
        "product_id": "LAP-008",
        "rating": 4.7,
        "reviewer": "Tanya B",
        "review_text": "Beautiful 2-in-1. OLED display is stunning.",
    },
    {
        "review_id": "REV-029",
        "product_id": "LAP-008",
        "rating": 4.5,
        "reviewer": "Aryan K",
        "review_text": "Premium feel. Touch screen works flawlessly.",
    },
    # LAP-009 — ZenBook 14
    {
        "review_id": "REV-030",
        "product_id": "LAP-009",
        "rating": 4.5,
        "reviewer": "Ishaan M",
        "review_text": "Lightweight and powerful. Great display.",
    },
    {
        "review_id": "REV-031",
        "product_id": "LAP-009",
        "rating": 4.3,
        "reviewer": "Ritika S",
        "review_text": "Good build quality. Runs cool and quiet.",
    },
    # LAP-010 — ROG Strix G16
    {
        "review_id": "REV-032",
        "product_id": "LAP-010",
        "rating": 4.7,
        "reviewer": "Harsh V",
        "review_text": "Best gaming laptop under 150k. Handles everything.",
    },
    {
        "review_id": "REV-033",
        "product_id": "LAP-010",
        "rating": 4.5,
        "reviewer": "Kunal P",
        "review_text": "Excellent performance. RGB is a nice touch.",
    },
    # LAP-011 — Predator Helios 16
    {
        "review_id": "REV-034",
        "product_id": "LAP-011",
        "rating": 4.6,
        "reviewer": "Raj M",
        "review_text": "Powerful gaming beast. Runs AAA games smoothly.",
    },
    {
        "review_id": "REV-035",
        "product_id": "LAP-011",
        "rating": 4.4,
        "reviewer": "Dev S",
        "review_text": "Great gaming laptop. Keyboard is excellent.",
    },
    # LAP-012 — Aspire 5
    {
        "review_id": "REV-036",
        "product_id": "LAP-012",
        "rating": 4.0,
        "reviewer": "Sunil K",
        "review_text": "Best budget laptop. Does the job well.",
    },
    {
        "review_id": "REV-037",
        "product_id": "LAP-012",
        "rating": 3.9,
        "reviewer": "Manoj T",
        "review_text": "Good value for money. Basic but reliable.",
    },
    # HPH-001 — WH-1000XM5
    {
        "review_id": "REV-038",
        "product_id": "HPH-001",
        "rating": 4.9,
        "reviewer": "Akash R",
        "review_text": "Best noise cancellation I have ever experienced.",
    },
    {
        "review_id": "REV-039",
        "product_id": "HPH-001",
        "rating": 4.7,
        "reviewer": "Nisha M",
        "review_text": "Incredible sound quality. Very comfortable for long sessions.",
    },
    # HPH-002 — WF-1000XM5
    {
        "review_id": "REV-040",
        "product_id": "HPH-002",
        "rating": 4.8,
        "reviewer": "Rohan G",
        "review_text": "Best TWS earbuds. ANC is top class.",
    },
    {
        "review_id": "REV-041",
        "product_id": "HPH-002",
        "rating": 4.6,
        "reviewer": "Simran K",
        "review_text": "Great sound and fit. Battery lasts long.",
    },
    # HPH-003 — AirPods Pro 2
    {
        "review_id": "REV-042",
        "product_id": "HPH-003",
        "rating": 4.8,
        "reviewer": "Varun S",
        "review_text": "Seamless Apple ecosystem integration. ANC is excellent.",
    },
    {
        "review_id": "REV-043",
        "product_id": "HPH-003",
        "rating": 4.6,
        "reviewer": "Aisha T",
        "review_text": "Spatial audio is amazing. Worth the price.",
    },
    # HPH-004 — AirPods Max
    {
        "review_id": "REV-044",
        "product_id": "HPH-004",
        "rating": 4.7,
        "reviewer": "Kabir M",
        "review_text": "Premium over-ear experience. Sound is exceptional.",
    },
    {
        "review_id": "REV-045",
        "product_id": "HPH-004",
        "rating": 4.5,
        "reviewer": "Lara S",
        "review_text": "Comfortable and great sounding. Expensive but worth it.",
    },
    # HPH-005 — QuietComfort 45
    {
        "review_id": "REV-046",
        "product_id": "HPH-005",
        "rating": 4.7,
        "reviewer": "Mihir P",
        "review_text": "Best comfort for long listening sessions. ANC is great.",
    },
    {
        "review_id": "REV-047",
        "product_id": "HPH-005",
        "rating": 4.5,
        "reviewer": "Riya K",
        "review_text": "Excellent noise cancellation. Very comfortable.",
    },
    # HPH-006 — QuietComfort Earbuds II
    {
        "review_id": "REV-048",
        "product_id": "HPH-006",
        "rating": 4.6,
        "reviewer": "Sagar N",
        "review_text": "Best ANC earbuds from Bose. Fit is secure.",
    },
    {
        "review_id": "REV-049",
        "product_id": "HPH-006",
        "rating": 4.4,
        "reviewer": "Tara V",
        "review_text": "Great sound quality. ANC works brilliantly.",
    },
    # HPH-007 — Momentum 4
    {
        "review_id": "REV-050",
        "product_id": "HPH-007",
        "rating": 4.8,
        "reviewer": "Uday M",
        "review_text": "Audiophile grade sound. Best headphones for music lovers.",
    },
    {
        "review_id": "REV-051",
        "product_id": "HPH-007",
        "rating": 4.6,
        "reviewer": "Veda S",
        "review_text": "Exceptional sound quality. Very comfortable.",
    },
    # HPH-008 — HD 560S
    {
        "review_id": "REV-052",
        "product_id": "HPH-008",
        "rating": 4.7,
        "reviewer": "Wren K",
        "review_text": "Reference sound quality. Perfect for studio use.",
    },
    {
        "review_id": "REV-053",
        "product_id": "HPH-008",
        "rating": 4.5,
        "reviewer": "Xena P",
        "review_text": "Incredible detail and clarity. Best wired headphones.",
    },
    # HPH-009 — Galaxy Buds3 Pro
    {
        "review_id": "REV-054",
        "product_id": "HPH-009",
        "rating": 4.5,
        "reviewer": "Yash R",
        "review_text": "Great Samsung earbuds. ANC works well.",
    },
    {
        "review_id": "REV-055",
        "product_id": "HPH-009",
        "rating": 4.3,
        "reviewer": "Zara M",
        "review_text": "Good sound and fit. Battery life is decent.",
    },
    # HPH-010 — Soundcore Q35
    {
        "review_id": "REV-056",
        "product_id": "HPH-010",
        "rating": 4.4,
        "reviewer": "Anil S",
        "review_text": "Best budget ANC headphones. Great value.",
    },
    {
        "review_id": "REV-057",
        "product_id": "HPH-010",
        "rating": 4.2,
        "reviewer": "Bina K",
        "review_text": "Good ANC for the price. Comfortable fit.",
    },
    # HPH-011 — ATH-M50x
    {
        "review_id": "REV-058",
        "product_id": "HPH-011",
        "rating": 4.8,
        "reviewer": "Chetan M",
        "review_text": "Industry standard studio headphones. Exceptional clarity.",
    },
    {
        "review_id": "REV-059",
        "product_id": "HPH-011",
        "rating": 4.6,
        "reviewer": "Disha R",
        "review_text": "Best wired headphones for the price. Very detailed sound.",
    },
    # HPH-012 — Nothing Ear (2)
    {
        "review_id": "REV-060",
        "product_id": "HPH-012",
        "rating": 4.4,
        "reviewer": "Elan S",
        "review_text": "Stylish design and good sound. Great value.",
    },
    {
        "review_id": "REV-061",
        "product_id": "HPH-012",
        "rating": 4.2,
        "reviewer": "Fiona K",
        "review_text": "Transparent design looks amazing. ANC is decent.",
    },
]


DEMO_SPECS = [
    # CLO products — clothes specs
    {"spec_id": "SPC-001", "product_id": "CLO-001", "spec_key": "material", "spec_value": "100% Cotton"},
    {"spec_id": "SPC-002", "product_id": "CLO-001", "spec_key": "fit", "spec_value": "Regular Fit"},
    {"spec_id": "SPC-003", "product_id": "CLO-002", "spec_key": "material", "spec_value": "100% Cotton"},
    {"spec_id": "SPC-004", "product_id": "CLO-002", "spec_key": "fit", "spec_value": "Regular Fit"},
    {"spec_id": "SPC-005", "product_id": "CLO-003", "spec_key": "material", "spec_value": "Denim"},
    {"spec_id": "SPC-006", "product_id": "CLO-003", "spec_key": "fit", "spec_value": "Slim Fit"},
    {"spec_id": "SPC-007", "product_id": "CLO-004", "spec_key": "material", "spec_value": "Denim"},
    {"spec_id": "SPC-008", "product_id": "CLO-004", "spec_key": "fit", "spec_value": "Slim Fit"},
    {"spec_id": "SPC-009", "product_id": "CLO-005", "spec_key": "material", "spec_value": "Polyester Blend"},
    {"spec_id": "SPC-010", "product_id": "CLO-005", "spec_key": "fit", "spec_value": "Regular Fit"},
    {"spec_id": "SPC-011", "product_id": "CLO-006", "spec_key": "material", "spec_value": "Polyester Blend"},
    {"spec_id": "SPC-012", "product_id": "CLO-006", "spec_key": "fit", "spec_value": "Regular Fit"},
    {"spec_id": "SPC-013", "product_id": "CLO-007", "spec_key": "material", "spec_value": "Denim"},
    {"spec_id": "SPC-014", "product_id": "CLO-007", "spec_key": "fit", "spec_value": "Tapered Fit"},
    {"spec_id": "SPC-015", "product_id": "CLO-008", "spec_key": "material", "spec_value": "Denim"},
    {"spec_id": "SPC-016", "product_id": "CLO-008", "spec_key": "fit", "spec_value": "Tapered Fit"},
    {"spec_id": "SPC-017", "product_id": "CLO-009", "spec_key": "material", "spec_value": "Fleece Cotton"},
    {"spec_id": "SPC-018", "product_id": "CLO-009", "spec_key": "fit", "spec_value": "Oversized"},
    {"spec_id": "SPC-019", "product_id": "CLO-010", "spec_key": "material", "spec_value": "Fleece Cotton"},
    {"spec_id": "SPC-020", "product_id": "CLO-010", "spec_key": "fit", "spec_value": "Oversized"},
    {"spec_id": "SPC-021", "product_id": "CLO-011", "spec_key": "material", "spec_value": "Cotton Blend"},
    {"spec_id": "SPC-022", "product_id": "CLO-011", "spec_key": "fit", "spec_value": "Regular Fit"},
    {"spec_id": "SPC-023", "product_id": "CLO-012", "spec_key": "material", "spec_value": "Cotton Blend"},
    {"spec_id": "SPC-024", "product_id": "CLO-012", "spec_key": "fit", "spec_value": "Regular Fit"},
    # LAP products — laptop specs
    {"spec_id": "SPC-025", "product_id": "LAP-001", "spec_key": "battery_life", "spec_value": "18 hours"},
    {"spec_id": "SPC-026", "product_id": "LAP-001", "spec_key": "weight", "spec_value": "1.24 kg"},
    {"spec_id": "SPC-027", "product_id": "LAP-001", "spec_key": "display", "spec_value": "13.6-inch Liquid Retina"},
    {"spec_id": "SPC-028", "product_id": "LAP-002", "spec_key": "battery_life", "spec_value": "22 hours"},
    {"spec_id": "SPC-029", "product_id": "LAP-002", "spec_key": "weight", "spec_value": "1.55 kg"},
    {"spec_id": "SPC-030", "product_id": "LAP-002", "spec_key": "display", "spec_value": "14-inch Liquid Retina XDR"},
    {"spec_id": "SPC-031", "product_id": "LAP-003", "spec_key": "battery_life", "spec_value": "12 hours"},
    {"spec_id": "SPC-032", "product_id": "LAP-003", "spec_key": "weight", "spec_value": "1.17 kg"},
    {"spec_id": "SPC-033", "product_id": "LAP-003", "spec_key": "display", "spec_value": "13.4-inch InfinityEdge OLED"},
    {"spec_id": "SPC-034", "product_id": "LAP-004", "spec_key": "battery_life", "spec_value": "8 hours"},
    {"spec_id": "SPC-035", "product_id": "LAP-004", "spec_key": "weight", "spec_value": "1.83 kg"},
    {"spec_id": "SPC-036", "product_id": "LAP-004", "spec_key": "display", "spec_value": "15.6-inch FHD"},
    {"spec_id": "SPC-037", "product_id": "LAP-005", "spec_key": "battery_life", "spec_value": "15 hours"},
    {"spec_id": "SPC-038", "product_id": "LAP-005", "spec_key": "weight", "spec_value": "1.12 kg"},
    {"spec_id": "SPC-039", "product_id": "LAP-005", "spec_key": "display", "spec_value": "14-inch IPS Anti-glare"},
    {"spec_id": "SPC-040", "product_id": "LAP-006", "spec_key": "battery_life", "spec_value": "10 hours"},
    {"spec_id": "SPC-041", "product_id": "LAP-006", "spec_key": "weight", "spec_value": "1.46 kg"},
    {"spec_id": "SPC-042", "product_id": "LAP-006", "spec_key": "display", "spec_value": "14-inch FHD IPS"},
    {"spec_id": "SPC-043", "product_id": "LAP-007", "spec_key": "battery_life", "spec_value": "7 hours"},
    {"spec_id": "SPC-044", "product_id": "LAP-007", "spec_key": "weight", "spec_value": "1.59 kg"},
    {"spec_id": "SPC-045", "product_id": "LAP-007", "spec_key": "display", "spec_value": "14-inch FHD"},
    {"spec_id": "SPC-046", "product_id": "LAP-008", "spec_key": "battery_life", "spec_value": "17 hours"},
    {"spec_id": "SPC-047", "product_id": "LAP-008", "spec_key": "weight", "spec_value": "1.36 kg"},
    {"spec_id": "SPC-048", "product_id": "LAP-008", "spec_key": "display", "spec_value": "13.5-inch OLED Touch"},
    {"spec_id": "SPC-049", "product_id": "LAP-009", "spec_key": "battery_life", "spec_value": "12 hours"},
    {"spec_id": "SPC-050", "product_id": "LAP-009", "spec_key": "weight", "spec_value": "1.39 kg"},
    {"spec_id": "SPC-051", "product_id": "LAP-009", "spec_key": "display", "spec_value": "14-inch 2.8K OLED"},
    {"spec_id": "SPC-052", "product_id": "LAP-010", "spec_key": "battery_life", "spec_value": "9 hours"},
    {"spec_id": "SPC-053", "product_id": "LAP-010", "spec_key": "weight", "spec_value": "2.5 kg"},
    {"spec_id": "SPC-054", "product_id": "LAP-010", "spec_key": "display", "spec_value": "16-inch QHD 240Hz"},
    {"spec_id": "SPC-055", "product_id": "LAP-011", "spec_key": "battery_life", "spec_value": "8 hours"},
    {"spec_id": "SPC-056", "product_id": "LAP-011", "spec_key": "weight", "spec_value": "2.7 kg"},
    {"spec_id": "SPC-057", "product_id": "LAP-011", "spec_key": "display", "spec_value": "16-inch WQXGA 165Hz"},
    {"spec_id": "SPC-058", "product_id": "LAP-012", "spec_key": "battery_life", "spec_value": "7 hours"},
    {"spec_id": "SPC-059", "product_id": "LAP-012", "spec_key": "weight", "spec_value": "1.9 kg"},
    {"spec_id": "SPC-060", "product_id": "LAP-012", "spec_key": "display", "spec_value": "15.6-inch FHD"},
    # HPH products — headphone specs
    {"spec_id": "SPC-061", "product_id": "HPH-001", "spec_key": "battery_life", "spec_value": "30 hours"},
    {"spec_id": "SPC-062", "product_id": "HPH-001", "spec_key": "driver_size", "spec_value": "30mm"},
    {"spec_id": "SPC-063", "product_id": "HPH-001", "spec_key": "anc", "spec_value": "Yes — Industry Leading"},
    {
        "spec_id": "SPC-064",
        "product_id": "HPH-002",
        "spec_key": "battery_life",
        "spec_value": "8 hours + 16 hours case",
    },
    {"spec_id": "SPC-065", "product_id": "HPH-002", "spec_key": "driver_size", "spec_value": "8.4mm"},
    {"spec_id": "SPC-066", "product_id": "HPH-002", "spec_key": "anc", "spec_value": "Yes — Dual Noise Sensor"},
    {
        "spec_id": "SPC-067",
        "product_id": "HPH-003",
        "spec_key": "battery_life",
        "spec_value": "6 hours + 24 hours case",
    },
    {"spec_id": "SPC-068", "product_id": "HPH-003", "spec_key": "driver_size", "spec_value": "11mm"},
    {"spec_id": "SPC-069", "product_id": "HPH-003", "spec_key": "anc", "spec_value": "Yes — Adaptive Transparency"},
    {"spec_id": "SPC-070", "product_id": "HPH-004", "spec_key": "battery_life", "spec_value": "20 hours"},
    {"spec_id": "SPC-071", "product_id": "HPH-004", "spec_key": "driver_size", "spec_value": "40mm"},
    {"spec_id": "SPC-072", "product_id": "HPH-004", "spec_key": "anc", "spec_value": "Yes — Computational Audio"},
    {"spec_id": "SPC-073", "product_id": "HPH-005", "spec_key": "battery_life", "spec_value": "24 hours"},
    {"spec_id": "SPC-074", "product_id": "HPH-005", "spec_key": "driver_size", "spec_value": "40mm"},
    {"spec_id": "SPC-075", "product_id": "HPH-005", "spec_key": "anc", "spec_value": "Yes"},
    {
        "spec_id": "SPC-076",
        "product_id": "HPH-006",
        "spec_key": "battery_life",
        "spec_value": "6 hours + 18 hours case",
    },
    {"spec_id": "SPC-077", "product_id": "HPH-006", "spec_key": "driver_size", "spec_value": "9.3mm"},
    {"spec_id": "SPC-078", "product_id": "HPH-006", "spec_key": "anc", "spec_value": "Yes — Adaptive"},
    {"spec_id": "SPC-079", "product_id": "HPH-007", "spec_key": "battery_life", "spec_value": "60 hours"},
    {"spec_id": "SPC-080", "product_id": "HPH-007", "spec_key": "driver_size", "spec_value": "42mm"},
    {"spec_id": "SPC-081", "product_id": "HPH-007", "spec_key": "anc", "spec_value": "Yes"},
    {"spec_id": "SPC-082", "product_id": "HPH-008", "spec_key": "battery_life", "spec_value": "Wired — No battery"},
    {"spec_id": "SPC-083", "product_id": "HPH-008", "spec_key": "driver_size", "spec_value": "38mm"},
    {"spec_id": "SPC-084", "product_id": "HPH-008", "spec_key": "anc", "spec_value": "No — Open Back"},
    {
        "spec_id": "SPC-085",
        "product_id": "HPH-009",
        "spec_key": "battery_life",
        "spec_value": "6 hours + 15 hours case",
    },
    {"spec_id": "SPC-086", "product_id": "HPH-009", "spec_key": "driver_size", "spec_value": "10mm"},
    {"spec_id": "SPC-087", "product_id": "HPH-009", "spec_key": "anc", "spec_value": "Yes"},
    {"spec_id": "SPC-088", "product_id": "HPH-010", "spec_key": "battery_life", "spec_value": "40 hours"},
    {"spec_id": "SPC-089", "product_id": "HPH-010", "spec_key": "driver_size", "spec_value": "40mm"},
    {"spec_id": "SPC-090", "product_id": "HPH-010", "spec_key": "anc", "spec_value": "Yes — Hybrid"},
    {"spec_id": "SPC-091", "product_id": "HPH-011", "spec_key": "battery_life", "spec_value": "Wired — No battery"},
    {"spec_id": "SPC-092", "product_id": "HPH-011", "spec_key": "driver_size", "spec_value": "45mm"},
    {"spec_id": "SPC-093", "product_id": "HPH-011", "spec_key": "anc", "spec_value": "No — Closed Back"},
    {
        "spec_id": "SPC-094",
        "product_id": "HPH-012",
        "spec_key": "battery_life",
        "spec_value": "6 hours + 30 hours case",
    },
    {"spec_id": "SPC-095", "product_id": "HPH-012", "spec_key": "driver_size", "spec_value": "11.6mm"},
    {"spec_id": "SPC-096", "product_id": "HPH-012", "spec_key": "anc", "spec_value": "Yes"},
]


def seed_reviews_and_specs():
    db = SessionLocal()

    try:
        seeded_reviews = 0
        for review_data in DEMO_REVIEWS:
            existing = db.query(Review).filter(Review.review_id == review_data["review_id"]).first()
            if not existing:
                db.add(Review(**review_data))
                seeded_reviews += 1

        seeded_specs = 0
        for spec_data in DEMO_SPECS:
            existing = db.query(Spec).filter(Spec.spec_id == spec_data["spec_id"]).first()
            if not existing:
                db.add(Spec(**spec_data))
                seeded_specs += 1

        db.commit()

        if seeded_reviews == 0 and seeded_specs == 0:
            logger.info("Reviews and specs already seeded — skipping")
        else:
            logger.info(f"Seeded {seeded_reviews} reviews and {seeded_specs} specs")

    except Exception as e:
        logger.error(f"Reviews/specs seed failed | {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()
