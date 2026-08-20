import asyncio
import json
import os
import re
from typing import Type
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .errors import AgentRunError


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def resolve_model_config(environ=None):
    """Resolve any OpenAI-compatible provider without exposing the secret."""
    env = os.environ if environ is None else environ
    api_key = (env.get("OPENAI_API_KEY") or "").strip()
    if api_key:
        return {
            "provider": "openai-compatible",
            "api_key": api_key,
            "base_url": (env.get("OPENAI_BASE_URL") or "").strip() or None,
            "model": (env.get("OPENAI_MODEL") or "gpt-4o-mini").strip(),
        }

    raise AgentRunError(
        "MODEL_CONFIG_MISSING",
        "缺少 OPENAI_API_KEY，无法运行多 Agent 分析。",
        stage="模型配置",
        retryable=False,
    )


def create_llm():
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    project_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(project_env, override=False)
    config = resolve_model_config()

    kwargs = {
        "api_key": config["api_key"],
        "model": config["model"],
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
        "timeout": float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "45")),
    }
    base_url = config["base_url"]
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def extract_text(message):
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def parse_json_object(text):
    text = text.strip()
    block = JSON_BLOCK_RE.search(text)
    if block:
        text = block.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("model output must be a JSON object")
    return data


def is_retryable_error(error):
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    if status in (408, 409, 429) or (isinstance(status, int) and status >= 500):
        return True
    return isinstance(error, (TimeoutError, asyncio.TimeoutError, ConnectionError))


async def invoke_json(llm, *, stage, system, user, response_model: Type[BaseModel], writer=None):
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    request_failures = 0
    parse_failures = 0

    while True:
        try:
            response = await llm.ainvoke(messages)
            text = extract_text(response)
            if not text.strip():
                raise ValueError("model returned empty content")
            payload = parse_json_object(text)
            return response_model.model_validate(payload)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            if parse_failures >= 1:
                raise AgentRunError(
                    "MODEL_OUTPUT_INVALID",
                    "模型输出无法解析为目标 JSON schema。",
                    stage=stage,
                    retryable=True,
                    cause=exc,
                ) from exc
            parse_failures += 1
            if writer:
                writer({
                    "type": "retry",
                    "stage": stage,
                    "message": "模型 JSON 输出解析失败，正在重试。",
                    "data": {"attempt": parse_failures},
                })
            messages.append(HumanMessage(content="上一轮输出无效。请只返回符合 schema 的 JSON 对象，不要包含 Markdown。"))
        except Exception as exc:
            if request_failures >= 2 or not is_retryable_error(exc):
                raise AgentRunError(
                    "MODEL_REQUEST_FAILED",
                    "模型请求失败。",
                    stage=stage,
                    retryable=is_retryable_error(exc),
                    cause=exc,
                ) from exc
            request_failures += 1
            if writer:
                writer({
                    "type": "retry",
                    "stage": stage,
                    "message": "模型请求失败，正在重试。",
                    "data": {"attempt": request_failures},
                })
            await asyncio.sleep(0.4 * (2 ** (request_failures - 1)))
