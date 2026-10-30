# 整理 Codex 对话：codex-session-rearrange

简体中文 · [English](README.md)

一个实验性的本地 **Codex 技能 + Python 脚本**，用于整理被容量错误反复打断的聊天，将中间消息、推理总结、工具记录合并到以最终答案结束的轮次，方便折叠查看。

搜索关键词：**整理codex对话**、**删除codex上下文的报错信息**、清理 Codex 聊天记录、429 Too Many Requests、selected model is at capacity、恢复推理折叠、Codex conversation cleanup。

**默认只生成独立副本，强制保留备份。这不是 OpenAI 官方工具。** 它修改副本的历史与显示结构，不会修复模型服务故障，不会解除额度限制，也不保证后续模型输入上下文一定变短。

## 功能

- 按继承截止位置展开本地历史链，支持 `.jsonl` 与 `.jsonl.zst`。
- 使用全新会话 UUID，去掉对原会话历史的继承引用。
- 只有真正的最终模型答案才结束一轮；异步提问保留在轮内。
- 重建连续序号、UTF-8 字节偏移、轮次索引和消息索引，处理曾遇到的缺少序号、打开空白问题。
- 缺少最终答案的内容保持未完成。用时只按已有时间戳计算，由 Codex 决定展示“用时”或“上 n 条消息”，不强制伪造标签。
- `prepare` 离线准备、`verify` 验证、`install` 登记；准备阶段不新增聊天。

## 其他报错能否整理？

| 情况 | 当前处理 |
|---|---|
| 429／at capacity 的旧任务结束事件、可识别独立错误事件 | 副本清除旧结束边界／对应错误显示事件；原始详情保存在备份 |
| 其他错误的旧任务结束、终止边界 | 合轮时也被移除，边界中嵌入的错误元数据不会写入整理后的记录；需要详情时读取原始备份 |
| 500、工具报错等其他独立错误事件 | 保留，不是通用“全部报错删除器” |
| 正文里有实质内容的报错说明 | 保留；不会全局替换 `429`，避免误删编号和正常内容 |
| 未知数据格式、缺少原生 UI 索引模板 | 检测到时停止，不转为修改原对话 |
| API、网络、编译、工具本身的故障 | 不修复，也不会把真实失败变成成功 |

因此，**同一种存储结构下，合轮可以跨越其他中断；自动清理独立错误消息目前主要识别 429／at capacity。** 新错误类型需要明确规则和回归测试，不建议粗暴删除全部错误。

## 环境与兼容范围

- Python 3.10+；压缩祖先记录需要 `zstandard`。
- 当前观察到的 `state_5.sqlite` / `thread_history_1.sqlite` 格式；需要已停工、UUID 明确且已有完整 UI 消息索引的源对话。
- 手工工作流在 Windows、Codex Desktop **26.1027.30824** 上验证。内部格式可能变化，不保证所有版本可用；不支持把 ChatGPT 云端聊天直接作为本地记录处理。
- 脚本按稳定消息 ID 复用本机原生 UI 索引，优先源会话，再查看已索引的其他副本。缺少可显示消息模板时停止；无模板的 Extension 作为账务记录保留在原始历史中并计数。

## 安装技能

PowerShell（已有同名技能时先备份并检查，不直接覆盖）：

```powershell
$skillDir = Join-Path $HOME '.codex/skills/codex-session-rearrange'
if (Test-Path -LiteralPath $skillDir) { throw '已有同名技能，请先备份再更新。' }
git clone https://github.com/wujiseclusion/codex-session-rearrange.git $skillDir
python -m pip install -r "$skillDir/requirements.txt"
```

macOS/Linux 命令行安装（桌面 UI 兼容性未验证）：

```sh
test ! -e "$HOME/.codex/skills/codex-session-rearrange" || exit 1
git clone https://github.com/wujiseclusion/codex-session-rearrange.git "$HOME/.codex/skills/codex-session-rearrange"
python3 -m pip install -r "$HOME/.codex/skills/codex-session-rearrange/requirements.txt"
```

