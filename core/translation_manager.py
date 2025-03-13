from pathlib import Path
import json
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import sqlite3

class TranslationManager:
    def __init__(self, epub_path):
        self.epub_path = epub_path
        # 添加 API 类型标记（移到最前面）
        self.current_api = "ollama"  # 默认使用 ollama
        # 然后再获取缓存文件路径
        self.cache_file = self._get_cache_file_path()
        self.translations = self._load_translations()
        
    def _get_cache_file_path(self):
        """获取缓存文件路径，为不同API使用不同的缓存文件"""
        cache_dir = Path.home() / "AppData" / "Local" / "EPUBTranslator" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        epub_name = Path(self.epub_path).stem
        # 根据当前API类型选择缓存文件
        cache_name = f"{epub_name}_{self.current_api}_translations.json"
        return cache_dir / cache_name
        
    def switch_api(self, api_type):
        """切换API类型，重新加载对应的缓存"""
        self.current_api = api_type
        self.cache_file = self._get_cache_file_path()
        self.translations = self._load_translations()
        
    def _load_translations(self):
        """加载翻译记录"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
        
    def save_translation_record(self):
        """保存翻译记录"""
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.translations, f, ensure_ascii=False, indent=2)
            
    def get_cached_translation(self, text):
        """获取缓存的翻译"""
        return self.translations.get(text)
        
    def add_translation(self, original, translated):
        """添加新的翻译"""
        self.translations[original] = translated
        self.save_translation_record()
        
        # 更新译本
        self.update_translation_epub(original, translated)
        
    def update_translation_epub(self, original, translated):
        """更新译本EPUB文件"""
        try:
            # 如果译本不存在，先复制原文件
            if not self.epub_path.exists():
                import shutil
                shutil.copy2(self.epub_path, self.epub_path)
            
            # 打开译本
            book = epub.read_epub(str(self.epub_path))
            
            # 遍历所有文档
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                content = item.get_content().decode('utf-8')
                if original in content:
                    # 在原文后添加译文
                    soup = BeautifulSoup(content, 'html.parser')
                    for element in soup.find_all(text=True):
                        if original in element.string:
                            new_text = element.string.replace(
                                original,
                                f"{original}\n【译文】{translated}"
                            )
                            element.string.replace_with(new_text)
                    
                    # 更新内容
                    item.set_content(str(soup).encode('utf-8'))
            
            # 保存译本
            epub.write_epub(str(self.epub_path), book)
            
        except Exception as e:
            print(f"更新译本错误: {str(e)}") 
        
    def remove_translation(self, original_text):
        """删除指定原文的翻译缓存"""
        try:
            # 从翻译记录中删除
            if original_text in self.translations:
                del self.translations[original_text]
                # 保存更新后的记录
                self.save_translation_record()
                print(f"已删除缓存: {original_text[:50]}...")
        except Exception as e:
            print(f"删除翻译缓存错误: {str(e)}") 