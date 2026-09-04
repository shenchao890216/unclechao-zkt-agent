# zkt 协作规范

本仓库开源运行。任何人(包括 AI 助手)改动代码前先读这一页。

## 安全红线(最高优先级)

这些内容**永远不进 git**,每次提交前自查:

- `.env`(真实 API key)、任何 `sk-` 开头的密钥串
- `zk/`(用户的卡片盒数据:卡片、草稿、审计日志)
- `graph.html` / `guide.html`(渲染产物,内嵌卡片全文)
- `skills/`、`.claude/`(本机个人配置与路径)
- 任何绝对个人路径(`/Users/xxx`、`C:\Users\xxx`)

提交前跑:`git diff --staged | grep -nE "sk-[A-Za-z0-9]{16,}|/Users/|C:\\\\Users"` ——有命中就不要提交。

## 工作流

- 功能/修复一律走分支:`feat/<主题>`、`fix/<主题>`、`docs/<主题>`
- PR 描述三段:**改了什么 / 为什么 / 怎么验证的**
- 合并用 squash,main 上一事一提交
- 例外:错别字、README 微调可直接 push main

## 代码改动纪律

- 最小改动:每行 diff 能追溯到本次需求,不顺手重构
- 架构不变量(动了要先说明理由):
  - 签字权在人:`propose_promote` / `propose_delete` 必须经 CONFIRM_HOOK,审计 actor 记 human
  - 审计不缺位:所有 agent 工具执行都要 `log_action`
  - provider 不绑定:`_call_model` 只走 `make_client()` / `MODEL` 配置
- 交互改动(TUI)必须有 headless 验证,参考 `python3 -c` + `app.run_test()` 的现有用法

## 测试与验证

- 纯逻辑改动:`python3 -m py_compile zkt/*.py` + 相关函数直测
- 涉及 agent 循环:可 monkeypatch `agent._call_model`,别烧真 API
- 真机验证(流式/签字弹窗): headless `run_test()` 跑通后才算完成

## 版本

- main 对应最新发布;发布 = 更新 `pyproject.toml` version + 打 tag `vX.Y.Z`
- 语义化:破坏性 major / 新功能 minor / 修复 patch
