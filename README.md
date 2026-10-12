# 小红书商品采集客户端

命令行客户端 + 图形界面：添加商品链接 → 抓取页面存 HTML → 解析出商品名称/主图/价格/销量，全部记录存 SQLite。

## 文件结构

```
project/
├── client.py      # 命令行入口
├── gui.py         # 图形界面入口（tkinter，含销量折线图）
├── service.py     # 业务层：组合抓取、解析、入库
├── fetcher.py     # Playwright 抓取模块（来自 demo2）
├── parser.py      # HTML 解析模块（来自 demo3/demo4）
├── db.py          # SQLite 数据访问层（products / sales_history / settings 表）
├── config.py      # 路径、状态常量
├── database/      # products.db（自动创建）
└── html_output/   # 抓取的 HTML，按日期分文件夹（自动创建）
```

## 使用

```bash
# 添加商品链接
python client.py add https://xhslink.com/m/xxxx

# 抓取所有待抓取记录（或指定记录 ID）
python client.py fetch
python client.py fetch 1

# 解析所有“待解析详情”的记录，提取商品名称/主图/价格/销量
python client.py parse

# 一步到位：添加 + 抓取 + 解析
python client.py run https://xhslink.com/m/xxxx

# 查询
python client.py show 1     # 单条详情
python client.py list       # 全部记录
python client.py list 2     # 按状态筛选：0待抓取 1待解析 2已完成 3无效
```

## 图形界面

```bash
python gui.py
```

- **添加并采集**：顶部输入框可粘贴多行链接（每行一个，自动去重），点击按钮后后台依次抓取+解析，进度显示在日志区
- **列表**：支持状态筛选下拉 + 搜索框按商品名称/链接模糊查询（回车触发）
- **详情**：选中行右侧显示文字详情 + 历史销量折线图（tkinter Canvas 绘制，随窗口宽度自适应重绘）
- **重新采集**：选中记录重置为待抓取，重新抓取+解析；每次解析成功都会向 `sales_history` 追加一条销量快照（时间 + 销量），主表 `sales` 始终为最新值，折线图随之更新
- **刷新 / 删除选中 / 重试失败**：重试会把状态 3 的记录重置为待抓取并重新采集；抓取期间按钮置灰，不阻塞界面
- **设置**：弹窗配置定时采集开关与频率（1h/2h/6h/12h/1d/2d/7d），设置存 SQLite（`settings` 表），重启后仍生效；定时任务只刷新「已完成」状态的记录（重新抓取+解析，追加销量快照），双击列表行也可立即更新单条

## 状态流转

| 状态 | 含义 | 触发 |
|---|---|---|
| 0 | 待获取数据 | `add` 添加链接后 |
| 1 | 待解析详情 | `fetch` 抓取成功、HTML 已保存 |
| 2 | 已完成 | `parse` 解析成功、字段已入库 |
| 3 | 无效数据 | 抓取失败 / 文件缺失 / 字段全空 |

## 依赖

- Python 3.10+
- `playwright`（抓取）、`beautifulsoup4`（解析）；GUI 用内置 tkinter，无额外依赖

```bash
pip install playwright beautifulsoup4
playwright install chromium
```
