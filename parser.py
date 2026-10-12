# -*- coding: utf-8 -*-
"""HTML 解析模块（逻辑参考 demo3.py/demo4.py）：提取商品名称、主图、价格、销量。"""
import re
from pathlib import Path

from bs4 import BeautifulSoup


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def extract_product_name(soup, page_text):
    """
    优先从“商品名称”规格参数行提取值。
    如果当前 DOM 结构不同，则从页面文本中回退提取。
    """
    # 常见结构：<p class="name">商品名称</p>，同一行或相邻节点放商品名
    label = soup.select_one("p.name")
    if label and clean_text(label.get_text(" ", strip=True)) == "商品名称":
        # 先检查后续兄弟节点
        for sibling in label.next_siblings:
            if getattr(sibling, "get_text", None):
                candidate = clean_text(sibling.get_text(" ", strip=True))
            else:
                candidate = clean_text(str(sibling))
            if candidate and candidate != "商品名称":
                return candidate

        # 再检查父容器中除标签以外的文本
        parent = label.parent
        if parent:
            pieces = []
            for child in parent.find_all(string=True):
                text = clean_text(str(child))
                if text and text != "商品名称":
                    pieces.append(text)
            candidate = clean_text(" ".join(pieces))
            if candidate:
                return candidate

    # 页面文本回退：商品名称之后、价格说明之前的内容
    match = re.search(r"商品名称\s*(.*?)\s*价格说明", page_text)
    if match:
        return clean_text(match.group(1)) or None

    # 最后回退到页面顶部商品标题附近
    match = re.search(
        r"(【[^】]+】[^。]*?)(?:\s+保障|\s+已选|\s+发货|\s+商品名称)",
        page_text
    )
    return clean_text(match.group(1)) if match else None


def extract_current_price(page_text, soup):
    """
    价格：优先取“到手价”（例如：¥ 49 到手价 ¥99，不把 .del-price 的 99
    误判为当前价）；没有到手价时回退取当前价节点 .price（例如：¥19.8）。
    """
    match = re.search(r"¥\s*([0-9]+(?:\.[0-9]{1,2})?)\s*到手价", page_text)
    if match:
        return match.group(1)

    hand_label = soup.select_one(".price-in-hands_text")
    if hand_label:
        for ancestor in list(hand_label.parents)[:5]:
            text = clean_text(ancestor.get_text(" ", strip=True))
            match = re.search(
                r"¥\s*([0-9]+(?:\.[0-9]{1,2})?)\s*到手价", text
            )
            if match:
                return match.group(1)

    # 回退：无“到手价”时取当前价节点（价格可能被拆成多个 span，如 “¥ 19 .8”）
    price_node = soup.select_one(".price")
    if price_node:
        text = price_node.get_text(strip=True).replace(" ", "")
        match = re.search(r"¥?\s*([0-9]+(?:\.[0-9]{1,2})?)", text)
        if match:
            return match.group(1)
    return None


def extract_product_sales(soup, page_text):
    """销量：优先取商品“已售1.2万+”，避免店铺的“已售 14.2万”。"""
    node = soup.select_one(".spu-text")
    if node:
        text = clean_text(node.get_text(" ", strip=True))
        match = re.search(r"已售\s*([0-9.万千亿+]+)", text)
        if match:
            return match.group(1)

    match = re.search(r"已售\s*([0-9.万千亿+]+)", page_text)
    if match:
        return match.group(1)
    return None


def extract_main_image(soup):
    """主图：优先轮播图，其次商品 CDN 图片，排除头像等无关图片。"""
    node = soup.select_one("img.carousel-image")
    if node:
        src = node.get("src") or node.get("data-src")
        if src:
            return src

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "mall-i8.xhscdn.com/arkgoods/" in src:
            return src
    return None


def parse_html_file(html_path) -> dict:
    """
    解析本地 HTML 文件，返回字段字典：
    {product_name, main_image_url, price, sales}，提取失败的字段为 None。
    """
    html_path = Path(html_path)
    if not html_path.is_absolute():
        html_path = Path.cwd() / html_path

    html = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))

    return {
        "product_name": extract_product_name(soup, page_text),
        "main_image_url": extract_main_image(soup),
        "price": extract_current_price(page_text, soup),
        "sales": extract_product_sales(soup, page_text),
    }
