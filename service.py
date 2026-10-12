# -*- coding: utf-8 -*-
"""业务服务层：组合抓取、解析、入库，供客户端命令调用。"""
import asyncio

import db
import fetcher
import parser
from config import (
    STATUS_INVALID, STATUS_PENDING_PARSE, STATUS_DONE, STATUS_TEXT,
)


def _log_print(msg):
    """默认日志输出：直接打印。"""
    print(msg)


def add_product(product_url: str, log=_log_print) -> int:
    """添加商品链接到数据库，返回记录 ID。"""
    db.init_db()
    record_id = db.add_product(product_url)
    log(f"已添加商品链接，记录 ID={record_id}（状态：待获取数据）")
    return record_id


def fetch_product(record_id: int, log=_log_print) -> bool:
    """
    抓取指定记录的商品页面并保存 HTML。
    成功：状态置为待解析详情；失败：状态置为无效数据。
    """
    record = db.get_product(record_id)
    if record is None:
        log(f"记录 {record_id} 不存在。")
        return False

    if not record["product_url"]:
        log(f"记录 {record_id} 没有商品链接。")
        return False

    if record["status"] == STATUS_DONE:
        log(f"记录 {record_id} 已完成，无需重复抓取。")
        return True

    log(f"[记录 {record_id}] 正在抓取: {record['product_url']}")
    success, product_id, final_url, html_path, info = asyncio.run(
        fetcher.fetch_product_page(record["product_url"])
    )
    log(f"  {info}")

    if success:
        db.update_record(
            record_id,
            product_id=product_id,
            product_url=final_url,
            html_file_path=html_path,
            status=STATUS_PENDING_PARSE,
        )
        log(f"  已保存 HTML: {html_path}")
        log(f"  状态更新为：待解析详情")
        return True

    db.update_record(
        record_id,
        product_id=product_id,
        html_file_path=html_path,
        status=STATUS_INVALID,
    )
    log("  抓取未确认成功，状态更新为：无效数据")
    return False


def fetch_all_pending(log=_log_print) -> int:
    """抓取所有待获取数据的记录，返回成功条数。"""
    pending = db.list_products(status=0, limit=1000)
    if not pending:
        log("没有待抓取的记录。")
        return 0
    done = 0
    for record in pending:
        if fetch_product(record["id"], log=log):
            done += 1
    return done


def parse_product(record: dict, log=_log_print) -> bool:
    """解析单条记录的 HTML，字段写回数据库。返回是否成功。"""
    from pathlib import Path

    record = dict(record)  # 兼容 sqlite3.Row
    record_id = record["id"]
    html_path = Path(record["html_file_path"] or "")
    if not html_path.is_absolute():
        html_path = Path.cwd() / html_path

    if not html_path.is_file():
        log(f"  [记录 {record_id}] HTML 文件不存在：{html_path}")
        db.update_record(record_id, status=STATUS_INVALID)
        return False

    result = parser.parse_html_file(html_path)
    log(f"  商品名称: {result['product_name']}")
    log(f"  主图: {result['main_image_url']}")
    log(f"  价格: {result['price']}")
    log(f"  销量: {result['sales']}")

    # 关键字段全部缺失视为无效，避免误标完成
    if not any(result.values()):
        log("  关键字段均未提取到，标记为无效数据。")
        db.update_record(record_id, status=STATUS_INVALID)
        return False

    db.update_record(
        record_id,
        status=STATUS_DONE,
        product_name=result["product_name"],
        main_image_url=result["main_image_url"],
        price=result["price"],
        sales=result["sales"],
    )
    # 记录本次采集的销量快照（主表 sales 始终为最新值）
    db.add_sales_history(record_id, record.get("product_id"), result["sales"])
    log("  状态更新为：已完成")
    return True


def parse_all_pending(log=_log_print) -> int:
    """解析所有待解析详情的记录，返回成功条数。"""
    pending = db.fetch_pending_parse()
    if not pending:
        log("没有待解析的记录。")
        return 0
    log(f"共 {len(pending)} 条待解析记录。")
    done = 0
    for record in pending:
        log(f"[记录 {record['id']}] 开始解析...")
        if parse_product(record, log=log):
            done += 1
    log(f"解析完成：成功 {done} / {len(pending)} 条。")
    return done


def show_product(record_id: int):
    """打印单条记录详情。"""
    record = db.get_product(record_id)
    if record is None:
        print(f"记录 {record_id} 不存在。")
        return

    print(f"\n===== 记录 {record['id']} =====")
    print(f"商品ID:    {record['product_id'] or '-'}")
    print(f"商品链接:  {record['product_url'] or '-'}")
    print(f"HTML文件:  {record['html_file_path'] or '-'}")
    print(f"状态:      {record['status']}（{STATUS_TEXT.get(record['status'], '未知')}）")
    print(f"商品名称:  {record['product_name'] or '-'}")
    print(f"主图:      {record['main_image_url'] or '-'}")
    print(f"价格:      {record['price'] or '-'}")
    print(f"销量:      {record['sales'] or '-'}")
    print(f"创建时间:  {record['created_at']}")
    print(f"更新时间:  {record['updated_at']}")


def list_products(status: int = None):
    """打印商品列表。"""
    records = db.list_products(status=status)
    if not records:
        print("暂无记录。")
        return

    if status is not None:
        print(f"状态={status}（{STATUS_TEXT.get(status, '未知')}）的记录：")
    else:
        print("全部记录：")

    print(f"{'ID':<5} {'状态':<10} {'价格':<8} {'销量':<10} 商品名称")
    print("-" * 80)
    for r in records:
        status_str = f"{r['status']} {STATUS_TEXT.get(r['status'], '')}"
        name = (r['product_name'] or '-')[:30]
        print(f"{r['id']:<5} {status_str:<10} {r['price'] or '-':<8} {r['sales'] or '-':<10} {name}")
