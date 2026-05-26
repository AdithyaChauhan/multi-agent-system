"""
ETL script: Load balanced Amazon dataset into PostgreSQL
"""
import pandas as pd
import random
import json
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.db.database import SessionLocal, engine
from app.models.user import User
from app.models.product import Product
from app.models.review import Review
from app.models.spec import Spec
from app.models.order import Order
from app.models.session import Session as SessionModel
from app.models.message import Message
from app.core.logger import get_logger

logger = get_logger("app.db.load_amazon_data")

# Sampling targets per category
SAMPLING_PLAN = {
    "Toys & Games": 400,
    "Home & Kitchen": 300,
    "Clothing, Shoes & Jewelry": 300,
    "Sports & Outdoors": 300,
    "Baby Products": 200,
    "Arts, Crafts & Sewing": 120,
    "Office Products": 80,
}

def clear_existing_data():
    """Clear all existing seed data"""
    db = SessionLocal()
    try:
        logger.info("Clearing existing data...")
        db.query(Message).delete()
        db.query(SessionModel).delete()
        db.query(Order).delete()
        db.query(Spec).delete()
        db.query(Review).delete()
        db.query(Product).delete()
        db.query(User).delete()
        db.commit()
        logger.info("✓ Existing data cleared")
    finally:
        db.close()


def load_and_sample_data():
    """Load CSV and sample balanced subset"""
    logger.info("Loading Amazon dataset...")
    df = pd.read_csv('data/marketing_sample_for_amazon_com-ecommerce__20200101_20200131__10k_data.csv')
    
    # Extract top-level category
    df['top_category'] = df['Category'].fillna('Uncategorized').str.split('|').str[0].str.strip()
    
    # Sample from each major category
    sampled_dfs = []
    
    for category, target_count in SAMPLING_PLAN.items():
        cat_df = df[df['top_category'] == category]
        sample_size = min(target_count, len(cat_df))
        sampled = cat_df.sample(n=sample_size, random_state=42)
        sampled_dfs.append(sampled)
        logger.info(f"Sampled {sample_size} products from {category}")
    
    # Sample from remaining categories
    remaining = df[~df['top_category'].isin(SAMPLING_PLAN.keys())]
    if len(remaining) > 0:
        other_sample = remaining.sample(n=min(300, len(remaining)), random_state=42)
        sampled_dfs.append(other_sample)
        logger.info(f"Sampled {len(other_sample)} products from other categories")
    
    result = pd.concat(sampled_dfs, ignore_index=True)
    logger.info(f"✓ Total sampled: {len(result)} products")
    
    return result


def parse_category_hierarchy(category_str):
    """Split category path into levels"""
    if pd.isna(category_str) or category_str == 'Uncategorized':
        return 'Uncategorized', None, None
    
    parts = [p.strip() for p in category_str.split('|')]
    
    category = parts[0] if len(parts) > 0 else 'Uncategorized'
    subcategory = parts[1] if len(parts) > 1 else None
    product_type = parts[2] if len(parts) > 2 else None
    
    return category, subcategory, product_type


def extract_brand(product_name):
    """Extract brand from product name (first 1-2 words usually)"""
    if pd.isna(product_name):
        return None
    
    words = product_name.split()
    if len(words) == 0:
        return None
    
    # Take first 1-2 words as brand
    brand = ' '.join(words[:2]) if len(words) > 1 else words[0]
    return brand[:50]  # Limit length


def parse_price(price_str):
    """Convert '$237.68' to integer cents (23768)"""
    if pd.isna(price_str):
        return None
    
    try:
        # Remove $ and commas, convert to float, then to cents
        clean = str(price_str).replace('$', '').replace(',', '')
        dollars = float(clean)
        cents = int(dollars * 100)
        return cents
    except:
        return None


def generate_rating():
    """Generate realistic rating between 3.5 and 5.0"""
    return round(random.uniform(3.5, 5.0), 1)


def parse_attributes(spec_str, tech_str):
    """Extract key-value pairs from specification text into JSON"""
    attributes = {}
    
    # Parse Product Specification
    if pd.notna(spec_str):
        # Try to extract key:value patterns
        lines = str(spec_str).split('|')
        for line in lines[:10]:  # Limit to first 10
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()[:30]
                    value = parts[1].strip()[:100]
                    attributes[key] = value
    
    return attributes if attributes else None


def create_products(df):
    """Transform DataFrame to Product objects"""
    db = SessionLocal()
    products = []
    
    try:
        for idx, row in df.iterrows():
            # Parse category hierarchy
            category, subcategory, product_type = parse_category_hierarchy(row['Category'])
            
            # Parse price
            price = parse_price(row['Selling Price'])
            if price is None or price <= 0:
                continue  # Skip products without valid price
            
            # Extract brand
            brand = extract_brand(row['Product Name'])
            
            # Generate rating
            rating = generate_rating()
            
            # Parse attributes
            attributes = parse_attributes(
                row.get('Product Specification'),
                row.get('Technical Details')
            )
            
            # Create product
            product = Product(
                product_id=f"AMZN-{idx:05d}",
                name=str(row['Product Name'])[:200],
                brand=brand,
                category=category,
                subcategory=subcategory,
                type=product_type,  # Using 'type' for product_type
                price=price,
                rating=rating,
                description=str(row.get('About Product', ''))[:1000] if pd.notna(row.get('About Product')) else None,
                attributes=attributes
            )
            
            products.append(product)
            
            if len(products) % 100 == 0:
                logger.info(f"Processed {len(products)} products...")
        
        # Bulk insert
        db.bulk_save_objects(products)
        db.commit()
        logger.info(f"✓ Inserted {len(products)} products")
        
        return products
        
    finally:
        db.close()


