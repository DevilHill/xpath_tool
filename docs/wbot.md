# wbot Python 自动化库

`wbot 0.1.0` 是与 XPath Studio 配套的独立 Python 库。参考本机 ShadowBot 发布产物中的公开接口声明，独立实现网页定位与操作、元素库和常用自动化工具。可安装的包只包含 `wbot`，不需要把桌面项目 `app` 放进 Python 路径，也不调用影刀运行时。

这不是将 xbot 文件复制后改名：调查发现大量 xbot Python 文件是文档桩，部分原生/托管实现尚未恢复。本库提供下表所列的实际能力，不声称完整兼容 xbot 的全部模块、参数和行为。

## 安装

Python 3.10 或更新版本，在项目根目录执行：

```powershell
python -m pip install .
# Excel 文件能力
python -m pip install ".[excel]"
# 独立创建浏览器 + Excel
python -m pip install ".[all]"
```

也可以安装交付目录中的 `wbot-0.1.0-py3-none-any.whl`。基础依赖是 lxml；Excel 可选依赖 openpyxl；独立浏览器可选依赖 Playwright。桌面扩展桥模式不需要 Playwright。

## 软件中的元素库

运行新版 XPath Studio，刷新已安装的浏览器扩展后，在网页上抓取元素。工作台右侧的「元素库」可以：

1. 保存当前 XPath，填写名称、分组和描述。
2. 按名称、XPath、描述搜索，按分组筛选。
3. 编辑、删除、导入／导出 JSON；导入可停止、跳过或替换同名记录。
4. 点击「使用」载入工作台校验；点击「复制 wbot 代码」生成带当前服务端口的 Python 示例。

默认保存为 `~/.xpath_studio/elements.sqlite3`，与 `SelectorStore()` 使用同一位置。设置 `WBOT_ELEMENT_LIBRARY` 环境变量可为桌面服务和 Python 库指定其他文件。库中 `(分组, 名称)` 唯一；导入整体提交，出错不保留一半数据。

元素记录含 `id/name/group/xpath/description/url/frame/created_at/updated_at`。JSON 格式为 `{ "format": "wbot-elements", "version": 1, "items": [...] }`，不接受影刀私有的加密 SelectorStore 或 selectorsV2.xml 作为兼容导入。

## 连接已抓取的网页

先启动 XPath Studio 并完成一次抓取。端口默认 8790，被占用后以软件实际端口为准。

```python
from wbot import web, selector

browser = web.get(base_url="http://127.0.0.1:8790")
elements = selector.SelectorStore()

login = browser.find(elements.get("登录按钮", group="登录页"), timeout=5)
print(login.get_text())
# 在你的测试页面执行动作
login.click()
```

也可直接使用 XPath：

```python
field = browser.find("//input[@name='username']", timeout=5)
field.input("tester")
field.input("-01", append=True)
print(field.get_value())

browser.find("//select[@id='city']").select("上海", mode="text")
browser.find("//input[@type='checkbox']").check()
print(browser.count("//a"))
for link in browser.find_all("//a", timeout=0):
    print(link.get_text(), link.get_attribute("href"))
```

`find`、`find_by_xpath` 默认要求唯一匹配；每次动作重新检查，DOM 变化出现多个匹配会抛 `AmbiguousElementError`。`find_all` 返回显式索引元素，索引跟随当前 DOM 排序，并不是永久绑定的 DOM 节点；列表重排后应重新查询。结果超过 500 项时明确报错，请收窄 XPath。

等待参数单位为秒，`timeout=0` 只查询一次。`wait_appear`、`wait_disappear`、元素 `wait('visible'/'hidden'/'attached'/'detached')` 提供轮询等待。服务单次桥请求最多等待 8 秒，网络与查询时间计入实际耗时，不能把轮询 timeout 当作中断正在进行的系统调用。

桥模式绑定最近一次抓取的 `browserId/tabId/frameId/documentId`，支持已抓取的跨域 iframe。导航、刷新、重新抓取别处后，旧对象不会自动切到新网页；请在正确页面重新抓取并再次 `web.get()`。元素库保存的临时 documentId 不直接复用，URL 与框架信息用于核对当前作用域。

扩展桥动作使用 DOM 事件和属性赋值，支持点击、输入、文本、属性、可见性、启用状态、复选框、下拉框、悬停、滚动。网页可能拒绝非可信事件；它不等同于系统级鼠标键盘模拟，`simulative=True` 会明确报不支持。

## 独立浏览器

安装 `.[web]` 后，可使用已有的 Chrome/Edge，或另行安装 Playwright Chromium：

```python
from wbot import web

with web.create("https://example.com", channel="msedge", headless=False) as browser:
    print(browser.find("//h1").get_text())
    browser.navigate("https://example.com")
```

