import requests
import traceback
import json
import time
import os
from src.config_manager import ConfigManager

class OllamaTranslator:
    def __init__(self, model_name=None):
        self.base_url = "http://localhost:11434"
        if not model_name:
            config_manager = ConfigManager()
            model_name = config_manager.get_ollama_model()
        self.model = model_name
        
        # 临时禁用代理设置
        self.original_http_proxy = os.environ.get('http_proxy')
        self.original_https_proxy = os.environ.get('https_proxy')
        os.environ.pop('http_proxy', None)
        os.environ.pop('https_proxy', None)
        
        # 检查 Ollama 服务是否运行
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                raise Exception("Ollama 服务未正常运行")
            
            # 检查模型是否可用
            models = response.json().get('models', [])
            model_names = [m.get('name') for m in models]
            print(f"可用模型: {model_names}")
            
            if self.model not in model_names:
                print(f"警告: 模型 {self.model} 不在可用列表中")
                # 尝试拉取模型
                print(f"正在拉取模型 {self.model}...")
                pull_response = requests.post(
                    f"{self.base_url}/api/pull",
                    json={"name": self.model}
                )
                if pull_response.status_code != 200:
                    raise Exception(f"拉取模型失败: {pull_response.status_code}")
                print("模型拉取成功")
                
        except requests.ConnectionError:
            raise Exception("无法连接到 Ollama 服务，请确保服务已启动")
        
    def translate(self, text, timeout=90):
        """调用Ollama API进行翻译"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # 根据不同模型调整提示词
                if "llama" in self.model.lower():
                    prompt = f"Translate to Chinese:\n{text}"
                else:
                    prompt = f"请将下面的句子翻译为中文：{text}"
                
                # 确保不使用代理
                session = requests.Session()
                session.trust_env = False
                
                response = session.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,  # 使用实际选择的模型
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=timeout
                )
                
                if response.status_code == 200:
                    result = response.json().get("response", "")
                    return result
                else:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    raise Exception(f"API错误: {response.status_code}")
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                raise
                
    def __del__(self):
        # 恢复原始代理设置
        if self.original_http_proxy:
            os.environ['http_proxy'] = self.original_http_proxy
        if self.original_https_proxy:
            os.environ['https_proxy'] = self.original_https_proxy 