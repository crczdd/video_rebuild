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
- Header：`Content-Type: application/json`
- 勾选：等待响应
- HTTP节点最长等待：150秒；服务端LLM超时120秒，Nginx上限145秒

请求 Body 可以直接使用中文字段：

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
