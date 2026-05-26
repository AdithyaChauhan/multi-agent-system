"""
Schema migration: Add category/subcategory columns and SSO fields
"""
from sqlalchemy import text
from app.db.database import engine

def migrate_schema():
    """Add new columns for flexible categorization and SSO"""
    
    with engine.connect() as conn:
        # Add category and subcategory columns to products
        conn.execute(text("""
            ALTER TABLE products 
            ADD COLUMN IF NOT EXISTS category VARCHAR,
            ADD COLUMN IF NOT EXISTS subcategory VARCHAR
        """))
        
        # Make products columns nullable
        conn.execute(text("""
            ALTER TABLE products 
            ALTER COLUMN type DROP NOT NULL,
            ALTER COLUMN brand DROP NOT NULL,
            ALTER COLUMN description DROP NOT NULL,
            ALTER COLUMN attributes DROP NOT NULL
        """))
        
        # Make review_id and spec_id nullable
        conn.execute(text("""
            ALTER TABLE reviews 
            ALTER COLUMN review_id DROP NOT NULL
        """))
        
        conn.execute(text("""
            ALTER TABLE specs 
            ALTER COLUMN spec_id DROP NOT NULL
        """))
        
        # Add SSO fields to users table
        conn.execute(text("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS email VARCHAR,
            ADD COLUMN IF NOT EXISTS name VARCHAR,
            ADD COLUMN IF NOT EXISTS google_id VARCHAR,
            ADD COLUMN IF NOT EXISTS auth_provider VARCHAR DEFAULT 'anonymous'
        """))

        # Make email and google_id unique (but handle NULL values)
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email 
            ON users(email) WHERE email IS NOT NULL;
            
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id 
            ON users(google_id) WHERE google_id IS NOT NULL;
        """))
        
        conn.commit()
        print("✓ Schema migration complete (with SSO support)")

if __name__ == "__main__":
    migrate_schema()