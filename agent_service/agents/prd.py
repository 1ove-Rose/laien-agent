from ..llm import invoke_json
from ..schemas import RequirementsResponse
from .common import data_limitations_instruction, dump_json, emit, resolve_writer
from ..analysis_mode import mode_instruction


STAGE = "产品需求"


async def prd_planner(state, llm, writer=None):
    writer = resolve_writer(writer)
    emit(writer, "stage_started", STAGE, "开始把已审查洞察转换为 PRD 需求。")
    mode = state.get("analysisMode", "negative")
    system = """
你是移动应用产品经理。只输出 JSON。
schema: {"requirements":[{"id":"REQ-1","title":"string","priority":"P0|P1|P2","sourceFindingId":"F-1","acceptance":"string","version":"v0.1 初稿"}]}
每条 requirement 必须引用一个真实 finding.id。验收标准必须可测试。
如果 source finding 的 status 是 hypothesis，仍可生成需求，但必须保留假设状态，不能写成已验证事实。
title、acceptance 和 version 必须使用简体中文；ID、优先级 P0/P1/P2 和 sourceFindingId 保持 schema 规定的格式。
"""
    user = f"分析目标：{state['goal']}\n{mode_instruction(mode)}\n{data_limitations_instruction(state)}\n仅使用以下已通过审查或明确标记为假设的洞察：{dump_json(state['findings'])}"
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=RequirementsResponse, writer=writer)
    finding_map = {item["id"]: item for item in state["findings"]}
    requirements = []
    for item in parsed.requirements:
        requirement = item.model_dump()
        source = finding_map.get(requirement.get("sourceFindingId"))
        if source and source.get("status") == "hypothesis":
            requirement.update(status="hypothesis", statusReason="源洞察已明确标记为假设，需求需要产品验证后再实施。")
        elif source and source.get("status") == "revised":
            requirement.update(status="revised", statusReason="源洞察已根据证据审查修订。")
        requirements.append(requirement)
    emit(writer, "artifact", STAGE, "PRD 初稿已生成。", {"requirements": requirements})
    emit(writer, "stage_completed", STAGE, f"完成 {len(requirements)} 条需求。")
    return {"requirements": requirements}
