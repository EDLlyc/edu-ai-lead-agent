# 微信公众号自动推文技术路线：官方接口与公开实现核验

检索日期：2026-08-19。本文只为技术路线汇报提供研究依据，不代表对任何项目的质量、安全性或生产适用性背书。核验方法为读取微信官方开发文档当前页面、公开仓库 README/专项文档及 GitHub 仓库元数据；未运行任何代码，也未连接真实公众号。

## 1. 微信官方接口边界

- 服务端 API 调用说明、AppSecret、API IP 白名单与 access token：<https://developers.weixin.qq.com/doc/service/guide/dev/api/>
- 获取接口调用凭据：<https://developers.weixin.qq.com/doc/service/api/base/api_getaccesstoken>
- 上传发表内容中的图片：<https://developers.weixin.qq.com/doc/service/api/material/permanent/api_uploadimage>
- 上传永久素材：<https://developers.weixin.qq.com/doc/service/api/material/permanent/api_addmaterial>
- 草稿箱能力总览：<https://developers.weixin.qq.com/doc/service/guide/product/draft.html>
- 新增草稿：<https://developers.weixin.qq.com/doc/service/api/draftbox/draftmanage/api_draft_add>
- 发布能力总览：<https://developers.weixin.qq.com/doc/service/guide/product/publish.html>
- 发布草稿：<https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_submit>
- 发布状态查询：<https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_get>

### 核验结论

- 官方服务端 API 调用说明页明确，API IP 白名单会约束接口调用；access token 是全局接口调用凭据，应统一获取、缓存并在有效期前刷新，不能由各业务环节分别刷新。
- 正文中的外部图片不能直接原样引用。官方“上传发表内容中的图片”接口返回微信侧图片 URL；草稿正文中的图片引用必须来自该接口。图文封面则使用永久素材的 `media_id`，与正文图片是两类资源。
- 官方“新增草稿”接口把文章保存到公众号后台草稿箱，并返回草稿标识；“发布草稿”是另一个独立接口。发布请求提交成功只代表任务已受理，不代表最终发布成功，还需查询状态或接收结果事件。
- 官方发布能力页注明：自 2025 年 7 月起，个人主体账号、企业主体未认证账号及不支持认证的账号会被回收相关发布接口调用权限。因此不能只根据“已注册公众号”判断可行性，必须在目标账号后台逐项核对认证状态、接口权限、草稿箱开关和发布能力。

设计含义：公众号接入不是“把一段文字 POST 出去”。系统需要先处理凭证与 token，再处理正文图片和封面，生成微信可接受的 HTML，最后创建草稿；正式发布必须作为单独审批和异步状态跟踪流程。账号类型、认证状态、接口权限和 IP 白名单必须在真实公众号后台核验。

## 2. 代表性公开实现

### wechatpy / wechatpy

- 地址：<https://github.com/wechatpy/wechatpy>
- 类型：Python 微信 SDK。
- 许可证：MIT（GitHub 仓库元数据及 LICENSE）。
- 可借鉴点：把 token、素材上传和公众平台 API 封装为独立客户端；业务工作流不直接拼接微信请求。
- 边界：SDK 解决接口封装，不解决采集、选题、写作、审核和运营复盘。

### caol64 / wenyan-core

- 地址：<https://github.com/caol64/wenyan-core>
- 微信发布文档：<https://github.com/caol64/wenyan-core/blob/main/docs/wechat.md>
- 许可证：Apache-2.0（GitHub 仓库元数据及 LICENSE）。
- 可借鉴点：渲染与发布解耦；Markdown/结构化文章先渲染，再统一处理本地或远程图片、封面和草稿上传；发布被封装在 Node adapter 中。
- 边界：主要解决排版和微信草稿适配，不替代内容事实治理与审批。

### jiabao-wang / md2wechat-free

- 地址：<https://github.com/jiabao-wang/md2wechat-free>
- 许可证：MIT（GitHub 仓库元数据及 README）。
- 可借鉴点：Markdown/Notion 作为可编辑中间格式，提供实时预览、主题、图片上传、批量草稿和本地凭证管理；强调“保存草稿箱，不自动群发”。
- 边界：适合编辑与发布辅助，不提供完整的可信采集、选题和审核链路。

### jiji262 / wechat-publisher

