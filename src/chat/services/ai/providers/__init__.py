# -*- coding: utf-8 -*-
"""
AI Provider 模块 - 支持多种 AI 服务后端
"""
from importlib import import_module

_EXPORTS = {
    "BaseProvider": (".base", "BaseProvider"),
    "GenerationConfig": (".base", "GenerationConfig"),
    "GenerationResult": (".base", "GenerationResult"),
    "FinishReason": (".base", "FinishReason"),
    "ToolCall": (".base", "ToolCall"),
    "ProviderInfo": (".base", "ProviderInfo"),
    "AIServiceError": (".base", "AIServiceError"),
    "ProviderNotAvailableError": (".base", "ProviderNotAvailableError"),
    "ModelNotSupportedError": (".base", "ModelNotSupportedError"),
    "GenerationError": (".base", "GenerationError"),
    "GeminiProvider": (".gemini_provider", "GeminiProvider"),
    "GeminiCustomProvider": (".gemini_provider", "GeminiCustomProvider"),
    "DeepSeekProvider": (".deepseek_provider", "DeepSeekProvider"),
    "OpenAICompatibleProvider": (".openai_provider", "OpenAICompatibleProvider"),
    "ProviderFormat": (".provider_format", "ProviderFormat"),
    "MessageFormat": (".provider_format", "MessageFormat"),
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
    # 基类
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
    # 格式常量
    "ProviderFormat",
    "MessageFormat",
]
