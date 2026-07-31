const uploadForm = document.querySelector("#uploadForm");
const excelFile = document.querySelector("#excelFile");
const fileName = document.querySelector("#fileName");
const submitButton = document.querySelector("#submitButton");
const statusMessage = document.querySelector("#statusMessage");
const metricsPanel = document.querySelector("#metrics");
const resultRows = document.querySelector("#resultRows");
const reviewRows = document.querySelector("#reviewRows");
const reviewCount = document.querySelector("#reviewCount");
const actionFilter = document.querySelector("#actionFilter");
const downloadLink = document.querySelector("#downloadLink");

const DETAIL_COLUMN_COUNT = 11;
let latestRows = [];

const actionText = {
  approved: "自动通过",
  rejected: "自动驳回",
  needs_more_evidence: "证据不足",
  needs_human_review: "人工复核",
};

excelFile.addEventListener("change", () => {
  fileName.textContent = excelFile.files[0]?.name || "仅支持 .xlsx";
});

actionFilter.addEventListener("change", () => {
  renderDecisionRows(latestRows);
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!excelFile.files.length) {
    setStatus("请选择一个 .xlsx 文件", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", excelFile.files[0]);

  submitButton.disabled = true;
  setStatus("审计处理中，请稍候", false);
  clearTables();

  try {
    const response = await fetch("/api/audit/upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "审计处理失败");
    }

    latestRows = buildDecisionRows(data);
    renderMetrics(data.metrics || {});
    renderDecisionRows(latestRows);
    renderReviewRows(data.review_tasks || []);
    updateDownloadLink(data.download_url);
    setStatus(`批次 ${data.batch_id} 已完成`, false);
  } catch (error) {
    setStatus(error.message, true);
    renderEmpty(resultRows, DETAIL_COLUMN_COUNT, "暂无审计结果");
    renderEmpty(reviewRows, 5, "暂无人工复核任务");
  } finally {
    submitButton.disabled = false;
  }
});

function buildDecisionRows(data) {
  const caseMap = new Map((data.cases || []).map((auditCase) => [auditCase.case_id, auditCase]));

  return (data.decisions || []).map((decision) => {
    const auditCase = caseMap.get(decision.case_id) || {};
    return {
      ...auditCase,
      ...decision,
    };
  });
}

function renderMetrics(metrics) {
  const cards = [
    ["总数", metrics.total_count ?? 0],
    ["自动处理", metrics.auto_handled_count ?? 0],
    ["人工复核", metrics.review_count ?? 0],
    ["自动处理率", formatRate(metrics.auto_handled_rate)],
    ["复核率", formatRate(metrics.review_rate)],
  ];

  metricsPanel.innerHTML = cards
    .map(
      ([label, value]) => `
        <article class="metric">
          <div class="metric-label">${escapeHtml(label)}</div>
          <div class="metric-value">${escapeHtml(String(value))}</div>
        </article>
      `,
    )
    .join("");
}

function renderDecisionRows(rows) {
  const selectedAction = actionFilter.value;
  const visibleRows = selectedAction ? rows.filter((row) => row.action === selectedAction) : rows;

  if (!visibleRows.length) {
    renderEmpty(resultRows, DETAIL_COLUMN_COUNT, "暂无审计结果");
    return;
  }

  resultRows.innerHTML = visibleRows
    .map(
      (row) => `
        <tr>
          <td>${cellText(row.employee_name)}</td>
          <td>${cellText(row.company_name)}</td>
          <td>${cellHtml(renderWebsite(row.website_url))}</td>
          <td>${cellText(row.entered_level1)}</td>
          <td>${cellText(row.entered_subcategory)}</td>
          <td>${cellHtml(`<span class="badge ${escapeHtml(row.action || "")}">${escapeHtml(actionText[row.action] || row.action || "")}</span>`)}</td>
          <td>${cellText(row.confidence ?? "")}</td>
          <td>${cellText(row.risk_score ?? "")}</td>
          <td>${cellText(row.needs_review ? "是" : "否")}</td>
          <td>${cellText(row.reason, "reason-cell")}</td>
          <td>${cellText(row.suggestion, "suggestion-cell")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderReviewRows(tasks) {
  reviewCount.textContent = `${tasks.length} 条`;

  if (!tasks.length) {
    renderEmpty(reviewRows, 5, "暂无人工复核任务");
    return;
  }

  reviewRows.innerHTML = tasks
    .map(
      (task) => `
        <tr>
          <td>${escapeHtml(task.task_id || "")}</td>
          <td>${escapeHtml(task.case_id || "")}</td>
          <td>${escapeHtml(task.priority || "")}</td>
          <td>${cellText(task.reason, "review-reason-cell")}</td>
          <td>${escapeHtml(task.status || "")}</td>
        </tr>
      `,
    )
    .join("");
}

function updateDownloadLink(downloadUrl) {
  if (!downloadUrl) {
    downloadLink.classList.add("is-hidden");
    return;
  }

  downloadLink.href = downloadUrl;
  downloadLink.classList.remove("is-hidden");
}

function clearTables() {
  metricsPanel.innerHTML = "";
  latestRows = [];
  renderEmpty(resultRows, DETAIL_COLUMN_COUNT, "审计处理中");
  renderEmpty(reviewRows, 5, "审计处理中");
  reviewCount.textContent = "0 条";
  downloadLink.classList.add("is-hidden");
}

function renderEmpty(target, colspan, text) {
  target.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">${escapeHtml(text)}</td></tr>`;
}

function renderWebsite(value) {
  if (!value) {
    return "";
  }

  const safeValue = escapeHtml(value);
  return `<a href="${safeValue}" target="_blank" rel="noreferrer">${safeValue}</a>`;
}

function cellText(value, extraClass = "") {
  return cellHtml(escapeHtml(value ?? ""), extraClass);
}

function cellHtml(innerHtml, extraClass = "") {
  const className = extraClass ? `cell-content ${extraClass}` : "cell-content";
  return `<div class="${className}">${innerHtml}</div>`;
}

function formatRate(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "0%";
  }

  return `${Math.round(Number(value) * 100)}%`;
}

function setStatus(message, isError) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
