import json
import os

class ConfigManager:
    def __init__(self):
        # 使用绝对路径来存储配置文件
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        self.config = self.load_config()
        print(f"配置文件路径: {self.config_path}")  # 添加日志

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"加载配置: {config}")  # 添加日志
                    return config
            except Exception as e:
                print(f"加载配置失败: {str(e)}")  # 添加错误日志
                return self.get_default_config()
        return self.get_default_config()

    def save_config(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
            print(f"保存配置成功: {self.config}")  # 添加日志
            return True
        except Exception as e:
            print(f"保存配置失败: {str(e)}")  # 添加错误日志
            return False

    def get_default_config(self):
        return {
            "ollama_model": "deepseek-r1:14b"
        }

    def get_ollama_model(self):
        return self.config.get("ollama_model", "deepseek-r1:14b")

    def set_ollama_model(self, model_name):
        print(f"正在保存模型设置: {model_name}")
        self.config["ollama_model"] = model_name
        try:
            self.save_config()
            print(f"模型设置已保存到: {self.config_path}")
            return True
        except Exception as e:
            print(f"保存模型设置失败: {str(e)}")
            return False 