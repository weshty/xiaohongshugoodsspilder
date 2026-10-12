# -*- coding: utf-8 -*-
"""
小红书商品采集客户端（命令行）。

用法：
  python client.py add <商品链接>        添加商品链接
  python client.py fetch [记录ID]        抓取：不传ID则抓取所有待抓取记录
  python client.py parse                 解析所有“待解析详情”的记录
  python client.py run [商品链接]        一步到位：添加（可选）+ 抓取 + 解析
  python client.py show <记录ID>         查看单条记录详情
  python client.py list [状态]           列出记录，可按状态筛选（0/1/2/3）
"""
import sys
from pathlib import Path

# Windows 控制台默认 GBK 编码无法显示部分字符，统一改用 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 保证以脚本方式从任意目录运行时能导入同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import service
from config import STATUS_TEXT

USAGE = __doc__


def main(args):
    if not args:
        print(USAGE)
        return 1

    cmd = args[0]

    if cmd == "add" and len(args) >= 2:
        service.add_product(args[1])
        return 0

    if cmd == "fetch":
        if len(args) >= 2:
            service.fetch_product(int(args[1]))
        else:
            service.fetch_all_pending()
        return 0

    if cmd == "parse":
        service.parse_all_pending()
        return 0

    if cmd == "run":
        if len(args) >= 2:
            service.add_product(args[1])
        service.fetch_all_pending()
        service.parse_all_pending()
        return 0

    if cmd == "show" and len(args) >= 2:
        service.show_product(int(args[1]))
        return 0

    if cmd == "list":
        status = int(args[1]) if len(args) >= 2 else None
        service.list_products(status=status)
        return 0

    print("无法识别的命令或参数不足。")
    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
