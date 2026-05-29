# 开发问题记录

记录项目开发过程中遇到的主要问题、根本原因和解决方案。

---

## 问题 1：hatchling 打包失败

**阶段**：环境配置

**报错**：
```
ValueError: Unable to determine which files to ship inside the wheel
The most likely cause: no directory matches the name of your project (localnow_backend)
```

**根本原因**：
hatchling 是 Python 打包工具，需要找到一个合法的 Python 包目录才能工作。
我们只创建了目录但没有 `__init__.py`，Python 不认为这些是"包"。

**解决方案**：
1. 在每个子目录下创建空的 `__init__.py` 文件
2. 在 `pyproject.toml` 里声明包路径：
```toml
[tool.hatch.build.targets.wheel]
packages = ["agent", "api", "tools", "llm", "models", "prompts"]
```

**经验**：Python 识别"包"的标志是目录下有 `__init__.py`，即使是空文件也必须存在。

---

## 问题 2：终端多行命令缩进报错

**阶段**：环境验证

**报错**：
```
IndentationError: unexpected indent
```

**根本原因**：
在终端用 `python -c "..."` 执行多行代码时，粘贴带缩进的代码，
缩进字符被当成 Python 语法处理，导致报错。

**解决方案**：
改用 heredoc 语法执行多行代码：
```bash
uv run python - <<'EOF'
from config import config
print(config.llm_provider)
EOF
```

---

## 问题 3：API Key 泄露

**阶段**：环境配置

**问题**：将包含真实 API Key 的 `.env` 内容粘贴进了对话窗口，导致 Key 暴露。

**根本原因**：
对话内容可能被记录，API Key 一旦出现在非安全环境就视为泄露。

**解决方案**：
1. 立即去 console.anthropic.com 撤销（Revoke）泄露的 Key
2. 生成新 Key 替换
3. 确保 `.env` 在 `.gitignore` 里，永远不提交到代码仓库

**经验**：API Key 只应出现在 `.env` 文件中，不能出现在代码、截图、对话、日志里。

---

## 问题 4：.env 同行注释导致配置读取异常

**阶段**：环境配置

**问题**：
```bash
LLM_PROVIDER=anthropic  # anthropic | openai | deepseek | ollama
```
`python-dotenv` 不同版本对同行注释的处理行为不一致，可能读到带注释的值。

**解决方案**：
注释单独成行，值单独一行：
```bash
# LLM Provider 选择：anthropic | openai | deepseek | ollama
LLM_PROVIDER=anthropic
```

---

## 问题 5：Anthropic API 余额不足

**阶段**：数据生成

**报错**：
```
anthropic.BadRequestError: 400 - Your credit balance is too low
```

**根本原因**：Anthropic 账户余额为零，API 调用被拒绝。

**解决方案**：
数据生成是一次性任务，改用 Ollama 本地模型（qwen3:8b）替代：
- Ollama 完全免费，无需 API Key
- 暴露 OpenAI 兼容接口（`http://localhost:11434/v1`），代码改动极小
- qwen3:8b 中文质量好，足以胜任数据生成任务

**经验**：
工具链设计时要考虑降级路径。我们的 LLM Factory 多 provider 设计，
正是为了在某个 provider 不可用时能快速切换。

---

## 问题 6：Ollama 连接被拒绝

**阶段**：数据生成

**报错**：
```
httpx.ConnectError: [Errno 111] Connection refused
```

**根本原因**：
WSL2 环境下 Ollama 不会自动作为后台服务启动，需要手动启动，
或者 Ollama 根本还没有安装。

**解决方案**：
```bash
# 安装（WSL2 用官方脚本，不要用 snap）
curl -fsSL https://ollama.com/install.sh | sh

# 启动服务（安装后自动启动，重启 WSL 后需要重新启动）
ollama serve

# 验证
ollama list
```

**经验**：
WSL2 没有 systemd，部分服务不能开机自启，需要手动管理。
`snap install` 在 WSL2 里不可靠，应该用官方安装脚本。

---

## 问题 7：generate.py 找不到 .env 文件

**阶段**：数据生成

**报错**：
```
TypeError: Could not resolve authentication method. Expected one of api_key...
```

**根本原因**：
`generate.py` 在 `data/` 子目录里，`load_dotenv()` 默认在当前目录找 `.env`，
而 `.env` 在上一级的 `backend/` 目录。

**解决方案**：
显式指定 `.env` 路径：
```python
load_dotenv(Path(__file__).parent.parent / ".env")
```

**经验**：
在子目录里运行的脚本，读取配置文件要用相对于脚本位置的绝对路径，
不能依赖"当前工作目录"，因为从不同目录调用脚本时结果不同。

---

## 问题 8：LLM 输出 JSON 被截断

**阶段**：数据生成

**报错**：
```
json.decoder.JSONDecodeError: Expecting ',' delimiter: line 1 column 6870
```

**根本原因**：
`max_tokens=4096` 不足以容纳 42 条餐厅数据的完整 JSON 输出
（42条 × 约200 tokens/条 ≈ 8400 tokens）。
模型在输出中途被强制截断，JSON 数组不完整，解析失败。

**解决方案**：
分批生成，每批不超过 15 条，保证单次输出在 3000 tokens 以内：
```python
def generate(prompt, label, total, batch_size=15):
    results = []
    batches = (total + batch_size - 1) // batch_size
    for i in range(batches):
        current = min(batch_size, total - len(results))
        batch = generate_batch(prompt, current)  # 带重试
        results.extend(batch)
    return results
```

每批独立，失败自动重试 3 次，不影响其他批次。

**经验**：
让 LLM 生成大量结构化数据时，单次生成量要控制在输出 token 预算的 60% 以内，
留出模型可能产生的额外说明文字空间。分批是处理本地模型输出限制的标准做法。

---

## 问题 9：评估脚本汇总结论与实际结果不符

**阶段**：数据评估

**问题**：
评估脚本最后输出"结构验证失败=0"，但实际场所数据有 1 条结构验证失败。
最终汇总是写死的静态文字，没有读取实际验证结果。

**解决方案**：
每个评估函数返回失败条数，main() 汇总后基于实际数字打印结论：
```python
r_errors = evaluate_restaurants(restaurants)
v_errors = evaluate_venues(venues)
total_errors = r_errors + v_errors
if total_errors == 0:
    print("✓ 全部通过")
else:
    print(f"✗ 共发现 {total_errors} 个问题")
```

**经验**：评估脚本的结论必须由代码计算得出，不能写死文字，否则等于没有评估。

---

## 问题 10：分批生成导致数据 ID 重复

**阶段**：数据生成

**问题**：
分 3 批各生成 15 条餐厅数据，每批 LLM 都从 `rg001` 开始编号，
合并后出现大量重复 ID。重复 ID 会导致 ChromaDB 索引时覆盖已有条目，数据实际少于预期。

**解决方案**：
合并所有批次后统一重新分配 ID：
```python
def reassign_ids(data: list[dict], prefix: str) -> list[dict]:
    for i, item in enumerate(data):
        item["id"] = f"{prefix}{i + 1:03d}"
    return data
```

**经验**：不要信任 LLM 生成的 ID，任何需要全局唯一的字段都应该在代码层统一生成和管理。
