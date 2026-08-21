from ..errors import AgentRunError
from ..llm import invoke_json
from ..schemas import CriticResponse, ValidationResult
from .common import data_limitations_instruction, dump_json, emit, resolve_writer, reviews_for_prompt
from ..analysis_mode import mode_instruction


STAGE = "证据审查"


def deterministic_evidence_checks(state):
    review_ids = {review["id"] for review in state["reviews"]}
    validations = []
    problems = []
    for finding in state["findings"]:
        evidence_ids = finding.get("evidenceIds") or []
        missing = [review_id for review_id in evidence_ids if review_id not in review_ids]
        conflict_ids = finding.get("conflictEvidenceIds") or []
        missing_conflicts = [review_id for review_id in conflict_ids if review_id not in review_ids]
        if not evidence_ids:
            problems.append(f"{finding.get('id')} 缺少证据。")
        if missing:
            problems.append(f"{finding.get('id')} 引用了不存在的评论 ID: {', '.join(missing)}。")
        if missing_conflicts:
            problems.append(f"{finding.get('id')} 的冲突证据引用了不存在的评论 ID: {', '.join(missing_conflicts)}。")
        if finding.get("supportCount") != len(evidence_ids):
            problems.append(f"{finding.get('id')} supportCount 与 evidenceIds 数量不一致。")

    if problems:
        validations.append(ValidationResult(type="error", title="洞察证据校验失败", detail=" ".join(problems), stage=STAGE))
    else:
        validations.append(ValidationResult(type="pass", title="洞察证据校验通过", detail="所有洞察均引用真实评论且支持数一致。", stage=STAGE))
    return not problems, validations, " ".join(problems)


def finalize_invalid_as_hypotheses(state, notes):
    review_ids = {review["id"] for review in state["reviews"]}
    findings = []
    changed = []
    for finding in state["findings"]:
        evidence_ids = [review_id for review_id in finding.get("evidenceIds", []) if review_id in review_ids]
        conflict_ids = [review_id for review_id in finding.get("conflictEvidenceIds", []) if review_id in review_ids]
        reason = notes or "修订后仍缺少充分证据。"
        findings.append({
            **finding,
            "evidenceIds": list(dict.fromkeys(evidence_ids)),
            "supportCount": len(set(evidence_ids)),
            "conflictEvidenceIds": list(dict.fromkeys(conflict_ids)),
            "status": "hypothesis",
            "statusReason": reason,
        })
        changed.append(finding.get("id"))
    return findings, changed


def apply_critic_decisions(state, decisions):
    decision_map = {item.findingId: item for item in decisions}
    findings = []
    rejected = list(state.get("rejectedFindings", []))
    for finding in state["findings"]:
        decision = decision_map.get(finding.get("id"))
        decision_conflicts = decision.conflictEvidenceIds if decision else []
        merged_conflicts = list(dict.fromkeys((finding.get("conflictEvidenceIds") or []) + decision_conflicts))
        enriched = {**finding, "conflictEvidenceIds": merged_conflicts}
        if not decision or decision.action == "accept":
            findings.append({**enriched, "status": finding.get("status", "validated")})
        elif decision.action == "hypothesis":
            findings.append({**enriched, "status": "hypothesis", "statusReason": decision.reason})
        elif decision.action == "reject":
            findings.append({
                **enriched,
                "status": "hypothesis",
                "statusReason": f"结论当前完全不受评论证据支持，作为待验证假设保留：{decision.reason}",
            })
        else:
            findings.append({**enriched, "status": "revised", "statusReason": decision.reason})
    return findings, rejected


def decision_validations(decisions):
    labels = {
        "accept": ("pass", "证据审查通过"),
        "revise": ("revised", "需要修订"),
        "hypothesis": ("revised", "已标记为假设"),
        "reject": ("revised", "完全不支持，已标记为假设"),
    }
    validations = []
    for decision in decisions:
        validation_type, action_label = labels[decision.action]
        validations.append({
            "type": validation_type,
            "title": f"{decision.findingId}：{action_label}",
            "detail": decision.reason,
            "stage": STAGE,
        })
    return validations


def decisions_resolve_review(findings, decisions, model_passed):
    decision_map = {item.findingId: item.action for item in decisions}
    actions = [decision_map.get(finding.get("id")) for finding in findings]
    if any(action == "revise" for action in actions):
        return False
    if model_passed:
        return True
    return bool(actions) and all(action is not None for action in actions) and any(
        action in {"hypothesis", "reject"} for action in actions
    )


def finalize_unresolved_as_hypotheses(findings, decisions, notes):
    decision_map = {item.findingId: item for item in decisions}
    all_accept_but_failed = bool(findings) and all(
        decision_map.get(finding.get("id")) and decision_map[finding.get("id")].action == "accept"
        for finding in findings
    )
    finalized = []
    changed = []
    for finding in findings:
        decision = decision_map.get(finding.get("id"))
        unresolved = all_accept_but_failed or decision is None or decision.action in {"revise", "reject"}
        if unresolved:
            reason = (decision.reason if decision else "") or notes or "修订后仍缺少充分证据。"
            finalized.append({**finding, "status": "hypothesis", "statusReason": reason})
            changed.append(finding.get("id"))
        else:
            finalized.append(finding)
    return finalized, changed


