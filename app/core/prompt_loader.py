"""Load prompts from LangSmith Prompt Hub at runtime"""
import os
from langsmith import Client
from app.core.logger import get_logger

logger = get_logger("app.core.prompt_loader")

client = Client()

def load_prompt(prompt_name: str, version: str = "latest") -> tuple[str, str]:
    """
    Load a prompt from LangSmith Prompt Hub
    
    Args:
        prompt_name: Name of the prompt in the hub
        version: Version/commit hash (default: "latest")
    
    Returns:
        Tuple of (prompt_text, commit_hash)
    """
    try:
        prompt_identifier = f"{prompt_name}:{version}"
        prompt = client.pull_prompt(prompt_identifier)
        
        # Extract system message text
        messages = prompt.messages
        system_text = ""
        for msg in messages:
            if hasattr(msg, 'prompt'):
                system_text = msg.prompt.template
                break
        
        # Get commit hash
        commit_hash = version if version != "latest" else "latest"
        
        logger.info(f"Loaded prompt | name={prompt_name} | version={version}")
        return system_text, commit_hash
        
    except Exception as e:
        logger.error(f"Failed to load prompt {prompt_name}: {str(e)}")
        return None, None


# Prompt version config — change version here to switch without code change
PROMPT_VERSIONS = {
    "router-classification-prompt":     os.getenv("ROUTER_PROMPT_VERSION", "latest"),
    "support-classification-prompt":    os.getenv("SUPPORT_PROMPT_VERSION", "latest"),
    "support-resolution-prompt":        os.getenv("SUPPORT_RESOLUTION_PROMPT_VERSION", "latest"),
    "product-extraction-prompt":        os.getenv("PRODUCT_EXTRACTION_PROMPT_VERSION", "latest"),
    "order-response-prompt":            os.getenv("ORDER_RESPONSE_PROMPT_VERSION", "latest"),
}