使用 Playwright 自带浏览器时先执行 `python -m playwright install chromium`，再省略 `channel`。只管理本库创建的浏览器；该后端当前作用域是主框架。复杂 iframe 操作可通过公开的 `browser.page` 使用原生 Playwright API，不能把其行为宣称为 xbot 兼容接口。

## 独立使用元素库

```python
from wbot import ElementLibrary, SelectorStore

library = ElementLibrary("project-elements.sqlite3")
saved = library.upsert({
    "name": "搜索框", "group": "首页", "xpath": "//input[@name='q']",
    "description": "站内搜索", "url": "https://example.com/"
})
print(library.list(query="搜索"))
store = SelectorStore("project-elements.sqlite3")
print(store("搜索框", group="首页").xpath())
payload = library.export_data()
# 其他库可使用 import_data(payload, conflict='error'/'replace'/'skip')
```

元素 XPath 使用 XPath 1.0。保存时拒绝标量、属性节点、文本节点和 `node()`；正常的属性谓词、元素 union、索引可用。原包的变量表达式和私有结构化选择器未实现。

## 模块与兼容范围

| 模块 | 已实现能力 | 范围说明 |
|---|---|---|
| `web` | `get/attach/get_active/create`、`find/find_all/find_by_xpath`、等待、元素动作 | xbot 风格子集；桥与独立浏览器的生命周期不同 |
| `selector` / `elements` | `Selector.xpath()`、`SelectorStore.get/__call__`、SQLite CRUD、JSON 导入导出 | 独立数据格式，不解密影刀资源 |
| `files` | 文本/字节读写、追加、复制、移动、删除、校验和、列举 | wbot 实用 API |
| `folders` | 创建、列举、复制、删除 | 删除非空目录需要显式 recursive |
| `strings` | 截取、拆分、替换、标准化、Base64、HTML/URL 编解码 | 实用字符串接口，无动态代码执行 |
| `regex` | 编译、搜索、匹配、替换、拆分 | Python re 语义 |
| `json` / `csv` | 字符串和文件转换、字典行/列表行 | UTF-8/中文支持 |
| `xzip` | ZIP 打包与解包 | 路径穿越/符号链接检查；不支持加密写入 |
| `request` | HTTP 方法、JSON/表单、响应体/状态、下载 | urllib 后端，TLS 默认验证；非原包响应类型全兼容 |
| `excel` | 工作簿/表/单元格/区域读写、追加行列、保存 | openpyxl 离线 XLSX/XLSM；不控制 Office/WPS，不计算公式 |
| `logging` | 显式配置、各级日志、异常日志 | 标准 logging |
| `process` / `sleep` | 参数列表执行子进程、暂停 | 无 shell 字符串拼接 |

文件写入与复制、JSON/CSV 导出、ZIP、下载、Excel `save_as()` 默认不覆盖，需要显式 `overwrite=True`。Excel `save()` 保存回当前文件。工作表索引和行号从 1 开始。

```python
from wbot import files, json, csv, regex, request, excel

files.write_text("note.txt", "中文", overwrite=True)
print(regex.findall(r"\d+", "订单 123"))
json.dump({"ok": True}, "result.json", overwrite=True)

# 对你自己的测试服务发请求
# response = request.post("http://127.0.0.1:8000/echo", json={"name": "测试"})
# response.raise_for_status()
# print(response.json())

with excel.create() as book:
    sheet = book.get_active_sheet()
    sheet.cell("A", 1).value = "名称"
    sheet.append_row(["示例"])
    book.save_as("result.xlsx", overwrite=True)
```

未覆盖 Windows UIA、SAP、Java 桌面自动化、OCR/图像识别、鼠标键盘驱动、Office COM/WPS、邮件、PDF、远程调度、账号许可、影刀流程编译器和自愈算法。仅有公开声明的功能不会用空 `pass` 或假成功冒充实现。

## 验证和构建

```powershell
python -m unittest discover -s tests -v
python tools/test_browser_validation.py
python tools/test_live_validation.py
python -m pip wheel . --no-deps -w dist/wbot
python build.py
python tools/verify_exe.py
```

单元测试使用临时目录、SQLite 和本机 HTTP 服务。真实浏览器联动测试使用独立配置与本机页面，验证扩展、跨域 iframe、Python 动作、元素库读取和页面失效。独立 Playwright 后端测试在安装依赖后运行；设置 `WBOT_BROWSER_EXECUTABLE_PATH` 可指定本机 Chrome，不会使用日常浏览器配置。

公开接口调查依据：`Resources/Code-Activity/Zh-CN/xbot/web/browser.py`（find/wait）、`web/element.py`（动作声明）、`selector.py`（Selector/SelectorStore），以及 `request.py`、`xzip.py`、Excel 抽象类。原包多数代码为桩，以上接口风格不构成对其内部实现的恢复证明。
