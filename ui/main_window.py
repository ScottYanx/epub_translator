from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                           QPushButton, QFileDialog, QLabel, QTextEdit,
                           QSpinBox, QSplitter, QLineEdit, QComboBox, QToolTip,
                           QApplication, QMessageBox, QDialog, QTreeWidget, QTreeWidgetItem,
                           QTextBrowser, QFontComboBox, QGroupBox, QScrollArea, QToolBar)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QSettings, QLocale, QTranslator
from PyQt6.QtGui import (QIntValidator, QTextCharFormat, QColor, QTextCursor, QTextDocument,
                        QClipboard, QFont, QAction)  # 添加 QAction 到 QtGui 导入
from src.ui.progress_widget import ProgressWidget
from src.core.epub_handler import EpubHandler
from src.core.translator import Translator
from bs4 import BeautifulSoup
import traceback
import sys
import os
import ebooklib
from threading import Thread
import time
from src.ui.bookshelf_window import BookshelfWindow
from pathlib import Path
import shutil
from src.core.translation_manager import TranslationManager
import difflib
import subprocess
import webbrowser
from PyQt6.QtGui import QIcon
import queue
import requests
from src.translate.deepseek_translator import DeepSeekTranslator
from src.translate.ollama_translator import OllamaTranslator
from src.core.config import config
from src.config_manager import ConfigManager

# 创建一个信号发射器类
class TranslationSignals(QObject):
    # 定义信号
    progress = pyqtSignal(str, str)      # 用于更新翻译进度 (原文, 译文)
    error = pyqtSignal(str)              # 用于显示错误
    finished = pyqtSignal()              # 用于通知翻译完成
    highlight = pyqtSignal(str)          # 用于高亮显示
    clear_highlight = pyqtSignal()       # 用于清除高亮
    update_html = pyqtSignal(str)        # 用于更新HTML内容
    update_analysis = pyqtSignal(str)     # 用于更新AI分析结果
    clear_generating_status = pyqtSignal() # 用于清除生成状态提示

