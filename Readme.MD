<img src="app/web/app.png" alt="XPath Studio" width="64" />

# XPath Studio

网页元素定位工具：在桌面端分析 HTML/XML，或通过 Chrome / Edge 扩展拾取元素，生成并验证 **XPath、CSS、Playwright** 定位器。

- DOM 树、高亮匹配、批量验证与页面扫描。
- 稳定祖先锚定、动态属性识别、定位器评分和自愈建议。
- 支持离线检索，可选接入 OpenAI 兼容 AI 服务。

[界面截图](docs/images/install-current-chrome.png) · [扩展说明](extension/README.md)

## 获取代码

```powershell
git clone https://github.com/DevilHill/xpath_tool.git
cd xpath_tool
```

私有仓库，克隆需要访问权限。

## 环境

- Windows，推荐 [Python 3.13](https://www.python.org/downloads/)；依赖见 [requirements.txt](requirements.txt)。
- 原生窗口需要 [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)；可改用浏览器模式。
- [Git 2.x](https://git-scm.com/downloads/) 用于克隆；[Node.js 22](https://nodejs.org/en/download) 和 `jsdom` 仅用于 JavaScript 测试。

## 运行与使用

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install cssselect
.\.venv\Scripts\python.exe run.py --browser
```

默认访问 `http://127.0.0.1:8790/`，端口被占用时自动选择其他端口，以终端输出为准。粘贴 HTML 并解析，点击 DOM 节点查看定位器。`Ctrl+C` 停止服务；修改 Python 代码后需重启。

使用 `run.py` 打开原生窗口，`run.py --serve` 仅启动服务，`--port 8798` 指定首选端口。

### 浏览器扩展

1. 在桌面端点击连接状态 → **安装到现有浏览器**。
2. 在打开的扩展页开启开发者模式，选择“加载已解压的扩展程序”，粘贴已复制的目录。
3. 刷新目标网页，点击桌面端“抓取元素”；`Ctrl+左键` 锁定，`Enter` 确认，`Esc` 取消。

也可在 `chrome://extensions/` 或 `edge://extensions/` 手动加载 `extension/`。独立使用时，`Alt+Shift+X` 打开面板。

> [!NOTE]
> 默认安装需要手动加载到现有个人资料；高级 CDP / 启动参数方式使用独立实例。iframe 内的定位器仅在对应框架有效。企业策略安装受管理环境限制，真实环境完整流程尚未验证。

### AI（可选）

在“AI 设置”填写接口、模型和密钥。配置保存在本机 `~/.xpath_studio/config.json` 及浏览器本地存储；AI 请求会将提交的 HTML 和描述发送至配置的接口。规则功能无需 AI。

## 构建与测试

```powershell
.\.venv\Scripts\python.exe build.py
.\.venv\Scripts\python.exe tools/pack_extension.py
.\.venv\Scripts\python.exe -X utf8 tools/smoke_test.py
.\.venv\Scripts\python.exe -X utf8 tools/test_extension_static.py
```

产物：`dist/XPathStudio.exe`、`dist/xpath-studio-extension.zip`。修改界面或扩展后需重新打包；运行 `tools/verify_exe.py` 可检查 EXE 内嵌资源。产物不提交到 Git，未配置自动发布。

前端测试示例：

```powershell
npm install --no-save --package-lock=false jsdom
node tools/test_install_ui.js
```

更多测试见 [tools/](tools/)。双引擎回归脚本 `test_engine_parity.py`、`test_ancestor_anchor.py` 含开发机 Node 路径，其他机器运行前需调整。

## 贡献与许可

通过 [Issues](https://github.com/DevilHill/xpath_tool/issues) 报告问题，附复现步骤和脱敏日志。PR 请说明改动与验证结果；定位算法改动需保持 Python / JavaScript 两端一致。

[.gitignore](.gitignore) 已忽略 `Agent.MD` 的大小写变体、本地工作记录、构建产物和密钥。

本项目采用 [MIT 许可证](LICENSE)。
