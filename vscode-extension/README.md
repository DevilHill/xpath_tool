# WBot Studio for VS Code

在 VS Code 中管理网页元素、抓取 XPath、插入元素调用代码，并运行或调试 wbot Python 脚本。脚本由 Python 解释器执行。

## 安装与首次使用

1. 在 VS Code 的扩展面板菜单中选择 **从 VSIX 安装**，选择 `wbot-studio-0.1.0.vsix`。本版为本地分发包，未发布到 Marketplace。
2. 打开本机项目文件夹，并将工作区设为受信任。需要 Python **3.10 或更高版本**。
3. 打开左侧 **WBot**，点击 **选择 Python**，选择项目环境中的 `python.exe`。也可以留空配置，使用 Microsoft Python 扩展当前选择的解释器、项目 `.venv` 或 PATH 中的 Python。
4. 执行 **WBot: 将 wbot 安装到所选 Python 环境**。终端显示安装成功后，点击侧栏插头图标 **启动 / 连接浏览器服务**。内置 wbot wheel；首次安装 `lxml` 依赖可能需要网络。
5. 执行 **WBot: 准备浏览器扩展目录**。目录会复制到剪贴板并在文件管理器中打开。进入 `chrome://extensions` 或 `edge://extensions`，开启开发者模式，点击 **加载已解压的扩展程序**，选择该目录。随后刷新需要操作的网页。
6. 在 WBot 侧栏点击 **抓取元素**。切换到网页，悬停选择元素，`Ctrl + 左键` 锁定，`Enter` 确认。回到 VS Code 填写名称、分组、XPath、页面 URL 和描述，保存到元素库。
7. 执行 **WBot: 新建自动化脚本**。元素条目上的代码图标会插入调用代码；Python 编辑器右上角的运行按钮将当前脚本交给所选 Python 执行。点击前确认脚本内容。

浏览器扩展首次加载由浏览器管理页面完成。已安装 XPath Studio 1.4.0 浏览器扩展、且连接地址一致时可以继续使用。无需打开桌面 EXE；VS Code 扩展可以独立启动本机桥接服务。

## 元素库

- 按组展示、搜索、新增、编辑、删除；单击元素复制 XPath，代码图标插入调用代码。
- JSON 导入 / 导出与桌面版共用 `wbot-elements` 格式。导入时可选择遇到同名元素停止、跳过或替换；替换以分组和名称识别。
- 默认数据库为 `~/.xpath_studio/elements.sqlite3`，与桌面版及 `wbot.ElementLibrary()` 共用。可以通过 `wbot.libraryPath` 指定另一个绝对路径。
- **校验并高亮**使用最近抓取结果的浏览器、标签页、框架和文档身份。更换页面或导航后请重新抓取；跨域 iframe 的 XPath 只在对应框架内有效。
- 插入的代码包含服务地址和元素库路径。将脚本移到其他机器时请调整这两个参数。

```python
from wbot import web, selector

browser = web.get(base_url="http://127.0.0.1:8790")
elements = selector.SelectorStore()
element = browser.find(elements.get("搜索框", group="首页"), timeout=10)
element.input("wbot")
```

可在 Python 编辑器中输入 `wbot-connect`、`wbot-element` 或 `wbot-browser` 使用代码片段。

## Python 运行与调试

运行使用 VS Code 的 ProcessExecution 任务，参数分别传入 Python，不拼接 Shell 命令。脚本以工作区目录为当前目录，运行输出在集成终端中显示；可以通过终端停止任务。

调试按钮调用 **Microsoft Python Debugger**（`ms-python.debugpy`）。请先安装此扩展，然后在 Python 文件中设置断点。WBot 使用所选 Python、当前文件和 `wbot.scriptArgs` 创建调试会话。

安装操作只安装 wbot 核心和 `lxml`。若需要 Excel 或 Playwright 独立浏览器功能，可以在同一 Python 环境中安装 `openpyxl`、`playwright`，并按 Playwright 的要求安装浏览器。文件、文件夹、文本、正则、JSON、CSV、ZIP、HTTP、日志与进程等能力由已有 wbot 库提供，不依赖编辑器插件。

## 配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `wbot.pythonPath` | 空 | Python 可执行文件路径，不含参数 |
| `wbot.bridgeUrl` | `http://127.0.0.1:8790` | 仅支持本机 HTTP 服务 |
| `wbot.libraryPath` | 空 | 空值使用用户目录下的默认元素库；否则必须为绝对路径 |
| `wbot.scriptArgs` | `[]` | 运行 / 调试脚本的字符串参数数组 |

修改服务端口、解释器或数据库路径后，请停止本扩展的服务，再启动。修改端口还需重新执行 **准备浏览器扩展目录**，在浏览器中重新加载扩展。

已有 XPath Studio 1.4.0 服务运行时会复用它。此时 `wbot.libraryPath` 必须与该服务实际使用的数据库一致。**停止本扩展启动的服务**只关闭本扩展创建的子进程；VS Code 退出时也会自动关闭该子进程。

## 故障处理与范围

- 服务启动失败：检查 **输出 → WBot**，确认解释器已安装 wbot / lxml、端口可用。
- 没有浏览器连接：确认浏览器扩展已启用、地址和端口一致，刷新普通 HTTP/HTTPS 网页。浏览器内部页面不能抓取。
- 抓取后暂不显示：点击侧栏刷新；从其他应用修改数据库后也需要刷新。
- 只能在本机可信工作区使用；本版本不支持 Remote SSH、WSL、Dev Container 和虚拟工作区。
- 本版提供网页元素与 Python 开发工作流；没有加入桌面 UIA 元素抓取和可视化流程编排。wbot 的现有模块覆盖范围仍以项目 `docs/wbot.md` 为准。

## 从源码构建

先在仓库根目录构建 wbot wheel（产物应为 `dist/wbot/wbot-0.1.0-py3-none-any.whl`），再执行：

```powershell
cd vscode-extension
npm ci
npm run prepare-runtime
$env:WBOT_TEST_PYTHON = "你的 Python 绝对路径"
npm test
npm run package
```

`runtime/` 从当前项目复制生成。VSIX 包含桥接服务、定位工作台、浏览器扩展和 wbot wheel，不包含 Node 开发依赖。测试使用独立临时数据库。

扩展宿主集成测试入口为 `test/integration.js`，可通过 VS Code 的 `--extensionDevelopmentPath` 与 `--extensionTestsPath` 运行；使用隔离的用户数据和扩展目录。

API 参考：[Tree View](https://code.visualstudio.com/api/extension-guides/tree-view)、[Workspace Trust](https://code.visualstudio.com/api/extension-guides/workspace-trust)、[扩展打包](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)。
