# -*- coding: utf-8 -*-
"""
AI 服务配置模块
"""
from importlib import import_module

_EXPORTS = {
    "ProviderConfig": (".providers", "ProviderConfig"),
    "get_provider_configs": (".providers", "get_provider_configs"),
    "ModelConfig": (".models", "ModelConfig"),
    "PromptConfig": (".models", "PromptConfig"),
    "GenerationConfigParams": (".models", "GenerationConfigParams"),
    "SupportedParam": (".models", "SupportedParam"),
    "PROVIDER_SUPPORTED_PARAMS": (".models", "PROVIDER_SUPPORTED_PARAMS"),
    "get_model_configs": (".models", "get_model_configs"),
    "get_model_config": (".models", "get_model_config"),
    "get_generation_config": (".models", "get_generation_config"),
    "get_prompt_config": (".models", "get_prompt_config"),
    "get_supported_params_for_provider": (
        ".models",
        "get_supported_params_for_provider",
    ),
    "reload_model_configs": (".models", "reload_model_configs"),
    "FALLBACK_PRIORITY": (".models", "FALLBACK_PRIORITY"),
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
    "ProviderConfig",
    "get_provider_configs",
    "ModelConfig",
    "PromptConfig",
    "GenerationConfigParams",
    "SupportedParam",
    "PROVIDER_SUPPORTED_PARAMS",
    "get_model_configs",
    "get_model_config",
    "get_generation_config",
    "get_prompt_config",
    "get_supported_params_for_provider",
    "reload_model_configs",
    "FALLBACK_PRIORITY",
]
