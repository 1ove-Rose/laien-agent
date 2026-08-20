import asyncio
import json
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .errors import AgentRunError, error_payload
from .graph import build_graph
from .llm import create_llm
from .schemas import AnalysisRunRequest, RunEvent
from .state import initial_state


RUN_TIMEOUT_SECONDS = float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "180"))

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
            llm = create_llm()
            graph = build_graph(llm)
            yield sse(make_event("stage_started", "多 Agent 编排", "多 Agent 分析任务已启动。"))

            async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                async for mode, chunk in graph.astream(latest_state, stream_mode=["custom", "updates"]):
                    if await request.is_disconnected():
                        break
                    if mode == "custom":
                        yield sse(RunEvent.model_validate(chunk).model_dump())
                    elif mode == "updates":
                        for update in chunk.values():
                            if isinstance(update, dict):
                                latest_state.update(update)

            completed = {
                "classifications": latest_state.get("classifications", []),
                "insights": latest_state.get("findings", []),
                "requirements": latest_state.get("requirements", []),
                "tests": latest_state.get("tests", []),
                "validations": latest_state.get("validations", []),
                "revisions": latest_state.get("revisions", []),
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

