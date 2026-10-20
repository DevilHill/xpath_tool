# WBot Studio for VS Code

在 VS Code 中编排可视化流程、管理网页元素、抓取 XPath，并运行 wbot 自动化。0.3.0 为可视化流程加入断点、单步、暂停与继续；流程文件由 Python 解释器逐条执行。

## 断点与单步调试（0.3.0）

1. 打开 `.wbot.json` 流程，点击指令左侧圆点设置或移除断点。红色圆点表示已设置，断点随流程保存；旧流程文件不需要迁移。
2. 点击顶部 **调试**。会先停在第一条启用的指令之前，金色高亮和“下一条执行”标记显示当前尚未执行的步骤；底部自动切到只读变量页。
3. 点击 **单步** 执行当前一条指令，更新变量后暂停在下一条启用指令之前。禁用指令会跳过；最后一条执行后正常结束。
4. 点击 **继续**，运行至下一个断点或流程结束。从断点继续时不会重复停在同一条，也不会重复执行已经完成的指令。
5. 执行中点击 **暂停**，会在当前指令完成后、下一条启用指令开始前暂停。当前浏览器请求或等待不会因“暂停”立即中断；需要结束运行时点击 **停止**。在断点暂停状态也可以直接停止。

**运行**按钮忽略断点；**调试**按钮遵循断点。普通运行也可以手动暂停，再单步或继续。运行中的断点和参数不可修改；调试使用启动时的流程快照，通过 JSON 编辑器进行的修改在下次运行生效。

暂停时显示已经完成的指令产生的变量值；当前高亮指令尚未执行。停止不会撤销之前的文件写入或网页操作。此功能针对可视化流程中的指令，与 Python 脚本的 debugpy 断点调试入口独立。

可将 `examples/breakpoint-demo.wbot.json` 复制到工作区：调试启动后单步观察 `message` 的变化，再继续至“检查替换后的值”断点。

## 可视化流程编辑器（0.2.0）

安装新版 VSIX 后，打开本机文件夹，按 `Ctrl+Shift+P` 执行 **WBot: 新建可视化流程**，保存为 `*.wbot.json`，即可进入编辑器。WBot 侧栏顶部也有新建流程按钮。现有流程文件可以直接双击打开；如果显示 JSON，右键标签选择 **重新打开编辑器 → WBot 流程编辑器**。

- **左侧指令库**：搜索并点击添加，也可以拖动到指定指令之前。
- **中间主流程**：拖动排序、上移/下移、复制、删除、复选框启停；支持 VS Code 撤销、重做与保存。
- **右侧配置**：填写参数、设置备注，网页指令可从元素库选择目标，也可直接填写 XPath。
- **底部变量与日志**：编辑初始文本变量，查看逐步执行状态、日志和最近运行的变量值。失败会停止后续指令并标记出错步骤。
- **运行 / 停止**：执行前保存当前流程；运行期间禁止通过可视化界面修改步骤。等待可立即中止，其他操作超过两秒仍未退出时结束本扩展创建的 Python 进程。停止不会撤销已发生的点击或文件写入。

初版支持 11 类指令：连接已抓取网页、点击网页元素、填写输入框、获取元素文本、等待网页元素、设置变量、替换文本、输出日志、等待、读取文本文件、写入文本文件。

文本中可用 `${message}` 引用名为 `message` 的变量。变量名使用英文字母、数字与下划线，不能以数字开头。文本替换和文件操作结果可以保存为新变量。UTF-8 文件读写限于当前工作区；写入操作会覆盖同名文件。

新建的默认流程只输出日志并等待，无需浏览器即可试运行。还可以将扩展源码中的 `examples/text-processing.wbot.json` 复制到工作区，体验设置变量、替换、写入、读取和日志的完整流程；它会生成 `output/wbot-demo.txt`。

网页流程使用前先启动 WBot 浏览器服务、加载浏览器扩展并抓取页面，随后在流程中加入 **连接已抓取网页**。右侧 **刷新** 从同一元素库读取数据；**抓取网页元素** 调用已有抓取与保存流程。页面导航后需要重新抓取，元素库的框架作用域检查继续生效。

本版为顺序流程初版，尚不包含条件分支、循环、子流程、桌面 UIA、OCR 与 Excel 可视化指令。已有 wbot Python 库及 Python 脚本调试入口仍可使用。

## 安装与首次使用

1. 在 VS Code 的扩展面板菜单中选择 **从 VSIX 安装**，选择 `wbot-studio-0.3.0.vsix`。本版为本地分发包，未发布到 Marketplace。
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
- 本版提供网页元素、顺序流程编排与 Python 开发工作流；没有加入桌面 UIA 元素抓取。wbot 的现有模块覆盖范围仍以项目 `docs/wbot.md` 为准。

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

只预览界面时，可以运行 `python scripts/preview-editor.py` 并访问 `http://127.0.0.1:8797`。该预览支持编辑和下载 JSON，实际运行、保存至工作区和元素库连接须使用 VS Code 扩展。

API 参考：[Tree View](https://code.visualstudio.com/api/extension-guides/tree-view)、[Workspace Trust](https://code.visualstudio.com/api/extension-guides/workspace-trust)、[扩展打包](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)。
