You label products in an Indian electronics and home store's catalog. For each numbered product name, return:
- product_type: exactly one type name from the list below. Use an "other ..." type only when no specific type fits. Accessories for a product (covers, cases, mats, mounts, spare parts) are not that product.
- kind: for types that list kinds, the one that fits, else null.
- brand: the maker as written in the name ("boAt", "Samsung"); null for unbranded or generic items. Never a model or series name.
- title: a short clean title, at most 60 characters: brand, model or series, and what it is. No colours, pack sizes or long spec lists.
- confidence: 0 to 1, how sure you are of the type and kind.

Types (type: kinds):
{types}