- 地址：<https://github.com/jiji262/wechat-publisher>
- 许可证：GitHub 仓库元数据未识别到许可证；本次只观察公开文档，不据此复制代码。
- 可借鉴点：把搜索、写作、配图、排版、质量门和草稿创建拆成阶段；所有 CSS 内联；区分正文图片和封面素材；缓存 token，并给出白名单和常见错误处理。
- 边界：README 展示的是项目自身能力描述，不能替代独立的质量、安全和生产验证。

### Rpeng666 / auto-wx-post

- 地址：<https://github.com/Rpeng666/auto-wx-post>
- 许可证：GitHub 仓库元数据未识别到许可证；本次只观察公开文档，不据此复制代码。
- 可借鉴点：token 自动刷新、图片并发上传、基于内容的缓存、有限重试、临时资源清理、结构化日志；同时通过 HTTP 与 MCP 暴露发布能力，说明平台适配器可以服务不同客户端。
- 边界：发布工具不应直接向 LLM 暴露无限制账号权限；对外工具仍需要审批、参数约束和审计。

### 16Miku / wechat-auto-publishing

- 地址：<https://github.com/16Miku/wechat-auto-publishing>
- 许可证：GitHub 仓库元数据未识别到许可证；本次只观察公开文档，不据此复制代码。
- 可借鉴点：完整工作流明确区分写稿、配图、草稿、通知/批准、正式发表、归档和调度；生产默认建议“API 仅进草稿箱，管理员后台确认发表”。
- 边界：公开说明中的经验结论需要在目标账号和实际环境中重新验证。

## 3. 可归纳为领导版的设计原则

1. 内容生产和微信公众号接口分开建设，任何一侧更换都不影响另一侧。
2. 用可编辑的中间稿保存标题、摘要、正文、图片和栏目元数据，再统一渲染微信 HTML。
3. 图片上传、封面、正文、草稿是多个步骤，要记录每步状态并支持安全重试。
4. 公众号密钥只交给受控发布适配器，写作模型不直接接触密钥。
5. 第一阶段止于草稿箱；运营人员在手机和后台完成预览、修改和签发。
6. 任务、版本、审核意见、草稿 ID 和错误原因需要持久化，避免重复创建或无依据重试。
7. 多账号、定时发布和数据复盘建立在单账号草稿闭环稳定之后。

## 4. 采用与不采用

| 观察到的共性 | 本项目采用方式 | 明确不采用 |
|---|---|---|
| 内容、排版、平台接口分层 | 复用现有内容生产底座，新增微信适配器 | 用一个脚本串起全部步骤 |
| Markdown/结构化中间稿 | 保留标题、摘要、正文、图片和栏目元数据，可重新渲染 | 直接让模型输出并提交平台 |
| 正文图片与封面分开上传 | 分步记录微信侧 URL、封面素材 ID 和错误 | 外链图片原样写入正文 |
| token 缓存与有限重试 | 凭据集中保管，按错误类别重试，保存幂等记录 | 多进程各自刷新 token、无限重试 |
| 草稿箱与正式发布分离 | 第一阶段止于草稿箱，人工预览签发 | 浏览器模拟登录、无人审核群发 |
| 状态与版本可追踪 | 记录任务、版本、审核意见、草稿标识与失败原因 | 只看终端输出、失败后整条重跑 |

## 5. 与当前项目的衔接

当前项目可以复用：可信来源采集、证据治理、规则和 LLM 受控选题、品牌知识、文案、配图、质量检查、任务状态、失败回退和内部审核经验。

公众号方向新增：长文模板、微信兼容 HTML、正文图片/封面上传、公众号 token 与白名单管理、草稿箱适配、移动端预览、人工签发、发布记录及阅读互动数据回流。

推荐不是从零重建，而是在现有内容生产链后增加“公众号呈现 + 草稿适配 + 人工审批 + 运营复盘”四个模块。

## 6. 研究边界

- 上述公开项目的功能陈述来自各自维护者的公开文档，未进行安装、接口调用、性能、安全或生产稳定性测试。
- “许可证未识别”不等于可以自由使用；若后续考虑代码复用，必须由法务/合规与技术人员重新核对具体文件和依赖许可证。
- 微信官方规则、账号权限和接口字段可能继续变化。正式实施前应以目标账号后台与当时官方文档重新确认，本记录不能替代上线检查。
