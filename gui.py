# -*- coding: utf-8 -*-
"""
小红书商品采集客户端（图形界面）。

启动：
  python gui.py
"""
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 GBK 编码无法显示部分字符，统一改用 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 保证以脚本方式从任意目录运行时能导入同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import service
from config import STATUS_DONE, STATUS_INVALID, STATUS_PENDING_FETCH, \
    STATUS_PENDING_PARSE, STATUS_TEXT

# 折线图区域高度
CHART_HEIGHT = 280

# 定时采集可选频率（秒）
SCHEDULE_CHOICES = [
    ("1h", 1 * 3600),
    ("2h", 2 * 3600),
    ("6h", 6 * 3600),
    ("12h", 12 * 3600),
    ("1d", 1 * 86400),
    ("2d", 2 * 86400),
    ("7d", 7 * 86400),
]

STATUS_OPTIONS = ["全部"] + [
    f"{code} {STATUS_TEXT[code]}"
    for code in (STATUS_PENDING_FETCH, STATUS_PENDING_PARSE, STATUS_DONE, STATUS_INVALID)
]


def parse_sales_value(sales):
    """'1.2万+' -> 12000.0，'626' -> 626.0。解析失败返回 None。"""
    if not sales:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万|亿)?", str(sales))
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "万":
        value *= 10_000
    elif unit == "亿":
        value *= 100_000_000
    return value


def format_sales_value(value):
    """12000.0 -> '1.2万'，626.0 -> '626'，用于图表刻度/数据点标签。"""
    if value >= 10_000:
        return f"{value / 10_000:g}万"
    return f"{value:g}"


class ProductGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("小红书商品采集客户端")
        self.root.geometry("1080x680")

        db.init_db()

        self.msg_queue = queue.Queue()
        self.worker_busy = False
        self._schedule_next_at = None  # 定时采集的下一次触发时间戳

        self._build_top_bar()
        self._build_main_area()
        self._build_log_area()

        self.refresh_list()
        self.root.after(100, self._poll_queue)
        self._schedule_tick()  # 启动定时采集调度循环

    # ==================== 界面构建 ====================

    def _build_top_bar(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="商品链接（可粘贴多行，每行一个）：").pack(anchor=tk.W)
        row = ttk.Frame(top)
        row.pack(fill=tk.X)

        self.url_input = tk.Text(row, height=3, wrap=tk.WORD)
        self.url_input.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.collect_btn = ttk.Button(
            row, text="添加并采集", command=self.on_collect
        )
        self.collect_btn.pack(side=tk.LEFT, padx=8)

    def _build_main_area(self):
        # 左右分栏：中间分隔条可拖动缩放两侧宽度
        self.main_pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=8)

        # ---- 左侧：搜索 + 列表 ----
        left = ttk.Frame(self.main_pane)
        self.main_pane.add(left, weight=3)

        search_row = ttk.Frame(left)
        search_row.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(search_row, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        search_entry.bind("<Return>", lambda e: self.refresh_list())

        self.filter_var = tk.StringVar(value=STATUS_OPTIONS[0])
        filter_box = ttk.Combobox(
            search_row, textvariable=self.filter_var,
            values=STATUS_OPTIONS, state="readonly", width=12,
        )
        filter_box.pack(side=tk.LEFT, padx=4)
        filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        columns = ("id", "status", "name", "price", "sales", "created", "updated")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=14)
        self.tree.heading("id", text="ID")
        self.tree.heading("status", text="状态")
        self.tree.heading("name", text="商品名称")
        self.tree.heading("price", text="价格")
        self.tree.heading("sales", text="销量")
        self.tree.heading("created", text="创建时间")
        self.tree.heading("updated", text="更新时间")
        self.tree.column("id", width=45, stretch=False)
        self.tree.column("status", width=90, stretch=False)
        self.tree.column("name", width=220)
        self.tree.column("price", width=55, anchor=tk.E, stretch=False)
        self.tree.column("sales", width=70, anchor=tk.E, stretch=False)
        self.tree.column("created", width=130, anchor=tk.CENTER, stretch=False)
        self.tree.column("updated", width=130, anchor=tk.CENTER, stretch=False)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        # 双击行：重新采集该记录（更新状态与最新数据）
        self.tree.bind("<Double-1>", lambda e: self.on_refetch())

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="刷新", command=self.refresh_list).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="重新采集", command=self.on_refetch).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="删除选中", command=self.on_delete).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="重试失败", command=self.on_retry_failed).pack(side=tk.LEFT, padx=6)
        # ttk.Button(btn_row, text="设置", command=self.on_settings).pack(side=tk.RIGHT)

        # ---- 右侧：详情 + 销量折线图 ----
        right = ttk.Frame(self.main_pane)
        self.main_pane.add(right, weight=2)

        chart_frame = ttk.LabelFrame(right, text="历史销量趋势", padding=4)
        chart_frame.pack(fill=tk.X, pady=(0, 8))
        self.sales_chart = tk.Canvas(
            chart_frame, height=CHART_HEIGHT, background="#fafafa",
            highlightthickness=0,
        )
        self.sales_chart.pack(fill=tk.X)
        self._current_history = []  # 当前选中记录的销量历史，供重绘
        self.sales_chart.bind("<Configure>", lambda e: self._draw_sales_chart(self._current_history))

        self.detail_text = tk.Text(
            right, height=10, wrap=tk.WORD, state=tk.DISABLED,
            background="#f5f5f5",
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True)

    def _build_log_area(self):
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=4)
        log_frame.pack(fill=tk.X, padx=8, pady=8)

        self.log_text = tk.Text(log_frame, height=7, wrap=tk.WORD, state=tk.DISABLED)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.X)
        self.log_text.tag_configure("error", foreground="#cc0000")

    # ==================== 消息与日志 ====================

    def log(self, msg: str, error: bool = False):
        """线程安全日志：投递到队列，由 UI 线程写入。"""
        self.msg_queue.put(("log", (msg, error)))

    def _append_log(self, msg: str, error: bool):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n", "error" if error else None)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _poll_queue(self):
        """UI 线程每 100ms 处理一次后台消息。"""
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(*payload)
                elif kind == "refresh":
                    self.refresh_list()
                elif kind == "busy":
                    self.worker_busy = payload
                    state = tk.DISABLED if payload else tk.NORMAL
                    self.collect_btn.configure(state=state)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ==================== 列表与详情 ====================

    def _parse_filter(self):
        """从下拉框解析状态码，'全部' 返回 None。"""
        text = self.filter_var.get()
        if text == "全部":
            return None
        return int(text.split(" ")[0])

    def refresh_list(self):
        keyword = self.search_var.get().strip() or None
        records = db.list_products(
            status=self._parse_filter(), name_keyword=keyword, limit=500,
        )
        self.tree.delete(*self.tree.get_children())
        for r in records:
            status_str = f"{r['status']} {STATUS_TEXT.get(r['status'], '')}"
            self.tree.insert("", tk.END, values=(
                r["id"], status_str,
                r["product_name"] or "-",
                r["price"] or "-",
                r["sales"] or "-",
                r["created_at"] or "-",
                r["updated_at"] or "-",
            ))
        if not records:
            self._clear_detail()

    def _selected_record(self):
        selection = self.tree.selection()
        if not selection:
            return None
        record_id = int(self.tree.item(selection[0], "values")[0])
        return db.get_product(record_id)

    def on_select(self, _event=None):
        record = self._selected_record()
        if record is None:
            return

        # 文字详情
        detail = (
            f"记录 ID:  {record['id']}\n"
            f"商品 ID:  {record['product_id'] or '-'}\n"
            f"商品名称: {record['product_name'] or '-'}\n"
            f"价格:     {record['price'] or '-'}\n"
            f"销量:     {record['sales'] or '-'}\n"
            f"状态:     {record['status']}（{STATUS_TEXT.get(record['status'], '未知')}）\n"
            f"更新时间: {record['updated_at']}\n"
            f"链接:     {record['product_url'] or '-'}"
        )

        # 销量历史（折线图展示，详情里不再重复文字）
        history = db.get_sales_history(record["id"])
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", detail)
        self.detail_text.configure(state=tk.DISABLED)

        # 销量折线图
        self._draw_sales_chart(history)

    def _draw_sales_chart(self, history):
        """在 Canvas 上绘制销量历史折线图。history 为空时显示提示文字。"""
        self._current_history = history
        canvas = self.sales_chart
        canvas.delete("all")

        points = [
            (h["collected_at"], parse_sales_value(h["sales"]))
            for h in history
        ]
        points = [(t, v) for t, v in points if v is not None]

        if not points:
            canvas.create_text(
                10, CHART_HEIGHT // 2, anchor=tk.W,
                text="暂无销量历史，采集后显示趋势",
                fill="#999999", font=("Microsoft YaHei", 10),
            )
            return

        if len(points) == 1:
            ts, v = points[0]
            width = max(canvas.winfo_width(), 100)
            canvas.create_text(
                width // 2, CHART_HEIGHT // 2 - 12,
                text=f"{format_sales_value(v)}  ({ts[:16]})",
                fill="#1a73e8", font=("Microsoft YaHei", 11),
            )
            canvas.create_text(
                width // 2, CHART_HEIGHT // 2 + 12,
                text="再次采集后显示趋势", fill="#999999",
                font=("Microsoft YaHei", 9),
            )
            return

        width = max(canvas.winfo_width(), 100)
        left, right_margin = 52, 12
        top, bottom = 24, 34
        plot_w = width - left - right_margin
        plot_h = CHART_HEIGHT - top - bottom

        values = [v for _, v in points]
        vmin, vmax = min(values), max(values)
        if vmin == vmax:
            vmin -= 1
            vmax += 1
        pad = (vmax - vmin) * 0.12
        vmin, vmax = vmin - pad, vmax + pad

        step = (vmax - vmin) / 3
        if step >= 10_000:
            def fmt_tick(v):
                return f"{v / 10_000:.1f}万"
        else:
            def fmt_tick(v):
                return f"{v:,.0f}"

        def to_xy(i, v):
            x = left + plot_w * i / (len(points) - 1)
            y = top + plot_h * (1 - (v - vmin) / (vmax - vmin))
            return x, y

        # Y 轴刻度线（4 条）
        for k in range(4):
            v = vmin + (vmax - vmin) * k / 3
            y = to_xy(0, v)[1]
            canvas.create_line(
                left, y, width - right_margin, y,
                fill="#e0e0e0",
            )
            canvas.create_text(
                left - 4, y, anchor=tk.E,
                text=fmt_tick(v), fill="#888888",
                font=("Microsoft YaHei", 8),
            )

        # 折线
        coords = [c for i, (_, v) in enumerate(points) for c in to_xy(i, v)]
        if len(coords) >= 4:
            canvas.create_line(*coords, fill="#1a73e8", width=2)

        # 数据点 + 标签
        prev_label_i = -2
        for i, (ts, v) in enumerate(points):
            x, y = to_xy(i, v)
            r = 3
            canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill="#1a73e8", outline="",
            )
            canvas.create_text(
                x, y - 9, text=format_sales_value(v),
                fill="#1a73e8", font=("Microsoft YaHei", 8),
            )
            # X 轴时间标签：首尾必标，中间点只在间隔足够时标注，避免重叠
            label = ts[5:16] if len(ts) >= 16 else ts
            if i == 0 or i == len(points) - 1:
                show_label = True
            elif len(points) <= 4 or i == len(points) // 2:
                show_label = True
            else:
                show_label = False
            if show_label and i != prev_label_i + 1:
                canvas.create_text(
                    x, CHART_HEIGHT - 12, text=label,
                    fill="#888888", font=("Microsoft YaHei", 8),
                )
                prev_label_i = i

    def _clear_detail(self):
        self.sales_chart.delete("all")
        self.sales_chart.create_text(
            10, CHART_HEIGHT // 2, anchor=tk.W,
            text="选中商品显示销量趋势", fill="#999999",
            font=("Microsoft YaHei", 10),
        )
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.configure(state=tk.DISABLED)

    # ==================== 设置与定时采集 ====================

    def on_settings(self):
        """弹出设置窗口：定时采集开关与频率。"""
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        win.geometry("+%d+%d" % (
            self.root.winfo_rootx() + 240,
            self.root.winfo_rooty() + 180,
        ))

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame, text="定时采集（只刷新“已完成”状态的记录）:",
        ).pack(anchor=tk.W)

        enabled_var = tk.BooleanVar(
            value=db.get_setting("schedule_enabled", "0") == "1"
        )
        ttk.Checkbutton(
            frame, text="启用定时采集", variable=enabled_var,
        ).pack(anchor=tk.W, pady=(4, 8))

        freq_var = tk.StringVar(
            value=db.get_setting("schedule_interval", "6h")
        )
        row = ttk.Frame(frame)
        row.pack(anchor=tk.W)
        ttk.Label(row, text="采集频率:").pack(side=tk.LEFT)
        combo = ttk.Combobox(
            row, textvariable=freq_var, state="readonly", width=6,
            values=[label for label, _ in SCHEDULE_CHOICES],
        )
        combo.pack(side=tk.LEFT, padx=4)

        def save_and_close():
            db.set_setting("schedule_enabled", "1" if enabled_var.get() else "0")
            db.set_setting("schedule_interval", freq_var.get())
            # 保存后立即触发一次（tick 里 next_at=0 视为到期）
            self._schedule_next_at = 0.0
            self.log(
                f"设置已保存：定时采集{'开启' if enabled_var.get() else '关闭'}"
                + (f"，频率 {freq_var.get()}" if enabled_var.get() else "")
            )
            win.destroy()

        ttk.Button(frame, text="保存", command=save_and_close).pack(pady=(12, 0))

    def _schedule_tick(self):
        """每 30 秒检查一次是否到达定时采集时间。"""
        enabled = db.get_setting("schedule_enabled", "0") == "1"
        interval = dict(SCHEDULE_CHOICES).get(
            db.get_setting("schedule_interval", "6h"), 6 * 3600
        )
        now = datetime.now().timestamp()
        if enabled:
            if self._schedule_next_at is None:
                # 程序启动后的首次检查：等一个完整周期再触发
                # （保存设置时会把 next_at 置 0，从而立即触发一次）
                self._schedule_next_at = now + interval
            elif now >= self._schedule_next_at and not self.worker_busy:
                self._schedule_next_at = now + interval
                self.log("定时采集触发：刷新已完成记录...")
                self._start_worker(self._scheduled_task)
        else:
            self._schedule_next_at = None
        self.root.after(30_000, self._schedule_tick)

    def _scheduled_task(self):
        """定时任务：重新抓取+解析所有已完成记录（追加销量快照）。"""
        done_records = db.list_products(status=STATUS_DONE, limit=1000)
        self.log(f"定时采集：共 {len(done_records)} 条已完成记录。")
        for record in done_records:
            record_id = record["id"]
            # 先重置为待抓取，绕过 fetch_product 的“已完成跳过”检查
            db.update_record(record_id, status=STATUS_PENDING_FETCH)
            if service.fetch_product(record_id, log=self.log):
                fresh = db.get_product(record_id)
                if fresh["status"] == STATUS_PENDING_PARSE:
                    service.parse_product(dict(fresh), log=self.log)
            self.msg_queue.put(("refresh", None))
        self.log("定时采集结束。")

    # ==================== 操作 ====================

    def on_collect(self):
        """批量添加链接并后台抓取+解析。"""
        raw = self.url_input.get("1.0", tk.END)
        urls = []
        seen = set()
        for line in raw.splitlines():
            url = line.strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        if not urls:
            messagebox.showinfo("提示", "请先粘贴商品链接。")
            return

        for url in urls:
            service.add_product(url, log=self.log)
        self.url_input.delete("1.0", tk.END)
        self.refresh_list()
        self._start_worker(self._collect_task, urls)
        self.log(f"已提交 {len(urls)} 个链接，开始采集...")

    def _collect_task(self, urls):
        for url in urls:
            record = db.find_by_url(url)
            if record is None:
                self.log(f"未找到记录：{url}", error=True)
                continue
            record_id = record["id"]
            if service.fetch_product(record_id, log=self.log):
                record = db.get_product(record_id)
                if record["status"] == STATUS_PENDING_PARSE:
                    service.parse_product(dict(record), log=self.log)
            self.msg_queue.put(("refresh", None))
        self.log("本轮采集结束。")

    def on_refetch(self):
        """重新采集选中记录：重置为待抓取，重新抓取+解析（销量会追加一条历史快照）。"""
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("提示", "请先在列表中选中一条记录。")
            return
        record_id = record["id"]
        db.update_record(record_id, status=STATUS_PENDING_FETCH)
        self.log(f"记录 {record_id} 已重置为待抓取，开始重新采集...")
        self.refresh_list()
        self._start_worker(self._refetch_task, record_id)

    def _refetch_task(self, record_id):
        if service.fetch_product(record_id, log=self.log):
            record = db.get_product(record_id)
            if record["status"] == STATUS_PENDING_PARSE:
                service.parse_product(dict(record), log=self.log)
        self.msg_queue.put(("refresh", None))
        self.log(f"记录 {record_id} 重新采集结束。")

    def on_delete(self):
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("提示", "请先在列表中选中一条记录。")
            return
        if not messagebox.askyesno(
            "确认删除", f"确定删除记录 {record['id']}（{record['product_name'] or '未解析'}）？"
        ):
            return
        with db._connect() as conn:
            conn.execute("DELETE FROM products WHERE id = ?", (record["id"],))
        self.log(f"已删除记录 {record['id']}。")
        self.refresh_list()

    def on_retry_failed(self):
        """把无效记录重置为待抓取并重新采集。"""
        invalid = db.list_products(status=STATUS_INVALID, limit=1000)
        if not invalid:
            messagebox.showinfo("提示", "没有无效数据需要重试。")
            return
        for record in invalid:
            db.update_record(record["id"], status=STATUS_PENDING_FETCH)
        self.log(f"已重置 {len(invalid)} 条无效记录，开始重新采集...")
        self.refresh_list()
        self._start_worker(self._retry_task)

    def _retry_task(self):
        service.fetch_all_pending(log=self.log)
        self.msg_queue.put(("refresh", None))
        service.parse_all_pending(log=self.log)
        self.msg_queue.put(("refresh", None))
        self.log("重试结束。")

    def _start_worker(self, task, *args):
        """启动后台工作线程，期间禁用采集按钮。"""
        if self.worker_busy:
            messagebox.showinfo("提示", "当前有采集任务进行中，请稍候。")
            return

        def run():
            try:
                task(*args)
            except Exception as exc:
                self.log(f"任务异常: {type(exc).__name__} {exc}", error=True)
            finally:
                self.msg_queue.put(("busy", False))

        self.msg_queue.put(("busy", True))
        threading.Thread(target=run, daemon=True).start()


def main():
    root = tk.Tk()
    ProductGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
