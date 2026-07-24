"""
自定义 LLM 模型配置 - 支持多提供商
参考: https://doc.agentscope.io/zh_CN/tutorial/task_model.html

支持的提供商：
- DashScope (qwen-max, qwen-turbo, ...)
- OpenAI (gpt-4o, gpt-4o-mini, ...)
- OpenAI 兼容 (vLLM, DeepSeek, 本地模型)
- Anthropic (claude-3-5-sonnet, ...)
- Gemini (gemini-1.5-pro, ...)
- Ollama (本地模型)

配置方式：
1. 环境变量（DASHSCOPE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / ...）
2. 配置文件 model_config.json
3. API 运行时设置
"""
from __future__ import annotations

import os
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path


CONFIG_FILE = Path(__file__).parent.parent / "model_config.json"


@dataclass
class LLMProviderConfig:
    """单个 LLM 提供商配置"""
    provider: str           # dashscope / openai / openai_compatible / anthropic / gemini / ollama
    api_key: str = ""
    model_name: str = ""
    base_url: str = ""
    stream: bool = False
    enable_thinking: bool = False
    temperature: float = 0.7
    max_tokens: int = 2000
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_configured(self) -> bool:
        """是否已配置可用"""
        if self.provider == "ollama":
            return bool(self.base_url or self.model_name)
        return bool(self.api_key and self.model_name)

    def to_dict(self) -> Dict:
        d = asdict(self)
        # 脱敏 API key
        if d["api_key"]:
            d["api_key_masked"] = d["api_key"][:8] + "..." if len(d["api_key"]) > 8 else "***"
            d["api_key"] = d["api_key_masked"]
            del d["api_key_masked"]
        return d


# 默认配置（从环境变量读取）
DEFAULT_PROVIDERS: List[LLMProviderConfig] = [
    LLMProviderConfig(
        provider="dashscope",
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        model_name=os.environ.get("DASHSCOPE_MODEL", "qwen-max"),
        stream=False,
    ),
    LLMProviderConfig(
        provider="openai",
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model_name=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        stream=False,
    ),
    LLMProviderConfig(
        provider="openai_compatible",
        api_key=os.environ.get("OPENAI_COMPATIBLE_API_KEY", ""),
        model_name=os.environ.get("OPENAI_COMPATIBLE_MODEL", ""),
        base_url=os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000/v1"),
        stream=False,
    ),
    LLMProviderConfig(
        provider="anthropic",
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        model_name=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        stream=False,
    ),
    LLMProviderConfig(
        provider="gemini",
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        model_name=os.environ.get("GEMINI_MODEL", "gemini-1.5-pro"),
        stream=False,
    ),
    LLMProviderConfig(
        provider="ollama",
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model_name=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
        stream=False,
    ),
]

