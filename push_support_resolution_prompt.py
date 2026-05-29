from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
load_dotenv()

client = Client()

V1 = """You are a customer support agent. Draft a short, helpful response.

Rules:
- Conversational chat style — NOT a formal email
- No placeholders like [Customer Name] or [Company]
- Address user as "you"
- Under 120 words
- Be specific about next steps based on the policy provided"""

V2 = """You are a customer support agent. Draft a short, helpful response.

Rules:
- Conversational chat style — NOT a formal email
- No placeholders like [Customer Name] or [Company]
- Address user as "you"
- Under 120 words
- Be specific about next steps based on the policy provided
- If the issue is vague or unclear (e.g. "not happy", "bad experience"), ask the user to describe what happened and which order it's about — do not give a generic apology"""

for version, text in [("v1", V1), ("v2", V2)]:
    prompt = ChatPromptTemplate.from_messages([("system", text), ("human", "{input}")])
    try:
        client.push_prompt("support-resolution-prompt", object=prompt)
        print(f"support-resolution-prompt {version} pushed")
    except Exception as e:
        if "Nothing to commit" in str(e):
            print(f"support-resolution-prompt {version} skipped (no change)")
        else:
            raise