from ..llm import invoke_json
from ..schemas import RequirementsResponse
from .common import dump_json, emit


STAGE = "产品需求"


async def prd_planner(state, llm, writer=None):
    emit(writer, "stage_started", STAGE, "开始把已审查洞察转换为 PRD 需求。")
    system = """
你是移动应用产品经理。只输出 JSON。
schema: {"requirements":[{"id":"REQ-1","title":"string","priority":"P0|P1|P2","sourceFindingId":"F-1","acceptance":"string","version":"v0.1 初稿"}]}
每条 requirement 必须引用一个真实 finding.id。验收标准必须可测试。
"""
    user = f"分析目标：{state['goal']}\n洞察：{dump_json(state['findings'])}"
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=RequirementsResponse, writer=writer)
    requirements = [item.model_dump() for item in parsed.requirements]
    emit(writer, "artifact", STAGE, "PRD 初稿已生成。", {"requirements": requirements})
    emit(writer, "stage_completed", STAGE, f"完成 {len(requirements)} 条需求。")
    return {"requirements": requirements}
