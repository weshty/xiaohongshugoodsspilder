# -*- coding: utf-8 -*-
"""SQLite 数据访问层：建表、商品记录的增查改。"""
import sqlite3
from datetime import datetime

from config import DB_PATH, STATUS_PENDING_FETCH


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    """初始化数据库目录和商品表。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT,
                product_url TEXT,
                html_file_path TEXT,
                status INTEGER NOT NULL DEFAULT 0,
                product_name TEXT,
                main_image_url TEXT,
                price TEXT,
                sales TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_status ON products(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_product_id ON products(product_id)"
        )
        # 销量历史表：每次解析成功记录一条快照，主表 sales 只保留最新值
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                product_id TEXT,
                sales TEXT,
                collected_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sales_history_record"
            " ON sales_history(record_id)"
        )
        # 键值配置表：保存定时任务开关与频率等设置
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)


def add_product(product_url: str) -> int:
    """新增一条商品记录，初始状态为待获取数据，返回记录 ID。"""
    now = _now()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO products (product_url, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (product_url, STATUS_PENDING_FETCH, now, now),
        )
        return cur.lastrowid


def get_product(record_id: int):
    """按记录 ID 查询单条记录，返回 sqlite3.Row 或 None。"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM products WHERE id = ?", (record_id,)
        ).fetchone()


def find_by_url(product_url: str):
    """按商品链接查询最近一条记录。"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM products WHERE product_url = ?"
            " ORDER BY id DESC LIMIT 1",
            (product_url,),
        ).fetchone()


def list_products(status: int = None, limit: int = 50, name_keyword: str = None):
    """按状态筛选商品列表（不传则查全部），默认最多返回 50 条。
    name_keyword 不为空时，模糊匹配商品名称或商品链接。
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conditions = []
        params = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if name_keyword:
            conditions.append("(product_name LIKE ? OR product_url LIKE ?)")
            keyword = f"%{name_keyword}%"
            params.extend([keyword, keyword])
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        return conn.execute(
            f"SELECT * FROM products{where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()


def update_record(record_id, product_id=None, product_url=None,
                  html_file_path=None, status=None,
                  product_name=None, main_image_url=None,
                  price=None, sales=None):
    """按记录 ID 更新字段并刷新更新时间，未传的字段保持不变。"""
    fields = ["updated_at = ?"]
    params = [_now()]
    if product_id is not None:
        fields.append("product_id = ?")
        params.append(product_id)
    if product_url is not None:
        fields.append("product_url = ?")
        params.append(product_url)
    if html_file_path is not None:
        fields.append("html_file_path = ?")
        params.append(str(html_file_path))
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if product_name is not None:
        fields.append("product_name = ?")
        params.append(product_name)
    if main_image_url is not None:
        fields.append("main_image_url = ?")
        params.append(main_image_url)
    if price is not None:
        fields.append("price = ?")
        params.append(price)
    if sales is not None:
        fields.append("sales = ?")
        params.append(sales)
    params.append(record_id)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE products SET {', '.join(fields)} WHERE id = ?", params
        )


def add_sales_history(record_id: int, product_id: str, sales: str):
    """记录一条销量快照。sales 为空时不记录。"""
    if not sales:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO sales_history (record_id, product_id, sales, collected_at)"
            " VALUES (?, ?, ?, ?)",
            (record_id, product_id, sales, _now()),
        )


def get_sales_history(record_id: int):
    """查询某记录的全部销量快照（按时间升序）。"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM sales_history WHERE record_id = ? ORDER BY id",
            (record_id,),
        ).fetchall()


def get_setting(key: str, default: str = None):
    """读取配置项，不存在返回 default。"""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str):
    """写入/更新配置项。"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def fetch_pending_parse():
    """读取所有“待解析详情”状态的记录（按 id 升序处理）。"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM products WHERE status = ? ORDER BY id",
            (1,),
        ).fetchall()
