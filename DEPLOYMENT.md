# 阿里云 Docker Compose 部署

## 架构

钉钉 AI 表格自动化通过 HTTP POST 调用本服务。服务同步调用 LLM，在钉钉 150 秒上限内返回 JSON；钉钉后续“更新记录”节点引用 `data.final_prompt` 写回当前行。

```text
DingTalk -> Nginx:80 -> FastAPI:8000 -> LLM
                               -> SQLite /data/jobs.db
```

生产主流程没有轮询、Redis、Celery、Chrome、Selenium、Playwright 或 9222。

## 钉钉 HTTP 节点

- 方法：`POST`
- URL：`http://39.105.209.143/api/v1/video-remake/generate`
- Header：`Authorization: Bearer <WEBHOOK_AUTH_TOKEN>`
- Header：`Content-Type: application/x-www-form-urlencoded`（钉钉多行文本推荐）
- 勾选：等待响应
- HTTP节点最长等待：150秒；服务端LLM超时120秒，Nginx上限145秒

钉钉 AI 表格的多行提示词可能包含换行和引号，直接拼接 JSON 容易产生
`JSON decode error`。HTTP 节点推荐选择 `x-www-form-urlencoded`，逐项添加：

```text
record_id          = 当前记录ID
视频名称           = 当前行视频名称
nanophoto提示词    = 当前行拉片笔记
台词修改           = 当前行台词修改
产品修改           = 当前行产品修改
人物修改           = 当前行人物修改
背景修改           = 当前行背景修改
痛点变化           = 当前行痛点变化
特殊镜头描述       = 当前行特殊镜头描述
修改最终建议       = 当前行修改最终建议
```

`Content-Type` 由 HTTP 节点自动设置时，不必手工添加。请求参数仍留空。

服务端继续兼容 `application/json`。合法 JSON 请求示例：

`视频链接`不是必填字段；视频作为钉钉附件保存时，不需要发送给本服务。

```json
{
  "request_id": "自动化执行ID，若无法取得可不传",
  "record_id": "当前记录ID",
  "视频名称": "当前行视频名称",
  "nanophoto提示词": "当前行nanophoto提示词",
  "台词修改": "当前行台词修改",
  "产品修改": "当前行产品修改",
  "人物修改": "当前行人物修改",
  "背景修改": "当前行背景修改",
  "痛点变化": "当前行痛点变化",
  "特殊镜头描述": "当前行特殊镜头描述",
  "修改最终建议": "当前行修改最终建议"
}
```

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "request_id": "...",
    "record_id": "...",
    "final_prompt": "...",
    "cached": false
  }
}
```

“更新记录”节点把 `data.final_prompt` 写入“最终提示词”。

### 纯文本端点（钉钉无法引用嵌套字段时使用）

如果钉钉 AI 表格的“更新记录”节点不支持引用多层嵌套字段（如 `data.final_prompt`），可改用纯文本端点。该端点成功时直接返回提示词正文（`text/plain`），无 JSON 外壳，响应体就是最终提示词本身。

- 方法：`POST`
- URL：`http://39.105.209.143/api/v1/video-remake/generate-text`
- Header：`Authorization: Bearer <WEBHOOK_AUTH_TOKEN>`
- Header：`Content-Type: application/json` 或 `application/x-www-form-urlencoded`
- 请求 Body：与 JSON 端点完全相同

响应规则：

| 场景 | HTTP 状态码 | 响应体 |
|------|------------|--------|
| 成功 | 200 | 提示词正文（纯文本） |
| 鉴权失败 | 401 | 错误信息（纯文本） |
| 缺字段 | 422 | 错误信息（纯文本） |
| 正在处理中 | 409 | 错误信息（纯文本，含已耗时与等待秒数） |
| LLM 失败 | 502 | 错误信息（纯文本） |

钉钉配置：

- HTTP 请求节点：URL 改为 `.../generate-text`，超时设 150 秒
- 条件分支：`HTTP状态码 == 200` → 更新记录，引用整个响应体写入“最终提示词”
- `HTTP状态码 != 200` → 不更新，记录或通知响应体（错误信息）

两个端点共享同一份去重缓存与任务记录，可按需混用。

## 服务器目录

```text
/srv/workflow/app   Git仓库和Compose文件
/srv/workflow/data  SQLite持久化目录
```

服务器 `.env` 从 `.env.example` 创建，只填写 LLM 与 Webhook 配置。不要提交 `.env`。

## 发布

```bash
ssh aliyun-workflow
cd /srv/workflow/app
./deploy.sh
```

检查：

```bash
docker compose ps
curl http://127.0.0.1/healthz
docker compose logs --tail=100 app
```

当前 IP HTTP 适合联调。正式环境建议绑定域名并启用 HTTPS。

## 409 排查与卡死任务回收

当钉钉日志出现 `40901 相同请求正在处理中`，通常是以下原因之一：

1. **同一请求正在 LLM 调用中**（LLM 慢、钉钉重试或用户短时间内多次触发同一行）
2. **processing 状态卡死**：服务在 LLM 调用过程中被重启/部署，记录永久停留在 `processing`

服务端已内置 TTL 自动回收：`processing` 超过 `PROCESSING_TIMEOUT_SECONDS`（默认 180 秒）后，相同请求会自动接管重新处理，不再永久卡死。409 响应消息会附带已耗时与建议等待秒数。

如需立即清理卡死任务（不等 TTL）：

```bash
curl -X POST \
  -H "Authorization: Bearer $WEBHOOK_AUTH_TOKEN" \
  http://39.105.209.143/api/v1/video-remake/admin/reset-stale
```

返回 `{"code":0,"data":{"reset":N}}`，N 为本次回收的卡死任务数。

查看任务统计（含 processing 数量）：

```bash
curl -H "Authorization: Bearer $WEBHOOK_AUTH_TOKEN" \
  http://39.105.209.143/api/status
```
