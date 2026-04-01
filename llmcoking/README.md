# DeepCoke 智能焦化决策平台

焦化配煤智能问答系统，支持配煤优化、文献检索和语音对话。全本地部署，无需联网。

## 安装

```bash
# 创建 conda 环境
conda env create -f environment.yml
conda activate deepcoke

# 前端依赖
npm install
```

## 启动

双击 `start_all_windows.bat` 或手动启动：

```bash
conda activate deepcoke

# 终端1 - 文本后端 (port 8000)
cd src/LLM_back
python -m uvicorn test:app --host 0.0.0.0 --port 8000

# 终端2 - 语音后端 (port 8001)
cd voice_agent_backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 终端3 - 前端 (port 8080)
npm run serve
```

详细说明见根目录 [README](../README.md)。
