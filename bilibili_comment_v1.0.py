import sys
import os
import json
import requests
import time
import csv
import re  # 用于清理文件名
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QPushButton, QTextEdit, QProgressBar, QLabel
from PyQt5.QtCore import Qt, QThread, pyqtSignal


# 获取并显示 ChromeDriver 路径
def get_chrome_driver_path():
    chrome_driver_path = ChromeDriverManager().install()
    return chrome_driver_path

# 保存 Headers 到本地文件
def save_headers_to_file(headers, file_path="headers.json"):
    # 使用绝对路径
    abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)
    with open(abs_path, 'w', encoding='utf-8') as file:
        json.dump(headers, file, ensure_ascii=False, indent=4)

# 从本地文件加载 Headers
def load_headers_from_file(file_path="headers.json"):
    # 使用绝对路径
    abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)
    if os.path.exists(abs_path):
        with open(abs_path, 'r', encoding='utf-8') as file:
            headers = json.load(file)
        return headers
    return None

# 动态获取 Headers 并提示用户登录
def get_dynamic_headers_with_login(url, file_path="headers.json"):
    headers = load_headers_from_file(file_path)
    if headers:
        return headers

    chrome_driver_path = get_chrome_driver_path()
    options = Options()
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')

    service = Service(chrome_driver_path)
    driver = webdriver.Chrome(service=service, options=options)

    driver.get(url)

    while True:
        cookies = driver.get_cookies()
        cookie_names = [cookie['name'] for cookie in cookies]
        if 'DedeUserID' in cookie_names and 'SESSDATA' in cookie_names:
            break
        time.sleep(1)

    cookies = driver.get_cookies()
    cookie_str = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
    user_agent = driver.execute_script("return navigator.userAgent;")
    driver.quit()

    headers = {
        "Cookie": cookie_str,
        "User-Agent": user_agent,
    }

    save_headers_to_file(headers, file_path)

    return headers

# 获取视频的名字
def get_video_name(video_bv, headers):
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={video_bv}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'title' in data['data']:
                return data['data']['title']
            else:
                return video_bv
        else:
            return video_bv
    except requests.RequestException as e:
        return video_bv

# 获取评论（包括二级评论）
def fetch_comments(video_id, headers, max_pages=500, sleep_time=0.3, progress_callback=None, log_callback=None):
    comments = []
    last_count = 0
    url_base = f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={video_id}&mode=3"

    for page in range(1, max_pages + 1):
        if progress_callback:
            progress_callback(int((page / max_pages) * 100))

        url = f"{url_base}&next={page}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data['data']['replies'] is None:
                    break
                if data and 'replies' in data['data']:
                    for comment in data['data']['replies']:
                        comment_info = {
                            '评论ID': comment['rpid'],
                            '评论层级': '一级评论',
                            '用户昵称': comment['member']['uname'],
                            '评论内容': comment['content']['message'],
                            '被回复用户': '',
                            '性别': comment['member']['sex'],
                            '用户当前等级': comment['member']['level_info']['current_level'],
                            '点赞数量': comment['like'],
                            '回复时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(comment['ctime'])),
                            'IP属地': comment['reply_control']['location'].replace("IP属地：", ""),
                            '父评论内容': '',
                        }
                        comments.append(comment_info)

                        if 'replies' in comment:
                            for reply in comment['replies']:
                                reply_info = {
                                    '评论ID': reply['rpid'],
                                    '评论层级': '二级评论',
                                    '用户昵称': reply['member']['uname'],
                                    '评论内容': reply['content']['message'],
                                    '被回复用户': comment['member']['uname'],
                                    '性别': reply['member']['sex'],
                                    '用户当前等级': reply['member']['level_info']['current_level'],
                                    '点赞数量': reply['like'],
                                    '回复时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(reply['ctime'])),
                                    'IP属地': reply['reply_control']['location'].replace("IP属地：", ""),
                                    '父评论内容': comment['content']['message'],
                                }
                                comments.append(reply_info)

                if last_count == len(comments):
                    break
                last_count = len(comments)
            else:
                if log_callback:
                    log_callback(f"第 {page} 页请求失败，状态码：{response.status_code}")
                break
        except requests.RequestException as e:
            if log_callback:
                log_callback(f"第 {page} 页请求异常：{e}")
            break
        time.sleep(sleep_time)

    if progress_callback:
        progress_callback(100)
    return comments

# 清理文件名，移除非法字符
def sanitize_filename(filename):
    return re.sub(r'[\\/:"*?<>|]+', '_', filename)

# 保存评论到 CSV 文件
def save_comments_to_csv(comments, video_name):
    # 使用绝对路径
    results_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
    if not os.path.exists(results_folder):
        os.makedirs(results_folder)

    sanitized_video_name = sanitize_filename(video_name)
    file_path = os.path.join(results_folder, f'{sanitized_video_name}.csv')

    fieldnames = [
        '评论ID', '评论层级', '用户昵称', '性别', '评论内容', '被回复用户', '用户当前等级',
        '点赞数量', '回复时间', 'IP属地', '父评论内容'
    ]

    with open(file_path, mode='w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(comments)


# 创建线程类用于后台执行爬取任务
class FetchTaskThread(QThread):
    progress_updated = pyqtSignal(int)
    log_updated = pyqtSignal(str)

    def __init__(self, bv_number, parent=None):
        super().__init__(parent)
        self.bv_number = bv_number
        self.headers = get_dynamic_headers_with_login("https://www.bilibili.com")

    def run(self):
        self.log_updated.emit("开始爬取任务...")

        video_name = get_video_name(self.bv_number, self.headers)
        self.log_updated.emit(f"视频标题: {video_name}")

        comments = fetch_comments(
            self.bv_number,
            self.headers,
            progress_callback=self.progress_updated.emit,
            log_callback=self.log_updated.emit
        )
        self.log_updated.emit(f"共抓取到 {len(comments)} 条评论")

        save_comments_to_csv(comments, video_name)
        self.log_updated.emit(f"评论已保存到文件夹 'results'")

        self.progress_updated.emit(100)


class MyWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Bilibili 评论爬取")
        self.setGeometry(100, 100, 600, 400)

        self.layout = QVBoxLayout()

        self.bv_input = QLineEdit(self)
        self.bv_input.setPlaceholderText("请输入视频的 BV 号")
        self.layout.addWidget(self.bv_input)

        self.start_button = QPushButton("开始爬取", self)
        self.start_button.clicked.connect(self.start_task)
        self.layout.addWidget(self.start_button)

        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.layout.addWidget(self.log_output)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.layout.addWidget(self.progress_bar)

        # 添加水印
        self.watermark = QLabel("Powered by Jacky Wang", self)
        self.watermark.setAlignment(Qt.AlignCenter)
        self.watermark.setStyleSheet("color: gray; font-size: 12px; margin-top: 10px;")
        self.layout.addWidget(self.watermark)

        self.setLayout(self.layout)

    def start_task(self):
        bv_number = self.bv_input.text()
        if bv_number:
            self.progress_bar.setValue(0)
            self.log_output.clear()
            self.thread = FetchTaskThread(bv_number)
            self.thread.progress_updated.connect(self.update_progress)
            self.thread.log_updated.connect(self.update_log)
            self.thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_log(self, message):
        self.log_output.append(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MyWindow()
    window.show()
    sys.exit(app.exec_())