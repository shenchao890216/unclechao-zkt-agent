# 贡献指南

## 快速上手

```bash
git clone https://github.com/shenchao890216/unclechao-zkt-agent
cd unclechao-zkt-agent
pip install -e .
cp .env.example .env   # 填入你的 DEEPSEEK_API_KEY
zkt
```

## 提交流程

1. 从 main 切分支:`git checkout -b feat/你的主题`
2. 改动保持最小,每行 diff 对应这次主题
3. `python3 -m py_compile zkt/*.py` 通过
4. 推分支、开 PR,按模板填写(改动/动机/验证)
5. CI 绿了等维护者 review

## 红线

`.env`、`zk/`、`graph.html`、`guide.html`、`.claude/`、`skills/` 永远不要提交——
不小心提交了真实密钥,视为泄露,请立即通知维护者并作废该 key。

## 代码约定

- 中文注释与文档,代码标识符英文
- 签字权在人、审计不缺位、provider 可切换,是三条架构不变量,改动需在 PR 里专门论证
