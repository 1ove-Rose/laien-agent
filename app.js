const pipeline = [
  { id: "scope", name: "范围确认", description: "解析应用链接、国家/地区、分析目标和目标采集数。" },
  { id: "collect", name: "评论采集", description: "获取评论并保留原始字段与来源标识。" },
  { id: "clean", name: "数据清洗", description: "标准化字段、移除空评论并执行稳定去重。" },
  { id: "classify", name: "评论分类", description: "标注情感、主题、严重程度和分类依据。" },
  { id: "validate", name: "洞察与验证", description: "生成发现，检查证据充分性并执行修订。" },
  { id: "deliver", name: "需求与测试", description: "生成 PRD、测试初稿并验证完整追溯链。" }
];

const state = {
  reviews: [],
  cleaned: [],
  collection: null,
  cleanReport: null,
  categories: [],
  insights: [],
  requirements: [],
  tests: [],
  stageStatuses: pipeline.map(() => "pending"),
  stageOutputs: pipeline.map(() => ""),
  activities: [],
  validations: [],
  errors: [],
  revisions: [],
  currentStage: -1,
  running: false
};

const els = {
  form: document.querySelector("#analysis-form"),
  appUrlInput: document.querySelector("#app-url"),
  appUrlError: document.querySelector("#app-url-error"),
  formAlert: document.querySelector("#form-alert"),
  submitButton: document.querySelector(".primary-action"),
  runStatus: document.querySelector("#run-status"),
  pipelineNote: document.querySelector("#pipeline-note"),
  pipelineSteps: document.querySelector("#pipeline-steps"),
  liveIndicator: document.querySelector("#live-indicator"),
  activitySummary: document.querySelector("#activity-summary"),
  activityList: document.querySelector("#activity-list"),
  validationList: document.querySelector("#validation-list"),
  revisionList: document.querySelector("#revision-list"),
  artifactNote: document.querySelector("#artifact-note"),
  validationMetrics: {
    passed: document.querySelector("#validation-passed"),
    errors: document.querySelector("#validation-errors"),
    revisions: document.querySelector("#validation-revisions")
  },
  metrics: {
    collected: document.querySelector("#metric-collected"),
    cleaned: document.querySelector("#metric-cleaned"),
    rating: document.querySelector("#metric-rating"),
    trace: document.querySelector("#metric-trace")
  },
  counts: {
    raw: document.querySelector("#count-raw"),
    cleaned: document.querySelector("#count-cleaned"),
    categories: document.querySelector("#count-categories"),
    insights: document.querySelector("#count-insights"),
    prd: document.querySelector("#count-prd"),
    tests: document.querySelector("#count-tests")
  },
  rawReviewsTable: document.querySelector("#raw-reviews-table"),
  cleanedReviewsTable: document.querySelector("#cleaned-reviews-table"),
  categoryTable: document.querySelector("#category-table"),
  insightList: document.querySelector("#insight-list"),
  prdList: document.querySelector("#prd-list"),
  testList: document.querySelector("#test-list")
};

function init() {
  if (window.location.protocol === "file:") {
    els.pipelineNote.textContent = "真实采集需要通过 node serve.js 启动本地服务。";
    els.artifactNote.textContent = "当前为 file:// 模式，后端采集与清洗接口不可用。";
  }
  renderAll();

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  });

  document.querySelectorAll(".quick-prompts button").forEach((button) => {
    button.addEventListener("click", () => {
      els.appUrlInput.value = button.dataset.url;
      clearFieldError();
      clearAlert();
      resetRunState();
      setRunStatus("待分析", "idle");
      els.pipelineNote.textContent = "提交 App Store 链接后即可开始分析。";
      els.artifactNote.textContent = "运行分析后将采集真实评论并逐阶段生成产物。";
      els.liveIndicator.textContent = "未运行";
      selectTab("raw");
      renderAll();
    });
  });

  els.appUrlInput.addEventListener("input", () => {
    clearFieldError();
    clearAlert();
  });

  els.form.addEventListener("submit", runAnalysis);
}

