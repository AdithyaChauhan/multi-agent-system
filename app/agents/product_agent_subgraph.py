from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.tools.product_tools import fetch_reviews, fetch_specs
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.agents.product_subgraph")


# ---------- Scoring weights ----------

WEIGHT_RATING = 0.30
WEIGHT_REVIEW_RATING = 0.20
WEIGHT_PRICE = 0.15
WEIGHT_SPEC_MATCH = 0.10
WEIGHT_BRAND_MATCH = 0.15
WEIGHT_TAG_MATCH = 0.07
WEIGHT_TITLE_MATCH = 0.03
WEIGHT_TYPE_MATCH = 0.07


# ---------- Nodes ----------


def fetch_reviews_node(state: AgentState) -> dict:
    """
    Tool node — fetches reviews for each product in the LLM-ranked list.
    Reads from ranked_products (set by rank_and_filter) and writes back to it.
    """
    products = state.get("ranked_products") or []

    enriched = []
    for product in products:
        product_id = product.get("product_id")
        reviews = fetch_reviews(product_id)

        avg_review_rating = 0.0
        if reviews:
            avg_review_rating = sum(r["rating"] for r in reviews) / len(reviews)

        enriched.append(
            {
                **product,
                "reviews": reviews,
                "avg_review_rating": round(avg_review_rating, 2),
            }
        )

    logger.info(f"request_id={get_request_id()} | " f"Reviews fetched for {len(enriched)} products")

    return {"ranked_products": enriched}


def fetch_specs_node(state: AgentState) -> dict:
    """
    Tool node — fetches specs for each product in the LLM-ranked list.
    Reads from ranked_products and writes back to it.
    """
    products = state.get("ranked_products") or []

    enriched = []
    for product in products:
        product_id = product.get("product_id")
        specs = fetch_specs(product_id)

        specs_dict = {s["spec_key"]: s["spec_value"] for s in specs}

        enriched.append(
            {
                **product,
                "specs": specs,
                "specs_dict": specs_dict,
            }
        )

    logger.info(f"request_id={get_request_id()} | " f"Specs fetched for {len(enriched)} products")

    return {"ranked_products": enriched}


def compute_score(state: AgentState) -> dict:
    """
    Deterministic node — computes a final enriched score
    combining product rating, review rating, price, and spec match.
    """
    products = state.get("ranked_products") or []
    prefs = state.get("preferences") or {}
    max_price = prefs.get("max_price")
    keywords = prefs.get("keywords") or []

    if not products:
        return {"ranked_products": []}

    scored = []
    for product in products:

        # 1. product rating score (0 to 1)
        rating_score = (product.get("rating") or 0) / 5.0

        # 2. review rating score (0 to 1)
        avg_review = product.get("avg_review_rating") or 0
        review_score = avg_review / 5.0

        # 3. price score (0 to 1) — value-based
        # products closer to budget but within it get the highest score
        # too cheap is penalized (likely lower quality)
        price = product.get("price") or 0
        if max_price and max_price > 0:
            ratio = price / max_price
            if ratio > 1.0:
                price_score = 0.0  # over budget — safety case
            elif ratio >= 0.7:
                price_score = 1.0  # using 70-100% of budget — best value
            elif ratio >= 0.5:
                price_score = 0.7  # using 50-70% — decent
            else:
                price_score = 0.4  # too cheap — likely lower quality
        else:
            # no budget specified — neutral
            price_score = 0.5

        # 4. spec match score (0 to 1) — keywords found in specs
        spec_match_score = 0.0
        if keywords:
            specs_dict = product.get("specs_dict") or {}
            description = (product.get("description") or "").lower()
            spec_text = " ".join(str(v) for v in specs_dict.values()).lower()
            combined = description + " " + spec_text

            matched = sum(1 for kw in keywords if kw.lower() in combined)
            spec_match_score = matched / len(keywords)

        # 5. brand match score (0 or 1)
        brand_match_score = 0.0
        user_brand = (prefs.get("brand") or "").lower()
        product_brand = (product.get("brand") or "").lower()
        if user_brand and user_brand in product_brand:
            brand_match_score = 1.0

        # 6. tag match score (0 to 1)
        tag_match_score = 0.0
        if keywords:
            tags = product.get("tags") or []
            tags_text = " ".join(tags).lower() if isinstance(tags, list) else str(tags).lower()
            tag_matched = sum(1 for kw in keywords if kw.lower() in tags_text)
            tag_match_score = tag_matched / len(keywords)

        # 7. title match score (0 to 1)
        title_match_score = 0.0
        if keywords:
            title = (product.get("name") or "").lower()
            title_matched = sum(1 for kw in keywords if kw.lower() in title)
            title_match_score = title_matched / len(keywords)

        # 8. type match score (0 or 1)
        type_match_score = 0.0
        user_type = (prefs.get("type") or "").lower()
        product_type = (product.get("type") or "").lower()
        if user_type and user_type in product_type:
            type_match_score = 1.0

        # combine all scores

        final_score = (
            WEIGHT_RATING * rating_score
            + WEIGHT_REVIEW_RATING * review_score
            + WEIGHT_PRICE * price_score
            + WEIGHT_SPEC_MATCH * spec_match_score
            + WEIGHT_BRAND_MATCH * brand_match_score
            + WEIGHT_TAG_MATCH * tag_match_score
            + WEIGHT_TITLE_MATCH * title_match_score
            + WEIGHT_TYPE_MATCH * type_match_score
        )

        scored.append(
            {
                **product,
                "rating_score": round(rating_score, 3),
                "review_score": round(review_score, 3),
                "price_score": round(price_score, 3),
                "spec_match_score": round(spec_match_score, 3),
                "brand_match_score": round(brand_match_score, 3),
                "tag_match_score": round(tag_match_score, 3),
                "title_match_score": round(title_match_score, 3),
                "type_match_score": round(type_match_score, 3),
                "final_score": round(final_score, 3),
            }
        )

    # sort: tier 0 (relevant) before tier 1 (maybe), quality within each tier
    scored.sort(key=lambda x: (x.get("llm_tier", 1), -x["final_score"]))

    # take top 5
    top = scored[:5]

    logger.info(f"request_id={get_request_id()} | " f"Scores computed | total={len(scored)} | top={len(top)}")

    return {"ranked_products": top}


# ---------- Graph builder ----------


def build_product_enrichment_subgraph():
    graph = StateGraph(AgentState)

    graph.add_node("fetch_reviews", fetch_reviews_node)
    graph.add_node("fetch_specs", fetch_specs_node)
    graph.add_node("compute_score", compute_score)

    graph.set_entry_point("fetch_reviews")

    graph.add_edge("fetch_reviews", "fetch_specs")
    graph.add_edge("fetch_specs", "compute_score")
    graph.add_edge("compute_score", END)

    return graph.compile()


product_enrichment_subgraph = build_product_enrichment_subgraph()
