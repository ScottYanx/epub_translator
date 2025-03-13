from openai import OpenAI
import os
import traceback
import httpx
import time
import ssl

class DeepSeekTranslator:
    def __init__(self, api_key=None, target_language='zh'):
        print("初始化 DeepSeek 翻译器...")
        self.api_key = api_key
        self.target_language = target_language
        
        # 语言映射
        self.language_map = {
            'zh': '中文',
            'en': '英文',
            'ja': '日文',
            'fr': '法文',
            'de': '德文'
        }
        
        if not self.api_key:
            print("警告：未设置 DeepSeek API Key")
            return
            
        print(f"使用 API Key: {self.api_key[:8]}...")
        print(f"目标语言: {self.language_map.get(self.target_language, '未知')}")
        
        try:
            # 禁用 SSL 验证
            ssl._create_default_https_context = ssl._create_unverified_context
            
            # 创建自定义的 httpx 客户端
            transport = httpx.HTTPTransport(
                retries=3,
                verify=False
            )
            
            # 设置代理（如果需要）
            proxy_url = "http://127.0.0.1:7890"
            
            # 创建客户端，使用环境变量设置代理
            os.environ['http_proxy'] = proxy_url
            os.environ['https_proxy'] = proxy_url
            
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepseek.com/v1",
                http_client=httpx.Client(
                    transport=transport,
                    timeout=30.0
                )
            )
            print("OpenAI 客户端初始化成功")
        except Exception as e:
            print(f"OpenAI 客户端初始化失败: {str(e)}")
            print(traceback.format_exc())
            
    def translate(self, text):
        """使用 DeepSeek API 翻译文本"""
        if not hasattr(self, 'client'):
            raise Exception("翻译器未正确初始化")
            
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                print(f"准备翻译文本 (尝试 {retry_count + 1}/{max_retries}): {text[:100]}...")
                
                target_lang = self.language_map.get(self.target_language, '中文')
                system_prompt = f"你是一个翻译助手。请将用户输入的英文文本翻译成{target_lang}，只返回翻译结果，不要包含原文或其他解释。"
                
                print("发送请求到 DeepSeek API...")
                response = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    stream=False,
                    temperature=0.3,
                    max_tokens=2000
                )
                print("收到 API 响应")
                
                result = response.choices[0].message.content
                print(f"翻译结果: {result}")
                return result
                
            except Exception as e:
                print(f"翻译尝试 {retry_count + 1} 失败: {str(e)}")
                print(f"错误详情: {traceback.format_exc()}")
                retry_count += 1
                if retry_count >= max_retries:
                    raise Exception(f"DeepSeek API 调用失败 (已重试 {max_retries} 次): {str(e)}")
                print(f"等待 2 秒后重试...")
                time.sleep(2) 