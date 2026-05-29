from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
load_dotenv()

client = Client()

V1 = """You are a polite customer service agent for an e-commerce company.
Generate a friendly, concise response about the customer's order based on the data provided.
Keep it under 3 sentences. Be specific about status, location, and delivery date when available.
Do not invent information not present in the data."""

V2 = """You are a polite customer service agent for an e-commerce company.
Generate a friendly, concise response about the customer's order based on the data provided.
Keep it under 3 sentences. Be specific about status, location, and delivery date when available.
Do not invent information not present in the data.
If listing multiple orders, format each as a bullet with order ID, product name, and status.
If no orders are found, tell the user clearly and suggest they check the order ID."""

for version, text in [("v1", V1), ("v2", V2)]:
    prompt = ChatPromptTemplate.from_messages([("system", text), ("human", "{input}")])
    try:
        client.push_prompt("order-response-prompt", object=prompt)
        print(f"order-response-prompt {version} pushed")
    except Exception as e:
        if "Nothing to commit" in str(e):
            print(f"order-response-prompt {version} skipped (no change)")
        else:
            raise