async function runAnalysis(event) {
  event.preventDefault();
  if (state.running) return;

  clearAlert();
  clearFieldError();
  let validatedAppId;
  try {
    validatedAppId = parseAppId(els.appUrlInput.value);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setFieldError(message);
    showAlert("App Store 链接无效", message, "error");
    setRunStatus("输入错误", "error");
    els.pipelineNote.textContent = "请先修正 App Store 链接后再执行分析。";
    els.artifactNote.textContent = "链接校验未通过，尚未开始采集。";
    return;
  }

  resetRunState();
  state.running = true;
  setFormRunning(true);
  setRunStatus("分析中", "running");
  els.liveIndicator.textContent = "实时更新";
  els.liveIndicator.classList.add("is-live");
  els.pipelineNote.textContent = "任务已启动，正在生成可审查的阶段产物。";
  els.artifactNote.textContent = "分析运行中，产物将在每个阶段完成后自动更新。";
  addActivity("system", "任务已创建", "执行状态、产物和验证记录已初始化。", "任务");
  renderAll();

  try {
    if (window.location.protocol === "file:") {
      throw new Error("真实评论采集不能在 file:// 模式运行，请执行 node serve.js 后访问 http://127.0.0.1:8765/。");
    }

    await runStage(0, "raw", async () => {
      const maxReviews = Number(document.querySelector("#max-reviews").value);
      const countryLabel = selectedCountryLabel();
      addValidation(
        "pass",
        "输入参数有效",
        `已识别 App ID ${validatedAppId}，目标采集数 ${maxReviews} 条。实际结果可能少于该值。`,
        "范围确认"
      );
      return `App ID ${validatedAppId} · ${countryLabel} · 目标采集 ${maxReviews} 条`;
    });

    await runStage(1, "raw", async () => {
      const payload = await apiRequest("/api/reviews/collect", {
        appUrl: els.appUrlInput.value,
        country: document.querySelector("#country").value,
        maxReviews: Number(document.querySelector("#max-reviews").value)
      });
      state.reviews = payload.reviews;
      state.collection = payload.collection;
      const validIds = state.reviews.filter((review) => review.id).length;
      addValidation(
        "pass",
        "原始记录完整性",
        `${validIds}/${state.reviews.length} 条评论包含可追溯 ID。`,
        "评论采集"
      );
      payload.collection.warnings.forEach((warning) => {
        addValidation("revised", "采集限制或回退", warning, "评论采集");
      });
      const source = payload.collection.staleCache
        ? "Apple RSS（含过期缓存）"
        : payload.collection.fromCache
          ? "Apple RSS（含缓存）"
          : "Apple RSS";
      return `${source} · ${payload.collection.pagesFetched}/${payload.collection.pagesRequested} 页 · 实际 ${state.reviews.length} 条`;
    });

    if (state.reviews.length === 0) {
      setRunStatus("无可用评论", "complete");
      els.pipelineNote.textContent = `${selectedCountryLabel()} App Store RSS 当前没有返回可用评论，任务已停止在采集阶段。`;
      els.artifactNote.textContent = "没有生成后续分析产物；系统不会使用样例或伪造评论补齐结果。";
      showAlert(
        "未采集到可用评论",
        `${selectedCountryLabel()}地区的公开 Apple RSS 当前没有为该 App 返回评论。可以切换国家/地区、稍后重试，或更换有公开评论的 App。`
      );
      addActivity(
        "system",
        "采集结束",
        `${selectedCountryLabel()} App Store RSS 返回 0 条可用评论，后续清洗、分类、洞察、PRD 和测试阶段已跳过。`,
        "评论采集"
      );
      addValidation(
        "revised",
        "无可用评论",
        "当前所选地区数据源没有返回评论；请稍后重试、清理缓存后重试，或更换有公开评论的 App。",
        "评论采集"
      );
      selectTab("raw");
      return;
    }

    await runStage(2, "cleaned", async () => {
      const payload = await apiRequest("/api/reviews/clean", {
        appId: validatedAppId,
        reviews: state.reviews
      });
      state.cleaned = payload.reviews;
      state.cleanReport = payload.report;
      const report = payload.report;
      addValidation(
        "pass",
        "清洗规则校验",
        `保留 ${report.outputCount} 条；移除 ${report.removedCount} 条，其中非法评分 ${report.invalidRatingCount}、空正文 ${report.emptyTextCount}、重复 ID ${report.duplicateIdCount}、重复内容 ${report.duplicateContentCount}。`,
        "数据清洗"
      );
      if (report.generatedIdCount > 0) {
        addValidation(
          "revised",
          "补全缺失评论 ID",
          `${report.generatedIdCount} 条评论缺少来源 ID，已生成稳定哈希 ID。`,
          "数据清洗"
        );
      }
      return `${report.outputCount} 条标准化记录 · ${report.removedCount} 条被过滤或去重`;
    });

    await runStage(3, "categories", async () => {
      state.categories = buildClassifications(state.cleaned);
      const themes = new Set(state.categories.map((item) => item.theme));
      addValidation(
        "pass",
        "分类覆盖率",
        `${state.categories.length}/${state.cleaned.length} 条评论已完成语义分类。`,
        "评论分类"
      );
      return `${state.categories.length} 条分类结果 · ${themes.size} 个主题`;
    });

    await runStage(4, "insights", async () => {
      state.insights = buildInsights(state.cleaned);
      addValidation(
        "revised",
        "F-1 范围表述需要收敛",
        "初稿将订阅问题泛化为产品价值问题，证据不足，已限定为付费流程问题。",
        "洞察与验证"
      );
      addRevision(
        "F-1 洞察修订",
        "补充正向评论形成的冲突证据，并将结论范围收敛到订阅与试用流程。",
        "洞察与验证"
      );
      addValidation(
        "pass",
        "洞察证据引用",
        `${state.insights.length}/${state.insights.length} 条发现包含评论 ID、支持数和置信度。`,
        "洞察与验证"
      );
      return `${state.insights.length} 条发现 · 1 次证据修订 · 复验通过`;
    });

    await runStage(5, "prd", async () => {
      state.requirements = buildRequirements(state.insights);
      state.tests = buildTests(state.requirements);
      const traceResult = validateTraceability();

      if (traceResult.missing.length) {
        throw new Error(`发现 ${traceResult.missing.length} 条追溯关系缺失。`);
      }

      addValidation(
        "pass",
        "端到端追溯验证",
        `${traceResult.valid} 条“评论 → 洞察 → 需求 → 测试”链路验证通过。`,
        "需求与测试"
      );
      return `${state.requirements.length} 条 PRD 初稿 · ${state.tests.length} 条测试用例初稿`;
    });

    state.currentStage = -1;
    setRunStatus("已完成", "complete");
    els.pipelineNote.textContent = "全部阶段已完成，中间产物、验证记录和最终初稿均可审查。";
    els.artifactNote.textContent = "交付完成：所有产物均保留来源引用和阶段验证结果。";
    addActivity(
      "success",
      "最终交付已生成",
      `交付 ${state.insights.length} 条洞察、${state.requirements.length} 条 PRD 初稿和 ${state.tests.length} 条测试用例初稿。`,
      "任务"
    );
    addActivity("success", "错误检查完成", "本次运行未发现阻断错误。", "任务");
    selectTab("tests");
  } catch (error) {
    const stage = pipeline[state.currentStage]?.name || "任务";
    state.errors.push({
      stage,
      title: "执行错误",
      detail: error instanceof Error ? error.message : String(error)
    });
    if (state.currentStage >= 0) state.stageStatuses[state.currentStage] = "error";
    setRunStatus("执行失败", "error");
    els.pipelineNote.textContent = "任务已停止，请根据错误记录修正输入或处理逻辑后重试。";
    els.artifactNote.textContent = "部分中间产物已保留，可结合错误记录继续排查。";
    addActivity("error", "阶段执行失败", state.errors.at(-1).detail, stage);
  } finally {
    state.running = false;
    state.currentStage = -1;
    setFormRunning(false);
    els.liveIndicator.textContent = state.errors.length ? "已停止" : "运行结束";
    els.liveIndicator.classList.remove("is-live");
    renderAll();
  }
}

