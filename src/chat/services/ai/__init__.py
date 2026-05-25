# -*- coding: utf-8 -*-
"""
AI 服务模块 - 多端点支持的统一 AI 服务

此模块提供统一的 AI 服务接口，支持多种后端：
- Gemini 官方 API
- Gemini 自定义端点
- DeepSeek API
- OpenAI 兼容端点
"""
from importlib import import_module

_EXPORTS = {
    "AIService": (".service", "AIService"),
    "ai_service": (".service", "ai_service"),
    "BaseProvider": (".providers.base", "BaseProvider"),
    "GenerationConfig": (".providers.base", "GenerationConfig"),
    "GenerationResult": (".providers.base", "GenerationResult"),
    "FinishReason": (".providers.base", "FinishReason"),
    "ToolCall": (".providers.base", "ToolCall"),
    "ProviderInfo": (".providers.base", "ProviderInfo"),
    "AIServiceError": (".providers.base", "AIServiceError"),
    "ProviderNotAvailableError": (".providers.base", "ProviderNotAvailableError"),
    "ModelNotSupportedError": (".providers.base", "ModelNotSupportedError"),
    "GenerationError": (".providers.base", "GenerationError"),
    "GeminiProvider": (".providers.gemini_provider", "GeminiProvider"),
    "GeminiCustomProvider": (".providers.gemini_provider", "GeminiCustomProvider"),
    "DeepSeekProvider": (".providers.deepseek_provider", "DeepSeekProvider"),
    "OpenAICompatibleProvider": (
        ".providers.openai_provider",
        "OpenAICompatibleProvider",
    ),
    "ProviderConfig": (".config.providers", "ProviderConfig"),
    "get_provider_configs": (".config.providers", "get_provider_configs"),
    "ModelConfig": (".config.models", "ModelConfig"),
    "get_model_configs": (".config.models", "get_model_configs"),
    "FALLBACK_PRIORITY": (".config.models", "FALLBACK_PRIORITY"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    # 核心服务
    "AIService",
    "ai_service",
    # 基类和数据类
    "BaseProvider",
    "GenerationConfig",
    "GenerationResult",
    "FinishReason",
    "ToolCall",
    "ProviderInfo",
    # 错误类
    "AIServiceError",
    "ProviderNotAvailableError",
    "ModelNotSupportedError",
    "GenerationError",
    # Provider 实现
    "GeminiProvider",
    "GeminiCustomProvider",
    "DeepSeekProvider",
    "OpenAICompatibleProvider",
    # 配置
    "ProviderConfig",
    "get_provider_configs",
    "ModelConfig",
    "get_model_configs",
    "FALLBACK_PRIORITY",
]
