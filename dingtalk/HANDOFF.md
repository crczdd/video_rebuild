# 新会话开发交接

## 目标

使用本目录的钉钉 AI 表格能力，为新的业务工作流读取任务、上传举报材料、创建或更新执行状态。飞书逻辑不在本目录内，新工作流可单独选择是否保留双提供方适配。

## 已确认的实现约束

1. `DIPR_DINGTALK_OPERATOR_ID` 必须填写用户 `unionId`。如果只有 `userid`，调用 `resolve_operator_from_userid()` 查询，不需要用户在浏览器重新登录钉钉。
2. 一个 `baseId` 可以包含多张 sheet。侵权和夸大宣传通过各自的 `SHEET_ID_OR_NAME` 定向读写；不要把 `viewId` 当成 sheet ID。
3. AI 表格记录 API 的附件值是 `resourceId + resourceUrl + 文件元数据`。不能混用 MCP 的 `fileToken` 或钉盘目录 `dentryUuid`。
4. 共享素材目录只读与本模块无关；调用方只把已经落到本地 D 盘的证据文件传给 `upload_file()`。
5. `投诉文案`和`抖音号`按纯文本写入；`侵权截图1/2`、`工程文件`、`夸大效果`应是附件字段。

## 推荐工作流

```text
启动
  -> DingtalkSettings.from_env().validate(case)
  -> make_client(case)
  -> list_fields() 做一次字段预检
  -> list_records() 获取任务
  -> 执行业务/RPA
  -> upload_file() 上传每份本地证据
  -> create_record() 或 update_record()
  -> 再读取该记录，确认字段和附件已经返回
```

## 两类表配置

- `infringement` 使用 `DIPR_DINGTALK_INFRINGEMENT_SHEET_ID_OR_NAME`
- `exaggeration` 使用 `DIPR_DINGTALK_EXAGGERATION_SHEET_ID_OR_NAME`
- 专用值为空时才回退 `DIPR_DINGTALK_SHEET_ID_OR_NAME`
- 当前客户端保存 `view_id`，但基础记录读取 API 按 sheet 分页，并未用 view 过滤记录

## 新工作流必须补的业务层

本目录只负责钉钉 API，不包含以下业务规则，新会话应在独立 service/repository 层实现：

- 将钉钉字段映射为业务任务对象
- 根据视频链接去重，存在时更新而非重复新增
- `执行数`为空或 0 的判断与原子递增
- `是否下架`、`是否执行`、`人工审核`等状态机
- 侵权与夸大宣传各自的必填字段校验
- RPA 成功后再更新执行结果，失败时保存错误但不增加成功执行数
- 多浏览器并发时，围绕“视频链接查询 + 执行数更新”增加数据库锁或幂等键

## 错误日志要求

捕获 `DingtalkAPIError` 时至少记录：

```python
except DingtalkAPIError as exc:
    logger.error("dingtalk request failed", extra={
        "code": exc.code,
        "payload": exc.payload,
    })
```

HTTP 400 通常不是网络问题，而是字段名称、字段类型或附件结构与目标 sheet 不一致。不要只记录 `400 Bad Request`，完整响应才足够定位。

## 安全边界

- 不要把 `.env`、accessToken、AppSecret 写进日志或提交到版本库。
- `example.py --image` 会真实新增记录；默认的 `--list` 是只读。
- 删除接口已经封装，但新工作流除非有明确业务授权，不应自动删除表格记录。
- 附件下载会验证图片格式；如果未来要下载 PDF/视频，应新增对应 MIME 校验，不能直接取消校验。

## 首次开发建议

1. 运行 `pytest -q dingtalk`，确认独立模块可导入。
2. 填好测试环境变量，只运行 `example --list`。
3. 打印 `list_fields()` 结果，制作字段映射表。
4. 用一张小测试图验证上传和新增记录。
5. 再接业务工作流，最后接 RPA 的成功/失败状态更新。