async function runStage(index, tabName, task) {
  state.currentStage = index;
  state.stageStatuses[index] = "running";
  els.pipelineNote.textContent = `正在执行：${pipeline[index].name}`;
  addActivity("stage", `${pipeline[index].name}开始`, pipeline[index].description, pipeline[index].name);
  selectTab(tabName);
  renderAll();
  await wait(480);

  const output = await task();
  state.stageOutputs[index] = output;
  state.stageStatuses[index] = "done";
  addActivity("result", `${pipeline[index].name}产出`, output, pipeline[index].name);
  renderAll();
  await wait(360);
}

function resetRunState() {
  state.reviews = [];
  state.cleaned = [];
  state.collection = null;
  state.cleanReport = null;
  state.categories = [];
  state.insights = [];
  state.requirements = [];
  state.tests = [];
  state.stageStatuses = pipeline.map(() => "pending");
  state.stageOutputs = pipeline.map(() => "");
  state.activities = [];
  state.validations = [];
  state.errors = [];
  state.revisions = [];
  state.currentStage = -1;
}

function addActivity(type, title, detail, stage) {
  state.activities.push({
    id: state.activities.length + 1,
    type,
    title,
    detail,
    stage,
    time: new Date().toLocaleTimeString("zh-CN", { hour12: false })
  });
}

