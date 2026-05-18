import os
import subprocess
import re
import json
import argparse
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict

try:
    import pysrt
except ImportError:
    print("Warning: pysrt not installed, subtitle processing will be skipped")
    pysrt = None

try:
    import you_get
    from you_get.extractors import bilibili
except ImportError:
    print("Warning: you-get not installed, will try ffmpeg download")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    print("Warning: openai-whisper not installed, ASR will not be available")
    WHISPER_AVAILABLE = False

class VideoToMarkdown:
    def __init__(self):
        self.screenshot_count = 0
        self.temp_dir = tempfile.mkdtemp()
        self.ffmpeg_path = self._find_ffmpeg()
        self.keywords = {
            'intro': ['介绍', '简介', '开始', '今天', '主题', '内容', '目的'],
            'concept': ['概念', '定义', '含义', '意思', '理解', '本质'],
            'method': ['方法', '步骤', '流程', '过程', '做法', '技巧', '如何', '步骤'],
            'example': ['例子', '示例', '案例', '演示', '实战', '练习'],
            'code': ['代码', '编程', '实现', '开发', '编写', '函数', '类', '接口'],
            'result': ['结果', '效果', '输出', '展示', '对比', '差异'],
            'summary': ['总结', '回顾', '要点', '核心', '重点', '关键']
        }
        
    def _find_ffmpeg(self) -> str:
        """查找ffmpeg可执行文件路径"""
        possible_paths = [
            os.path.join(os.path.dirname(__file__), 'ffmpeg', 'ffmpeg-master-latest-win64-gpl', 'bin', 'ffmpeg.exe'),
            'ffmpeg.exe',
            'ffmpeg'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return 'ffmpeg'
        
    def download_video(self, url: str) -> str:
        """从URL下载视频"""
        try:
            import sys
            from io import StringIO
            
            old_stdout = sys.stdout
            sys.stdout = StringIO()
            
            you_get.main(['-o', self.temp_dir, url])
            
            sys.stdout = old_stdout
            
            for file in os.listdir(self.temp_dir):
                if file.endswith(('.mp4', '.mov', '.mkv', '.webm', '.flv')):
                    return os.path.join(self.temp_dir, file)
        except Exception as e:
            print(f"You-get download failed: {e}")
        
        try:
            video_path = os.path.join(self.temp_dir, 'video.mp4')
            cmd = [
                self.ffmpeg_path, '-i', url,
                '-c', 'copy', '-bsf:a', 'aac_adtstoasc',
                '-y', video_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300, encoding='utf-8', errors='ignore')
            if result.returncode == 0 and os.path.exists(video_path):
                return video_path
        except Exception as e:
            print(f"FFmpeg download failed: {e}")
        
        return None
        
    def is_url(self, path: str) -> bool:
        """判断是否为URL"""
        return path.startswith(('http://', 'https://'))
    
    def extract_audio(self, video_path: str) -> str:
        """从视频中提取音频"""
        audio_path = os.path.join(self.temp_dir, 'audio.wav')
        try:
            cmd = [
                self.ffmpeg_path, '-i', video_path,
                '-vn', '-acodec', 'pcm_s16le',
                '-ar', '16000', '-ac', '1',
                '-y', audio_path
            ]
            subprocess.run(cmd, capture_output=True, timeout=600, encoding='utf-8', errors='ignore')
            if os.path.exists(audio_path):
                return audio_path
        except Exception as e:
            print(f"Audio extraction failed: {e}")
        return None
    
    def transcribe_with_whisper(self, audio_path: str) -> List[Tuple[float, float, str]]:
        """Use Whisper for speech recognition"""
        if not WHISPER_AVAILABLE:
            return []

        subs = []
        try:
            # Add ffmpeg to PATH for Whisper
            ffmpeg_dir = os.path.dirname(self.ffmpeg_path)
            os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')
            
            print("Loading Whisper model (first run may take some time)...")
            model = whisper.load_model("tiny", device="cpu")
            print("Whisper model loaded, starting transcription...")

            # vad_filter not supported in openai-whisper
            result = model.transcribe(audio_path, beam_size=5)

            print(f"Detected language: {result['language']}, processing audio...")

            for segment in result['segments']:
                start = segment['start']
                end = segment['end']
                text = segment['text'].strip()
                if text:
                    subs.append((start, end, text))

            print(f"Transcription complete, {len(subs)} segments recognized")

        except Exception as e:
            print(f"Whisper transcription failed: {e}")

        return subs
        
    def extract_subtitles(self, video_path: str) -> List[Tuple[float, float, str]]:
        """从视频中提取字幕"""
        subs = []
        srt_path = os.path.splitext(video_path)[0] + ".srt"
        
        if os.path.exists(srt_path) and pysrt:
            try:
                srt_subs = pysrt.open(srt_path)
                for sub in srt_subs:
                    start = sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds + sub.start.milliseconds / 1000
                    end = sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds + sub.end.milliseconds / 1000
                    text = sub.text.replace('\n', ' ')
                    subs.append((start, end, text))
            except Exception as e:
                print(f"SRT file read failed: {e}")
        
        if not subs:
            subs = self.extract_subtitles_via_ffmpeg(video_path)
        
        if not subs:
            print("No embedded subtitles found, trying ASR...")
            audio_path = self.extract_audio(video_path)
            if audio_path:
                subs = self.transcribe_with_whisper(audio_path)
        
        return subs
    
    def extract_subtitles_via_ffmpeg(self, video_path: str) -> List[Tuple[float, float, str]]:
        """使用ffmpeg提取字幕"""
        subs = []
        try:
            cmd = [
                self.ffmpeg_path, '-i', video_path,
                '-map', 's:0', '-f', 'srt', '-'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='ignore')
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                i = 0
                while i < len(lines):
                    if lines[i].strip().isdigit():
                        i += 1
                        if i < len(lines):
                            time_line = lines[i].strip()
                            i += 1
                            text = ""
                            while i < len(lines) and lines[i].strip():
                                text += lines[i].strip() + " "
                                i += 1
                            if time_line and text:
                                match = re.match(r'(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)', time_line)
                                if match:
                                    start = self.parse_time(match.group(1))
                                    end = self.parse_time(match.group(2))
                                    subs.append((start, end, text.strip()))
                    i += 1
        except Exception as e:
            print(f"FFmpeg subtitle extraction failed: {e}")
        
        return subs
    
    def parse_time(self, time_str: str) -> float:
        """解析时间字符串为秒数"""
        parts = re.split(r'[:,]', time_str)
        if len(parts) >= 4:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            milliseconds = int(parts[3]) if len(parts) > 3 else 0
            return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
        return 0.0
    
    def format_time(self, seconds: float) -> str:
        """将秒数格式化为mm:ss"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def should_add_screenshot(self, text: str) -> bool:
        """判断是否需要添加截图提示"""
        triggers = [
            '代码', '编程', '界面', '页面', '按钮', '点击',
            '这么', '这里', '这儿', '那里', '那边',
            '网址', '地址', '链接', '网站',
            '对比', '比较', '区别', '差异',
            '演示', '展示', '操作', '步骤',
            '效果', '结果', '界面'
        ]
        for trigger in triggers:
            if trigger in text:
                return True
        return False
    
    def group_subtitles_into_paragraphs(self, subs: List[Tuple[float, float, str]]) -> List[Dict]:
        """将字幕分组为段落"""
        paragraphs = []
        current_paragraph = []
        current_start = 0
        max_gap = 3.0
        
        for start, end, text in subs:
            if not current_paragraph:
                current_paragraph.append(text)
                current_start = start
            else:
                gap = start - current_start
                if gap > max_gap or len(' '.join(current_paragraph)) > 200:
                    paragraphs.append({
                        'text': ' '.join(current_paragraph),
                        'start': current_start,
                        'end': current_start + 1
                    })
                    current_paragraph = [text]
                    current_start = start
                else:
                    current_paragraph.append(text)
        
        if current_paragraph:
            paragraphs.append({
                'text': ' '.join(current_paragraph),
                'start': current_start,
                'end': current_start + 1
            })
        
        return paragraphs
    
    def analyze_content_type(self, text: str) -> str:
        """分析内容类型，用于智能标题生成"""
        text_lower = text.lower()
        for content_type, keywords in self.keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return content_type
        return 'general'
    
    def extract_core_points(self, subs: List[Tuple[float, float, str]]) -> List[Dict]:
        """从字幕中提取核心观点"""
        core_points = []
        important_patterns = [
            r'(重要|关键|核心|重点).*?([。！？])',
            r'(必须|应该|建议|需要).*?([。！？])',
            r'(首先|其次|然后|最后|第一步|第二步).*?([。！？])',
            r'(总结|结论|要点).*?([。！？])',
            r'(注意|警告|提示).*?([。！？])'
        ]
        
        for start, end, text in subs:
            for pattern in important_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    core_points.append({
                        'text': match[0] + match[1],
                        'start': start,
                        'end': end,
                        'is_important': True
                    })
            if len(text) > 30 and ('。' in text or '！' in text or '？' in text):
                core_points.append({
                    'text': text,
                    'start': start,
                    'end': end,
                    'is_important': False
                })
        
        return core_points
    
    def generate_intelligent_title(self, text: str, index: int) -> str:
        """根据内容智能生成标题"""
        content_type = self.analyze_content_type(text)
        
        title_templates = {
            'intro': ['简介', '概述', '内容介绍', '主题引入', '开篇说明'],
            'concept': ['核心概念', '基本定义', '概念解析', '理论基础', '关键术语'],
            'method': ['实现步骤', '操作流程', '方法详解', '步骤指南', '实践方法'],
            'example': ['示例演示', '实战案例', '代码示例', '应用实例', '案例分析'],
            'code': ['代码实现', '编程讲解', '代码解析', '开发要点', '代码说明'],
            'result': ['结果展示', '效果对比', '输出分析', '结果解读', '对比总结'],
            'summary': ['总结归纳', '要点回顾', '核心要点', '关键总结', '内容回顾']
        }
        
        if content_type in title_templates:
            templates = title_templates[content_type]
            return templates[min(index, len(templates) - 1)]
        
        default_titles = [
            '主要内容', '核心观点', '关键要点', '深入分析',
            '详细解读', '要点阐述', '内容讲解', '重点说明'
        ]
        return default_titles[min(index, len(default_titles) - 1)]
    
    def generate_paragraph_title(self, text: str, index: int) -> str:
        """生成段落标题（兼容旧方法）"""
        return self.generate_intelligent_title(text, index)
    
    def process_paragraph(self, text: str, end_time: float) -> str:
        """处理段落文本，添加必要的截图提示"""
        text = text.strip()
        
        if not text.endswith(('。', '！', '？', '；', ':', '.')):
            text += '。'
        
        if self.should_add_screenshot(text):
            text += f" Screenshot-{self.format_time(end_time)}"
        
        return text
    
    def generate_article_title(self, subs: List[Tuple[float, float, str]]) -> str:
        """从字幕中生成文章主标题"""
        first_text = ' '.join([text for _, _, text in subs[:5]]).strip()
        
        patterns = [
            r'(主题|题目|内容|介绍|教程|实战|入门).*?([。！？：])',
            r'(今天|本次|我们|大家好).*?(讲|说|分享|介绍|学习|教你).*?([。！？：])'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_text)
            if match:
                title = match.group(0).replace('。', '').replace('！', '').replace('？', '').replace('：', '')
                if len(title) > 5:
                    return title
        
        if len(first_text) > 80:
            return first_text[:80] + '...'
        return first_text or '视频笔记'
    
    def analyze_video_structure(self, subs: List[Tuple[float, float, str]]) -> List[Dict]:
        """分析视频结构，识别主要章节"""
        chapters = []
        current_chapter = {'title': '', 'content': [], 'start': 0, 'end': 0}
        chapter_patterns = [
            r'(第[一二三四五六七八九十]章|第[0-9]+节|第[0-9]+部分|接下来|下面|现在)',
            r'(开始|首先|第一步|第一部分|入门|介绍)',
            r'(总结|回顾|结束|最后)'
        ]
        
        for start, end, text in subs:
            matched = False
            for pattern in chapter_patterns:
                if re.search(pattern, text):
                    if current_chapter['content']:
                        chapters.append(current_chapter)
                    current_chapter = {
                        'title': text.strip()[:50],
                        'content': [(start, end, text)],
                        'start': start,
                        'end': end
                    }
                    matched = True
                    break
            
            if not matched:
                current_chapter['content'].append((start, end, text))
                current_chapter['end'] = end
        
        if current_chapter['content']:
            chapters.append(current_chapter)
        
        return chapters
    
    def summarize_chapter(self, chapter_content: List[Tuple[float, float, str]]) -> str:
        """总结章节内容"""
        texts = [text for _, _, text in chapter_content]
        full_text = ' '.join(texts)
        
        if len(full_text) > 500:
            sentences = re.split(r'[。！？]', full_text)
            key_sentences = []
            
            important_patterns = [
                r'(重要|关键|核心|重点|必须|应该|建议)',
                r'(首先|其次|然后|最后|第一步|第二步)',
                r'(总结|结论|要点)'
            ]
            
            for sentence in sentences[:20]:
                if any(re.search(pattern, sentence) for pattern in important_patterns):
                    key_sentences.append(sentence.strip())
            
            if key_sentences:
                return '。'.join(key_sentences[:5]) + '。'
            
            return full_text[:300] + '...'
        
        return full_text
    
    def generate_tutorial_structure(self, subs: List[Tuple[float, float, str]]) -> Dict:
        """生成教程式文章结构"""
        chapters = self.analyze_video_structure(subs)
        
        structure = {
            'title': self.generate_article_title(subs),
            'intro': '',
            'chapters': [],
            'summary': ''
        }
        
        if chapters:
            structure['intro'] = self.summarize_chapter(chapters[0]['content'])[:200]
            
            for i, chapter in enumerate(chapters[1:-1], 1):
                chapter_text = ' '.join([text for _, _, text in chapter['content']])
                chapter_summary = self.summarize_chapter(chapter['content'])
                
                chapter_info = {
                    'number': i,
                    'title': self.generate_intelligent_title(chapter_text, i),
                    'original_title': chapter['title'],
                    'content': chapter_summary,
                    'start_time': chapter['start'],
                    'end_time': chapter['end'],
                    'screenshots': self.identify_screenshot_points(chapter['content'])
                }
                structure['chapters'].append(chapter_info)
            
            if len(chapters) > 1:
                last_chapter = chapters[-1]
                structure['summary'] = self.summarize_chapter(last_chapter['content'])
        
        return structure
    
    def identify_screenshot_points(self, content: List[Tuple[float, float, str]]) -> List[float]:
        """识别需要截图的时间点"""
        points = []
        for start, end, text in content:
            if self.should_add_screenshot(text):
                points.append(end)
        return points[:5]
    
    def generate_markdown(self, video_path: str, style: str = 'detailed') -> str:
        """生成Markdown笔记（增强版）"""
        subs = self.extract_subtitles(video_path)
        
        if not subs:
            return "## 无法提取字幕\n\n视频中未找到字幕信息，请确保视频包含字幕轨道或提供配套的SRT字幕文件。"
        
        if style == 'tutorial':
            return self.generate_tutorial_markdown(subs)
        
        article_title = self.generate_article_title(subs)
        paragraphs = self.group_subtitles_into_paragraphs(subs)
        core_points = self.extract_core_points(subs)
        
        markdown_parts = [f"# {article_title}"]
        
        for i, para in enumerate(paragraphs):
            title = self.generate_intelligent_title(para['text'], i)
            content = self.process_paragraph(para['text'], para.get('end', para['start'] + 5))
            
            for cp in core_points:
                if cp['start'] >= para['start'] and cp['text'] in para['text']:
                    content = f"**{cp['text']}**\n\n" + content
                    break
            
            markdown_parts.append(f"## {title}\n\n{content}")
        
        if core_points:
            important_points = [cp['text'] for cp in core_points if cp.get('is_important')][:5]
            if important_points:
                markdown_parts.append("## 核心要点\n\n" + "\n\n".join([f"- {point}" for point in important_points]))
        
        return '\n\n'.join(markdown_parts)
    
    def generate_tutorial_markdown(self, subs: List[Tuple[float, float, str]]) -> str:
        """生成教程风格的Markdown文章"""
        structure = self.generate_tutorial_structure(subs)
        return self._build_tutorial_markdown(structure, subs, include_images=False)
    
    def generate_tutorial_markdown_with_images(self, subs: List[Tuple[float, float, str]], structure: Dict, video_path: str, output_dir: str) -> str:
        """生成带实际截图的教程风格Markdown文章"""
        screenshots_dir = os.path.join(output_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        
        image_counter = 1
        for chapter in structure['chapters']:
            for time in chapter.get('screenshots', []):
                time_str = self.format_time(time)
                image_name = f"screenshot_{image_counter:03d}_{time_str.replace(':', '_')}.png"
                image_path = os.path.join(screenshots_dir, image_name)
                
                if self.capture_screenshot(video_path, time_str, image_path):
                    chapter.setdefault('images', []).append(image_name)
                
                image_counter += 1
        
        return self._build_tutorial_markdown(structure, subs, include_images=True)
    
    def _build_tutorial_markdown(self, structure: Dict, subs: List[Tuple[float, float, str]], include_images: bool = False) -> str:
        """构建教程风格的Markdown文章"""
        markdown_parts = []
        
        markdown_parts.append(f"## 🚀 {structure['title']}")
        markdown_parts.append("")
        markdown_parts.append("---")
        markdown_parts.append("")
        
        markdown_parts.append("### 👋 嗨，我是你的AI助手")
        markdown_parts.append("")
        
        intro_text = structure['intro'] or "今天给大家分享一个超实用的教程！"
        markdown_parts.append(intro_text)
        markdown_parts.append("")
        
        if structure['chapters']:
            markdown_parts.append("### 📋 教程目录")
            markdown_parts.append("")
            for i, chapter in enumerate(structure['chapters'][:6], 1):
                markdown_parts.append(f"{i}️⃣ **{chapter['title']}**")
            markdown_parts.append("")
            markdown_parts.append("---")
            markdown_parts.append("")
        
        step_num = 1
        for chapter in structure['chapters']:
            markdown_parts.append(f"## 📝 第{step_num}步：{chapter['title']}")
            markdown_parts.append("")
            markdown_parts.append(chapter['content'])
            
            if include_images and chapter.get('images'):
                for idx, image_name in enumerate(chapter['images'], 1):
                    markdown_parts.append("")
                    markdown_parts.append(f"![截图{idx}](screenshots/{image_name})")
            elif chapter['screenshots']:
                for idx, time in enumerate(chapter['screenshots'], 1):
                    time_str = self.format_time(time)
                    markdown_parts.append("")
                    markdown_parts.append(f"**【配图位置{idx}：{time_str}截图】**")
                    markdown_parts.append(f"*(配图描述：{chapter['title']}相关界面截图)*")
            
            markdown_parts.append("")
            markdown_parts.append("---")
            markdown_parts.append("")
            step_num += 1
        
        if structure['summary']:
            markdown_parts.append("## ✨ 总结")
            markdown_parts.append("")
            markdown_parts.append(structure['summary'])
            markdown_parts.append("")
            markdown_parts.append("**重点记住：**")
            markdown_parts.append("")
            
            core_points = self.extract_core_points(subs)
            important_points = [cp['text'] for cp in core_points if cp.get('is_important')][:4]
            for i, point in enumerate(important_points, 1):
                markdown_parts.append(f"{i}. {point}")
            
            markdown_parts.append("")
            markdown_parts.append("---")
            markdown_parts.append("")
        
        markdown_parts.append("## 💬 有问题？来聊天！")
        markdown_parts.append("")
        markdown_parts.append("你们在学习过程中遇到什么问题了吗？欢迎在评论区留言！")
        markdown_parts.append("")
        markdown_parts.append("**评论区见！**")
        markdown_parts.append("")
        markdown_parts.append("---")
        markdown_parts.append("")
        markdown_parts.append("*关注我，获取更多实用教程！*")
        
        return '\n'.join(markdown_parts)
    
    def extract_screenshot_placeholders(self, markdown_content: str) -> List[Tuple[str, str]]:
        """提取Markdown中的截图占位符"""
        pattern = r'Screenshot-(\d{2}:\d{2})'
        matches = re.findall(pattern, markdown_content)
        return [(match, f"screenshot_{match.replace(':', '_')}.png") for match in matches]
    
    def capture_screenshot(self, video_path: str, time_str: str, output_path: str):
        """使用ffmpeg截取指定时间点的画面"""
        try:
            cmd = [
                self.ffmpeg_path, '-ss', time_str,
                '-i', video_path,
                '-vframes', '1',
                '-q:v', '2',
                '-y', output_path
            ]
            subprocess.run(cmd, capture_output=True, timeout=30, encoding='utf-8', errors='ignore')
            return True
        except Exception as e:
            print(f"Screenshot failed {time_str}: {e}")
            return False
    
    def replace_placeholders_with_images(self, markdown_content: str, video_path: str, output_dir: str) -> str:
        """将截图占位符替换为实际图片"""
        placeholders = self.extract_screenshot_placeholders(markdown_content)
        
        for time_str, image_name in placeholders:
            image_path = os.path.join(output_dir, image_name)
            if self.capture_screenshot(video_path, time_str, image_path):
                markdown_content = markdown_content.replace(
                    f"Screenshot-{time_str}",
                    f"![截图]({image_name})"
                )
        
        return markdown_content
    
    def process_video(self, video_path: str, output_dir: str = "./output", style: str = 'detailed') -> str:
        """处理视频并生成完整的Markdown笔记"""
        os.makedirs(output_dir, exist_ok=True)
        
        actual_video_path = video_path
        
        if self.is_url(video_path):
            print(f"Downloading video: {video_path}")
            actual_video_path = self.download_video(video_path)
            if not actual_video_path:
                raise Exception("Failed to download video")
            print(f"Video downloaded: {actual_video_path}")
        
        if style == 'tutorial':
            subs = self.extract_subtitles(actual_video_path)
            structure = self.generate_tutorial_structure(subs)
            markdown_content = self.generate_tutorial_markdown_with_images(subs, structure, actual_video_path, output_dir)
        else:
            markdown_content = self.generate_markdown(actual_video_path, style)
            markdown_content = self.replace_placeholders_with_images(markdown_content, actual_video_path, output_dir)
        
        video_name = os.path.splitext(os.path.basename(actual_video_path))[0].replace(' ', '_')
        output_file = os.path.join(output_dir, f"{video_name}_notes.md")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        return output_file

def main():
    parser = argparse.ArgumentParser(description='将视频转换为Markdown笔记')
    parser.add_argument('video_file', help='视频文件路径')
    parser.add_argument('--output', '-o', default='./output', help='输出目录')
    parser.add_argument('--style', '-s', default='detailed', choices=['detailed', 'tutorial'], 
                        help='输出风格: detailed(详细笔记), tutorial(教程风格)')
    args = parser.parse_args()
    
    converter = VideoToMarkdown()
    output_file = converter.process_video(args.video_file, args.output, args.style)
    print(f"Markdown notes generated: {output_file}")

if __name__ == "__main__":
    main()
