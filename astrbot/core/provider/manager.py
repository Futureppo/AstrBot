import traceback
from astrbot.core.config.astrbot_config import AstrBotConfig
from .provider import Provider, STTProvider
from .entites import ProviderType
from typing import List
from astrbot.core.db import BaseDatabase
from collections import defaultdict
from .register import provider_cls_map, llm_tools
from astrbot.core import logger, sp

class ProviderManager():
    def __init__(self, config: AstrBotConfig, db_helper: BaseDatabase):
        self.providers_config: List = config['provider']
        self.provider_settings: dict = config['provider_settings']
        self.provider_stt_settings: dict = config.get('provider_stt_settings', {})
        
        self.provider_insts: List[Provider] = []
        '''加载的 Provider 的实例'''
        self.stt_provider_insts: List[STTProvider] = []
        '''加载的 Speech To Text Provider 的实例'''
        self.llm_tools = llm_tools
        self.curr_provider_inst: Provider = None
        '''当前使用的 Provider 实例'''
        self.curr_stt_provider_inst: STTProvider = None
        '''当前使用的 Speech To Text Provider 实例'''
        self.loaded_ids = defaultdict(bool)
        self.db_helper = db_helper
        
        self.curr_kdb_name = ""
        kdb_cfg = config.get("knowledge_db", {})
        if kdb_cfg and len(kdb_cfg):
            self.curr_kdb_name = list(kdb_cfg.keys())[0]
        
        for provider_cfg in self.providers_config:
            if not provider_cfg['enable']:
                continue
            
            if provider_cfg['id'] in self.loaded_ids:
                raise ValueError(f"Provider ID 重复：{provider_cfg['id']}。")
            self.loaded_ids[provider_cfg['id']] = True
            
            match provider_cfg['type']:
                case "openai_chat_completion":
                    from .sources.openai_source import ProviderOpenAIOfficial # noqa: F401
                case "zhipu_chat_completion":
                    from .sources.zhipu_source import ProviderZhipu # noqa: F401
                case "llm_tuner":
                    logger.info("加载 LLM Tuner 工具 ...")
                    from .sources.llmtuner_source import LLMTunerModelLoader # noqa: F401
                case "dify":
                    from .sources.dify_source import ProviderDify # noqa: F401
                case "googlegenai_chat_completion":
                    from .sources.gemini_source import ProviderGoogleGenAI # noqa: F401
                case "openai_whisper_api":
                    from .sources.whisper_api_source import ProviderOpenAIWhisperAPI # noqa: F401
                    
            
    async def initialize(self):
        for provider_config in self.providers_config:
            if not provider_config['enable']:
                continue
            if provider_config['type'] not in provider_cls_map:
                logger.error(f"未找到适用于 {provider_config['type']}({provider_config['id']}) 的提供商适配器，请检查是否已经安装或者名称填写错误。已跳过。")
                continue
            selected_provider_id = sp.get("curr_provider")
            selected_stt_provider_id = self.provider_stt_settings.get("provider_id")
            
            provider_metadata = provider_cls_map[provider_config['type']]
            logger.info(f"尝试实例化 {provider_config['type']}({provider_config['id']}) 提供商适配器 ...")
            try:
                # 按任务实例化提供商
                
                if provider_metadata.provider_type == ProviderType.SPEECH_TO_TEXT:
                    # STT 任务
                    inst = provider_metadata.cls_type(provider_config, self.provider_settings)
                    self.stt_provider_insts.append(inst)
                    if selected_stt_provider_id == provider_config['id']:
                        self.curr_stt_provider_inst = inst
                        logger.info(f"已选择 {provider_config['type']}({provider_config['id']}) 作为当前语音转文本提供商适配器。")
                    
                elif provider_metadata.provider_type == ProviderType.CHAT_COMPLETION:
                    # 文本生成任务
                    inst = provider_metadata.cls_type(provider_config, self.provider_settings, self.db_helper, self.provider_settings.get('persistant_history', True))
                    self.provider_insts.append(inst)
                    if selected_provider_id == provider_config['id']:
                        self.curr_provider_inst = inst
                        logger.info(f"已选择 {provider_config['type']}({provider_config['id']}) 作为当前提供商适配器。")
                        
            except Exception as e:
                traceback.print_exc()
                logger.error(f"实例化 {provider_config['type']}({provider_config['id']}) 提供商适配器失败：{e}")
        
        if len(self.provider_insts) > 0 and not self.curr_provider_inst:
            self.curr_provider_inst = self.provider_insts[0]
            
        if len(self.stt_provider_insts) > 0 and not self.curr_stt_provider_inst:
            self.curr_stt_provider_inst = self.stt_provider_insts[0]
            
        if not self.curr_provider_inst:
            logger.warning("未启用任何用于 文本生成 的提供商适配器。")
        if self.provider_stt_settings.get("enable"):
            if not self.curr_stt_provider_inst:
                logger.warning("未启用任何用于 语音转文本 的提供商适配器。")

    def get_insts(self):
        return self.provider_insts
    
    async def terminate(self):
        for provider_inst in self.provider_insts:
            if hasattr(provider_inst, "terminate"):
                await provider_inst.terminate()