const $ = (selector) => document.querySelector(selector);
const tokenInput = $("#token");
const toast = $("#toast");
let timer;

tokenInput.value = sessionStorage.getItem("webhookToken") || "";

function notify(message, error = false) {
  toast.textContent = message;
  toast.className = `toast show${error ? " error" : ""}`;
  setTimeout(() => { toast.className = "toast"; }, 2500);
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

function render(data) {
  $("#total").textContent = data.total;
  $("#success").textContent = data.success;
  $("#failed").textContent = data.failed;
  $("#processing").textContent = data.processing;
  $("#duration").textContent = `${(data.avg_duration_ms / 1000).toFixed(1)}s`;
  $("#updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", {hour12:false})}`;
  const rows = data.recent || [];
  $("#jobs").replaceChildren(...(rows.length ? rows.map((job) => {
    const row = document.createElement("tr");
    const values = [job.status, job.video_name || "未命名", job.record_id || "—",
      job.duration_ms == null ? "—" : `${(job.duration_ms / 1000).toFixed(1)}s`,
      formatTime(job.updated_at), job.error_message || (job.status === "success" ? "已返回最终提示词" : "处理中")];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 0) cell.className = `state state-${job.status}`;
      row.appendChild(cell);
    });
    return row;
  }) : [Object.assign(document.createElement("tr"), { innerHTML: '<td colspan="6" class="empty">暂无请求</td>' })]);
}

async function refresh(showError = false) {
  const token = tokenInput.value.trim();
  try {
    const health = await fetch("/healthz");
    if (!health.ok) throw new Error("服务异常");
    $("#statusDot").className = "status-dot active";
    $("#statusText").textContent = "服务在线";
    if (!token) return;
    const response = await fetch("/api/status", { headers: { Authorization: `Bearer ${token}` } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "鉴权失败");
    render(payload);
  } catch (error) {
    $("#statusDot").className = "status-dot";
    $("#statusText").textContent = error.message;
    if (showError) notify(error.message, true);
  }
}

$("#connect").addEventListener("click", () => {
  const token = tokenInput.value.trim();
  if (!token) return notify("请输入 Webhook Token", true);
  sessionStorage.setItem("webhookToken", token);
  refresh(true);
});

refresh();
timer = setInterval(refresh, 5000);
