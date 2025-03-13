import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import re
import traceback
import os
import base64
import mimetypes
from pathlib import Path
from langdetect import detect

class EpubHandler:
    def __init__(self, file_path):
        self.book = epub.read_epub(file_path)
        self.file_path = file_path
        self.pages = []
        self.CHAR_LIMIT_ANCIENT_CHINESE = 300  # 古文字符限制
        self.CHAR_LIMIT_DEFAULT = 1000        # 其他语言字符限制
        self.images = {}  # 存储图片数据
        self.temp_dir = None
        self.modified_content = {}  # 存储修改后的内容
        
    def extract_pages(self):
        """将EPUB文件拆分为页面，并处理图片"""
        pages = []
        
        print("开始提取图片...")
        # 提取所有图片
        for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
            try:
                print(f"处理图片: {item.file_name}")
                image_data = base64.b64encode(item.content).decode('utf-8')
                mime_type = mimetypes.guess_type(item.file_name)[0] or 'image/jpeg'
                image_name = item.file_name.split('/')[-1]
                self.images[image_name] = f"data:{mime_type};base64,{image_data}"
                self.images[item.file_name] = f"data:{mime_type};base64,{image_data}"
                if hasattr(item, 'id'):
                    print(f"图片ID: {item.id}")
                    self.images[item.id] = f"data:{mime_type};base64,{image_data}"
                print(f"成功处理图片: {image_name}, 大小: {len(item.content)} 字节")
            except Exception as e:
                print(f"处理图片错误 {item.file_name}: {str(e)}")

        print(f"共处理 {len(self.images)} 个图片")
        print("开始处理HTML页面...")

        # 处理HTML页面
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            try:
                print(f"处理页面: {item.file_name}")
                content = item.get_content().decode('utf-8')
                
                # 使用 lxml 解析器以更好地保留原始格式
                soup = BeautifulSoup(content, 'lxml')
                
                # 添加文件名信息到页面（隐藏的元数据）
                meta_tag = soup.new_tag('meta')
                meta_tag['name'] = 'epub-file'
                meta_tag['content'] = item.file_name
                if soup.head:
                    soup.head.append(meta_tag)
                else:
                    head_tag = soup.new_tag('head')
                    head_tag.append(meta_tag)
                    if soup.html:
                        soup.html.insert(0, head_tag)
                    else:
                        html_tag = soup.new_tag('html')
                        html_tag.append(head_tag)
                        soup.append(html_tag)
                
                # 处理所有图片标签
                for img in soup.find_all('img'):
                    src = img.get('src', '')
                    print(f"找到图片标签, src={src}")
                    
                    # 尝试多种路径形式
                    if src in self.images:
                        img['src'] = self.images[src]
                    elif src.split('/')[-1] in self.images:
                        img['src'] = self.images[src.split('/')[-1]]
                    else:
                        # 尝试处理相对路径
                        for key in self.images.keys():
                            if key.endswith(src):
                                img['src'] = self.images[key]
                                break
                
                # 添加基本的样式
                style_tag = soup.new_tag('style')
                style_tag.string = """
                    body { 
                        font-family: Arial, sans-serif; 
                        line-height: 1.6; 
                        margin: 2em;
                    }
                    img { 
                        max-width: 100%; 
                        height: auto; 
                        display: block; 
                        margin: 1em auto; 
                    }
                    p { 
                        margin: 1em 0; 
                    }
                    h1, h2, h3, h4, h5, h6 {
                        margin: 1.5em 0 0.5em 0;
                    }
                """
                
                # 确保有完整的HTML结构
                if not soup.html:
                    new_html = soup.new_tag('html')
                    new_html.append(soup)
                    soup = BeautifulSoup(str(new_html), 'lxml')
                
                if not soup.head:
                    head = soup.new_tag('head')
                    soup.html.insert(0, head)
                
                if not soup.body:
                    body = soup.new_tag('body')
                    for tag in list(soup.html.children):
                        if tag.name not in ['head', None]:
                            body.append(tag)
                    soup.html.append(body)
                
                # 添加样式
                if style_tag not in soup.head:
                    soup.head.append(style_tag)
                
                # 保存处理后的页面
                processed_html = str(soup)
                print(f"页面处理完成，HTML长度: {len(processed_html)}")
                if 'base64' in processed_html:
                    print("HTML中包含base64图片数据")
                
                pages.append(processed_html)
                
            except Exception as e:
                print(f"处理页面错误: {str(e)}")
                print(traceback.format_exc())
                # 如果处理失败，使用原始内容
                pages.append(f"<html><body>{content}</body></html>")
        
        print(f"共处理 {len(pages)} 个页面")
        return pages
        
    def extract_paragraphs_from_html(self, html_content):
        """从HTML内容中提取段落"""
        soup = BeautifulSoup(html_content, 'html.parser')
        paragraphs = []
        
        # 提取所有段落标签
        for p in soup.find_all(['p', 'div']):
            text = p.get_text().strip()
            if text:  # 只保留非空段落
                paragraphs.append(text)
                
        return paragraphs
        
    def replace_translated_content(self, original, translated, item):
        """替换翻译后的内容"""
        content = item.get_content().decode('utf-8')
        content = content.replace(original, translated)
        item.set_content(content.encode('utf-8')) 
        
    def extract_sentences_from_html(self, html_content):
        """从HTML内容中提取句子"""
        soup = BeautifulSoup(html_content, 'html.parser')
        text = soup.get_text()
        
        # 使用更复杂的分句规则
        sentence_endings = r'(?<=[.!?。！？])\s+'
        sentences = re.split(sentence_endings, text)
        
        # 过滤空句子并清理每个句子
        return [s.strip() for s in sentences if s.strip()] 
        
    def is_ancient_chinese(self, text):
        """检测是否为古文"""
        try:
            # 检测语言
            lang = detect(text)
            if lang != 'zh':
                return False
                
            # 古文特征词列表
            ancient_words = [
                '之', '乎', '也', '矣', '焉', '哉', '耳', '夫', '盖', '诚',
                '而', '若', '其', '或', '所', '以', '故', '曰', '且', '者',
                '何', '不', '然', '已', '于', '此', '之', '无', '有', '亦'
            ]
            
            # 计算特征词出现的频率
            word_count = sum(text.count(word) for word in ancient_words)
            text_length = len(text)
            
            # 如果特征词密度超过阈值，认为是古文
            return (word_count / text_length) > 0.1
            
        except:
            return False
            
    def get_translation_units(self, html_content):
        """智能提取翻译单位，根据语言类型调整分段大小"""
        soup = BeautifulSoup(html_content, 'html.parser')
        translation_units = []
        current_texts = []
        current_length = 0
        
        def add_current_unit():
            if current_texts:
                translation_units.append({
                    'text': '\n'.join(current_texts),
                    'elements': [],
                    'length': current_length
                })
        
        # 获取页面的主要文本用于语言检测
        main_text = soup.get_text()
        is_ancient = self.is_ancient_chinese(main_text)
        char_limit = self.CHAR_LIMIT_ANCIENT_CHINESE if is_ancient else self.CHAR_LIMIT_DEFAULT
        
        print(f"检测到{'古文' if is_ancient else '其他语言'}, 使用字符限制: {char_limit}")
        
        for element in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            text = element.get_text().strip()
            if not text:
                continue
            
            # 如果是超长文本，单独处理
            if len(text) > char_limit:
                # 先添加之前累积的文本
                add_current_unit()
                current_texts = []
                current_length = 0
                
                # 处理长文本
                remaining_text = text
                while remaining_text:
                    # 找到合适的切分点
                    cut_point = self.find_cut_point(remaining_text, char_limit)
                    unit_text = remaining_text[:cut_point]
                    translation_units.append({
                        'text': unit_text,
                        'elements': [element],
                        'length': len(unit_text)
                    })
                    remaining_text = remaining_text[cut_point:].strip()
            else:
                # 如果加上新文本会超过限制，先保存当前单位
                if current_length + len(text) > char_limit:
                    add_current_unit()
                    current_texts = []
                    current_length = 0
                
                current_texts.append(text)
                current_length += len(text)
        
        # 添加最后一个单位
        add_current_unit()
        
        return translation_units
        
    def find_cut_point(self, text, limit):
        """找到合适的切分点，优先在句子末尾切分"""
        if len(text) <= limit:
            return len(text)
        
        # 在限制范围内查找最后一个句子结束标记
        search_text = text[:limit]
        
        # 中文句子结束标记
        chinese_endings = ['。', '！', '？', '…', '"', '」', '』', '）', '】', '》', '；']
        # 英文句子结束标记
        english_endings = ['. ', '! ', '? ', '... ', '" ', ') ', '] ', '} ', '> ', '; ']
        
        last_ending = -1
        
        # 检查中文句子结束标记
        for ending in chinese_endings:
            pos = search_text.rfind(ending)
            last_ending = max(last_ending, pos)
        
        # 检查英文句子结束标记
        for ending in english_endings:
            pos = search_text.rfind(ending)
            if pos != -1:
                last_ending = max(last_ending, pos + 1)  # +1 包含空格
        
        if last_ending != -1:
            return last_ending + 1
        
        # 如果找不到句子结束标记，查找最后一个标点符号
        punctuation = [',', '，', '、', '；', '：', ';', ':', ' ', '\n']
        for punct in punctuation:
            pos = search_text.rfind(punct)
            if pos != -1:
                return pos + 1
        
        # 如果实在找不到合适的切分点，就在限制处直接切分
        return limit
        
    def update_translated_content(self, html_content, original_text, translated_text):
        """更新HTML内容中的文本，保持原有格式和图片"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 查找包含原文的所有文本节点
            text_nodes = []
            for element in soup.find_all(text=True):
                if original_text in element.string:
                    text_nodes.append(element)
            
            # 替换文本，保持图片不变
            for node in text_nodes:
                new_text = node.string.replace(original_text, translated_text)
                node.string.replace_with(new_text)
            
            return str(soup)
        except Exception as e:
            print(f"更新HTML内容错误: {str(e)}")
            print(traceback.format_exc())
            return html_content 
        
    def update_content(self, original_text, translated_text):
        """更新EPUB内容"""
        try:
            # 遍历所有文档
            for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                content = item.get_content().decode('utf-8')
                if original_text in content:
                    # 更新内容
                    new_content = content.replace(original_text, translated_text)
                    self.modified_content[item.id] = new_content
        except Exception as e:
            print(f"更新EPUB内容错误: {str(e)}")
            print(traceback.format_exc())
    
    def save_epub(self):
        """保存修改后的EPUB文件"""
        try:
            # 更新所有修改过的文档
            for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                if item.id in self.modified_content:
                    item.set_content(self.modified_content[item.id].encode('utf-8'))
            
            # 保存EPUB文件
            epub.write_epub(self.file_path, self.book)
            print(f"EPUB文件已保存: {self.file_path}")
        except Exception as e:
            print(f"保存EPUB文件错误: {str(e)}")
            print(traceback.format_exc())
            raise 