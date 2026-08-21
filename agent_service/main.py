import asyncio
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .errors import AgentRunError, error_payload
from .graph import build_graph
from .llm import create_llm
from .schemas import AnalysisRunRequest, RunEvent
from .state import initial_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ENV = PROJECT_ROOT / ".env"
EXAMPLE_ENV = PROJECT_ROOT / ".env.example"
CONFIG_ENV = PROJECT_ENV if PROJECT_ENV.exists() else EXAMPLE_ENV
load_dotenv(CONFIG_ENV, override=False)

RUN_TIMEOUT_SECONDS = float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "900"))

app = FastAPI(title="App Review Insights Agent Service")


def sse(event: dict[str, Any]):
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def make_event(event_type, stage, message, data=None):
    return RunEvent(type=event_type, stage=stage, message=message, data=data or {}).model_dump()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analysis/run")
async def run_analysis(request: Request):
    try:
        payload = await request.json()
        run_request = AnalysisRunRequest.from_payload(payload)
    except Exception as exc:
        error = error_payload(exc)
        return JSONResponse({"error": error}, status_code=400 if error["code"] == "INVALID_AGENT_INPUT" else 500)

    async def event_stream():
        latest_state = initial_state(run_request)
        try:
            yield sse(make_event("stage_started", "多 Agent 编排", "多 Agent 分析任务已启动。"))
            yield sse(make_event(
                "artifact",
                "多 Agent 编排",
                "已确认本次分析的数据范围和限制。",
                {"dataLimitations": latest_state.get("dataLimitations", [])},
            ))
            llm = create_llm()
            graph = build_graph(llm)

            stream = graph.astream(latest_state, stream_mode=["custom", "updates"])
            try:
                async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                    async for mode, chunk in stream:
                        if await request.is_disconnected():
                            return
                        if mode == "custom":
                            yield sse(RunEvent.model_validate(chunk).model_dump())
                        elif mode == "updates":
                            for update in chunk.values():
                                if isinstance(update, dict):
                                    latest_state.update(update)
            finally:
                await stream.aclose()

            completed = {
                "analysisMode": latest_state.get("analysisMode", "balanced"),
                "classifications": latest_state.get("classifications", []),
                "insights": latest_state.get("findings", []),
                "insightsBeforeRevision": latest_state.get("findingsBeforeRevision", []),
                "insightsAfterRevision": latest_state.get("findings", []),
                "requirements": latest_state.get("requirements", []),
                "tests": latest_state.get("tests", []),
                "validations": latest_state.get("validations", []),
                "revisions": latest_state.get("revisions", []),
                "rejectedFindings": latest_state.get("rejectedFindings", []),
                "dataLimitations": latest_state.get("dataLimitations", []),
            }
            yield sse(make_event("completed", "多 Agent 编排", "多 Agent 分析完成。", completed))
        except TimeoutError as exc:
            error = error_payload(AgentRunError("AGENT_RUN_TIMEOUT", "多 Agent 分析超时。", stage="多 Agent 编排", retryable=True, cause=exc))
            yield sse(make_event("error", error["stage"], error["message"], {"error": error}))
        except Exception as exc:
            error = error_payload(exc)
            yield sse(make_event("error", error["stage"], error["message"], {"error": error}))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