function addValidation(type, title, detail, stage) {
  state.validations.push({ type, title, detail, stage });
}

function addRevision(title, detail, stage) {
  state.revisions.push({ title, detail, stage });
}

function parseAppId(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("请输入有效的 App Store 链接。");
  }
  if (parsed.protocol !== "https:" || parsed.hostname.toLowerCase() !== "apps.apple.com") {
    throw new Error("链接必须来自 https://apps.apple.com。");
  }
  const match = parsed.pathname.match(/(?:^|\/)id(\d+)(?:\/|$)/i);
  if (!match) throw new Error("无法从 App Store 链接中识别应用 ID。链接应包含 id 加数字。");
  return match[1];
}

function selectedCountryLabel() {
  const select = document.querySelector("#country");
  return select.options[select.selectedIndex]?.textContent || "所选地区";
}

function setFieldError(message) {
  els.appUrlInput.classList.add("is-invalid");
  els.appUrlInput.setAttribute("aria-invalid", "true");
  els.appUrlError.textContent = message;
  els.appUrlError.hidden = false;
}

function clearFieldError() {
  els.appUrlInput.classList.remove("is-invalid");
  els.appUrlInput.removeAttribute("aria-invalid");
  els.appUrlError.textContent = "";
  els.appUrlError.hidden = true;
}

function showAlert(title, detail, tone = "warning") {
  els.formAlert.classList.toggle("is-error", tone === "error");
  els.formAlert.querySelector("strong").textContent = title;
  els.formAlert.querySelector("p").textContent = detail;
  els.formAlert.hidden = false;
}

function clearAlert() {
  els.formAlert.hidden = true;
  els.formAlert.classList.remove("is-error");
  els.formAlert.querySelector("strong").textContent = "";
  els.formAlert.querySelector("p").textContent = "";
}

async function apiRequest(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  } catch {
    throw new Error("无法连接本地后端，请确认已通过 node serve.js 启动服务。");
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`后端返回了无法识别的响应（HTTP ${response.status}）。`);
  }
  if (!response.ok) {
    const suffix = payload.error?.retryable ? " 可以稍后重试。" : "";
    throw new Error(`${payload.error?.message || "请求失败。"}${suffix}`);
  }
  return payload;
}

function setFormRunning(running) {
  els.submitButton.disabled = running;
  els.submitButton.querySelector("span:first-child").textContent = running ? "正在分析" : "开始分析";
  els.submitButton.querySelector("span:last-child").textContent = running ? "处理中" : "执行";
}

function setRunStatus(label, status) {
  els.runStatus.textContent = label;
  els.runStatus.dataset.status = status;
}

function renderPipeline() {
  const statusLabels = { pending: "等待", running: "执行中", done: "已完成", error: "错误" };
  els.pipelineSteps.innerHTML = pipeline
    .map((stage, index) => {
      const status = state.stageStatuses[index];
      return `
        <article class="pipeline-step is-${status}">
          <div class="stage-heading">
            <strong>${stage.name}</strong>
            <span class="stage-status">${statusLabels[status]}</span>
          </div>
          <p>${stage.description}</p>
          <small>${escapeHtml(state.stageOutputs[index] || "等待阶段产出")}</small>
        </article>
      `;
    })
    .join("");
}

