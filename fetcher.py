# -*- coding: utf-8 -*-
"""浏览器抓取模块（逻辑参考 demo2.py）：打开商品链接，等待内容加载，保存 HTML。"""
import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from config import HTML_OUTPUT_DIR

# 等待配置
MAX_WAIT_SECONDS = 40
POLL_INTERVAL_SECONDS = 1
STABLE_ROUNDS_REQUIRED = 3

# 常见商品详情关键词，可根据真实页面调整
PRODUCT_KEYWORDS = (
    "价格", "销量", "已售", "商品详情",
    "店铺", "规格", "库存", "购买"
)

# 可能表示页面尚未正常进入商品详情
ERROR_KEYWORDS = (
    "访问频繁", "验证码", "登录后查看",
    "页面不存在", "暂时无法访问"
)


def normalize_text(text: str) -> str:
    """清理空白，方便比较页面文本是否稳定。"""
    return re.sub(r"\s+", " ", text or "").strip()


async def get_body_text(page) -> str:
    """安全读取当前页面可见文字。"""
    try:
        body = page.locator("body")
        return await body.inner_text(timeout=3000)
    except PlaywrightTimeoutError:
        return ""
    except Exception:
        return ""


async def wait_for_product_content(page):
    """
    轮询页面，等待出现有效商品内容。
    返回：(页面文字, 成功标记, 诊断原因)
    """
    start = asyncio.get_running_loop().time()
    previous_text = ""
    stable_rounds = 0
    last_text = ""

    while True:
        text = await get_body_text(page)
        normalized = normalize_text(text)
        last_text = text

        # 识别明显的访问异常，避免将错误页面当成商品详情
        if any(word in normalized for word in ERROR_KEYWORDS):
            return text, False, "页面可能要求登录或触发访问限制"

        # 商品关键词可作为辅助信号，但不是绝对条件
        has_product_keyword = any(word in normalized for word in PRODUCT_KEYWORDS)

        # 内容至少有一定长度，避免仅凭导航栏文字判定加载成功
        has_meaningful_content = len(normalized) >= 80

        # 检查文本是否连续稳定
        if normalized and normalized == previous_text:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_text = normalized

        # 内容足够长、有商品相关信息且文本稳定
        if (
            has_meaningful_content
            and has_product_keyword
            and stable_rounds >= STABLE_ROUNDS_REQUIRED
        ):
            return text, True, "检测到商品相关文字且内容稳定"

        # 对没有常见关键词的页面保留稳定文本兜底
        if (
            has_meaningful_content
            and stable_rounds >= STABLE_ROUNDS_REQUIRED + 2
        ):
            return text, True, "页面文字已稳定，但未匹配到常见商品关键词"

        elapsed = asyncio.get_running_loop().time() - start
        if elapsed >= MAX_WAIT_SECONDS:
            return last_text, False, f"等待超时：{MAX_WAIT_SECONDS} 秒内未满足内容加载条件"

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def extract_product_id(html, page_url):
    """从 URL 中提取商品 ID，用于命名保存的文件。"""
    match = re.search(r"goods-detail/([a-zA-Z0-9]+)", page_url or "")
    if match:
        return match.group(1)
    match = re.search(r"[?&]goodsid=([a-zA-Z0-9]+)", page_url or "")
    if match:
        return match.group(1)

    # 兜底：用时间戳命名，避免文件互相覆盖
    return f"unknown_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


async def fetch_product_page(product_url: str):
    """
    打开商品链接并保存 HTML。
    返回：(是否成功, 商品ID, HTML 文件绝对路径或 None, 说明文字)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1000},
        )
        page = await context.new_page()
        page.set_default_navigation_timeout(60000)
        page.set_default_timeout(10000)

        try:
            response = await page.goto(
                product_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            status = response.status if response else None

            # networkidle 只能作为辅助条件：页面持续有请求时不应无限等待
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                pass

            text, success, reason = await wait_for_product_content(page)

            # 保存 HTML（成功失败都保存，便于排查）
            try:
                html = await page.content()
            except Exception:
                html = ""

            product_id = extract_product_id(html, page.url)

            # 按日期创建子文件夹：html_output/2026-10-12/商品ID.html
            date_dir = HTML_OUTPUT_DIR / datetime.now().strftime("%Y-%m-%d")
            date_dir.mkdir(parents=True, exist_ok=True)
            html_path = date_dir / f"{product_id}.html"
            html_path.write_text(html, encoding="utf-8")

            info = (
                f"HTTP状态码: {status}，最终URL: {page.url}，"
                f"等待结果: {reason}"
            )
            if not success:
                info += f"，页面文字预览: {normalize_text(text)[:200]}"

            return success, product_id, page.url, html_path.resolve(), info

        except Exception as exc:
            return False, None, product_url, None, f"访问失败: {type(exc).__name__} {exc}"

        finally:
            await context.close()
            await browser.close()
