from ..llm import invoke_json
from ..schemas import TestCasesResponse
from .common import data_limitations_instruction, dump_json, emit, resolve_writer


STAGE = "测试用例"


async def test_designer(state, llm, writer=None):
    writer = resolve_writer(writer)
    emit(writer, "stage_started", STAGE, "开始为 PRD 需求生成 QA 测试用例。")
    system = """
你是 QA 测试设计师。只输出 JSON。
schema: {"tests":[{"id":"TC-1","title":"string","requirementId":"REQ-1","sourceFindingId":"F-1","steps":"string","expected":"string","version":"v0.1 初稿"}]}
每条 test 必须引用真实 requirementId，并继承对应 sourceFindingId。
如果需求或源 finding 是 hypothesis，测试仍可生成，但必须标记为 hypothesis，表示它验证的是待确认假设。
title、steps、expected 和 version 必须使用简体中文；ID、requirementId 和 sourceFindingId 保持 schema 规定的格式。
"""
    user = f"{data_limitations_instruction(state)}\n需求：{dump_json(state['requirements'])}\n洞察：{dump_json(state['findings'])}"
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=TestCasesResponse, writer=writer)
    finding_map = {item["id"]: item for item in state["findings"]}
    requirement_map = {item["id"]: item for item in state["requirements"]}
    tests = []
    for item in parsed.tests:
        test = item.model_dump()
        source = finding_map.get(test.get("sourceFindingId"))
        requirement = requirement_map.get(test.get("requirementId"))
        if (source and source.get("status") == "hypothesis") or (requirement and requirement.get("status") == "hypothesis"):
            test.update(status="hypothesis", statusReason="该测试用例依赖尚未被评论证据充分支持的假设。")
        elif (source and source.get("status") == "revised") or (requirement and requirement.get("status") == "revised"):
            test.update(status="revised", statusReason="该测试用例继承了经证据审查修订的洞察。")
        tests.append(test)
    emit(writer, "artifact", STAGE, "测试用例初稿已生成。", {"tests": tests})
    emit(writer, "stage_completed", STAGE, f"完成 {len(tests)} 条测试用例。")
    return {"tests": tests}