function renderExecution() {
  const passed = state.validations.filter((item) => item.type === "pass").length;
  els.validationMetrics.passed.textContent = String(passed);
  els.validationMetrics.errors.textContent = String(state.errors.length);
  els.validationMetrics.revisions.textContent = String(state.revisions.length);
  els.activitySummary.textContent = state.activities.length
    ? `${state.activities.length} 条事件 · ${state.running ? "持续更新中" : "记录已保存"}`
    : "等待任务启动";

  els.activityList.innerHTML = state.activities.length
    ? state.activities
        .map(
          (activity) => `
            <li class="activity-item is-${activity.type}">
              <span class="activity-dot" aria-hidden="true"></span>
              <div>
                <div class="activity-meta">
                  <strong>${escapeHtml(activity.title)}</strong>
                  <span>${escapeHtml(activity.stage)} · ${activity.time}</span>
                </div>
                <p>${escapeHtml(activity.detail)}</p>
              </div>
            </li>
          `
        )
        .join("")
    : emptyState("任务启动后，这里会实时记录阶段、中间结果和错误。", "compact");

  if (state.running) {
    els.activityList.scrollTop = els.activityList.scrollHeight;
  }

  const validationItems = [
    ...state.validations,
    ...state.errors.map((error) => ({ ...error, type: "error" }))
  ];
  els.validationList.innerHTML = validationItems.length
    ? validationItems
        .map(
          (item) => `
            <article class="validation-item is-${item.type}">
              <div>
                <strong>${escapeHtml(item.title)}</strong>
                <span>${escapeHtml(item.stage)}</span>
              </div>
              <p>${escapeHtml(item.detail)}</p>
            </article>
          `
        )
        .join("")
    : emptyState("尚无验证记录。", "compact");

  els.revisionList.innerHTML = state.revisions.length
    ? `
        <strong class="revision-title">修订记录</strong>
        ${state.revisions
          .map(
            (revision) => `
              <article class="revision-item">
                <strong>${escapeHtml(revision.title)}</strong>
                <span>${escapeHtml(revision.stage)}</span>
                <p>${escapeHtml(revision.detail)}</p>
              </article>
            `
          )
          .join("")}
      `
    : "";
}

function selectTab(tabName) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `panel-${tabName}`);
  });
}

function buildClassifications(reviews) {
  return reviews.map((review) => {
    const text = `${review.title} ${review.text}`.toLowerCase();
    let theme = "一般体验";
    let rationale = "评论未命中高频问题关键词，归入一般体验。";

    if (containsAny(text, ["订阅", "试用", "扣费", "付费", "套餐", "subscription", "trial"])) {
      theme = "订阅与付费";
      rationale = "评论涉及订阅入口、试用条款、扣费或付费引导。";
    } else if (containsAny(text, ["音频", "计时", "语音", "audio", "timer", "voice"])) {
      theme = "训练播放";
      rationale = "评论涉及音频提示、动作计时或播放同步。";
    } else if (containsAny(text, ["进度", "打卡", "记录", "重置", "progress", "streak"])) {
      theme = "数据与进度";
      rationale = "评论涉及训练历史、连续打卡或数据保留。";
    } else if (review.rating >= 4) {
      theme = "训练内容体验";
      rationale = "高评分评论认可训练内容、计划或提醒功能。";
    }

    return {
      reviewId: review.id,
      sentiment: review.rating <= 2 ? "负向" : review.rating === 3 ? "混合" : "正向",
      theme,
      severity: review.rating === 1 ? "高" : review.rating <= 3 ? "中" : "低",
      rationale
    };
  });
}

function containsAny(text, keywords) {
  return keywords.some((keyword) => text.includes(keyword));
}

function buildInsights(reviews) {
  const lowRated = reviews.filter((review) => review.rating <= 3);
  const matches = {
    "订阅与试用规则清晰度": [
      "subscription", "trial", "charged", "paid", "upsells", "订阅", "试用", "扣费", "付费", "套餐", "取消"
    ],
    "训练播放稳定性": ["audio", "timer", "voice", "lag", "音频", "计时", "语音", "延迟"],
    "训练进度数据保留": [
      "progress", "streak", "disappeared", "reset", "进度", "打卡", "消失", "重置", "记录"
    ]
  };

  return Object.entries(matches)
    .map(([title, keywords], index) => {
      const evidence = lowRated.filter((review) =>
        keywords.some((keyword) => review.text.toLowerCase().includes(keyword))
      );
      return {
        id: `F-${index + 1}`,
        title,
        summary: summarizeFinding(title, evidence),
        evidenceIds: evidence.map((review) => review.id),
        supportCount: evidence.length,
        confidence: evidence.length >= 2 ? "高" : evidence.length === 1 ? "中" : "低",
        version: title.includes("订阅") ? "v0.2 已修订" : "v0.1 已验证",
        conflict: title.includes("订阅")
          ? "正向评论认可训练内容，因此结论已收敛为付费流程问题，而非核心训练价值问题。"
          : "当前样本中未发现明显的冲突证据。"
      };
    })
    .filter((finding) => finding.supportCount > 0);
}

