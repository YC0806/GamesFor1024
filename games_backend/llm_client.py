import logging
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from requests import RequestException

logger = logging.getLogger(__name__)


def call_llm(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
    temperature: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Send a chat completion request to the configured language model provider.

    Returns a dictionary with keys:
    - success: whether the call succeeded.
    - content: the message content returned by the model when successful.
    - response: the raw SDK response object when successful.
    - error: a human-readable message when unsuccessful.
    """

    llm_base_url = getattr(settings, "LLM_BASE_URL", None)
    llm_api_key = getattr(settings, "LLM_API_KEY", None)
    default_model = getattr(settings, "LLM_MODEL", "deepseek-chat")

    if not (llm_base_url and llm_api_key):
        return {"success": False, "error": "LLM connection is not configured."}

    try:
        timeout = getattr(settings, "LLM_TIMEOUT", 60)
        url = f"{llm_base_url.rstrip('/')}/chat/completions"
        request_payload = {
            "model": model or default_model,
            "messages": messages,
            "stream": False,
        }
        if response_format:
            request_payload["response_format"] = response_format
        if temperature is not None:
            request_payload["temperature"] = temperature
        request_payload.update(kwargs)

        headers = {
            "Authorization": f"Bearer {llm_api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            url,
            headers=headers,
            json=request_payload,
            timeout=timeout,
        )
        response.raise_for_status()

        response_data = response.json()
        choices = response_data.get("choices")
        if not choices:
            raise KeyError("Missing 'choices' in response.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise KeyError("Missing 'content' in response message.")
        if isinstance(content, list):
            content = "".join(content)

        return {"success": True, "response": response_data, "content": content}
    except RequestException as exc:
        logger.exception("HTTP error when reaching language model service: %s", exc)
        return {
            "success": False,
            "error": f"Failed to reach language model service ({exc}). Please try again later.",
        }
    except ValueError as exc:
        logger.exception("Failed to decode language model response JSON: %s", exc)
        return {
            "success": False,
            "error": f"Invalid response from language model service ({exc}).",
        }
    except Exception as exc:
        logger.exception("Failed to process language model response: %s", exc)
        return {
            "success": False,
            "error": f"Unexpected language model service response ({exc}). Please try again later.",
        }
