import queue
import threading
import time
import traceback
from src.core.config import config

class Translator:
    def __init__(self):
        self.translation_queue = queue.Queue()
        self.should_stop = False
        self.worker_thread = None
        self.callback = None
        self.current_model = None
        self.using_deepseek = False
        self.deepseek_translator = None
        self.ollama_translator = None

    def start_translation_worker(self, callback, using_deepseek=False,
                               deepseek_translator=None, ollama_translator=None):
        """启动翻译工作线程"""
        try:
            if self.worker_thread and self.worker_thread.is_alive():
                print("翻译工作线程已在运行")
                return False

            self.callback = callback
            # 从配置管理器获取当前模型
            self.current_model = config.get_model()
            self.using_deepseek = using_deepseek
            self.deepseek_translator = deepseek_translator
            self.ollama_translator = ollama_translator
            self.should_stop = False

            # 清空队列
            while not self.translation_queue.empty():
                try:
                    self.translation_queue.get_nowait()
                except queue.Empty:
                    break

            # 创建并启动工作线程
            self.worker_thread = threading.Thread(target=self._translation_worker, daemon=True)
            self.worker_thread.start()
            print("翻译工作线程已启动")
            return True

        except Exception as e:
            print(f"启动翻译工作线程错误: {str(e)}")
            print(traceback.format_exc())
            return False

    def _translation_worker(self):
        """翻译工作线程"""
        try:
            while not self.should_stop:
                try:
                    # 从队列获取翻译任务，设置超时以便定期检查停止标志
                    item = self.translation_queue.get(timeout=1)
                    text_to_translate, original_text = item

                    if self.should_stop:
                        break

                    # 记录开始时间
                    start_time = time.time()

                    try:
                        # 根据设置选择翻译器
                        if self.using_deepseek and self.deepseek_translator:
                            translated_text = self.deepseek_translator.translate(text_to_translate)
                        elif self.ollama_translator:
                            translated_text = self.ollama_translator.translate(text_to_translate)
                        else:
                            raise Exception("没有可用的翻译器")

                        # 计算耗时
                        elapsed_time = time.time() - start_time

                        # 调用回调函数
                        if self.callback:
                            self.callback(
                                translated_text,
                                original_text=original_text,
                                estimated_time=0,
                                current_time=elapsed_time
                            )

                    except Exception as e:
                        print(f"翻译错误: {str(e)}")
                        if self.callback:
                            self.callback(None, error=str(e), original_text=original_text)

                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"工作线程错误: {str(e)}")
                    print(traceback.format_exc())
                    if self.callback:
                        self.callback(None, error=str(e))

        except Exception as e:
            print(f"翻译工作线程异常: {str(e)}")
            print(traceback.format_exc())
            if self.callback:
                self.callback(None, error=str(e))

    def add_to_queue(self, translation_item):
        """添加翻译任务到队列"""
        if not self.should_stop:
            self.translation_queue.put(translation_item)

    def stop_translation(self):
        """停止翻译"""
        try:
            self.should_stop = True
            
            # 清空队列
            while not self.translation_queue.empty():
                try:
                    self.translation_queue.get_nowait()
                except queue.Empty:
                    break
            
            # 等待工作线程结束
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=2)
            
            return True
        except Exception as e:
            print(f"停止翻译错误: {str(e)}")
            print(traceback.format_exc())
            return False 