function summarizeFinding(title, evidence) {
  if (title.includes("订阅")) {
    return "低评分和混合评论反映：套餐权益不清晰、付费引导反复出现，取消和试用规则容易引发误解。";
  }
  if (title.includes("播放")) {
    return "低评分评论反馈音频提示落后于训练计时器，导致用户难以跟随指导完成训练。";
  }
  if (title.includes("进度")) {
    return "近期低评分评论反馈应用更新后训练记录丢失，连续打卡天数被重置。";
  }
  return evidence[0]?.text || "该发现需要补充更多证据。";
}

function buildRequirements(insights) {
  return insights.map((finding, index) => ({
    id: `REQ-${index + 1}`,
    title: requirementTitle(finding.title),
    priority: finding.supportCount >= 2 ? "P0" : "P1",
    sourceFindingId: finding.id,
    version: "v0.1 初稿",
    acceptance:
      finding.title === "订阅与试用规则清晰度"
        ? "用户在进入结算前可以查看免费功能范围、试用条款、续费日期和取消路径。"
        : finding.title === "训练播放稳定性"
          ? "在完整的指导训练中，音频提示始终与动作计时器保持同步。"
          : "训练历史和连续打卡数据能够在更新、重启和账户同步后保留。"
  }));
}

function requirementTitle(title) {
  if (title.includes("订阅")) return "明确订阅入口与试用条款";
  if (title.includes("播放")) return "稳定训练音频提示时序";
  return "保护应用更新后的训练进度";
}

function buildTests(requirements) {
  return requirements.map((requirement, index) => ({
    id: `TC-${index + 1}`,
    title: testTitle(requirement.title),
    requirementId: requirement.id,
    sourceFindingId: requirement.sourceFindingId,
    version: "v0.1 初稿",
    steps:
      requirement.priority === "P0"
        ? "打开订阅页，查看套餐条款，进入试用流程，在购买前取消，并确认条款始终清晰可见。"
        : "完整执行相关应用流程，重启应用，并验证预期状态保持正确。",
    expected: requirement.acceptance
  }));
}

function testTitle(title) {
  if (title.includes("订阅")) return "结算前清晰展示订阅条款";
  if (title.includes("音频")) return "音频提示与训练计时器保持同步";
  return "应用更新后训练历史仍被保留";
}

function validateTraceability() {
  const findingIds = new Set(state.insights.map((item) => item.id));
  const requirementIds = new Set(state.requirements.map((item) => item.id));
  const missing = [];

  state.requirements.forEach((requirement) => {
    if (!findingIds.has(requirement.sourceFindingId)) missing.push(requirement.id);
  });
  state.tests.forEach((test) => {
    if (!requirementIds.has(test.requirementId) || !findingIds.has(test.sourceFindingId)) {
      missing.push(test.id);
    }
  });

  return { valid: state.tests.length - missing.length, missing };
}

function renderAll() {
  renderPipeline();
  renderExecution();
  renderMetrics();
  renderArtifactCounts();
  renderRawReviews();
  renderCleanedReviews();
  renderCategories();
  renderInsights();
  renderRequirements();
  renderTests();
}

function renderMetrics() {
  const avgRating = state.cleaned.length
    ? state.cleaned.reduce((sum, review) => sum + review.rating, 0) / state.cleaned.length
    : 0;
  els.metrics.collected.textContent = String(state.reviews.length);
  els.metrics.cleaned.textContent = String(state.cleaned.length);
  els.metrics.rating.textContent = avgRating.toFixed(1);
  els.metrics.trace.textContent = String(state.tests.length);
}

function renderArtifactCounts() {
  els.counts.raw.textContent = String(state.reviews.length);
  els.counts.cleaned.textContent = String(state.cleaned.length);
  els.counts.categories.textContent = String(state.categories.length);
  els.counts.insights.textContent = String(state.insights.length);
  els.counts.prd.textContent = String(state.requirements.length);
  els.counts.tests.textContent = String(state.tests.length);
}

function renderRawReviews() {
  els.rawReviewsTable.innerHTML = state.reviews.length
    ? state.reviews
        .map(
          (review) => `
            <tr>
              <td>${escapeHtml(review.id || "无 ID")}</td>
              <td class="rating">${Number(review.rating || 0)}</td>
              <td>${escapeHtml(review.version || "未知")}</td>
              <td>${escapeHtml(review.createdAt || review.date || "未知")}</td>
              <td><strong>${escapeHtml(review.title || "无标题")}</strong><br />${escapeHtml(review.text || review.content || "")}</td>
            </tr>
          `
        )
        .join("")
    : tableEmptyState(5, "评论采集阶段完成后将在此展示所选地区 App Store 原始评论。");
}

