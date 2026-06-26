"""
Schema migration: Add category/subcategory columns and SSO fields
"""

from sqlalchemy import inspect, text
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


def ensure_support_ticket_priority_column() -> None:
    """Add missing support_tickets columns when an older SQLite DB is still in use."""
    inspector = inspect(engine)
    if "support_tickets" not in inspector.get_table_names():
        return

    column_names = {column["name"] for column in inspector.get_columns("support_tickets")}
    additions = {
        "priority": "VARCHAR",
        "safety_alert": "BOOLEAN DEFAULT 0",
    }

    missing_columns = {name: ddl for name, ddl in additions.items() if name not in column_names}
    if not missing_columns:
        return

    with engine.connect() as conn:
        for column_name, ddl in missing_columns.items():
            conn.execute(text(f"ALTER TABLE support_tickets ADD COLUMN {column_name} {ddl}"))
        conn.commit()


if __name__ == "__main__":
    migrate_schema()
