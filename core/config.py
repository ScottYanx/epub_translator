from PyQt6.QtCore import QSettings
import subprocess

class Config:
    def __init__(self):
        self.settings = QSettings('EPUBTranslator', 'Settings')
        # 初始化时检查并设置默认模型
        if not self.settings.value('model'):
            self._init_default_model()
    
    def _init_default_model(self):
        """检测并设置默认模型"""
        try:
            # 检测本地安装的 Ollama 模型
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                # 获取第一个可用的模型
                models = []
                for line in result.stdout.strip().split('\n')[1:]:
                    if line.strip():
                        model_name = line.split()[0]
                        models.append(model_name)
                
                if models:
                    # 设置第一个检测到的模型为默认值
                    self.settings.setValue('model', models[0])
                    return
        except Exception as e:
            print(f"检测 Ollama 模型失败: {str(e)}")
        
        # 如果检测失败，设置一个通用的默认值
        self.settings.setValue('model', 'mistral')
    
    def get_model(self):
        """获取当前配置的模型"""
        return self.settings.value('model')
    
    def set_model(self, model_name):
        """设置当前使用的模型"""
        self.settings.setValue('model', model_name)
    
    def get_target_language(self):
        """获取目标语言"""
        return self.settings.value('target_language', 'zh')
    
    def set_target_language(self, language):
        """设置目标语言"""
        self.settings.setValue('target_language', language)

# 创建全局配置实例
config = Config() 