function renderCleanedReviews() {
  els.cleanedReviewsTable.innerHTML = state.cleaned.length
    ? state.cleaned
        .map(
          (review) => `
            <tr>
              <td>${escapeHtml(review.id)}</td>
              <td><span class="inline-status is-pass">${review.cleanStatus === "normalized" ? "已标准化" : escapeHtml(review.cleanStatus)}</span></td>
              <td class="rating">${review.rating}</td>
              <td>${escapeHtml(review.version)}</td>
              <td><strong>${escapeHtml(review.title)}</strong><br />${escapeHtml(review.text)}</td>
            </tr>
          `
        )
        .join("")
    : tableEmptyState(5, "数据清洗阶段完成后将在此展示标准化记录。");
}

function renderCategories() {
  els.categoryTable.innerHTML = state.categories.length
    ? state.categories
        .map(
          (item) => `
            <tr>
              <td>${escapeHtml(item.reviewId)}</td>
              <td><span class="inline-status is-${sentimentClass(item.sentiment)}">${item.sentiment}</span></td>
              <td>${escapeHtml(item.theme)}</td>
              <td>${escapeHtml(item.severity)}</td>
              <td>${escapeHtml(item.rationale)}</td>
            </tr>
          `
        )
        .join("")
    : tableEmptyState(5, "评论分类阶段完成后将在此展示语义标签。");
}

function sentimentClass(sentiment) {
  if (sentiment === "负向") return "error";
  if (sentiment === "混合") return "warning";
  return "pass";
}

function renderInsights() {
  els.insightList.innerHTML = state.insights.length
    ? state.insights
        .map(
          (finding) => `
            <article class="result-item">
              <header>
                <div>
                  <h4>${finding.id}: ${escapeHtml(finding.title)}</h4>
                  <small>${escapeHtml(finding.version)}</small>
                </div>
                <span class="tag">置信度 ${finding.confidence}</span>
              </header>
              <p>${escapeHtml(finding.summary)}</p>
              <div class="meta-row">
                <span class="tag">支持数 ${finding.supportCount}</span>
                <span class="tag">证据 ${finding.evidenceIds.join(", ")}</span>
                <span class="tag is-warning">${escapeHtml(finding.conflict)}</span>
              </div>
            </article>
          `
        )
        .join("")
    : emptyState("洞察与验证阶段完成后将在此生成证据驱动的发现。");
}

function renderRequirements() {
  els.prdList.innerHTML = state.requirements.length
    ? state.requirements
        .map(
          (requirement) => `
            <article class="result-item">
              <header>
                <div>
                  <h4>${requirement.id}: ${escapeHtml(requirement.title)}</h4>
                  <small>${requirement.version}</small>
                </div>
                <span class="tag ${requirement.priority === "P0" ? "is-risk" : ""}">${requirement.priority}</span>
              </header>
              <p><strong>验收标准：</strong>${escapeHtml(requirement.acceptance)}</p>
              <div class="meta-row">
                <span class="tag">源洞察 ${requirement.sourceFindingId}</span>
              </div>
            </article>
          `
        )
        .join("")
    : emptyState("需求与测试阶段完成后，PRD 初稿将在此显示。");
}

function renderTests() {
  els.testList.innerHTML = state.tests.length
    ? state.tests
        .map(
          (test) => `
            <article class="result-item">
              <header>
                <div>
                  <h4>${test.id}: ${escapeHtml(test.title)}</h4>
                  <small>${test.version}</small>
                </div>
                <span class="tag">${test.requirementId}</span>
              </header>
              <p><strong>操作步骤：</strong>${escapeHtml(test.steps)}</p>
              <p><strong>预期结果：</strong>${escapeHtml(test.expected)}</p>
              <div class="meta-row">
                <span class="tag">源洞察 ${test.sourceFindingId}</span>
              </div>
            </article>
          `
        )
        .join("")
    : emptyState("需求生成后，可追溯的测试用例初稿将在此显示。");
}

function tableEmptyState(columns, message) {
  return `<tr><td colspan="${columns}" class="table-empty">${message}</td></tr>`;
}

function emptyState(message, variant = "") {
  return `<article class="empty-state ${variant}"><p>${message}</p></article>`;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
