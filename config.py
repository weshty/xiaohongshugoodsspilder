# -*- coding: utf-8 -*-
"""项目公共配置：目录路径、数据库位置、状态常量。"""
from pathlib import Path

# 项目根目录（project 文件夹本身）
BASE_DIR = Path(__file__).resolve().parent

# SQLite 数据库文件
DB_PATH = BASE_DIR / "database" / "products.db"

# 抓取的 HTML 保存目录，按日期分文件夹：html_output/2026-10-12/商品ID.html
HTML_OUTPUT_DIR = BASE_DIR / "html_output"

# 状态定义：0 待获取数据、1 待解析详情、2 已完成、3 无效数据
STATUS_PENDING_FETCH = 0
STATUS_PENDING_PARSE = 1
STATUS_DONE = 2
STATUS_INVALID = 3

STATUS_TEXT = {
    STATUS_PENDING_FETCH: "待获取数据",
    STATUS_PENDING_PARSE: "待解析详情",
    STATUS_DONE: "已完成",
    STATUS_INVALID: "无效数据",
}
