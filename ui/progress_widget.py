from PyQt6.QtWidgets import QWidget, QVBoxLayout, QProgressBar, QLabel
from PyQt6.QtCore import Qt

class ProgressWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 状态标签
        self.status_label = QLabel("准备就绪")
        self.time_label = QLabel("预计剩余时间: --:--")
        self.count_label = QLabel("0 / 0 句已翻译")
        self.speed_label = QLabel("当前速度: -- 秒/句")
        
        # 添加到布局
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.speed_label)
        
    def update_progress(self, current, total, estimated_time=None, current_time=None):
        """更新进度和时间信息"""
        percentage = int((current / total) * 100)
        self.progress_bar.setValue(percentage)
        self.count_label.setText(f"{current} / {total} 句已翻译")
        
        if current_time is not None:
            self.speed_label.setText(f"当前速度: {current_time:.1f} 秒/句")
            
        if estimated_time is not None:
            minutes = int(estimated_time // 60)
            seconds = int(estimated_time % 60)
            self.time_label.setText(f"预计剩余时间: {minutes:02d}:{seconds:02d}")
        
    def update_status(self, status):
        self.status_label.setText(status) 

    def reset(self):
        """重置进度条和状态标签"""
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setValue(0)
            self.progress_bar.setMaximum(100)
        if hasattr(self, 'status_label'):
            self.status_label.setText("")
        if hasattr(self, 'time_label'):
            self.time_label.setText("") 