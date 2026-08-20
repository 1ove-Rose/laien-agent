from ..llm import invoke_json
from ..schemas import TestCasesResponse
from .common import dump_json, emit


STAGE = "测试用例"


async def test_designer(state, llm, writer=None):
    emit(writer, "stage_started", STAGE, "开始为 PRD 需求生成 QA 测试用例。")
    system = """
你是 QA 测试设计师。只输出 JSON。
schema: {"tests":[{"id":"TC-1","title":"string","requirementId":"REQ-1","sourceFindingId":"F-1","steps":"string","expected":"string","version":"v0.1 初稿"}]}
每条 test 必须引用真实 requirementId，并继承对应 sourceFindingId。
"""
    user = f"需求：{dump_json(state['requirements'])}\n洞察：{dump_json(state['findings'])}"
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=TestCasesResponse, writer=writer)
    tests = [item.model_dump() for item in parsed.tests]
    emit(writer, "artifact", STAGE, "测试用例初稿已生成。", {"tests": tests})
    emit(writer, "stage_completed", STAGE, f"完成 {len(tests)} 条测试用例。")
    return {"tests": tests}