# 各提供商说明
PROVIDER_INFO: Dict[str, Dict] = {
    "dashscope": {
        "name": "阿里云 DashScope (通义千问)",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long", "qwen2.5-72b-instruct"],
        "env_key": "DASHSCOPE_API_KEY",
        "docs": "https://dashscope.aliyun.com",
        "supports_tools": True,
        "supports_thinking": True,
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1-mini"],
        "env_key": "OPENAI_API_KEY",
        "docs": "https://platform.openai.com",
        "supports_tools": True,
        "supports_thinking": False,
    },
    "openai_compatible": {
        "name": "OpenAI 兼容 (vLLM / DeepSeek / 本地)",
        "models": ["自定义"],
        "env_key": "OPENAI_COMPATIBLE_API_KEY",
        "docs": "https://docs.vllm.ai",
        "supports_tools": True,
        "supports_thinking": False,
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
        "env_key": "ANTHROPIC_API_KEY",
        "docs": "https://www.anthropic.com",
        "supports_tools": True,
        "supports_thinking": True,
    },
    "gemini": {
        "name": "Google Gemini",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"],
        "env_key": "GEMINI_API_KEY",
        "docs": "https://ai.google.dev",
        "supports_tools": True,
        "supports_thinking": False,
    },
    "ollama": {
        "name": "Ollama (本地模型)",
        "models": ["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "deepseek-r1:7b"],
        "env_key": "无（本地部署）",
        "docs": "https://ollama.ai",
        "supports_tools": True,
        "supports_thinking": False,
    },
}


class ModelConfigManager:
    """LLM 配置管理器"""

    def __init__(self):
        self._providers: Dict[str, LLMProviderConfig] = {}
        self._active_provider: str = ""
        self._load()

    def _load(self):
        """加载配置：环境变量 + 配置文件"""
        # 1. 从默认（环境变量）初始化
        for p in DEFAULT_PROVIDERS:
            self._providers[p.provider] = LLMProviderConfig(**asdict(p))

        # 2. 配置文件覆盖
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for p_dict in data.get("providers", []):
                    p = LLMProviderConfig(**p_dict)
                    self._providers[p.provider] = p
                self._active_provider = data.get("active_provider", "")
            except Exception as e:
                print(f"[ModelConfig] load config file failed: {e}")

        # 3. 自动选择已配置的 provider
        if not self._active_provider:
            for p in self._providers.values():
                if p.is_configured():
                    self._active_provider = p.provider
                    break

    def save(self):
        """持久化到配置文件"""
        data = {
            "active_provider": self._active_provider,
            "providers": [asdict(p) for p in self._providers.values()],
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_providers(self) -> List[Dict]:
        """列出所有提供商及状态"""
        result = []
        for pid, p in self._providers.items():
            info = PROVIDER_INFO.get(pid, {})
            result.append({
                "provider": pid,
                "name": info.get("name", pid),
                "model_name": p.model_name,
                "is_configured": p.is_configured(),
                "is_active": pid == self._active_provider,
                "supports_tools": info.get("supports_tools", False),
                "supports_thinking": info.get("supports_thinking", False),
                "available_models": info.get("models", []),
                "env_key": info.get("env_key", ""),
                "docs": info.get("docs", ""),
                "has_base_url": bool(p.base_url),
            })
        return result

    def get_provider(self, provider_id: str) -> Optional[LLMProviderConfig]:
        return self._providers.get(provider_id)

    def get_active(self) -> Optional[LLMProviderConfig]:
        if not self._active_provider:
            return None
        return self._providers.get(self._active_provider)

    def set_active(self, provider_id: str) -> bool:
        if provider_id in self._providers:
            self._active_provider = provider_id
            self.save()
            return True
        return False

    def update_provider(self, provider_id: str, config: Dict) -> bool:
        """更新提供商配置"""
        if provider_id not in self._providers:
            self._providers[provider_id] = LLMProviderConfig(provider=provider_id)
        p = self._providers[provider_id]
        for k, v in config.items():
            if hasattr(p, k) and k != "provider":
                setattr(p, k, v)
        self.save()
        return True

    def has_active_llm(self) -> bool:
        active = self.get_active()
        return active is not None and active.is_configured()


# ===========================================
# 构建 AgentScope 模型实例
# ===========================================
def build_agentscope_model(config: LLMProviderConfig):
    """
    根据 LLMProviderConfig 构建对应的 AgentScope 模型实例
    参考: https://doc.agentscope.io/zh_CN/tutorial/task_model.html
    """
    if not config.is_configured():
        return None

    try:
        if config.provider == "dashscope":
            from agentscope.model import DashScopeChatModel
            from agentscope.credential import DashScopeCredential
            from agentscope.formatter import DashScopeChatFormatter
            cred = DashScopeCredential(
                api_key=config.api_key,
                base_url=config.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            return DashScopeChatModel(
                credential=cred,
                model=config.model_name,
                stream=config.stream,
                formatter=DashScopeChatFormatter(),
            )

        elif config.provider in ("openai", "openai_compatible"):
            from agentscope.model import OpenAIChatModel
            from agentscope.credential import OpenAICredential
            from agentscope.formatter import OpenAIChatFormatter
            cred = OpenAICredential(
                api_key=config.api_key or "EMPTY",
                base_url=config.base_url if config.provider == "openai_compatible" else None,
            )
            return OpenAIChatModel(
                credential=cred,
                model=config.model_name,
                stream=config.stream,
                formatter=OpenAIChatFormatter(),
                client_kwargs={"base_url": config.base_url} if config.base_url else None,
            )

        elif config.provider == "anthropic":
            from agentscope.model import AnthropicChatModel
            from agentscope.credential import AnthropicCredential
            from agentscope.formatter import AnthropicChatFormatter
            cred = AnthropicCredential(api_key=config.api_key)
            return AnthropicChatModel(
                credential=cred,
                model=config.model_name,
                stream=config.stream,
                formatter=AnthropicChatFormatter(),
            )

        elif config.provider == "gemini":
            from agentscope.model import GeminiChatModel
            from agentscope.credential import GeminiCredential
            from agentscope.formatter import GeminiChatFormatter
            cred = GeminiCredential(api_key=config.api_key)
            return GeminiChatModel(
                credential=cred,
                model=config.model_name,
                stream=config.stream,
                formatter=GeminiChatFormatter(),
            )

        elif config.provider == "ollama":
            from agentscope.model import OllamaChatModel
            from agentscope.credential import OllamaCredential
            from agentscope.formatter import OllamaChatFormatter
            cred = OllamaCredential(base_url=config.base_url or "http://localhost:11434")
            return OllamaChatModel(
                credential=cred,
                model=config.model_name,
                stream=config.stream,
                formatter=OllamaChatFormatter(),
            )

    except Exception as e:
        print(f"[build_agentscope_model] {config.provider}: {e}")
        return None

    return None