def create_reviews(products):
    """Generate reviews for products"""
    db = SessionLocal()
    reviews = []
    
    review_templates = [
        "Great product! Highly recommend.",
        "Good quality for the price.",
        "Exactly as described. Very satisfied.",
        "Works perfectly. Would buy again.",
        "Excellent value. Fast shipping.",
        "Not bad but could be better.",
        "Decent product overall.",
        "Met my expectations.",
    ]
    
    reviewer_names = [
        "John D.", "Sarah M.", "Mike R.", "Emily K.", "David L.",
        "Lisa P.", "James W.", "Anna S.", "Chris B.", "Maria G."
    ]
    
    try:
        for product in products:
            # Generate 1-3 reviews per product
            num_reviews = random.randint(1, 3)
            
            for _ in range(num_reviews):
                review_rating = product.rating + random.uniform(-0.5, 0.5)
                review_rating = max(1.0, min(5.0, round(review_rating, 1)))
                
                review = Review(
                    product_id=product.product_id,
                    rating=review_rating,
                    review_text=random.choice(review_templates),
                    reviewer=random.choice(reviewer_names)
                )
                reviews.append(review)
        
        db.add_all(reviews)
        db.commit()
        logger.info(f"✓ Inserted {len(reviews)} reviews")
        
    finally:
        db.close()


def create_specs(products):
    """Generate specs for products"""
    db = SessionLocal()
    specs = []
    
    try:
        for product in products:
            if product.attributes:
                # Convert JSON attributes to individual spec rows
                for key, value in product.attributes.items():
                    spec = Spec(
                        product_id=product.product_id,
                        spec_key=key,
                        spec_value=str(value)
                    )
                    specs.append(spec)
        
        db.add_all(specs)
        db.commit()
        logger.info(f"✓ Inserted {len(specs)} specs")
        
    finally:
        db.close()


def create_demo_users_and_orders(products):
    """Create demo users and sample orders for Agent 1"""
    from datetime import datetime, timedelta
    
    db = SessionLocal()
    
    try:
        # Create demo users with SSO-ready structure
        users = [
            User(
                user_id="demo-user-1",
                email="alice@demo.com",
                name="Alice Demo",
                google_id=None,
                auth_provider="demo"
            ),
            User(
                user_id="demo-user-2",
                email="bob@demo.com",
                name="Bob Demo",
                google_id=None,
                auth_provider="demo"
            ),
            User(
                user_id="demo-user-3",
                email="charlie@demo.com",
                name="Charlie Demo",
                google_id=None,
                auth_provider="demo"
            ),
        ]
        db.add_all(users)
        db.commit()
        logger.info(f"✓ Created {len(users)} demo users")
        
# Create sample orders using actual Amazon products
        sample_products = products[:10] if len(products) >= 10 else products
        
        orders = [
            Order(
                order_id="ORD-1001",
                user_id="demo-user-1",
                product_name=sample_products[0].name[:100],
                status="shipped",
                carrier="FedEx",
                tracking_id="TRK-9001"
            ),
            Order(
                order_id="ORD-1002",
                user_id="demo-user-1",
                product_name=sample_products[1].name[:100],
                status="delivered",
                carrier="UPS",
                tracking_id="TRK-9002"
            ),
            Order(
                order_id="ORD-1003",
                user_id="demo-user-2",
                product_name=sample_products[2].name[:100],
                status="processing",
                carrier=None,
                tracking_id="TRK-9003"
            ),
            Order(
                order_id="ORD-1004",
                user_id="demo-user-2",
                product_name=sample_products[3].name[:100] if len(sample_products) > 3 else "Sample Product",
                status="shipped",
                carrier="DHL",
                tracking_id="TRK-9004"
            ),
            Order(
                order_id="ORD-1005",
                user_id="demo-user-3",
                product_name=sample_products[4].name[:100] if len(sample_products) > 4 else "Sample Product",
                status="shipped",
                carrier="USPS",
                tracking_id="TRK-9005"
            ),
        ]
        
        db.add_all(orders)
        db.commit()
        logger.info(f"✓ Created {len(orders)} demo orders")
        
    finally:
        db.close()

def main():
    """Run the complete ETL process"""
    logger.info("=" * 80)
    logger.info("AMAZON DATA MIGRATION")
    logger.info("=" * 80)
    
    # Step 1: Clear existing data
    clear_existing_data()
    
    # Step 2: Load and sample data
    df = load_and_sample_data()
    
    # Step 3: Create products
    products = create_products(df)
    
    # Step 4: Create reviews
    create_reviews(products)
    
    # Step 5: Create specs
    create_specs(products)
    
    # Step 6: Create demo users and orders
    create_demo_users_and_orders(products)
    
    logger.info("=" * 80)
    logger.info("✓ MIGRATION COMPLETE")
    logger.info(f"  Products: {len(products)}")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()