class MainWindow(QMainWindow):
    # 添加一个新的信号用于设置计时器
    set_timer = pyqtSignal()
    
    # 添加新的信号
    update_translation_signal = pyqtSignal(str, str, float, float)  # 译文, 原文, 预计时间, 当前时间
    update_progress_signal = pyqtSignal(int, int, float, float)    # 当前进度, 总进度, 预计时间, 当前时间
    translation_error_signal = pyqtSignal(str)                     # 错误信息
    translation_complete_signal = pyqtSignal()                     # 翻译完成信号
    show_analysis_signal = pyqtSignal(str)  # 用于显示分析结果
    show_error_signal = pyqtSignal(str)     # 用于显示错误
    close_wait_dialog_signal = pyqtSignal()  # 用于关闭等待对话框
    update_analysis_signal = pyqtSignal(str)     # 用于更新AI分析结果
    clear_generating_status_signal = pyqtSignal() # 用于清除生成状态提示
    update_status_signal = pyqtSignal(str, str)  # (status_type, message)
    
    # 添加支持的语言列表
    SUPPORTED_UI_LANGUAGES = ['zh', 'en', 'ja', 'fr', 'de']
    SUPPORTED_TARGET_LANGUAGES = ['zh', 'en', 'ja', 'fr', 'de']
    
    def __init__(self):
        super().__init__()
        self.signals = TranslationSignals()
        self.config_manager = ConfigManager()
        
        # 初始化设置
        self.settings = QSettings('EPUBTranslator', 'Settings')
        self.target_language = self.settings.value('target_language', 'zh')
        self.ui_language = self.settings.value('ui_language', 'zh')
        
        # 创建模型选择下拉框
        self.model_combo = QComboBox()
        
        # 从配置管理器获取模型设置
        self.model = self.config_manager.get_ollama_model()
        print(f"当前使用的模型: {self.model}")
        
        # 检查可用模型并更新下拉框
        try:
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            if result.returncode == 0:
                models = []
                for line in result.stdout.strip().split('\n')[1:]:
                    if line.strip():
                        model_name = line.split()[0]
                        models.append(model_name)
                
                if models:
                    print(f"可用模型: {models}")
                    self.model_combo.addItems(models)
                    
                    # 如果配置的模型不在可用列表中，使用第一个可用模型
                    if self.model not in models:
                        print(f"警告: 模型 {self.model} 不在可用列表中")
                        self.model = models[0]
                        self.config_manager.set_ollama_model(self.model)
                    
                    # 设置当前选择的模型
                    index = self.model_combo.findText(self.model)
                    if index >= 0:
                        self.model_combo.setCurrentIndex(index)
        except Exception as e:
            print(f"检查可用模型失败: {e}")
        
        # 初始化翻译器相关属性
        self.deepseek_api_key = self.settings.value('deepseek_api_key', '')
        self.using_deepseek = False  # 默认不使用 DeepSeek
        self.deepseek_translator = None
        self.ollama_translator = None
        
        # 从设置中获取上次使用的模型,如果没有则使用默认值
        self.model = self.settings.value('model', 'deepseek-r1:14b')  # 从设置中读取默认值
        
        # 如果没有保存的模型设置,等待 model_combo 初始化后再设置
        if not self.model:
            QTimer.singleShot(0, self.init_default_model)
        
        # 设置窗口属性
        self.setWindowTitle("EPUB Translator")
        self.setMinimumSize(1200, 800)
        self.showMaximized()
        
        # 连接基本信号
        self.signals.error.connect(self.show_error)
        self.signals.finished.connect(self.translation_finished)
        self.signals.highlight.connect(self.highlight_paragraph)
        self.signals.clear_highlight.emit()
        self.signals.update_html.connect(self.update_html_content)
        
        self.update_translation_signal.connect(self._update_translation_text)
        self.update_progress_signal.connect(self._update_progress)
        self.translation_error_signal.connect(self.show_error)
        self.translation_complete_signal.connect(self._on_translation_complete)
        self.show_analysis_signal.connect(self.show_analysis_result)
        self.show_error_signal.connect(self.show_error_dialog)
        self.close_wait_dialog_signal.connect(
            lambda: self.wait_dialog.accept() if hasattr(self, 'wait_dialog') else None
        )
        self.update_analysis_signal.connect(self.update_analysis_result)
        self.clear_generating_status_signal.connect(self.clear_generating_status)
        self.update_status_signal.connect(self.update_status)
        
        # 初始化界面翻译器
        self.ui_translator = QTranslator()
        if self.ui_language != 'zh':
            if self.ui_translator.load(f"translations/epub_translator_{self.ui_language}"):
                QApplication.installTranslator(self.ui_translator)
        
        # 初始化文本翻译器
        self.text_translator = Translator()
        
        # 创建主窗口布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建所有按钮
        self.create_buttons()
        
        # 连接按钮信号
        self.connect_button_signals()
        
        # 创建布局
        self.create_layout(layout)
        
        # 初始化其他属性
        self.current_page = 0
        self.pages = []
        self.translation_pairs = []
        self.text_positions = {}
        
        # 创建计时器
        self.highlight_timer = QTimer(self)
        self.highlight_timer.setSingleShot(True)
        self.highlight_timer.timeout.connect(self.clear_highlight)
        
        self.translation_manager = None
        
        # 设置窗口样式
        self.setup_styles()
        
        # 添加字体设置相关属性
        self.font_family = self.settings.value('font_family', 'Microsoft YaHei')
        self.font_size = int(self.settings.value('font_size', 12))
        
        # 设置状态栏
        self.setup_status_bar()
        
        # 尝试初始化翻译器
        try:
            # 从 model_combo 获取当前选择的模型
            current_model = self.model_combo.currentText()
            print(f"Initializing Ollama translator with model: {current_model}")
            
            # 初始化 Ollama 翻译器
            self.ollama_translator = OllamaTranslator(model_name=current_model)
            print("Ollama translator initialized successfully")
            
            # 如果有 DeepSeek API key，也初始化 DeepSeek
            if self.deepseek_api_key:
                self.deepseek_translator = DeepSeekTranslator(
                    api_key=self.deepseek_api_key,
                    target_language=self.target_language
                )
                self.using_deepseek = True
                print("DeepSeek translator initialized successfully")
        except Exception as e:
            print(f"Failed to initialize translators: {e}")
            self.status_bar_api.setText(f"翻译器初始化失败: {str(e)}")

        # 初始化UI后自动检测Ollama模型
        QTimer.singleShot(0, self.check_ollama_models)

        # 在初始化时创建组件
        self.settings_model_combo = QComboBox()

        # 直接使用配置的模型初始化翻译器
        try:
            self.ollama_translator = OllamaTranslator(model_name=self.model)
            print(f"使用模型 {self.model} 初始化翻译器成功")
        except Exception as e:
            print(f"初始化翻译器失败: {e}")

    def init_default_model(self):
        """初始化默认模型"""
        # 不再依赖 settings_model_combo
        if not hasattr(self, 'model') or not self.model:
            self.model = 'deepseek-r1:14b'  # 使用默认值
            self.settings.setValue('model', self.model)

    def init_translator(self):
        """初始化翻译器"""
        try:
            if self.using_deepseek:
                if not self.deepseek_api_key:
                    raise Exception("DeepSeek API Key 未设置")
                self.deepseek_translator = DeepSeekTranslator(
                    api_key=self.deepseek_api_key,
                    target_language=self.target_language
                )
                self.translator = self.deepseek_translator  # 同时设置通用翻译器
            else:
                self.ollama_translator = OllamaTranslator(model_name=self.model)
                self.translator = self.ollama_translator  # 同时设置通用翻译器
                
            self.status_bar_api.setText(f"API: {'DeepSeek' if self.using_deepseek else 'Ollama'}")
        except Exception as e:
            self.status_bar_api.setText(f"翻译器初始化失败: {str(e)}")
            raise e  # 抛出异常以便上层处理

    def create_buttons(self):
        """创建所有按钮"""
        # 文件组按钮
        self.bookshelf_btn = QPushButton("我的书架")
        self.file_btn = QPushButton("选择EPUB文件")
        self.toc_btn = QPushButton("查看目录")
        self.search_button = QPushButton("搜索原文")
        self.ai_reading_btn = QPushButton("AI导读")
        self.settings_btn = QPushButton("设置")
        
        # 翻译控制按钮
        self.translate_page_btn = QPushButton("翻译当前页")
        self.translate_book_btn = QPushButton("翻译整本")
        self.translate_book_btn.hide()  # 隐藏整本翻译按钮
        self.stop_translation_btn = QPushButton("停止翻译")
        self.restart_translation_btn = QPushButton("重新翻译")
        self.copy_btn = QPushButton("复制译文")
        
        # 导航按钮
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(50)
        self.page_edit.setValidator(QIntValidator())
        self.total_pages_label = QLabel("/ 0")
        
        # 设置初始状态
        self.toc_btn.setEnabled(False)
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.page_edit.setEnabled(False)
        self.translate_page_btn.setEnabled(False)
        self.translate_book_btn.setEnabled(False)
        self.ai_reading_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.stop_translation_btn.setEnabled(False)
        self.restart_translation_btn.setEnabled(False)
        
        # AI导读按钮使用紫色样式
        self.ai_reading_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #6C5CE7, stop:1 #A17FE0);
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #A17FE0, stop:1 #6C5CE7);
            }
        """)
        
        # 立即初始化翻译器
        try:
            current_model = self.model_combo.currentText()
            print(f"Initializing Ollama translator with model: {current_model}")
            self.ollama_translator = OllamaTranslator(model_name=current_model)
            print("Ollama translator initialized successfully")
        except Exception as e:
            print(f"Failed to initialize Ollama translator: {e}")

    def connect_button_signals(self):
        """连接所有按钮信号"""
        self.bookshelf_btn.clicked.connect(self.show_bookshelf)
        self.file_btn.clicked.connect(self.select_file)
        self.toc_btn.clicked.connect(self.show_toc)
        self.search_button.clicked.connect(self.search_original_text)
        self.ai_reading_btn.clicked.connect(self.show_ai_reading)
        self.translate_page_btn.clicked.connect(self.translate_current_page)
        self.translate_book_btn.clicked.connect(self.translate_whole_book)
        self.stop_translation_btn.clicked.connect(self.stop_translation)
        self.restart_translation_btn.clicked.connect(self.restart_translation)
        self.copy_btn.clicked.connect(self.copy_translation_to_clipboard)
        self.settings_btn.clicked.connect(self.show_settings_dialog)
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn.clicked.connect(self.next_page)
        self.page_edit.returnPressed.connect(self.goto_page)

    def check_ollama_installation(self):
        """检查Ollama是否已安装"""
        try:
            result = subprocess.run(["ollama", "version"], capture_output=True, text=True)
            if result.returncode == 0:
                self.progress_widget.update_status("Ollama已安装")
            else:
                self.progress_widget.update_status("Ollama未安装")
        except Exception as e:
            self.progress_widget.update_status(f"检查Ollama安装错误: {str(e)}")


        
    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择EPUB文件",
            "",
            "EPUB Files (*.epub)"
        )
        if file_name:
            # 复制文件到书架目录
            app_data_dir = Path.home() / "AppData" / "Local" / "EPUBTranslator"
            books_dir = app_data_dir / "books"
            books_dir.mkdir(parents=True, exist_ok=True)
            
            source_path = Path(file_name)
            dest_path = books_dir / source_path.name
            
            try:
                shutil.copy2(str(source_path), str(dest_path))
            except Exception as e:
                print(f"复制文件到书架错误: {str(e)}")
            
            self.current_file = str(dest_path)
            self.load_epub()
            
    def load_epub(self):
        """加载EPUB文件"""
        try:
            self.epub_handler = EpubHandler(self.current_file)
            self.book = self.epub_handler.book  # 保存book引用以便访问目录
            self.pages = self.epub_handler.extract_pages()
            
            # 更新 translation_manager 的路径
            self.translation_manager = TranslationManager(self.current_file)
            
            if self.pages:
                # 启用所有相关按钮
                self.prev_btn.setEnabled(True)
                self.next_btn.setEnabled(True)
                self.page_edit.setEnabled(True)
                self.translate_page_btn.setEnabled(True)
                self.translate_book_btn.setEnabled(True)
                self.toc_btn.setEnabled(True)
                self.ai_reading_btn.setEnabled(True)  # 启用AI导读按钮
                
                # 更新总页数
                self.total_pages_label.setText(f"/ {len(self.pages)}")
                
                # 显示第一页
                self.show_page(0)
        except Exception as e:
            print(f"加载EPUB错误: {str(e)}")
            print(traceback.format_exc())
        
    def prev_page(self):
        if self.current_page > 0:
            self.show_page(self.current_page - 1)
            
    def next_page(self):
        if self.current_page < len(self.pages) - 1:
            self.show_page(self.current_page + 1)
            
    def goto_page(self):
        try:
            page_num = int(self.page_edit.text()) - 1
            if 0 <= page_num < len(self.pages):
                self.show_page(page_num)
        except ValueError:
            pass
            
    def show_page(self, page_idx):
        """显示指定页面，并处理页面内的链接"""
        if 0 <= page_idx < len(self.pages):
            self.current_page = page_idx
            
            # 获取页面内容
            html_content = self.pages[page_idx]
            
            # 修改页面内的链接，使其可点击
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 处理所有链接
            for link in soup.find_all('a'):
                href = link.get('href')
                if href:
                    # 保持href属性不变，QTextBrowser会自动处理
                    link['href'] = href
            
            # 设置HTML内容
            self.original_text.setHtml(str(soup))
            
            # 更新页码
            self.page_edit.setText(str(page_idx + 1))
            
            # 更新导航按钮状态
            self.prev_btn.setEnabled(page_idx > 0)
            self.next_btn.setEnabled(page_idx < len(self.pages) - 1)

    def handle_link_click(self, url):
        """处理页面内链接点击"""
        try:
            href = url.toString()
            if href:
                page_index = self.find_page_by_href(href)
                if page_index is not None:
                    self.show_page(page_index)
        except Exception as e:
            print(f"处理链接点击错误: {str(e)}")
            print(traceback.format_exc())

    def highlight_paragraph(self, text):
        """高亮显示指定的段落"""
        # 在原文中高亮
        cursor = self.original_text.textCursor()
        cursor.setPosition(0)
        format = QTextCharFormat()
        format.setBackground(QColor("#6C5CE7"))  # 使用紫色背景
        format.setForeground(QColor("white"))    # 使用白色文字
        
        # 清除之前的高亮
        cursor = self.original_text.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        clear_format = QTextCharFormat()
        cursor.setCharFormat(clear_format)
        
        # 设置新的高亮
        if text:
            # 查找并高亮所有匹配的文本
            cursor = self.original_text.textCursor()
            cursor.setPosition(0)
            while True:
                cursor = self.original_text.document().find(text, cursor)
                if cursor.isNull():
                    break
                cursor.mergeCharFormat(format)
        
        # 在译文中高亮对应的翻译
        for original, translated in self.translation_pairs:
            if original.strip() == text.strip():
                cursor = self.translated_text.textCursor()
                cursor.setPosition(0)
                
                # 清除译文的之前高亮
                cursor = self.translated_text.textCursor()
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.setCharFormat(clear_format)
                
                # 高亮对应的译文
                cursor = self.translated_text.textCursor()
                cursor.setPosition(0)
                while True:
                    cursor = self.translated_text.document().find(translated, cursor)
                    if cursor.isNull():
                        break
                    cursor.mergeCharFormat(format)
                break

    def on_translated_text_hover(self, event):
        """处理鼠标悬停事件"""
        try:
            # 获取鼠标位置对应的文本光标
            cursor = self.translated_text.cursorForPosition(event.pos())
            pos = cursor.position()
            
            # 查找当前位置对应的文本
            for start_pos, info in self.text_positions.items():
                if start_pos <= pos <= info['end']:
                    # 显示悬浮窗
                    QToolTip.showText(
                        self.translated_text.mapToGlobal(event.pos()),
                        f"原文：{info['original']}",
                        self.translated_text
                    )
                    return
            
            # 如果不在任何文本范围内，隐藏悬浮窗
            QToolTip.hideText()
            
        except Exception as e:
            print(f"处理悬停事件错误: {str(e)}")
            print(traceback.format_exc())

    def on_translated_text_click(self, event):
        """处理译文点击事件"""
        try:
            # 先停止之前的定时器（如果存在）
            if hasattr(self, 'highlight_timer') and self.highlight_timer.isActive():
                self.highlight_timer.stop()
                
            # 清除之前的所有高亮
            self.clear_highlight()
            
            # 获取用户选中的文本
            cursor = self.translated_text.textCursor()
            selected_text = cursor.selectedText().strip()
            
            if not selected_text:
                return
            
            # 在翻译对中查找包含选中文本的译文
            for pair in self.translation_pairs:
                translated = pair['translated'].strip()
                # 如果译文包含选中的文本
                if selected_text.lower() in translated.lower():
                    # 设置高亮格式
                    format = QTextCharFormat()
                    format.setBackground(QColor("#6C5CE7"))
                    format.setForeground(QColor("white"))
                    
                    # 高亮原文
                    cursor = self.original_text.textCursor()
                    cursor.setPosition(0)
                    while True:
                        cursor = self.original_text.document().find(pair['original'], cursor)
                        if cursor.isNull():
                            break
                        cursor.mergeCharFormat(format)
                    
                    # 高亮译文
                    cursor = self.translated_text.textCursor()
                    cursor.setPosition(0)
                    while True:
                        cursor = self.translated_text.document().find(translated, cursor)
                        if cursor.isNull():
                            break
                        cursor.mergeCharFormat(format)
                    
                    # 滚动到原文位置
                    cursor = self.original_text.textCursor()
                    cursor.setPosition(0)
                    cursor = self.original_text.document().find(pair['original'], cursor)
                    if not cursor.isNull():
                        self.original_text.setTextCursor(cursor)
                        self.original_text.ensureCursorVisible()
                    
                    # 3秒后清除高亮
                    self.highlight_timer.start(3000)
                    
                    # 更新状态栏
                    self.status_bar_translation.setText("找到对应原文")
                    return  # 找到第一个匹配就返回
                    
            # 如果没有找到匹配
            self.status_bar_translation.setText("未找到对应原文")
                
        except Exception as e:
            print(f"处理译文选择错误: {str(e)}")
            print(traceback.format_exc())
            self.status_bar_translation.setText("搜索原文时出错")

    def highlight_and_scroll_to_original(self, translated_text):
        """根据选中的译文查找并高亮显示原文"""
        try:
            # 在翻译对中查找最匹配的原文
            best_match = None
            best_ratio = 0
            selected_text = translated_text.strip().lower()  # 规范化选中的文本
            
            for pair in self.translation_pairs:
                translated = pair['translated'].strip().lower()  # 规范化译文
                
                # 1. 完全包含匹配
                if selected_text in translated:
                    # 计算选中文本与完整译文的相似度
                    ratio = len(selected_text) / len(translated)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = pair['original']
                        continue
                
                # 2. 部分匹配（使用difflib进行模糊匹配）
                ratio = difflib.SequenceMatcher(None, translated, selected_text).ratio()
                if ratio > best_ratio and ratio > 0.6:  # 提高相似度阈值
                    best_ratio = ratio
                    best_match = pair['original']
            
            if best_match:
                print(f"找到匹配原文，相似度: {best_ratio}")
                # 高亮显示原文
                self.highlight_paragraph(best_match)
                # 滚动到原文位置
                self.scroll_to_text(best_match)
                # 设置延时清除高亮
                self.start_highlight_timer()
            else:
                print(f"未找到匹配原文，最高相似度: {best_ratio}")
                # 显示提示信息
                self.progress_widget.update_status("未找到对应的原文")
                
        except Exception as e:
            print(f"查找原文错误: {str(e)}")
            print(traceback.format_exc())

    def scroll_to_text(self, text):
        """滚动到指定文本位置"""
        try:
            # 在原文中查找文本
            document = self.original_text.document()
            cursor = QTextCursor(document)
            
            # 创建查找格式
            find_format = QTextCharFormat()
            
            # 查找文本
            cursor = document.find(text, cursor)
            if not cursor.isNull():
                # 移动到找到的位置
                self.original_text.setTextCursor(cursor)
                # 确保文本可见
                self.original_text.ensureCursorVisible()
                
        except Exception as e:
            print(f"滚动到文本位置错误: {str(e)}")
            print(traceback.format_exc())

    def show_error(self, error_msg):
        """显示错误信息（在主线程中执行）"""
        self.progress_widget.update_status(f"错误: {error_msg}")

    def translation_finished(self):
        """翻译完成后的处理（在主线程中执行）"""
        self.progress_widget.update_status("翻译完成！")
        self.translate_page_btn.setEnabled(True)
        self.translate_book_btn.setEnabled(True)  # 重新启用整本翻译
        self.stop_translation_btn.setEnabled(False)
        self.restart_translation_btn.setEnabled(True)
        self.signals.clear_highlight.emit()

    def clear_highlight(self):
        """清除所有高亮"""
        try:
            # 清除原文高亮
            cursor = self.original_text.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            format = QTextCharFormat()
            format.setBackground(Qt.GlobalColor.transparent)
            format.setForeground(Qt.GlobalColor.black)  # 恢复默认文字颜色
            cursor.mergeCharFormat(format)
            
            # 清除译文高亮
            cursor = self.translated_text.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(format)
            
            # 重置光标选择
            cursor = self.original_text.textCursor()
            cursor.clearSelection()
            self.original_text.setTextCursor(cursor)
            
            cursor = self.translated_text.textCursor()
            cursor.clearSelection()
            self.translated_text.setTextCursor(cursor)
            
        except Exception as e:
            print(f"清除高亮错误: {str(e)}")
            print(traceback.format_exc())

    def update_html_content(self, html_content):
        """在主线程中更新HTML内容"""
        try:
            self.original_text.setHtml(html_content)
        except Exception as e:
            print(f"更新HTML内容错误: {str(e)}")

    def stop_translation(self):
        """停止当前翻译进程"""
        try:
            if hasattr(self, 'text_translator'):
                # 尝试停止翻译器
                if self.text_translator.stop_translation():
                    # 成功停止后删除翻译器
                    delattr(self, 'text_translator')
                    
                    self.progress_widget.update_status("翻译已停止")
                    self.translate_page_btn.setEnabled(True)
                    self.translate_book_btn.setEnabled(True)
                    self.stop_translation_btn.setEnabled(False)
                    self.restart_translation_btn.setEnabled(True)
                else:
                    # 如果停止失败，显示错误信息
                    self.progress_widget.update_status("停止翻译失败，请稍后重试")
                    
        except Exception as e:
            print(f"停止翻译错误: {str(e)}")
            print(traceback.format_exc())

    def restart_translation(self):
        """从当前进度重新开始翻译"""
        try:
            # 设置重新翻译标志
            self._is_retranslating = True
            
            # 禁用所有相关按钮
            self.translate_page_btn.setEnabled(False)
            self.translate_book_btn.setEnabled(False)
            self.restart_translation_btn.setEnabled(False)
            
            def start_new_translation():
                try:
                    # 确保完全清理旧的翻译器
                    if hasattr(self, 'text_translator'):
                        del self.text_translator
                    
                    # 等待一小段时间
                    time.sleep(0.2)
                    
                    # 清除当前页面的翻译缓存
                    current_page_text = self.pages[self.current_page]
                    translation_units = self.epub_handler.get_translation_units(current_page_text)
                    for unit in translation_units:
                        if unit['text'].strip():
                            # 从翻译管理器中删除这个文本的缓存
                            self.translation_manager.remove_translation(unit['text'])
                    
                    # 重新开始翻译当前页面
                    self.translate_current_page()
                    
                except Exception as e:
                    print(f"启动新翻译错误: {str(e)}")
                    print(traceback.format_exc())
                    self.progress_widget.update_status("启动翻译失败")
                    # 恢复按钮状态
                    self.translate_page_btn.setEnabled(True)
                    self.translate_book_btn.setEnabled(True)
                    self.restart_translation_btn.setEnabled(True)
                finally:
                    # 清除重新翻译标志
                    self._is_retranslating = False
            
            # 启动新翻译
            start_new_translation()
            
        except Exception as e:
            print(f"重新开始翻译错误: {str(e)}")
            print(traceback.format_exc())
            self.progress_widget.update_status("重新翻译失败")
            # 清除重新翻译标志
            self._is_retranslating = False

    def translation_callback(self, translated_text, error=None, original_text=None, 
                           estimated_time=None, current_time=None, is_timeout=False):
        """翻译回调函数"""
        try:
            if error:
                self.signals.error.emit(str(error))
                return

            if original_text and translated_text and not is_timeout:
                try:
                    # 更新进度和时间信息
                    self.current_para += 1
                    
                    # 更新翻译记录和译本
                    self.translation_manager.add_translation(original_text, translated_text)
                    
                    # 更新UI显示
                    self.update_translation_signal.emit(
                        translated_text,
                        original_text,
                        estimated_time or 0,
                        current_time or 0
                    )
                    
                    # 更新进度条
                    self.update_progress_signal.emit(
                        self.current_para,
                        self.total_paras,
                        estimated_time or 0,
                        current_time or 0
                    )
                    
                    # 检查是否完成
                    if self.current_para == self.total_paras:
                        self.translation_complete_signal.emit()
                        
                except Exception as e:
                    print(f"处理翻译结果错误: {str(e)}")
                    print(traceback.format_exc())
                    
        except Exception as e:
            print(f"翻译回调错误: {str(e)}")
            print(traceback.format_exc())

    def _update_translation_text(self, translated_text, original_text, estimated_time, current_time):
        """在主线程中更新翻译文本"""
        try:
            # 获取当前文本并添加新译文
            current_text = self.translated_text.toPlainText()
            new_text = current_text + "\n\n" + translated_text if current_text else translated_text
            
            # 更新文本显示
            self.translated_text.setPlainText(new_text)
            
            # 移动光标到末尾并滚动显示
            cursor = self.translated_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.translated_text.setTextCursor(cursor)
            self.translated_text.ensureCursorVisible()
            
            # 保存翻译对（确保文本被正确处理）
            self.translation_pairs.append({
                'original': original_text.strip(),  # 去除首尾空格
                'translated': translated_text.strip()  # 去除首尾空格
            })
            
            # 打印调试信息
            print(f"保存翻译对：\n原文：{original_text[:50]}...\n译文：{translated_text[:50]}...")
            
            # 启用复制按钮
            self.copy_btn.setEnabled(True)
            
            # 高亮原文
            self.highlight_paragraph(original_text)
            self.start_highlight_timer()
            
        except Exception as e:
            print(f"更新翻译文本错误: {str(e)}")
            print(traceback.format_exc())

    def _update_progress(self, current, total, estimated_time, current_time):
        """在主线程中更新进度"""
        try:
            self.progress_widget.update_progress(
                current,
                total,
                estimated_time=estimated_time,
                current_time=current_time
            )
        except Exception as e:
            print(f"更新进度错误: {str(e)}")
            print(traceback.format_exc())

    def _on_translation_complete(self):
        """在主线程中处理翻译完成"""
        try:
            self.progress_widget.update_status("翻译完成！")
            self.translate_page_btn.setEnabled(True)
            self.translate_book_btn.setEnabled(True)
            self.stop_translation_btn.setEnabled(False)
            self.restart_translation_btn.setEnabled(True)
        except Exception as e:
            print(f"处理翻译完成错误: {str(e)}")
            print(traceback.format_exc())

    def translate_current_page(self):
        try:
            # 检查翻译器状态
            if self.using_deepseek:
                if not self.deepseek_translator:
                    raise Exception("DeepSeek 翻译器未初始化")
            else:
                # 使用 Ollama 时才需要处理模型
                current_model = self.model
                if self.ollama_translator and self.ollama_translator.model != current_model:
                    self.ollama_translator = OllamaTranslator(model_name=current_model)
                elif not self.ollama_translator:
                    self.ollama_translator = OllamaTranslator(model_name=current_model)
                
                # 更新状态栏显示当前使用的模型
                self.status_bar_translation.setText(f"使用模型: {current_model}")
            
            # 检查翻译器状态
            if not self.ollama_translator and not (self.using_deepseek and self.deepseek_translator):
                raise Exception("没有可用的翻译器")
            
            self.translation_pairs = []
            self.translated_text.clear()
            
            # 禁用相关按钮
            self.translate_page_btn.setEnabled(False)
            self.translate_book_btn.setEnabled(False)
            self.restart_translation_btn.setEnabled(False)
            self.stop_translation_btn.setEnabled(True)
            
            # 创建新的翻译器
            if not hasattr(self, 'text_translator'):
                self.text_translator = Translator()
                print("创建新的翻译器")

            # 获取当前页面的翻译单位
            current_page_text = self.pages[self.current_page]
            translation_units = self.epub_handler.get_translation_units(current_page_text)

            if not translation_units:
                self.progress_widget.update_status("当前页面没有可翻译的内容！")
                return

            print(f"找到 {len(translation_units)} 个翻译单位")
            
            # 设置进度
            self.total_paras = len(translation_units)
            self.current_para = 0
            
            self.progress_widget.progress_bar.setMaximum(len(translation_units))
            print("进度条已设置")

            # 启动翻译器
            print("正在启动翻译器...")
            if not self.text_translator.start_translation_worker(
                self.translation_callback,
                using_deepseek=self.using_deepseek,
                deepseek_translator=self.deepseek_translator if self.using_deepseek else None,
                ollama_translator=self.ollama_translator
            ):
                raise Exception("启动翻译器失败")
            
            print("翻译器启动成功，开始添加翻译任务...")
            
            # 添加翻译单位到队列
            for unit in translation_units:
                if unit['text'].strip():
                    # 检查是否是重新翻译
                    if hasattr(self, '_is_retranslating') and self._is_retranslating:
                        print(f"重新翻译: {unit['text'][:50]}...")
                        self.text_translator.add_to_queue((unit['text'], unit['text']))
                    else:
                        # 正常翻译时检查缓存
                        cached_translation = self.translation_manager.get_cached_translation(unit['text'])
                        if cached_translation:
                            print(f"使用缓存的翻译: {unit['text'][:50]}...")
                            self.translation_callback(
                                cached_translation,
                                original_text=unit['text'],
                                estimated_time=0,
                                current_time=0
                            )
                        else:
                            print(f"添加翻译任务: {unit['text'][:50]}...")
                            self.text_translator.add_to_queue((unit['text'], unit['text']))

            print("所有翻译任务已添加到队列")

        except Exception as e:
            print(f"翻译页面错误: {str(e)}")
            print(traceback.format_exc())
            self.show_error(str(e))
            
            # 恢复按钮状态
            self.translate_page_btn.setEnabled(True)
            self.translate_book_btn.setEnabled(True)
            self.restart_translation_btn.setEnabled(True)
            self.stop_translation_btn.setEnabled(False)

    def start_highlight_timer(self):
        """启动高亮清除计时器"""
        self.highlight_timer.start(2000)  # 2秒后清除高亮 

    def translate_whole_book(self):
        """翻译整本书"""
        try:
            if not hasattr(self, 'EpubHandlerClass'):
                raise Exception("请先加载EPUB文件")
            
            # 禁用不需要的按钮
            self.translate_page_btn.setEnabled(False)
            self.translate_book_btn.setEnabled(False)
            self.restart_translation_btn.setEnabled(False)
            self.stop_translation_btn.setEnabled(True)
            
            # 创建新的EPUB文件名
            original_path = self.current_file
            file_name = os.path.splitext(os.path.basename(original_path))[0]
            new_file_name = f"{file_name}_中文翻译本.epub"
            new_file_path = os.path.join(os.path.dirname(original_path), new_file_name)
            
            # 复制原文件
            import shutil
            shutil.copy2(original_path, new_file_path)
            
            # 使用保存的EpubHandler类创建新实例
            self.translated_epub = self.EpubHandlerClass(new_file_path)
            
            # 获取所有需要翻译的内容
            all_units = []
            total_pages = len(self.pages)
            
            self.progress_widget.update_status("正在准备翻译...")
            
            # 收集所有页面的翻译单位
            for page_idx in range(total_pages):
                units = self.epub_handler.get_translation_units(self.pages[page_idx])
                for unit in units:
                    unit['page_idx'] = page_idx
                all_units.extend(units)
            
            self.total_paras = len(all_units)
            self.current_para = 0
            
            self.progress_widget.progress_bar.setMaximum(self.total_paras)
            self.progress_widget.update_status(f"开始翻译整本书 (共 {self.total_paras} 个单位)")
            
            # 创建翻译器
            if not hasattr(self, 'text_translator'):
                self.text_translator = Translator()
            
            def book_translation_callback(translated_text, error=None, original_text=None, 
                                        estimated_time=None, current_time=None, is_timeout=False):
                if error:
                    self.signals.error.emit(str(error))
                    return

                if original_text:
                    try:
                        # 更新进度和时间信息
                        self.current_para += 1
                        self.progress_widget.update_progress(
                            self.current_para, 
                            self.total_paras,
                            estimated_time=estimated_time,
                            current_time=current_time
                        )
                        
                        # 保存翻译结果
                        if not is_timeout and translated_text:
                            self.translated_epub.update_content(original_text, translated_text)
                        
                    except Exception as e:
                        print(f"处理翻译结果错误: {str(e)}")
                        print(traceback.format_exc())

                if self.current_para == self.total_paras:
                    try:
                        # 保存翻译后的EPUB文件
                        self.translated_epub.save_epub()
                        self.progress_widget.update_status("翻译完成！已保存翻译后的文件。")
                    except Exception as e:
                        print(f"保存EPUB文件错误: {str(e)}")
                        self.progress_widget.update_status("翻译完成，但保存文件时出错！")
                    finally:
                        # 恢复按钮状态
                        self.translate_page_btn.setEnabled(True)
                        self.translate_book_btn.setEnabled(True)
                        self.stop_translation_btn.setEnabled(False)
                        self.restart_translation_btn.setEnabled(True)

            # 启动翻译
            self.text_translator.start_translation_worker(
                book_translation_callback,
                model=self.model  # 改用 self.model 而不是 model_combo
            )

            # 添加所有翻译单位到队列
            for unit in all_units:
                if unit['text'].strip():
                    self.text_translator.add_to_queue((unit['text'], unit['text']))

        except Exception as e:
            print(f"整本翻译错误: {str(e)}")
            print(traceback.format_exc())
            self.show_error(str(e)) 

    def copy_translation_to_clipboard(self):
        """复制翻译文本到剪贴板"""
        try:
            # 获取翻译窗口的文本
            text = self.translated_text.toPlainText()
            if text:
                # 获取剪贴板
                clipboard = QApplication.clipboard()
                # 设置文本到剪贴板
                clipboard.setText(text)
                # 显示成功提示弹窗
                QMessageBox.information(
                    self,
                    "复制成功",
                    "译文已成功复制到剪贴板！",
                    QMessageBox.StandardButton.Ok
                )
                self.progress_widget.update_status("译文已复制到剪贴板")
        except Exception as e:
            print(f"复制到剪贴板错误: {str(e)}")
            print(traceback.format_exc())
            self.show_error("复制到剪贴板失败") 

    def show_toc(self):
        """显示目录"""
        try:
            # 创建目录窗口
            toc_dialog = QDialog(self)
            toc_dialog.setWindowTitle("目录")
            toc_dialog.setMinimumSize(400, 600)
            
            layout = QVBoxLayout(toc_dialog)
            
            # 创建目录树
            toc_tree = QTreeWidget()
            toc_tree.setHeaderLabel("目录")
            
            # 获取目录信息
            toc = self.book.toc
            print("目录结构：")  # 调试输出
            
            def add_toc_items(items, parent=None):
                for item in items:
                    if isinstance(item, tuple):
                        # 处理嵌套目录
                        section, children = item
                        toc_item = QTreeWidgetItem([section.title])
                        if parent:
                            parent.addChild(toc_item)
                        else:
                            toc_tree.addTopLevelItem(toc_item)
                        
                        # 保存href到item的数据中
                        if hasattr(section, 'href'):
                           # print(f"目录项: {section.title}, href: {section.href}")  # 调试输出
                            toc_item.setData(0, Qt.ItemDataRole.UserRole, section.href)
                            
                        if children:
                            add_toc_items(children, toc_item)
                    else:
                        # 处理单个目录项
                        toc_item = QTreeWidgetItem([item.title])
                        if parent:
                            parent.addChild(toc_item)
                        else:
                            toc_tree.addTopLevelItem(toc_item)
                        
                        # 保存href到item的数据中
                        if hasattr(item, 'href'):
                          #  print(f"目录项: {item.title}, href: {item.href}")  # 调试输出
                            toc_item.setData(0, Qt.ItemDataRole.UserRole, item.href)
            
            # 添加目录项
            add_toc_items(toc)
            
            # 处理目录项点击事件
            def on_toc_item_clicked(item, column):
                # 从item数据中获取href
                href = item.data(0, Qt.ItemDataRole.UserRole)
              #  print(f"点击目录项: {item.text(0)}, href: {href}")
                
                if href:
                    # 获取基本文件名（不含锚点）
                    base_href = href.split('#')[0]
                    
                    # 在所有页面中查找包含此文件名的页面
                    for i, page in enumerate(self.pages):
                        soup = BeautifulSoup(page, 'html.parser')
                        meta_tag = soup.find('meta', attrs={'name': 'epub-file'})
                        
                        if meta_tag and meta_tag['content'] == base_href:
                            print(f"找到目标页面: {i+1}")
                            self.show_page(i)
                            toc_dialog.close()
                            return
                        
                    print(f"未找到页面: {href}")
            
            toc_tree.itemClicked.connect(on_toc_item_clicked)
            
            # 添加到布局
            layout.addWidget(toc_tree)
            
            # 添加关闭按钮
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(toc_dialog.close)
            layout.addWidget(close_btn)
            
            # 显示目录窗口
            toc_dialog.exec()
            
        except Exception as e:
            print(f"显示目录错误: {str(e)}")
            print(traceback.format_exc())
            self.show_error("无法显示目录")

    def find_page_by_href(self, href):
        """根据href查找对应的页面索引"""
        try:
            print(f"查找页面: {href}")
            # 如果href包含#，说明是页内链接
            if '#' in href:
                base_href, anchor = href.split('#', 1)
            else:
                base_href, anchor = href, None

            # 遍历所有文档项
            target_item = None
            for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                # 检查href是否匹配当前文档
                if (base_href == item.file_name or  # 完全匹配
                    base_href in item.file_name or  # 部分匹配
                    base_href == os.path.basename(item.file_name)):  # 文件名匹配
                    print(f"找到匹配文档: {item.file_name}")
                    target_item = item
                    break

            if target_item:
                target_content = target_item.get_content().decode('utf-8')
                target_soup = BeautifulSoup(target_content, 'html.parser')
                
                # 遍历所有页面
                for i, page in enumerate(self.pages):
                    page_soup = BeautifulSoup(page, 'html.parser')
                    
                    # 1. 如果有锚点，先尝试通过锚点定位
                    if anchor:
                        # 检查id属性
                        if page_soup.find(id=anchor):
                            print(f"通过锚点id找到页面 {i+1}")
                            return i
                        # 检查name属性
                        if page_soup.find(attrs={"name": anchor}):
                            print(f"通过锚点name找到页面 {i+1}")
                            return i

                    # 2. 通过内容特征匹配
                    # 提取页面的特征内容（第一个标题或第一个段落）
                    target_feature = target_soup.find(['h1', 'h2', 'h3', 'p'])
                    if target_feature and target_feature.get_text().strip():
                        feature_text = target_feature.get_text().strip()
                        if feature_text in page:
                            print(f"通过内容特征找到页面 {i+1}")
                            return i

                    # 3. 通过文件名匹配
                    if target_item.file_name in page:
                        print(f"通过文件名找到页面 {i+1}")
                        return i

                # 4. 如果还找不到，尝试通过内容片段匹配
                target_text = target_soup.get_text()[:200]  # 取前200个字符
                for i, page in enumerate(self.pages):
                    if target_text in page:
                        print(f"通过内容片段找到页面 {i+1}")
                        return i

            print(f"未找到匹配页面: {href}")
            return None
        except Exception as e:
            print(f"查找页面错误: {str(e)}")
            print(traceback.format_exc())
            return None 

    def change_font(self, font):
        """改变字体"""
        try:
            # 更新原文和译文的字体
            self.original_text.setFont(font)
            self.translated_text.setFont(font)
        except Exception as e:
            print(f"更改字体错误: {str(e)}")
            print(traceback.format_exc())
            
    def change_font_size(self, size):
        """改变字体大小"""
        try:
            # 获取当前字体
            original_font = self.original_text.font()
            translated_font = self.translated_text.font()
            
            # 设置新的字体大小
            original_font.setPointSize(size)
            translated_font.setPointSize(size)
            
            # 应用新字体
            self.original_text.setFont(original_font)
            self.translated_text.setFont(translated_font)
        except Exception as e:
            print(f"更改字体大小错误: {str(e)}")
            print(traceback.format_exc()) 

    def setup_ui(self):
        """初始化UI"""
        # ... 其他UI代码 ...
        
        # 使用自定义的文本框
        self.translated_text = ClickableTextEdit(self)
        self.translated_text.setReadOnly(True)
        self.translated_text.setMouseTracking(True)
        
        # 测试点击事件
        self.translated_text.clicked = lambda: print("文本框被点击了！")
        self.translated_text.mousePressEvent = self.on_text_press
        
        # 如果使用布局，确保将translated_text添加到布局中
        # 例如：
        # self.layout().addWidget(self.translated_text)
        
    def on_text_press(self, event):
        """测试点击事件"""
        print("检测到点击！")
        cursor = self.translated_text.cursorForPosition(event.pos())
        text = cursor.block().text()
        print(f"点击的文本: {text}") 

    def show_bookshelf(self):
        """显示书架窗口"""
        self.bookshelf_window = BookshelfWindow()
        self.bookshelf_window.book_selected.connect(self.open_book_from_shelf)
        self.bookshelf_window.show()
        self.hide()  # 隐藏主窗口
        
    def open_book_from_shelf(self, book_path):
        """从书架打开书籍"""
        self.current_file = book_path
        self.load_epub()
        self.show()  # 显示主窗口 

    def search_original_text(self):
        """搜索原文并高亮显示"""
        # 获取译文窗口中选中的文本
        cursor = self.translated_text.textCursor()
        selected_text = cursor.selectedText()
        
        if not selected_text:
            QMessageBox.information(
                self,
                "提示",
                "请先在译文窗口中选择要搜索的文本"
            )
            return
            
        # 在翻译对中查找包含选中文本的译文句子
        best_match = self.find_containing_translation(selected_text)
        if not best_match:
            QMessageBox.information(
                self,
                "提示",
                "未找到包含所选文本的译文句子"
            )
            return
        
        # 获取对应的原文
        original_text = best_match["original"]
        
        # 清除之前的高亮
        self.clear_highlight()
        
        # 在原文中查找并高亮文本
        cursor = self.original_text.document().find(original_text)
        if not cursor.isNull():
            # 设置高亮格式
            format = cursor.charFormat()
            format.setBackground(Qt.GlobalColor.yellow)
            cursor.mergeCharFormat(format)
            
            # 滚动到找到的位置
            self.original_text.setTextCursor(cursor)
            self.original_text.ensureCursorVisible()
            
            # 3秒后清除高亮
            self.highlight_timer.start(3000)
    
    def find_containing_translation(self, selected_text):
        """查找包含所选文本的最佳匹配译文"""
        best_match = None
        best_ratio = 0
        
        for pair in self.translation_pairs:
            translated = pair["translated"]
            # 如果译文包含选中的文本
            if selected_text.lower() in translated.lower():
                # 计算选中文本与完整译文的相似度
                ratio = len(selected_text) / len(translated)
                # 找到最短的包含选中文本的译文（避免匹配过长的段落）
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = pair
        
        return best_match
    
    def clear_highlight(self):
        """清除所有高亮"""
        try:
            # 清除原文高亮
            cursor = self.original_text.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            format = QTextCharFormat()
            format.setBackground(Qt.GlobalColor.transparent)
            format.setForeground(Qt.GlobalColor.black)  # 恢复默认文字颜色
            cursor.mergeCharFormat(format)
            
            # 清除译文高亮
            cursor = self.translated_text.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(format)
            
            # 重置光标选择
            cursor = self.original_text.textCursor()
            cursor.clearSelection()
            self.original_text.setTextCursor(cursor)
            
            cursor = self.translated_text.textCursor()
            cursor.clearSelection()
            self.translated_text.setTextCursor(cursor)
            
        except Exception as e:
            print(f"清除高亮错误: {str(e)}")
            print(traceback.format_exc())

    def on_translation_complete(self):
        """翻译完成后的处理"""
        # 保存翻译对
        original = self.original_text.toPlainText()
        translated = self.translated_text.toPlainText()
        self.translation_pairs.append({
            "original": original,
            "translated": translated
        }) 

    def check_ollama_installation(self):
        """检查 Ollama 是否已安装"""
        try:
            # 使用 subprocess 运行 ollama list 命令
            result = subprocess.run(['ollama', 'list'], 
                                  capture_output=True, 
                                  text=True)
            
            if result.returncode == 0:
                # Ollama 已安装，解析模型列表
                models = self.parse_ollama_models(result.stdout)
                if models:
                    # 更新模型下拉框
                    self.model_combo.clear()
                    self.model_combo.addItems(models)
                    QMessageBox.information(
                        self,
                        "Ollama 状态",
                        "Ollama 已安装，模型列表已更新！",
                        QMessageBox.StandardButton.Ok
                    )
                else:
                    QMessageBox.information(
                        self,
                        "Ollama 状态",
                        "Ollama 已安装，但未找到可用模型。",
                        QMessageBox.StandardButton.Ok
                    )
            else:
                # Ollama 未安装，显示安装提示对话框
                self.show_ollama_install_dialog()
            
        except FileNotFoundError:
            # Ollama 命令未找到，显示安装提示对话框
            self.show_ollama_install_dialog()
        except Exception as e:
            QMessageBox.warning(
                self,
                "错误",
                f"检查 Ollama 状态时出错：{str(e)}",
                QMessageBox.StandardButton.Ok
            )

    def parse_ollama_models(self, output):
        """解析 ollama list 命令的输出，提取模型名称"""
        models = []
        for line in output.strip().split('\n')[1:]:  # 跳过标题行
            if line.strip():
                # 提取模型名称（第一列）
                model_name = line.split()[0]
                models.append(model_name)
        return models

    def show_ollama_install_dialog(self):
        """显示 Ollama 安装提示对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("安装 Ollama")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # 提示文本
        message = QLabel(
            "未检测到 Ollama，请先安装 Ollama 才能使用翻译功能。\n"
            "点击下方按钮下载安装包："
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        
        # 下载按钮
        download_btn = QPushButton("下载 Ollama")
        download_btn.clicked.connect(lambda: self.download_ollama(dialog))
        layout.addWidget(download_btn)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec()

    def download_ollama(self, dialog):
        """打开 Ollama 下载页面"""
        webbrowser.open('https://ollama.com/download/windows')
        
        QMessageBox.information(
            dialog,
            "下载提示",
            "已打开下载页面，请下载并安装 Ollama。\n"
            "安装完成后，请重新点击'检测 Ollama'按钮。",
            QMessageBox.StandardButton.Ok
        ) 

    def restart_ollama_service(self):
        """重启 Ollama 服务"""
        try:
            # 1. 强制结束所有 Ollama 进程
            self.progress_widget.update_status("正在停止 Ollama 服务...")
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
            time.sleep(2)
            
            # 2. 检查是否有残留进程
            try:
                subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE)
            except:
                pass
            
            # 3. 等待端口释放
            self.progress_widget.update_status("等待端口释放...")
            time.sleep(3)
            
            # 4. 启动 Ollama 服务
            self.progress_widget.update_status("正在启动 Ollama 服务...")
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            process = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startup_info,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # 5. 等待服务启动
            self.progress_widget.update_status("等待服务启动...")
            time.sleep(5)
            
            # 6. 检查服务是否正常
            max_retries = 3
            for i in range(max_retries):
                try:
                    response = requests.get('http://localhost:11434/api/tags', timeout=5)
                    if response.status_code == 200:
                        self.progress_widget.update_status("Ollama 服务已成功重启")
                        return True
                except:
                    if i < max_retries - 1:
                        self.progress_widget.update_status(f"正在重试 ({i + 1}/{max_retries})...")
                        time.sleep(2)
                    continue
            
            self.progress_widget.update_status("Ollama 服务启动失败，请手动重启")
            return False
            
        except Exception as e:
            self.progress_widget.update_status(f"重启 Ollama 服务失败: {str(e)}")
            return False

    def switch_api(self):
        """切换API接口"""
        self.using_deepseek = not self.using_deepseek
        self.init_translator()  # 重新初始化翻译器
        
        if self.using_deepseek:
            self.status_bar_api.setText("API: DeepSeek")
        else:
            self.status_bar_api.setText("API: Ollama")

    def show_ai_reading(self):
        """显示AI导读分析"""
        try:
            if not hasattr(self, 'book') or not self.book:
                self.status_bar_ai.setText("请先加载EPUB文件")
                return
            
          
            
            # 显示确认对话框
            reply = QMessageBox.information(
                self,
                "AI导读",
                "正在启动AI导读功能，点击确定开始分析。",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )
            
            if reply != QMessageBox.StandardButton.Ok:
                return
            
            # 获取并清理文本
            current_page_text = self.pages[self.current_page]
            if not current_page_text:
                self.status_bar_ai.setText("当前页面没有内容")
                return
            
            cleaned_text = self.clean_text_for_analysis(current_page_text)
            if not cleaned_text:
                self.status_bar_ai.setText("处理后的文本为空")
                return

            # 更新状态栏
            self.status_bar_ai.setText("正在生成AI导读分析...")
            
            # 创建一个信号用于显示结果
            class AnalysisSignals(QObject):
                show_result = pyqtSignal(str)
                
            signals = AnalysisSignals()
            signals.show_result.connect(self.show_analysis_result)  # 连接到显示结果的方法
            
            def analyze_thread():
                try:
                    # 根据目标语言设置提示词
                    prompts = {
                        'zh': """请按照以下方式总结文章内容：
1. 详细总结：概括文章的核心主旨和主要观点，分段落梳理内容。
2. 重要语句摘抄：摘抄文章中反映主旨的关键句子，并标注出处。
3. 引用人物及其言论：列出文章中引用的关键人物及其言论，说明这些言论如何反映文章主旨。
4. 文中有关的人物以及概念的介绍：尽可能的从文中提取人物和重要概念的信息进行总结。
5. 逻辑清晰：确保总结内容结构清晰，重点突出，便于理解。

请按照以上要求对以下文章进行总结：""",
                        'en': """Please summarize the article in the following way:...""",
                        'ja': """以下の方法で記事を要約してください：..."""
                    }
                    prompt = prompts.get(self.target_language, prompts['en'])
                    
                    print("\n=== AI导读开始 ===")
                    print(f"使用语言: {self.target_language}")
                    print(f"文本长度: {len(cleaned_text)} 字符")
                    print(f"使用翻译器: {'DeepSeek' if self.using_deepseek else 'Ollama'}")
                    
                    if self.using_deepseek:
                        print("\n正在调用 DeepSeek API...")
                        try:
                            response = self.deepseek_translator.client.chat.completions.create(
                                model="deepseek-chat",
                                messages=[
                                    {"role": "system", "content": "你是一个专业的文本分析助手，擅长结构化分析和总结文章内容。"},
                                    {"role": "user", "content": prompt + "\n\n" + cleaned_text}
                                ],
                                temperature=0.3,
                                max_tokens=8000
                            )
                            print("DeepSeek API 调用成功")
                            analysis_result = response.choices[0].message.content
                        except Exception as e:
                            print(f"DeepSeek API 调用失败: {str(e)}")
                            raise e
                    else:
                        print("\n正在调用 Ollama API...")
                        try:
                            response = self.ollama_translator.translate(prompt + "\n\n" + cleaned_text)
                            print("Ollama API 调用成功")
                            analysis_result = response
                        except Exception as e:
                            print(f"Ollama API 调用失败: {str(e)}")
                            raise e
                    
                    print("\n=== 分析结果 ===")
                    print(f"结果长度: {len(analysis_result)} 字符")
                    print("分析结果前100个字符:")
                    print(analysis_result[:100])
                    print("=== 分析完成 ===\n")
                    
                    # 发送信号显示结果
                    signals.show_result.emit(analysis_result)
                    self.status_bar_ai.setText("AI导读完成")
                    
                except Exception as e:
                    print(f"\n=== AI分析错误 ===")
                    print(f"错误信息: {str(e)}")
                    print("详细错误堆栈:")
                    print(traceback.format_exc())
                    self.status_bar_ai.setText(f"AI导读失败: {str(e)}")
            
            # 启动分析线程
            analysis_thread = Thread(target=analyze_thread, daemon=True)
            analysis_thread.start()
            print("分析线程已启动")
            
        except Exception as e:
            print(f"启动AI导读错误: {str(e)}")
            print(traceback.format_exc())
            self.status_bar_ai.setText(f"AI导读错误: {str(e)}")

    def show_analysis_result(self, analysis):
        """在对话框中显示分析结果"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("AI导读分析")
            dialog.setMinimumSize(800, 600)
            
            layout = QVBoxLayout(dialog)
            layout.setSpacing(20)
            
            # 创建文本浏览器
            text_browser = QTextBrowser()
            text_browser.setOpenExternalLinks(True)
            text_browser.setMarkdown(analysis)
            text_browser.setStyleSheet("""
                QTextBrowser {
                    background-color: white;
                    border: 1px solid #ddd;
                    border-radius: 10px;
                    padding: 15px;
                    font-size: 13px;
                    line-height: 1.6;
                }
            """)
            
            # 工具栏
            toolbar = QToolBar()
            
            # 添加复制按钮
            copy_action = QAction("复制全文", dialog)
            copy_action.triggered.connect(lambda: QApplication.clipboard().setText(analysis))
            toolbar.addAction(copy_action)
            
            # 添加保存按钮
            save_action = QAction("保存为文件", dialog)
            save_action.triggered.connect(lambda: self.save_analysis_to_file(dialog, analysis))
            toolbar.addAction(save_action)
            
            # 添加到布局
            layout.addWidget(toolbar)
            layout.addWidget(text_browser)
            
            # 显示对话框
            dialog.exec()
            
        except Exception as e:
            print(f"显示分析结果错误: {str(e)}")
            print(traceback.format_exc())
            QMessageBox.warning(self, "错误", f"显示分析结果失败: {str(e)}")

    def save_analysis_to_file(self, parent_window, analysis):
        """保存分析结果到文件"""
        file_name, _ = QFileDialog.getSaveFileName(
            parent_window,
            "保存分析结果",
            "",
            "Text Files (*.txt);;Markdown Files (*.md)"
        )
        if file_name:
            try:
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(analysis)
                QMessageBox.information(
                    parent_window,
                    "成功",
                    "分析结果已保存到文件",
                    QMessageBox.StandardButton.Ok
                )
            except Exception as e:
                QMessageBox.warning(
                    parent_window,
                    "错误",
                    f"保存文件失败: {str(e)}",
                    QMessageBox.StandardButton.Ok
                )

    def clean_text_for_analysis(self, html_content):
        """清理HTML文本，提取纯文本内容"""
        try:
            # 使用 BeautifulSoup 解析 HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 删除所有脚本和样式元素
            for script in soup(["script", "style"]):
                script.decompose()
                
            # 删除所有图片标签
            for img in soup.find_all('img'):
                img.decompose()
                
            # 获取文本
            text = soup.get_text()
            
            # 处理文本
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            
            # 重新组织文本，去除多余空白
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            # 限制文本长度（考虑到API的token限制）
            max_length = 2000  # 根据实际需求调整
            if len(text) > max_length:
                text = text[:max_length] + "..."
                
            return text
            
        except Exception as e:
            print(f"清理文本错误: {str(e)}")
            print(traceback.format_exc())
            return ""

    def show_error_dialog(self, error_message):
        """显示错误对话框"""
        QMessageBox.critical(
            self,
            "错误",
            f"生成导读内容时出错：{error_message}",
            QMessageBox.StandardButton.Ok
        ) 

    def show_settings_dialog(self):
        """显示设置对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("设置")
        dialog.setMinimumWidth(400)
        
        # 创建主布局
        main_layout = QVBoxLayout(dialog)
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        
        # 设置样式
        dialog.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            QLabel {
                font-size: 12px;
                color: #333;
            }
            QLabel[class="section-title"] {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                padding: 5px 0;
            }
            QPushButton {
                min-height: 30px;
                min-width: 200px;  /* 增加按钮宽度 */
                max-width: 300px;  /* 限制最大宽度 */
                border-radius: 15px;
                font-size: 12px;
                padding: 5px 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #4ECDC4, stop:1 #45B7AF);
                color: white;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #45B7AF, stop:1 #4ECDC4);
            }
            QPushButton[class="deepseek-btn"] {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #6C5CE7, stop:1 #A17FE0);
            }
            QPushButton[class="deepseek-btn"]:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #A17FE0, stop:1 #6C5CE7);
            }
            QComboBox {
                min-height: 30px;
                min-width: 250px;  /* 增加下拉框宽度 */
                border: 1px solid #ddd;
                border-radius: 15px;
                padding: 5px 15px;
                background-color: white;
                font-size: 12px;
            }
            QComboBox:hover {
                border-color: #4ECDC4;
            }
            QLineEdit {
                min-height: 30px;
                min-width: 400px;  /* 增加输入框宽度 */
                border: 1px solid #ddd;
                border-radius: 15px;
                padding: 5px 15px;
                background-color: white;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #6C5CE7;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #ddd;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        # 1. API 设置组
        api_group = QGroupBox("API 设置")
        api_layout = QVBoxLayout()
        api_layout.setSpacing(15)  # 增加组件间距
        
        # API 切换
        api_switch_layout = QHBoxLayout()
        api_switch_label = QLabel("翻译接口:")
        self.dialog_api_switch_btn = QPushButton("DeepSeek" if self.using_deepseek else "Ollama")
        
        # 设置按钮样式
        def update_api_button_style():
            if self.using_deepseek:
                self.dialog_api_switch_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                            stop:0 #6C5CE7, stop:1 #A17FE0);
                        color: white;
                        min-height: 30px;
                        min-width: 200px;
                        border-radius: 15px;
                        font-size: 12px;
                        padding: 5px 20px;
                        border: none;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                            stop:0 #A17FE0, stop:1 #6C5CE7);
                    }
                """)
            else:
                self.dialog_api_switch_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                            stop:0 #4ECDC4, stop:1 #45B7AF);
                        color: white;
                        min-height: 30px;
                        min-width: 200px;
                        border-radius: 15px;
                        font-size: 12px;
                        padding: 5px 20px;
                        border: none;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                            stop:0 #45B7AF, stop:1 #4ECDC4);
                    }
                """)
        
        update_api_button_style()
        
        # 连接切换事件
        def on_api_switch():
            self.switch_api()
            self.dialog_api_switch_btn.setText("DeepSeek" if self.using_deepseek else "Ollama")
            update_api_button_style()
            
            # 如果切换到 DeepSeek 且没有 API Key，高亮显示 API Key 输入框
            if self.using_deepseek and not self.deepseek_api_key:
                api_key_edit.setStyleSheet("""
                    QLineEdit {
                        background-color: #FFE4E1;
                        min-height: 30px;
                        min-width: 400px;
                        border: 2px solid #FF6B6B;
                        border-radius: 15px;
                        padding: 5px 15px;
                        font-size: 12px;
                    }
                """)
                QTimer.singleShot(500, lambda: api_key_edit.setStyleSheet(""))
                QTimer.singleShot(1000, lambda: api_key_edit.setStyleSheet("""
                    QLineEdit {
                        background-color: #FFE4E1;
                        min-height: 30px;
                        min-width: 400px;
                        border: 2px solid #FF6B6B;
                        border-radius: 15px;
                        padding: 5px 15px;
                        font-size: 12px;
                    }
                """))
                QTimer.singleShot(1500, lambda: api_key_edit.setStyleSheet(""))
        
        self.dialog_api_switch_btn.clicked.connect(on_api_switch)
        api_switch_layout.addWidget(api_switch_label)
        api_switch_layout.addWidget(self.dialog_api_switch_btn)
        api_switch_layout.addStretch()
        
        # Ollama 设置
        ollama_layout = QVBoxLayout()
        ollama_label = QLabel("Ollama 设置")
        ollama_label.setProperty("class", "section-title")
        
        model_layout = QHBoxLayout()
        model_label = QLabel("默认模型:")
        self.settings_model_combo = QComboBox()
        
        # 检测 Ollama 按钮
        check_ollama_btn = QPushButton("检测 Ollama")
        check_ollama_btn.setMinimumWidth(150)
        check_ollama_btn.clicked.connect(self.check_ollama_models)
        
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.settings_model_combo)
        model_layout.addStretch()
        
        # 在创建对话框时检测 Ollama 模型
        try:
            import subprocess
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                # 解析输出获取模型列表
                models = []
                for line in result.stdout.strip().split('\n')[1:]:  # 跳过标题行
                    if line.strip():
                        model_name = line.split()[0]  # 第一列是模型名称
                        models.append(model_name)
                
                if models:
                    # 更新设置对话框中的模型下拉框
                    self.settings_model_combo.clear()
                    self.settings_model_combo.addItems(models)
                    
                    # 如果有保存的模型设置，选择该模型
                    if self.model and self.model in models:
                        index = self.settings_model_combo.findText(self.model)
                        if index >= 0:
                            self.settings_model_combo.setCurrentIndex(index)
                    # 否则使用第一个可用模型
                    else:
                        self.model = models[0]
                        self.settings.setValue('model', self.model)
                    
                    self.status_bar_api.setText(f"检测到 {len(models)} 个 Ollama 模型")
                else:
                    self.status_bar_api.setText("未检测到已安装的 Ollama 模型")
            else:
                self.status_bar_api.setText("Ollama 服务未运行或未安装")
                
        except Exception as e:
            print(f"检测 Ollama 失败: {str(e)}")
            print(traceback.format_exc())
            self.status_bar_api.setText(f"检测 Ollama 失败: {str(e)}")
        
        ollama_layout.addWidget(ollama_label)
        ollama_layout.addLayout(model_layout)
        ollama_layout.addWidget(check_ollama_btn)
        
        # DeepSeek 设置
        deepseek_layout = QVBoxLayout()
        deepseek_label = QLabel("DeepSeek 设置")
        deepseek_label.setProperty("class", "section-title")
        
        api_key_layout = QVBoxLayout()
        api_key_label = QLabel("API Key:")
        api_key_edit = QLineEdit()
        api_key_edit.setText(self.deepseek_api_key)
        api_key_edit.setPlaceholderText("请输入您的 DeepSeek API Key")
        
        what_is_api_key_btn = QPushButton("什么是 DeepSeek API Key?")
        what_is_api_key_btn.setProperty("class", "deepseek-btn")
        what_is_api_key_btn.clicked.connect(
            lambda: webbrowser.open('https://platform.deepseek.com/usage')
        )
        
        api_key_layout.addWidget(api_key_label)
        api_key_layout.addWidget(api_key_edit)
        api_key_layout.addWidget(what_is_api_key_btn)
        
        deepseek_layout.addWidget(deepseek_label)
        deepseek_layout.addLayout(api_key_layout)
        
        # 将所有API相关设置添加到API组
        api_layout.addLayout(api_switch_layout)
        api_layout.addLayout(ollama_layout)
        api_layout.addLayout(deepseek_layout)
        api_group.setLayout(api_layout)
        
        # 2. 语言设置组
        language_group = QGroupBox("语言设置")
        language_layout = QVBoxLayout()
        language_layout.setSpacing(15)
        
        # 界面语言
        ui_lang_layout = QHBoxLayout()
        ui_lang_label = QLabel("界面语言:")
        ui_lang_combo = QComboBox()
        ui_lang_combo.addItems(["中文", "English", "日本語", "Français", "Deutsch"])
        lang_map = {"zh": 0, "en": 1, "ja": 2, "fr": 3, "de": 4}
        ui_lang_combo.setCurrentIndex(lang_map.get(self.ui_language, 0))
        ui_lang_layout.addWidget(ui_lang_label)
        ui_lang_layout.addWidget(ui_lang_combo)
        ui_lang_layout.addStretch()
        
        # 目标语言
        target_lang_layout = QHBoxLayout()
        target_lang_label = QLabel("翻译目标语言:")
        target_lang_combo = QComboBox()
        target_lang_combo.addItems(["中文", "English", "日本語", "Français", "Deutsch"])
        target_lang_combo.setCurrentIndex(lang_map.get(self.target_language, 0))
        target_lang_layout.addWidget(target_lang_label)
        target_lang_layout.addWidget(target_lang_combo)
        target_lang_layout.addStretch()
        
        language_layout.addLayout(ui_lang_layout)
        language_layout.addLayout(target_lang_layout)
        language_group.setLayout(language_layout)
        
        # 3. 关于作者组
        about_group = QGroupBox("关于作者")
        about_layout = QVBoxLayout()
        about_text = QLabel("QQ: 1048944652\n公众号：平湖菌")
        about_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        about_layout.addWidget(about_text)
        about_group.setLayout(about_layout)
        
        # 4. 字体设置组
        font_group = QGroupBox("字体设置")
        font_layout = QVBoxLayout()
        font_layout.setSpacing(15)
        
        # 字体选择
        font_family_layout = QHBoxLayout()
        font_family_label = QLabel("字体:")
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.font_family))
        font_family_layout.addWidget(font_family_label)
        font_family_layout.addWidget(self.font_combo)
        font_family_layout.addStretch()
        
        # 字号选择
        font_size_layout = QHBoxLayout()
        font_size_label = QLabel("字号:")
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(['8', '9', '10', '11', '12', '13', '14', '16', '18', '20', '22', '24'])
        self.font_size_combo.setCurrentText(str(self.font_size))
        font_size_layout.addWidget(font_size_label)
        font_size_layout.addWidget(self.font_size_combo)
        font_size_layout.addStretch()
        
        # 预览区域
        preview_label = QLabel("预览:")
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(100)
        self.preview_text.setText("这是预览文本 This is preview text あいうえお")
        self.update_preview_font()
        
        # 添加到字体布局
        font_layout.addLayout(font_family_layout)
        font_layout.addLayout(font_size_layout)
        font_layout.addWidget(preview_label)
        font_layout.addWidget(self.preview_text)
        font_group.setLayout(font_layout)
        
        # 连接字体更改信号
        self.font_combo.currentFontChanged.connect(self.update_preview_font)
        self.font_size_combo.currentTextChanged.connect(self.update_preview_font)
        
        # 添加所有组到主布局
        layout.addWidget(api_group)
        layout.addWidget(language_group)
        layout.addWidget(font_group)
        layout.addWidget(about_group)
        
        # 删除旧的按钮布局，只保留一组按钮
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.setMinimumWidth(120)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(120)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        # 连接信号
        ok_btn.clicked.connect(lambda: self.save_settings(
            dialog,
            ui_lang_combo.currentIndex(),
            target_lang_combo.currentIndex(),
            api_key_edit.text()
        ))
        cancel_btn.clicked.connect(dialog.reject)
        
        # 设置滚动区域
        scroll.setWidget(main_widget)
        
        # 添加到主布局
        main_layout.addWidget(scroll)
        main_layout.addLayout(button_layout)  # 添加按钮布局
        
        dialog.exec()

    def save_settings(self, dialog, ui_lang_idx, target_lang_idx, api_key):
        """保存设置"""
        try:
            # 保存语言设置
            self.ui_language = self.SUPPORTED_UI_LANGUAGES[ui_lang_idx]
            self.target_language = self.SUPPORTED_TARGET_LANGUAGES[target_lang_idx]
            
            # 保存到 QSettings
            self.settings.setValue('ui_language', self.ui_language)
            self.settings.setValue('target_language', self.target_language)
            
            # 保存选择的模型
            selected_model = self.settings_model_combo.currentText()
            if selected_model:
                print(f"保存选择的模型: {selected_model}")
                self.model = selected_model
                self.settings.setValue('model', selected_model)
                self.config_manager.set_ollama_model(selected_model)  # 更新 config.json
            
            # 保存 API Key
            if self.using_deepseek:
                self.deepseek_api_key = api_key
                self.settings.setValue('deepseek_api_key', api_key)
            
            # 保存字体设置
            self.font_family = self.font_combo.currentFont().family()
            self.font_size = int(self.font_size_combo.currentText())
            self.settings.setValue('font_family', self.font_family)
            self.settings.setValue('font_size', self.font_size)
            
            # 应用字体设置
            self.apply_font_settings()
            
            # 重新初始化翻译器
            self.init_translator()
            
            # 更新UI
            self.retranslateUi()
            
            # 显示成功消息
            QMessageBox.information(dialog, "成功", "设置已保存")
            
            # 关闭对话框
            dialog.accept()
            
        except Exception as e:
            print(f"保存设置错误: {str(e)}")
            print(traceback.format_exc())
            QMessageBox.warning(dialog, "错误", f"保存设置失败: {str(e)}")

    def apply_font_settings(self):
        """应用字体设置到文本显示区域"""
        font = QFont(self.font_family, self.font_size)
        self.original_text.setFont(font)
        self.translated_text.setFont(font)

    def apply_translation(self):
        """应用界面翻译"""
        # 移除旧的翻译器
        QApplication.removeTranslator(self.ui_translator)
        
        # 加载新的翻译
        self.ui_translator = QTranslator()
        if self.ui_language != 'zh':
            if self.ui_translator.load(f"translations/epub_translator_{self.ui_language}"):
                QApplication.installTranslator(self.ui_translator)
        
        # 更新界面文本
        self.retranslateUi()
        
        # 重新创建所有按钮
        self.recreate_buttons()
    
    def recreate_buttons(self):
        """重新创建所有按钮"""
        # 保存当前状态
        current_page = self.current_page if hasattr(self, 'current_page') else 0
        
        # 重新创建按钮
        self.bookshelf_btn.setText(self.tr("我的书架"))
        self.file_btn.setText(self.tr("选择EPUB文件"))
        self.toc_btn.setText(self.tr("查看目录"))
        self.search_button.setText(self.tr("搜索原文"))
        self.ai_reading_btn.setText(self.tr("AI导读"))
        self.check_ollama_btn.setText(self.tr("检测 Ollama"))
        self.translate_page_btn.setText(self.tr("翻译当前页"))
        self.translate_book_btn.setText(self.tr("翻译整本"))
        self.stop_translation_btn.setText(self.tr("停止翻译"))
        self.restart_translation_btn.setText(self.tr("重新翻译"))
        self.copy_btn.setText(self.tr("复制译文"))
        self.prev_btn.setText(self.tr("上一页"))
        self.next_btn.setText(self.tr("下一页"))
        self.settings_btn.setText(self.tr("设置"))
        
        # 更新窗口标题
        self.setWindowTitle(self.tr("EPUB Translator"))
        
        # 恢复状态
        if hasattr(self, 'pages'):
            self.total_pages_label.setText(self.tr(f"/ {len(self.pages)}"))
            self.show_page(current_page)

    def retranslateUi(self):
        """更新界面文本"""
        # 窗口标题
        self.setWindowTitle(self.tr("EPUB Translator"))
        
        # 文件操作按钮
        self.file_btn.setText(self.tr("选择EPUB文件"))
        self.bookshelf_btn.setText(self.tr("我的书架"))
        self.toc_btn.setText(self.tr("查看目录"))
        self.search_button.setText(self.tr("搜索原文"))
        self.ai_reading_btn.setText(self.tr("AI导读"))
        
        # 翻译控制按钮
        self.translate_page_btn.setText(self.tr("翻译当前页"))
        self.translate_book_btn.setText(self.tr("翻译整本"))
        
        # 操作控制按钮
        self.stop_translation_btn.setText(self.tr("停止翻译"))
        self.restart_translation_btn.setText(self.tr("重新翻译"))
        self.copy_btn.setText(self.tr("复制译文"))
        
        # 导航按钮
        self.prev_btn.setText(self.tr("上一页"))
        self.next_btn.setText(self.tr("下一页"))
        
        # 设置按钮
        self.settings_btn.setText(self.tr("设置"))
        
        # 标签文本
        self.total_pages_label.setText(self.tr(f"/ {len(self.pages) if hasattr(self, 'pages') else 0}"))

    def setup_styles(self):
        """设置窗口样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            
            QPushButton {
                min-height: 24px;
                min-width: 60px;
                max-width: 90px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: normal;
                padding: 2px 6px;
                border: none;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #4ECDC4, stop:1 #45B7AF);
                color: white;
                text-align: center;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #45B7AF, stop:1 #4ECDC4);
            }
            
            QPushButton:disabled {
                background: #cccccc;
            }
            
            QComboBox {
                min-height: 24px;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 2px 8px;
                background-color: white;
                font-size: 11px;
            }
            
            QComboBox:hover {
                border-color: #4ECDC4;
            }
            
            QLineEdit {
                min-height: 24px;
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 2px 8px;
                background-color: white;
                font-size: 11px;
            }
            
            QLabel {
                font-size: 11px;
                color: #333333;
                font-weight: normal;
            }
        """)
        
        # 设置文本框的选择颜色
        self.original_text.setStyleSheet("""
            QTextEdit {
                selection-background-color: #6C5CE7;
                selection-color: white;
            }
        """)
        
        self.translated_text.setStyleSheet("""
            QTextEdit {
                selection-background-color: #6C5CE7;
                selection-color: white;
            }
        """)

    def create_layout(self, layout):
        """创建主窗口布局"""
        # 顶部工具栏
        top_bar = QHBoxLayout()
        
        # 文件组
        file_group = QHBoxLayout()
        file_group.addWidget(self.bookshelf_btn)
        file_group.addWidget(self.file_btn)
        file_group.addWidget(self.toc_btn)
        file_group.addWidget(self.search_button)
        file_group.addWidget(self.ai_reading_btn)
        
        # 翻译控制组
        translation_control_group = QHBoxLayout()
        translation_control_group.addWidget(self.translate_page_btn)
        
        # 操作控制组
        action_group = QHBoxLayout()
        action_group.addWidget(self.stop_translation_btn)
        action_group.addWidget(self.restart_translation_btn)
        action_group.addWidget(self.copy_btn)
        
        # 将组件添加到顶部栏
        top_bar.addLayout(file_group)
        top_bar.addSpacing(20)
        top_bar.addLayout(translation_control_group)
        top_bar.addSpacing(20)
        top_bar.addLayout(action_group)
        top_bar.addStretch()
        top_bar.addWidget(self.settings_btn)

        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧原文显示
        self.original_text = QTextBrowser()
        self.original_text.setOpenExternalLinks(False)
        self.original_text.setOpenLinks(False)
        self.original_text.anchorClicked.connect(self.handle_link_click)
        # 添加鼠标释放事件处理
        self.original_text.mouseReleaseEvent = self.on_original_text_selection
        
        # 右侧容器
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 右侧翻译显示
        self.translated_text = QTextEdit()
        self.translated_text.setReadOnly(True)
        self.translated_text.setAcceptRichText(True)
        self.translated_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        
        # 连接鼠标释放事件
        self.translated_text.mouseReleaseEvent = self.on_translated_text_click
        
        # 初始化进度组件
        self.progress_widget = ProgressWidget()
        
        # 创建导航按钮容器
        nav_container = QWidget()
        nav_layout = QHBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加导航按钮到导航容器
        nav_layout.addStretch()
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.page_edit)
        nav_layout.addWidget(self.total_pages_label)
        nav_layout.addWidget(self.next_btn)
        
        # 将组件添加到右侧布局
        right_layout.addWidget(self.translated_text)
        right_layout.addWidget(self.progress_widget)
        right_layout.addWidget(nav_container)
        
        # 添加到分割器
        splitter.addWidget(self.original_text)
        splitter.addWidget(right_container)
        
        # 设置分割器比例
        splitter.setSizes([600, 600])
        
        # 添加到主布局
        layout.addLayout(top_bar)
        layout.addWidget(splitter)
        
        # 在布局创建完成后初始化翻译器
        try:
            self.ollama_translator = OllamaTranslator(model_name=self.model)  # 使用 self.model
        except Exception as e:
            print(f"Failed to initialize Ollama translator: {e}")
            self.ollama_translator = None

    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key.Key_Left:
            self.prev_page_action.trigger()  # 触发上一页动作
        elif event.key() == Qt.Key.Key_Right:
            self.next_page_action.trigger()  # 触发下一页动作
        else:
            super().keyPressEvent(event)

    def update_preview_font(self):
        """更新预览文本的字体"""
        font = self.font_combo.currentFont()
        font.setPointSize(int(self.font_size_combo.currentText()))
        self.preview_text.setFont(font)

    def show_api_key_status(self, is_valid):
        """显示 API Key 状态"""
        if hasattr(self, 'api_key_edit'):
            if is_valid:
                # 显示绿色对勾
                self.api_key_edit.setStyleSheet("""
                    QLineEdit {
                        border: 2px solid #4CAF50;
                        background-color: #F1F8E9;
                    }
                """)
                # 添加状态标签
                if not hasattr(self, 'api_status_label'):
                    self.api_status_label = QLabel("✓ API Key 可用")
                    self.api_status_label.setStyleSheet("color: #4CAF50;")
                    self.api_key_layout.addWidget(self.api_status_label)
            else:
                # 闪烁红色边框
                def flash():
                    self.api_key_edit.setStyleSheet("""
                        QLineEdit {
                            border: 2px solid #FF5252;
                            background-color: #FFEBEE;
                        }
                    """)
                    QTimer.singleShot(500, lambda: self.api_key_edit.setStyleSheet(""))
                    QTimer.singleShot(1000, lambda: self.api_key_edit.setStyleSheet("""
                        QLineEdit {
                            border: 2px solid #FF5252;
                            background-color: #FFEBEE;
                        }
                    """))
                flash()

    def update_analysis_result(self, result):
        """更新AI分析结果"""
        self.translated_text.clear()  # 修正：使用translated_text
        self.translated_text.append(result)

    def clear_generating_status(self):
        """清除生成状态提示"""
        current_text = self.translated_text.toPlainText()  # 修正：使用translated_text
        if current_text.endswith("正在生成AI导读分析，请稍候..."):
            text = current_text.replace("\n\n正在生成AI导读分析，请稍候...", "")
            self.translated_text.clear()
            self.translated_text.append(text)

    def setup_status_bar(self):
        """设置状态栏"""
        self.statusBar().setFixedHeight(25)  # 固定状态栏高度
        
        # 创建三个状态标签
        self.status_bar_api = QLabel("API: Ollama")
        self.status_bar_translation = QLabel("就绪")
        self.status_bar_ai = QLabel("AI导读就绪")
        
        # 设置固定宽度和样式
        width = self.width() // 3
        for label in [self.status_bar_api, self.status_bar_translation, self.status_bar_ai]:
            label.setMinimumWidth(width)
            label.setStyleSheet("""
                QLabel {
                    padding: 3px;
                    border-right: 1px solid #cccccc;
                }
            """)
        
        # 添加到状态栏
        self.statusBar().addWidget(self.status_bar_api)
        self.statusBar().addWidget(self.status_bar_translation)
        self.statusBar().addWidget(self.status_bar_ai)

    def update_status(self, status_type, message):
        """更新状态栏信息"""
        if status_type == "api":
            self.status_bar_api.setText(f"API: {message}")
        elif status_type == "translation":
            self.status_bar_translation.setText(message)
        elif status_type == "ai":
            self.status_bar_ai.setText(message)

    def test_api_key(self, api_key):
        """测试 DeepSeek API Key"""
        if not api_key:
            QMessageBox.warning(self, "警告", "请输入 API Key")
            return
            
        try:
            self.status_bar_api.setText("正在测试 API Key...")
            QApplication.processEvents()
            
            test_translator = DeepSeekTranslator(
                api_key=api_key,
                target_language=self.target_language
            )
            # 尝试进行一次简单翻译
            test_result = test_translator.translate("Hello world")
            
            if test_result:
                self.show_api_key_status(True)
                QMessageBox.information(self, "成功", "API Key 验证成功！")
                self.status_bar_api.setText("API Key 测试成功")
            else:
                raise Exception("翻译测试失败")
                
        except Exception as e:
            self.show_api_key_status(False)
            QMessageBox.warning(self, "错误", f"API Key 验证失败: {str(e)}")
            self.status_bar_api.setText("API Key 测试失败")

    def on_model_changed(self, index):
        """当用户选择新模型时"""
        model = self.settings_model_combo.currentText()
        config.set_model(model)  # 使用配置管理器保存设置
        self.model = model
        
        if not self.using_deepseek:
            self.status_bar_translation.setText(f"使用模型: {model}")

    def check_ollama_models(self):
        """检测 Ollama 可用模型"""
        try:
            import subprocess
            self.status_bar_api.setText("正在检测 Ollama 模型...")
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                # 解析输出获取模型列表
                models = []
                for line in result.stdout.strip().split('\n')[1:]:  # 跳过标题行
                    if line.strip():
                        model_name = line.split()[0]  # 第一列是模型名称
                        models.append(model_name)
                
                if models:
                    # 更新设置对话框中的模型下拉框
                    self.settings_model_combo.clear()
                    self.settings_model_combo.addItems(models)
                    
                    # 如果有保存的模型设置，选择该模型
                    if self.model and self.model in models:
                        index = self.settings_model_combo.findText(self.model)
                        if index >= 0:
                            self.settings_model_combo.setCurrentIndex(index)
                    # 否则使用第一个可用模型
                    else:
                        self.model = models[0]
                        self.settings.setValue('model', self.model)
                    
                    self.status_bar_api.setText(f"检测到 {len(models)} 个 Ollama 模型")
                else:
                    self.status_bar_api.setText("未检测到已安装的 Ollama 模型")
            else:
                self.status_bar_api.setText("Ollama 服务未运行或未安装")
                
        except Exception as e:
            print(f"检测 Ollama 失败: {str(e)}")
            print(traceback.format_exc())
            self.status_bar_api.setText(f"检测 Ollama 失败: {str(e)}")

    def translate_text(self, text):
        # 获取当前选择的模型名称
        current_model = self.ui.ollamaModelComboBox.currentText()
        if not current_model:
            QMessageBox.warning(self, "警告", "请先选择 Ollama 模型")
            return
            
        translator = OllamaTranslator(model_name=current_model)
        # ... 后续翻译逻辑 ...

    def on_model_selection_changed(self, model_name):
        # 当用户选择新的模型时保存设置
        self.config_manager.set_ollama_model(model_name)

    def on_original_text_selection(self, event):
        """处理原文选择事件"""
        try:
            # 先停止之前的定时器
            if hasattr(self, 'highlight_timer') and self.highlight_timer.isActive():
                self.highlight_timer.stop()
            
            # 清除译文框的高亮
            self.clear_opposite_highlight(is_original=True)
            
            # 获取选中的文本
            cursor = self.original_text.textCursor()
            selected_text = cursor.selectedText().strip()
            
            if not selected_text:
                return
            
            # 在翻译对中查找包含选中文本的原文
            for pair in self.translation_pairs:
                original = pair['original'].strip()
                if selected_text.lower() in original.lower():
                    # 设置高亮格式
                    format = QTextCharFormat()
                    format.setBackground(QColor("#6C5CE7"))
                    format.setForeground(QColor("white"))
                    
                    # 高亮原文
                    cursor = self.original_text.textCursor()
                    cursor.setPosition(0)
                    while True:
                        cursor = self.original_text.document().find(original, cursor)
                        if cursor.isNull():
                            break
                        cursor.mergeCharFormat(format)
                    
                    # 高亮译文
                    cursor = self.translated_text.textCursor()
                    cursor.setPosition(0)
                    while True:
                        cursor = self.translated_text.document().find(pair['translated'], cursor)
                        if cursor.isNull():
                            break
                        cursor.mergeCharFormat(format)
                    
                    # 滚动到译文位置
                    cursor = self.translated_text.textCursor()
                    cursor.setPosition(0)
                    cursor = self.translated_text.document().find(pair['translated'], cursor)
                    if not cursor.isNull():
                        self.translated_text.setTextCursor(cursor)
                        self.translated_text.ensureCursorVisible()
                    
                    # 3秒后清除高亮
                    self.highlight_timer.start(3000)
                    
                    # 更新状态栏
                    self.status_bar_translation.setText("找到对应译文")
                    return  # 找到第一个匹配就返回
                    
            # 如果没有找到匹配
            self.status_bar_translation.setText("未找到对应译文")
                
        except Exception as e:
            print(f"处理原文选择错误: {str(e)}")
            print(traceback.format_exc())
            self.status_bar_translation.setText("搜索译文时出错")

    def on_translated_text_click(self, event):
        """处理译文点击事件"""
        try:
            # 先停止之前的定时器
            if hasattr(self, 'highlight_timer') and self.highlight_timer.isActive():
                self.highlight_timer.stop()
            
            # 清除原文框的高亮
            self.clear_opposite_highlight(is_original=False)
            
            # 获取用户选中的文本
            cursor = self.translated_text.textCursor()
            selected_text = cursor.selectedText().strip()
            
            if not selected_text:
                return
            
            # 在翻译对中查找包含选中文本的译文
            for pair in self.translation_pairs:
                translated = pair['translated'].strip()
                if selected_text.lower() in translated.lower():
                    # 设置高亮格式
                    format = QTextCharFormat()
                    format.setBackground(QColor("#6C5CE7"))
                    format.setForeground(QColor("white"))
                    
                    # 高亮原文
                    cursor = self.original_text.textCursor()
                    cursor.setPosition(0)
                    while True:
                        cursor = self.original_text.document().find(pair['original'], cursor)
                        if cursor.isNull():
                            break
                        cursor.mergeCharFormat(format)
                    
                    # 高亮译文
                    cursor = self.translated_text.textCursor()
                    cursor.setPosition(0)
                    while True:
                        cursor = self.translated_text.document().find(translated, cursor)
                        if cursor.isNull():
                            break
                        cursor.mergeCharFormat(format)
                    
                    # 滚动到原文位置
                    cursor = self.original_text.textCursor()
                    cursor.setPosition(0)
                    cursor = self.original_text.document().find(pair['original'], cursor)
                    if not cursor.isNull():
                        self.original_text.setTextCursor(cursor)
                        self.original_text.ensureCursorVisible()
                    
                    # 3秒后清除高亮
                    self.highlight_timer.start(3000)
                    
                    # 更新状态栏
                    self.status_bar_translation.setText("找到对应原文")
                    return  # 找到第一个匹配就返回
                    
            # 如果没有找到匹配
            self.status_bar_translation.setText("未找到对应原文")
                
        except Exception as e:
            print(f"处理译文选择错误: {str(e)}")
            print(traceback.format_exc())
            self.status_bar_translation.setText("搜索原文时出错")

    def clear_opposite_highlight(self, is_original):
        """清除对方文本框的高亮
        is_original: True表示当前在原文框，需要清除译文框的高亮；False表示相反
        """
        try:
            # 创建透明背景的格式
            format = QTextCharFormat()
            format.setBackground(Qt.GlobalColor.transparent)
            format.setForeground(Qt.GlobalColor.black)
            
            # 根据当前操作的文本框，清除对方的高亮
            text_widget = self.translated_text if is_original else self.original_text
            cursor = text_widget.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(format)
            
            # 重置光标选择
            cursor.clearSelection()
            text_widget.setTextCursor(cursor)
            
        except Exception as e:
            print(f"清除对方高亮错误: {str(e)}")
            print(traceback.format_exc())