如 Python 环境要求，请使用虚拟环境。技能列表未刷新时开启新聊天。可以显式调用 **`$codex-session-rearrange`**，也可以说 **“整理codex对话”**、**“删除codex上下文的报错信息”**。技能描述和仓库文档均包含这些原词；搜索引擎何时收录、具体排名不受本项目控制。

本仓库提供技能与脚本，不是已注册的 Codex 插件市场插件。

## 使用方式

先让 Codex 根据标题查明精确源 UUID，并确认会话已停工：

```powershell
$repairScript = Join-Path $HOME '.codex/skills/codex-session-rearrange/scripts/rearrange.py'
python $repairScript prepare --source '<源会话UUID>' --title '原标题（整理副本）'
python $repairScript verify '<生成的备份包目录>'
python $repairScript install '<生成的备份包目录>'
```

`prepare` 会打印新 UUID 和包目录；默认保存在 `~/.codex/session-rearrange-backups/<新UUID>/`，可用 `--output` 改为其他持久目录，用 `--home` 指向隔离测试数据目录。不要把备份放进公开仓库。

`install` 再次验证后才登记新 UUID，并拒绝覆盖已有会话。脚本不会发送消息或启动项目工作。打开准确标题／UUID 的副本，检查早期、中间、最新内容及折叠效果，确认文件 diff 归入正确轮次。退出码为 0 或 `registered: true` 只代表相应阶段完成，不代表 UI 或继续工作已通过验收。

详细机制见 [命令行参考](references/cli.md) 和 [工作流](references/workflow.md)（英文）。

## 备份、删除与恢复：必须了解

每次准备都保存 `original/` 原始记录、完整 SQLite 备份、包含哈希和计数的 `manifest.json`，以及独立记录 `rollout.jsonl` 和索引 `projection.sqlite`。源记录只读，没有原地编辑模式。文件复制后与结束时会再次核对哈希；分别复制的文件和数据库不是运行中应用的同一时刻原子快照，应先停工。大对话和完整数据库备份可能占用数 GB 空间。

**数据库备份可能包含全部本地聊天、隐私数据和工具输出。禁止把备份包、manifest、JSONL、SQLite 文件直接上传到 GitHub 仓库或 issue。** 公开发布内容只应包含代码和脱敏测试。

主会话副本有自己的文件、索引，无 `history_base`／`forked_from_id` 依赖，隔离测试覆盖了删除模拟源数据后副本仍完整。但**不会递归复制子代理完整对话、附件、图片和项目文件**；旧代理 ID 仍是历史引用。删除原主对话和子代理对话前，应先独立备份并验证这些依赖。能读历史不等于能恢复旧子代理工作。

普通安装失败时会回滚事务和本次新写入的记录文件；跨 WAL 数据库的断电原子性不保证。验收后可通过 Codex 正常归档／删除不需要的实验副本。整库恢复是人工灾难恢复操作：先关闭 Codex，明确它可能回退**所有聊天**，不能把单个会话恢复当成直接覆盖数据库。不要覆盖运行中的数据库。

## 验证与测试

```powershell
python "$HOME/.codex/skills/codex-session-rearrange/scripts/test_rearrange.py"
```

隔离测试覆盖：继承截止、中文 UTF-8 偏移、异步提问、文件修改、最终答案合轮、未回答尾段、非容量独立错误保留、独立登记、拒绝覆盖、模拟删除源后的副本完整性、篡改检测，以及安装依赖后的 zstd 解压。CI 为 Windows/Ubuntu × Python 3.10/3.13。

一次真实离线准备复现了 **28,950 条消息、87 次异步提问、52 轮最终答案**。手工修复工作流已由用户确认界面成功；脚本新安装的每个副本仍需自己的 UI 验收，未验证进一步执行代理任务。

## 免责声明与归属

这是独立的社区工具，**不是 OpenAI 官方制作、认可或支持的产品**。Codex 和 ChatGPT 属于 OpenAI。本项目通过本地实验总结整理方法，使用的内部存储格式不是稳定公开导入 API。

软件按 **AS IS（原样）** 提供，不保证正确性、兼容性、适用性、数据完整性和后续可用性。使用者应自行备份、审查输出并保留恢复路径。在法律允许的范围内，作者和贡献者不对数据丢失、损坏、停工及其他损失负责。详见 [MIT License](LICENSE)。
