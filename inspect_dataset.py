import pandas as pd

# Load the CSV
df = pd.read_csv('data/marketing_sample_for_amazon_com-ecommerce__20200101_20200131__10k_data.csv')

print("=" * 80)
print("DATASET OVERVIEW")
print("=" * 80)
print(f"Total rows: {len(df)}")

print("\n" + "=" * 80)
print("CATEGORY ANALYSIS")
print("=" * 80)

# Clean and analyze categories
df['Category'] = df['Category'].fillna('Uncategorized')
categories = df['Category'].str.split('|').str[0].str.strip()
print(f"\nUnique TOP-LEVEL categories: {categories.nunique()}")
print("\nTop 30 categories by count:")
print(categories.value_counts().head(30))

print("\n" + "=" * 80)
print("FULL CATEGORY PATHS (sample)")
print("=" * 80)
print("\nSample category hierarchies:")
for cat in df['Category'].dropna().head(10):
    print(f"  {cat}")

print("\n" + "=" * 80)
print("CATEGORY DEPTH ANALYSIS")
print("=" * 80)
df['category_depth'] = df['Category'].str.split('|').str.len()
print(df['category_depth'].describe())
print(f"\nMost common depths:")
print(df['category_depth'].value_counts().head())

print("\n" + "=" * 80)
print("PRICE ANALYSIS")
print("=" * 80)
# Clean selling price
df['price_clean'] = df['Selling Price'].str.replace('$', '').str.replace(',', '')
df['price_clean'] = pd.to_numeric(df['price_clean'], errors='coerce')
print("\nSelling Price statistics:")
print(df['price_clean'].describe())
print(f"\nProducts with valid prices: {df['price_clean'].notna().sum()} / {len(df)}")

print("\n" + "=" * 80)
print("DATA QUALITY SUMMARY")
print("=" * 80)
print(f"Products with Category: {df['Category'].notna().sum()}")
print(f"Products with Selling Price: {df['Selling Price'].notna().sum()}")
print(f"Products with About Product: {df['About Product'].notna().sum()}")
print(f"Products with Product Specification: {df['Product Specification'].notna().sum()}")