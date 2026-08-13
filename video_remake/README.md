# AI 对标视频复刻提示词工作流

该模块复用 `dingtalk` 中的 AI 表格客户端，读取符合条件的记录，通过 OpenAI-compatible `/chat/completions` 生成 Seedance 2.0 中文提示词，并只回写当前记录的 `最终提示词` 字段。

## Web 控制台（推荐）

双击项目根目录的 `start_web.cmd`，或运行：

```powershell
python -m video_remake.web --open-browser
```

浏览器访问 `http://127.0.0.1:8000`。页面支持设置轮询秒数、启动/停止定时任务、立即正式执行、立即 dry-run，以及查看最近一次统计和运行动态。页面启动时不会自动执行任务。

定时秒数保存在本地 `.video_remake_web.json`，定时开关不会跨重启自动开启，避免程序重启后意外调用 LLM。

## 命令行

```powershell
python -m pip install -r requirements.txt
python -m video_remake.worker --dry-run --once
python -m video_remake.worker --once
python -m video_remake.worker --interval 300
```

字段在每轮开始时校验；缺字段会停止该轮，不会自动创建或删除字段。`--dry-run` 不调用 LLM，也不写入钉钉。
