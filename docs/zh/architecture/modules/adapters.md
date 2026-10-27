# adapters：AstrBot 宿主适配

## 职责

adapters 把 AstrBot 事件、provider 和消息发送映射到应用端口。宿主对象不进入 core、recall 或 app/runtime 的领域策略中。

## 组合根

AstrBotPlugin 在 start 时建立 Store、Cache、Tree、Graph、HybridRetriever、Source-backed Buffer、CheckpointManager、各应用服务、AgentRuntime、Jobs、WebRoutes 与后台服务；stop 时依次停止后台任务与管理任务、注销本实例路由、保存缓冲、flush checkpoint，最后关闭 Store。

main.py 定义插件入口并委托 lifecycle；组合和 wiring 位于 adapters/astrbot_plugin.py。AstrBotHooks 在 adapters/astrbot_hooks.py 把宿主 hook 映射为服务调用：访问策略、输入接收、记忆注入、助手回复捕获、实际发送后的交付记录、运行时/工具观测。它不实现抽取、容量或维护算法。

## 端口适配

- AstrBotRuntimeAdapter 将消息转成 RuntimeInput，并管理宿主 event extra 中的 user/reply Source ID、turn ID、final recall IDs 和 episode 去重标记。
- AstrBotModelGateway 提供延迟回复使用的 ModelGateway。
- AstrBotActionPort 提供 MessageSender。
- ProviderChatModel 将宿主 extraction/persona provider 包装为 ChatModel。
- SeekMemoryContextAdapter 将 Runtime 的 MemoryContextPort 接到现有 RecallService。

AccessService 基于完整 session UMO、sender ID、owner/trusted 配置和 observe_groups 决定观察/召回；宿主事件信息只在边界处转换。配置和 database path 仍由插件组合根读取。

## 当前边界

宿主 hook 注册必须绑定真实插件模块路径，避免热重载后回调无法识别。Runtime 的工具过滤在模型请求前运行；工具调用完成后的观测 hook 不能作为强制拦截。插件初始化/宿主 API 不可用时，由上层状态和 fail-open 处理，不应把 AstrBot 依赖泄漏到业务模块。
