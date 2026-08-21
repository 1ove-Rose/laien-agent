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
        "缺少 OPENAI_API_KEY。请在项目根目录的 .env 或 .env.example 文件中配置模型 API Key。",
        stage="模型配置",
        retryable=False,
    )


def create_llm():
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    project_root = Path(__file__).resolve().parents[1]
    project_env = project_root / ".env"
    example_env = project_root / ".env.example"
    config_env = project_env if project_env.exists() else example_env
    load_dotenv(config_env, override=False)
    config = resolve_model_config()

    kwargs = {
        "api_key": config["api_key"],
        "model": config["model"],
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
        "timeout": float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "180")),
    }
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    thinking_type = os.getenv("OPENAI_THINKING_TYPE", "").strip()
    if thinking_type and thinking_type.lower() not in {"disabled", "off", "false", "0"}:
        kwargs["extra_body"] = {"thinking": {"type": thinking_type}}
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
    return is_timeout_error(error) or isinstance(error, ConnectionError)


def is_timeout_error(error):
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return True
    return any(
        marker in error.__class__.__name__.lower()
        for marker in ("timeout", "readtimeout", "connecttimeout", "writetimeout")
    )


def model_error_message(error):
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    messages = {
        400: "模型请求参数不兼容，请检查模型名称和高级推理配置。",
        401: "模型 API Key 无效或已过期，请检查 OPENAI_API_KEY。",
        403: "模型 API Key 没有调用权限，请检查账户权限。",
        404: "模型或 API 地址不存在，请检查 OPENAI_BASE_URL 和 OPENAI_MODEL。",
        402: "模型账户余额不足或未开通计费。",
        408: "模型请求超时。",
        429: "模型接口触发限流，请稍后重试。",
    }
    if status in messages:
        return messages[status]
    if isinstance(status, int) and status >= 500:
        return "模型服务暂时不可用，请稍后重试。"
    if is_timeout_error(error):
        return "模型请求超时。"
    if isinstance(error, ConnectionError):
        return "无法连接模型服务，请检查网络和 OPENAI_BASE_URL。"
    return "模型请求失败，请检查模型配置和服务日志。"


async def emit_model_heartbeat(writer, stage, timeout_seconds):
    elapsed = 0
    interval = 15
    while elapsed + interval < timeout_seconds:
        await asyncio.sleep(interval)
        elapsed += interval
        if writer:
            writer({
                "type": "progress",
                "stage": stage,
                "message": f"模型仍在处理{stage}，已等待约 {elapsed} 秒。",
                "data": {"elapsedSeconds": elapsed, "timeoutSeconds": timeout_seconds},
            })


async def invoke_json(llm, *, stage, system, user, response_model: Type[BaseModel], writer=None):
    if writer is None:
        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
        except (ImportError, RuntimeError):
            writer = None
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    request_failures = 0
    parse_failures = 0
    timeout_seconds = float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "180"))

    while True:
        try:
            if writer:
                writer({
                    "type": "progress",
                    "stage": stage,
                    "message": f"正在等待模型返回{stage}结果。",
                    "data": {
                        "attempt": request_failures + 1,
                        "timeoutSeconds": timeout_seconds,
                    },
                })
            heartbeat = asyncio.create_task(emit_model_heartbeat(writer, stage, timeout_seconds))
            try:
                response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout_seconds)
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
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
                    model_error_message(exc),
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
