# Agent Service

Python sidecar for model-driven review analysis.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r agent_service\requirements.txt
# copy .env.example to .env and fill the model settings
uvicorn agent_service.main:app --host 127.0.0.1 --port 8770
```

Optional:

```powershell
# DeepSeek:
# OPENAI_API_KEY=your_key
# OPENAI_BASE_URL=https://api.deepseek.com
# OPENAI_MODEL=deepseek-v4-flash
# OPENAI_REASONING_EFFORT=low
# OPENAI_THINKING_TYPE=disabled
#
# Another OpenAI-compatible provider can use the same variables.
# OPENAI_TEMPERATURE=0.2
# AGENT_RUN_TIMEOUT_SECONDS=900
# AGENT_LLM_TIMEOUT_SECONDS=180
```

The root `.env.example` contains both the Node proxy setting and the Python model API settings used by the sidecar. The variable names describe the API protocol, not a specific vendor. The service reads `.env` first and falls back to `.env.example` when `.env` is absent.