async def evidence_critic(state, llm, writer=None):
    writer = resolve_writer(writer)
    emit(writer, "stage_started", STAGE, "开始检查洞察证据、冲突和结论边界。")
    mode = state.get("analysisMode", "negative")
    deterministic_passed, base_validations, base_notes = deterministic_evidence_checks(state)
    if not deterministic_passed:
        validations = [item.model_dump() for item in base_validations]
        for item in validations:
            emit(writer, "validation", STAGE, item["title"], item)
        if state.get("iteration", 0) < 1:
            emit(writer, "stage_completed", STAGE, "证据审查未通过，开始修订洞察。", {"passed": False})
            return {
                "criticPassed": False,
                "criticNotes": base_notes,
                "validations": state["validations"] + validations,
            }

        findings, changed = finalize_invalid_as_hypotheses(state, base_notes)
        fallback = {
            "type": "revised",
            "title": "完全不支持的洞察已保留为假设",
            "detail": (
                f"修订后 {', '.join(changed)} 仍缺少充分或有效证据；已移除无效引用、标记为假设，"
                "并继续生成 PRD 和测试用例。"
            ),
            "stage": STAGE,
        }
        emit(writer, "validation", STAGE, fallback["title"], fallback)
        emit(
            writer,
            "artifact",
            STAGE,
            "证据处理结果已更新。",
            {"insights": findings, "insightVersion": "after-revision"},
        )
        emit(writer, "stage_completed", STAGE, "证据不足的洞察已标记为假设。", {"passed": True})
        return {
            "findings": findings,
            "criticPassed": True,
            "criticNotes": base_notes,
            "validations": state["validations"] + validations + [fallback],
        }

    system = """
你是 Evidence Critic。只输出 JSON。
schema: {"passed":true,"validations":[{"type":"pass|error|revised","title":"string","detail":"string","stage":"证据审查"}],"revisionInstructions":"string|null","decisions":[{"findingId":"F-1","action":"accept|revise|hypothesis|reject","reason":"string","conflictEvidenceIds":["review-id"]}]}
审查是否存在过度泛化、证据不足、与评论文本矛盾的问题。失败时给出可执行修订意见。
不支持的结论必须 revise 或 hypothesis，不能 silently accept，也不要删除。hypothesis 必须明确说明尚未被评论证据充分支持的原因。
冲突证据、单条证据或低置信度本身不要求整个审查失败；可将对应 finding 标记为 hypothesis，并令 passed=true。
只有必须修改标题、摘要或证据引用时才使用 revise 和 passed=false。每个 finding 都必须给出一条 decision。
如果发现与结论相冲突的评论，必须在 conflictEvidenceIds 中列出真实 review.id；没有冲突时返回空数组 []。不要从评论内容中编造不存在的 ID。不要使用 reject；完全不支持时使用 hypothesis，使其以待验证假设进入下游。
validations、revisionInstructions 和每条 decision.reason 必须使用简体中文。不要输出英文解释。
"""
    user = (
        f"分析目标：{state['goal']}\n{mode_instruction(mode)}\n"
        f"{data_limitations_instruction(state)}\n"
        f"评论：{dump_json(reviews_for_prompt(state['reviews'], 500))}\n"
        f"洞察：{dump_json(state['findings'])}"
    )
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=CriticResponse, writer=writer)
    findings, rejected = apply_critic_decisions(state, parsed.decisions)
    validations = [item.model_dump() for item in parsed.validations] + decision_validations(parsed.decisions)
    critic_passed = decisions_resolve_review(state["findings"], parsed.decisions, parsed.passed)
    if not critic_passed and state.get("iteration", 0) >= 1:
        findings, changed = finalize_unresolved_as_hypotheses(
            findings,
            parsed.decisions,
            parsed.revisionInstructions or "",
        )
        if changed:
            fallback = {
                "type": "revised",
                "title": "未决洞察已降级为假设",
                "detail": f"修订后仍无法充分验证 {', '.join(changed)}，已明确标记为假设并继续生成下游产物。",
                "stage": STAGE,
            }
            validations.append(fallback)
            emit(writer, "validation", STAGE, fallback["title"], fallback)
        critic_passed = True
    if critic_passed:
        validations = [
            {
                **item,
                "type": "revised",
                "title": f"{item['title']}（已处置）",
                "detail": f"{item['detail']} 相关结论已修订或标记为假设。",
            }
            if item.get("type") == "error"
            else item
            for item in validations
        ]
    for item in validations:
        if item.get("title") == "未决洞察已降级为假设":
            continue
        emit(writer, "validation", STAGE, item["title"], item)
    emit(
        writer,
        "artifact",
        STAGE,
        "证据处理结果已更新。",
        {
            "insights": findings,
            "insightVersion": "after-revision",
            "rejectedFindings": rejected,
        },
    )
    emit(writer, "stage_completed", STAGE, "证据审查完成。", {"passed": critic_passed})
    return {
        "criticPassed": critic_passed,
        "criticNotes": parsed.revisionInstructions or "",
        "findings": findings,
        "rejectedFindings": rejected,
        "validations": state["validations"] + validations,
    }


async def critic_failure(state, writer=None):
    writer = resolve_writer(writer)
    message = "洞察证据审查未通过，且已达到最大修订次数。"
    emit(writer, "error", STAGE, message, {"code": "EVIDENCE_VALIDATION_FAILED", "retryable": False})
    raise AgentRunError("EVIDENCE_VALIDATION_FAILED", message, stage=STAGE, retryable=False)
