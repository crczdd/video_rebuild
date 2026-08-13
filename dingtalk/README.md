# 钉钉 AI 表格独立对接模块

本目录从 `Infrigence_Workstream` 中抽离，供新的自动化工作流直接复用。它不依赖飞书代码，也不会读取或修改 NAS 内容。

当前能力：

- 获取钉钉应用 `accessToken`
- 用 `userid` 或免登码解析用户 `unionId/operatorId`
- 列出 AI 表格中的数据表和字段
- 分页读取记录
- 新增、更新、删除记录
- 上传本地图片到 AI 表格资源存储，并写入附件字段
- 从已读取记录中解析并下载图片附件
- 为“侵权举报”和“夸大宣传举报”分别选择目标 sheet

## 目录

| 文件 | 用途 |
| --- | --- |
| `client.py` | AI 表格记录与附件 API 客户端 |
| `identity.py` | `userid/免登码 -> unionId` |
| `settings.py` | 环境变量和两类工作流的 sheet 选择 |
| `factory.py` | 按工作流创建客户端 |
| `attachments.py` | 附件字段和文本字段辅助函数 |
| `setup_operator.py` | 获取并保存 `DIPR_DINGTALK_OPERATOR_ID` |
| `example.py` | 只读检查及附件写入示例 |
| `test_*.py` | 无真实网络写入的单元测试 |
| `HANDOFF.md` | 给新开发会话的交接说明 |

## 参数关系

| 参数 | 实际含义 |
| --- | --- |
| `APP_KEY/APP_SECRET` | 钉钉企业内部应用凭证 |
| `BASE_ID` | 一份钉钉 AI 表格文档的 ID |
| `SHEET_ID_OR_NAME` | 文档内某一张数据表的 ID，优先使用 ID |
| `VIEW_ID` | 数据表内视图 ID；当前基础读写按 sheet 操作，不依赖视图筛选 |
| `USERID` | 企业内部用户 ID，可用于查询用户详情 |
| `OPERATOR_ID` | 用户 `unionId`，AI 表格 OpenAPI 的 `operatorId` 参数 |

`userid` 和 `operatorId` 不是同一个值。已有 `userid` 时运行 `setup_operator.py`，由后端查询 `unionId`，不要求浏览器执行钉钉免登。

## 快速接入

1. 安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r dingtalk\requirements.txt
```

2. 参考 `dingtalk/.env.example` 将参数放入项目实际加载的 `.env`。不要把真实密钥提交到代码库。

3. 已知 `userid` 时解析 `operatorId`：

```powershell
.\.venv\Scripts\python.exe -m dingtalk.setup_operator --env .env --userid YOUR_USERID
```

应用需要拥有“查询用户详情”相关权限，否则该步骤会返回 `errcode=88/subcode=60011` 一类权限错误。

4. 只读检查字段和记录：

```powershell
.\.venv\Scripts\python.exe -m dingtalk.example --workflow infringement --list
```

5. 测试上传图片并新增一条记录：

```powershell
.\.venv\Scripts\python.exe -m dingtalk.example --workflow infringement --image D:\temp\evidence.png --attachment-field 侵权截图1
```

这一步会真实写入钉钉表格，仅在测试表或确认目标 sheet 后运行。

## 在新工作流中使用

```python
from pathlib import Path

from dingtalk.attachments import attachment_value
from dingtalk.factory import make_client

with make_client("infringement") as client:
    rows = client.list_records(page_size=100, max_pages=20)

    uploaded = client.upload_file(Path(r"D:\evidence\frame_001.jpg"))
    created = client.create_record(
        {
            "视频链接": "https://www.douyin.com/video/123456",
            "侵权截图1": attachment_value(uploaded.file_token),
            "人工审核": "否",
        }
    )

    client.update_record(created["record_id"], {"是否执行": "是"})
```

## 附件的正确链路

```text
本地图片
  -> 请求 uploadUrl/resourceId/resourceUrl
  -> PUT 图片二进制到 uploadUrl
  -> 把 filename/size/type/resourceUrl/resourceId 写入附件字段
```

这里不用 `fileToken`、钉盘 `fileId` 或 `dentryUuid`。本模块为了兼容原工作流，把 `UploadedFile.file_token` 这个属性保留为名称，但其值实际是钉钉的 `resourceId`。

下载附件前应先调用 `list_records()`，客户端会缓存记录中返回的 `resourceId/resourceUrl`。当前下载逻辑会校验返回内容是否为真实图片，避免把登录页或 JSON 错误内容当图片保存。

## 字段注意事项

- `投诉文案`、`抖音号`应在钉钉中建为纯文本字段，代码按字符串写入。
- 图片字段必须是附件字段，不能建成单选或文本字段。
- 单选、多选、数字等字段传值必须和钉钉字段类型一致；HTTP 400 时先运行 `--list` 核对字段类型和名称。
- `create_record()` 和 `update_record()` 会把 API 的完整错误响应放在 `DingtalkAPIError.payload` 中，新工作流记录日志时应输出该 payload。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q dingtalk
```

单元测试使用本地模拟接口，不会访问钉钉，也不会新增或修改真实记录。

## 官方文档

- [更新 AI 表格](https://open.dingtalk.com/document/development/api-noatable-updatesheet)
- [查询用户详情](https://open.dingtalk.com/document/development/query-user-details)
- [获取资源上传信息](https://open.dingtalk.com/document/development/api-getresourceuploadinfo)
- [上传附件](https://open.dingtalk.com/document/development/upload-attachment)
- [预览钉盘文件](https://open.dingtalk.com/document/development/preview-nail-plate-file)
