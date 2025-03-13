from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                           QLabel, QPushButton, QScrollArea, QGridLayout,
                           QMessageBox, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QCursor
import os
import shutil
from pathlib import Path
import ebooklib
from ebooklib import epub
from PIL import Image
import io

class BookWidget(QWidget):
    """单本书的显示部件"""
    delete_requested = pyqtSignal(Path)  # 删除信号
    open_requested = pyqtSignal(Path)    # 打开信号
    
    def __init__(self, book_path, cover_path=None, is_translation=False, parent=None):
        super().__init__(parent)
        self.book_path = book_path
        self.is_translation = is_translation
        layout = QVBoxLayout(self)
        
        # 封面图片
        if cover_path:
            cover_label = QLabel()
            pixmap = QPixmap(str(cover_path))
            scaled_pixmap = pixmap.scaled(120, 160, Qt.AspectRatioMode.KeepAspectRatio)
            cover_label.setPixmap(scaled_pixmap)
            layout.addWidget(cover_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # 书名标签（译本添加标记）
        title = self.get_book_title()
        if is_translation:
            title += " [译本]"
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 打开按钮
        open_btn = QPushButton("打开")
        open_btn.clicked.connect(lambda: self.open_requested.emit(self.book_path))
        
        # 删除按钮
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self.confirm_delete)
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(open_btn)
        btn_layout.addWidget(delete_btn)
        layout.addLayout(btn_layout)
        
        self.setFixedSize(150, 250)
        
    def get_book_title(self):
        """获取书籍标题"""
        try:
            book = epub.read_epub(str(self.book_path))
            return book.get_metadata('DC', 'title')[0][0] or self.book_path.stem
        except:
            return self.book_path.stem
            
    def confirm_delete(self):
        """确认删除对话框"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除《{self.get_book_title()}》吗？\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(self.book_path)

class BookshelfWindow(QMainWindow):
    book_selected = pyqtSignal(str)  # 信号：当书籍被选中时发出
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("我的书架")
        self.setMinimumSize(800, 600)
        
        # 创建程序数据目录
        self.app_data_dir = Path.home() / "AppData" / "Local" / "EPUBTranslator"
        self.books_dir = self.app_data_dir / "books"
        self.covers_dir = self.app_data_dir / "covers"
        
        # 确保目录存在
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        
        # 添加译本目录
        self.translations_dir = self.app_data_dir / "translations"
        self.translations_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 顶部按钮栏
        top_bar = QHBoxLayout()
        self.import_btn = QPushButton("导入新书")
        self.import_btn.clicked.connect(self.import_book)
        top_bar.addWidget(self.import_btn)
        top_bar.addStretch()
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        self.grid_layout = QGridLayout(scroll_content)
        scroll_area.setWidget(scroll_content)
        
        # 添加到主布局
        layout.addLayout(top_bar)
        layout.addWidget(scroll_area)
        
        # 加载书架
        self.load_bookshelf()
        
    def load_bookshelf(self):
        """加载书架中的所有书籍"""
        # 清除现有内容
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        # 加载所有书籍（排除译本）
        books = []
        for book_path in self.books_dir.glob("*.epub"):
            # 检查是否是译本（文件名中不包含 "_translation"）
            if "_translation" not in book_path.stem:
                books.append(book_path)
        
        cols = 4  # 每行显示的书籍数
        
        for i, book_path in enumerate(books):
            row = i // cols
            col = i % cols
            
            # 获取封面
            cover_path = self.get_book_cover(book_path)
            
            # 创建书籍部件
            book_widget = BookWidget(book_path, cover_path)
            book_widget.open_requested.connect(lambda p: self.book_selected.emit(str(p)))
            book_widget.delete_requested.connect(self.delete_book)
            
            self.grid_layout.addWidget(book_widget, row, col)
        
    def delete_book(self, book_path):
        """删除书籍及其相关文件"""
        try:
            # 删除原书
            book_path.unlink()
            
            # 删除对应的译本
            translation_path = self.translations_dir / f"{book_path.stem}_translation.epub"
            if translation_path.exists():
                translation_path.unlink()
            
            # 删除翻译记录
            record_path = self.translations_dir / f"{book_path.stem}_record.json"
            if record_path.exists():
                record_path.unlink()
            
            # 删除封面文件
            cover_path = self.covers_dir / f"{book_path.stem}_cover.jpg"
            if cover_path.exists():
                cover_path.unlink()
            
            # 重新加载书架
            self.load_bookshelf()
            
        except Exception as e:
            QMessageBox.warning(
                self,
                "删除失败",
                f"删除书籍时出错：{str(e)}"
            )
            
    def get_book_cover(self, book_path):
        """获取书籍封面"""
        cover_path = self.covers_dir / f"{book_path.stem}_cover.jpg"
        
        # 如果封面已存在，直接返回
        if cover_path.exists():
            return cover_path
            
        try:
            book = epub.read_epub(str(book_path))
            
            # 查找封面
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if 'cover' in item.id.lower() or 'cover' in item.file_name.lower():
                    # 保存封面图片
                    image = Image.open(io.BytesIO(item.content))
                    image.save(str(cover_path))
                    return cover_path
                    
            # 如果没找到封面，使用第一张图片
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                image = Image.open(io.BytesIO(item.content))
                image.save(str(cover_path))
                return cover_path
                
        except Exception as e:
            print(f"获取封面错误: {str(e)}")
            
        return None
        
    def import_book(self):
        """导入新书"""
        from PyQt6.QtWidgets import QFileDialog
        
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择EPUB文件",
            "",
            "EPUB Files (*.epub)"
        )
        
        if file_name:
            # 复制文件到书架目录
            source_path = Path(file_name)
            dest_path = self.books_dir / source_path.name
            
            try:
                shutil.copy2(str(source_path), str(dest_path))
                self.load_bookshelf()  # 重新加载书架
            except Exception as e:
                print(f"导入书籍错误: {str(e)}")
                
    def open_book(self, book_path):
        """打开选中的书籍"""
        self.book_selected.emit(str(book_path))
        self.close() 