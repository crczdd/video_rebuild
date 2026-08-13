const $ = (selector) => document.querySelector(selector);

const elements = {
  interval: $("#interval"),
  saveInterval: $("#saveInterval"),
  start: $("#startSchedule"),
  stop: $("#stopSchedule"),
  runNow: $("#runNow"),
  dryRun: $("#dryRun"),
  immediate: $("#runImmediately"),
  statusDot: $("#statusDot"),
  statusText: $("#statusText"),
  savedLabel: $("#savedLabel"),
  nextRun: $("#nextRun"),
  eventList: $("#eventList"),
  errorBox: $("#errorBox"),
  lastFinished: $("#lastFinished"),
  toast: $("#toast"),
};

let initialLoad = true;
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "操作失败");
  return payload;
}

function showToast(message, isError = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast show${isError ? " error" : ""}`;
  toastTimer = setTimeout(() => { elements.toast.className = "toast"; }, 2600);
}

function localTime(iso, includeSeconds = false) {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
    hour12: false,
  });
}

function render(status) {
  if (initialLoad) {
    elements.interval.value = status.interval_seconds;
    initialLoad = false;
  }

  elements.statusDot.className = "status-dot";
  if (status.running) {
    elements.statusDot.classList.add("running");
    elements.statusText.textContent = `正在${status.run_mode}`;
  } else if (status.enabled) {
    elements.statusDot.classList.add("active");
    elements.statusText.textContent = "定时运行中";
  } else {
    elements.statusText.textContent = "定时已停止";
  }

  elements.savedLabel.textContent = `当前 ${status.interval_seconds} 秒`;
  elements.nextRun.textContent = status.enabled ? localTime(status.next_run_at, true) : "未启动";
  elements.lastFinished.textContent = status.last_finished_at
    ? `上次完成 ${localTime(status.last_finished_at, true)}`
    : "等待首次执行";

  const result = status.last_result || {};
  $("#metricDingtalkRead").textContent = result.dingtalk_read_success
    ? `成功 · ${result.fetched} 条`
    : "—";
  $("#metricLlm").textContent = result.dry_run
    ? "Dry-run 未调用"
    : result.llm_success !== undefined
      ? `成功 ${result.llm_success} / 失败 ${result.llm_failed}`
      : "—";
  $("#metricDingtalkWrite").textContent = result.dry_run
    ? "Dry-run 未写入"
    : result.dingtalk_update_success !== undefined
      ? `成功 ${result.dingtalk_update_success} / 失败 ${result.dingtalk_update_failed}`
      : "—";
  $("#metricOutcome").textContent = result.skipped !== undefined
    ? `${result.skipped} / ${result.failed}`
    : "—";

  const disabled = status.running;
  elements.runNow.disabled = disabled;
  elements.dryRun.disabled = disabled;
  elements.start.disabled = disabled || status.enabled;
  elements.stop.disabled = !status.enabled;

  const failures = result.failure_details || [];
  const errorLines = [];
  if (status.last_error) errorLines.push(`流程错误：${status.last_error}`);
  failures.forEach((detail) => errorLines.push(`记录失败：${detail}`));
  elements.errorBox.hidden = errorLines.length === 0;
  elements.errorBox.textContent = errorLines.join("\n");

  elements.eventList.replaceChildren();
  [...status.events].reverse().forEach((entry) => {
    const splitAt = entry.indexOf("  ");
    const item = document.createElement("li");
    const time = document.createElement("time");
    const message = document.createElement("span");
    time.textContent = splitAt > -1 ? entry.slice(0, splitAt) : "—";
    message.textContent = splitAt > -1 ? entry.slice(splitAt + 2) : entry;
    item.append(time, message);
    elements.eventList.append(item);
  });
}

async function refresh() {
  try {
    render(await api("/api/status"));
  } catch (error) {
    elements.statusText.textContent = "连接失败";
  }
}

async function act(path, body, successMessage) {
  try {
    const status = await api(path, { method: "POST", body: JSON.stringify(body || {}) });
    render(status);
    showToast(successMessage);
  } catch (error) {
    showToast(error.message, true);
  }
}

elements.saveInterval.addEventListener("click", async () => {
  const seconds = Number(elements.interval.value);
  try {
    const status = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ interval_seconds: seconds }),
    });
    render(status);
    showToast(`已保存：每 ${seconds} 秒执行一次`);
  } catch (error) {
    showToast(error.message, true);
  }
});

document.querySelectorAll("[data-seconds]").forEach((button) => {
  button.addEventListener("click", () => { elements.interval.value = button.dataset.seconds; });
});

elements.start.addEventListener("click", () => act(
  "/api/start",
  { run_immediately: elements.immediate.checked },
  "定时任务已启动",
));
elements.stop.addEventListener("click", () => act("/api/stop", {}, "定时任务已停止"));
elements.runNow.addEventListener("click", () => act("/api/run", { dry_run: false }, "正式任务已开始"));
elements.dryRun.addEventListener("click", () => act("/api/run", { dry_run: true }, "安全检查已开始"));

refresh();
setInterval(refresh, 2000);
