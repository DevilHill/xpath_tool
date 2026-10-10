# XPath Studio · AI 元素定位编辑器

一个面向爬虫 / Web 自动化测试场景的 **XPath 定位工作台**。粘贴或抓取 HTML，
实时查看 DOM 树、校验 XPath 并高亮匹配节点，自动生成「最短唯一」定位器并给出**稳定性评分**，
还能用自然语言或大模型直接生成稳健的 XPath。

提供两种形态：**桌面 exe 工具**（离线分析任意 HTML）+ **浏览器扩展**（在真实网页上直接拾取元素并高亮）。
两者共用同一套定位算法，结果完全一致。

## ✨ 功能

| 模块 | 说明 |
| --- | --- |
| **多源输入** | 粘贴 HTML/XML、输入网址抓取页面、拖拽上传 `.html/.xml` 文件 |
| **DOM 树可视化** | 懒加载渲染，支持标签/属性过滤、展开折叠，点击任意节点即可定位 |
| **XPath 实时校验** | 基于真正的 `lxml` XPath 1.0 引擎，显示匹配数量并在树上高亮 |
| **最短唯一 XPath** | Robula+ 思路：从绝对路径出发逐步削减前缀步骤，得到既短又唯一的表达式 |
| **稳定祖先锚定** | 目标在页面中重复时，用稳定容器属性限定范围并跳过中间包装层，校验唯一且命中目标 |
| **稳定性评分** | 每个定位器给出 0–100 分与「稳定 / 一般 / 脆弱」评级，并标注失效风险 |
| **动态 ID 识别** | 自动识别 JSF `j_idt88`、Vue `data-v-`、styled-components 哈希、UUID 等易变值并告警 |
| **多类型定位器** | 同时产出 **XPath / CSS 选择器 / Playwright 定位器**（getByRole、getByTestId…） |
| **列表模式** | 一键生成匹配「同类元素集合」的 XPath，适合批量提取 |
| **自然语言检索（离线）** | 用中文描述（如「登录按钮」）在文档内做启发式打分匹配，**无需联网** |
| **AI 智能生成** | 接入任意 OpenAI 兼容大模型，一句话生成 XPath 并本地校验 |
| **批量验证** | 粘贴多条定位器（XPath/CSS），一次性校验有效性、匹配数与唯一性 |
| **页面扫描** | 自动找出所有可交互元素（按钮/链接/输入框…）并给出最佳定位器，可导出 |
| **查询历史 / 双主题** | 自动记录用过的表达式；浅色 / 深色一键切换 |
| **浏览器联动抓取** | 桌面版点「抓取元素」→ 在浏览器里悬停**实时高亮**，按住 <kbd>Ctrl</kbd> 再左键点击选中，元素与定位器立刻回传到桌面版 |
| **浏览器扩展** | Chrome / Edge MV3 扩展：在**真实页面**上直接拾取元素、**页内高亮**、生成定位器，并可桥接桌面版的 AI 配置 |

## 🧠 算法参考

本项目的定位算法参考并吸收了以下开源项目的思路：

- **[Robula+](https://github.com/cyluxx/robula-plus)**（Leotta et al., JSEP 2016）—— 最短唯一 XPath：
  以绝对路径为起点，从头部逐步削减步骤，直到不能再短且仍能唯一定位目标。
- **[xpath-helper-plus](https://github.com/mic1on/xpath-helper-plus)** —— class 按 token 匹配、
  剔除 `active`/`hover`/`is-open` 等运行时状态 class、`tag[predicate][n]` 的位置索引语义。
- **[XPath Forte](https://samdaniel-s.github.io/XpathForte/)** —— 稳定性评分模型（深嵌套 / 位置索引 /
  绝对路径 / 兄弟轴各有扣分上限）、动态 ID 识别、多类型定位器与批量验证。
- **[parthsathwara22/xpath-generator-extension](https://github.com/parthsathwara22/xpath-generator-extension)**
  —— `data-testid` 等测试属性**一律视为稳定**（即使长得像哈希）；扩充动态值特征
  （`_ngcontent-*` / `_nghost-*`、React 18 `useId` 的 `:r1a:`、Ember `emberNNN`、纯数字 id）。
- **[cdnkr/xpath-generator](https://github.com/cdnkr/xpath-generator)**
  —— **表单标签锚定**（`<label>` 文案作为锚点，控件本身没有稳定属性时最耐用）。
- **[Healenium](https://github.com/healenium/healenium-web)** —— 自愈式定位器：按多维相似度
  给候选元素打分，阈值取它默认的 **0.6**。

## 🚀 快速开始

推荐在 Windows 上使用 Python 3.10+，并安装 Microsoft Edge WebView2 Runtime，
以便通过 pywebview 打开桌面窗口。开发与打包主要在 Windows / Python 3.13 上验证。

### 方式一：直接运行源码

```bash
pip install -r requirements.txt
python run.py            # 原生窗口（pywebview）
python run.py --browser  # 或使用系统浏览器打开
python run.py --serve    # 只启动本地服务
```

建议使用虚拟环境；在 Windows PowerShell 中可以先执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

服务默认从 `127.0.0.1:8790` 启动，端口被占用时顺延；以启动时输出的地址为准。

### 方式二：打包成 exe

```bash
python tools/make_icon.py   # 生成图标（可选）
python build.py             # 产物：dist/XPathStudio.exe
python build.py --console   # 打包带控制台的版本，便于排查问题
```

### 自检

```bash
python tools/smoke_test.py           # 启动服务并依次调用全部 API
python tools/verify_exe.py           # 对打包后的 exe 做真实进程验证（含「产物是否落后于源码」+ 策略更新服务）
python tools/test_ws_bridge.py       # WebSocket 帧编解码 + 与 Node 客户端端到端联调
python tools/test_engine_parity.py   # JS ↔ Python 定位引擎结果一致性（含自愈）
python tools/test_ancestor_anchor.py # 稳定祖先定位与包装层变化回归
python tools/test_extension_static.py# 扩展 manifest / 权限 / 消息通道一致性
python tools/test_extension_installer.py  # 浏览器探测 / 安装策略解析（不真的启动浏览器）
python tools/test_extension_permissions.py # 真机：host 权限是否够 executeScript（会起无头 Chrome）
python tools/test_crx.py             # 纯标准库 RSA / SPKI / CRX3 签名与自校验（50 项）
python tools/test_policy_install.py  # 企业策略读写（假 winreg，不碰真实注册表，50 项）
node tools/test_panel_render.js      # jsdom 渲染扩展面板并断言（需 npm i jsdom）
node tools/test_content_pick.js      # jsdom 跑拾取流程（悬停高亮 / Ctrl+左键 / 回传负载）
node tools/test_exe_ui.js            # jsdom 加载桌面版前端，验证桥接与抓取结果渲染
node tools/test_install_ui.js        # jsdom 验证「一键安装扩展」弹窗（含企业策略方式）
node tools/test_heal_ui.js           # jsdom 验证批量验证里的自愈建议渲染与采用
node tools/test_modal_css.js         # jsdom 解析真实 CSS 级联，验证「安装扩展」弹窗布局
```

Node 测试需要 Node.js 和 `jsdom`（可用 `npm install --no-save jsdom` 安装）。
部分 Python 联调脚本仍引用开发机的 Node / Chrome 路径；在其他机器运行前，
请检查脚本中的 `NODE`、`NODE_MODULES` 和浏览器路径。

> ⚠️ **改了 `app/web/` 下的任何文件，都要重新 `python build.py`。**
> exe 里跑的是打包时塞进 `_MEIPASS/web` 的**副本**，源码改好但没重打包，用户装到的还是旧界面。
> `tools/verify_exe.py` 的第 [13] 项会逐字节比对 exe 实际返回的静态资源与源码，不一致直接报错。

### 真机验证（会启动浏览器/进程，验证完自动关闭）

```bash
python tools/live_install_check.py --browser edge --strategy flag    # Edge 走 --load-extension
python tools/live_install_check.py --browser chrome --strategy cdp   # 品牌版 Chrome 走 CDP
python tools/shot_install_modal.py   # 无头 Chrome 真实渲染「安装扩展」弹窗 + 量像素几何 + 出图
```

> `shot_install_modal.py` 补的正是 jsdom 的短板：jsdom 能解析 CSS 级联但**不做布局**。
> 它会起 exe、用 CDP 点开弹窗，量 `getBoundingClientRect()` 并把截图存到 `shots/`。
> 注意真实浏览器会把 `width: auto` 解析成**实际用值**（如 `13px`），而 jsdom 只回 `"auto"`，
> 所以「声明值」由 `test_modal_css.js` 断言，「真实几何」由本脚本断言，两者互补。

## 🧩 浏览器联动（抓取元素 + 页内高亮）

桌面版只能分析「粘贴进来的 HTML」；要**直接在真实网页上点点点**，请安装配套的浏览器扩展。
**入口在桌面版**：点桌面版右上角的 **「抓取元素」** 按钮，剩下的事情扩展会自动完成。

### 一次完整抓取

1. 在桌面版点 **抓取元素**（右上角，紫色按钮）。
2. 切到浏览器 —— 鼠标移到目标上，页面上会**实时高亮**悬停区域并显示元素描述。
3. **↑ / ↓** 切换父子层级；**Ctrl＋左键**锁定（Mac 为 Cmd），预览后点「确认抓取」或 Enter 回传。`Esc` 取消。
4. 支持启动时已加载且有访问权限的 iframe；框架 XPath 只在对应框架内有效，桌面版明确提示作用域。确认后，该元素的 **XPath / CSS / Playwright** 定位器、稳定性评分、元素 HTML 会回传到桌面版的
   「浏览器抓取」标签页；桌面版还能一键把整页 HTML 载入编辑器做进一步分析。

> 拾取过程中**不会弹出任何页面内面板**，只有一个轻量提示条；扩展全程只做「助手」。

### 扩展的其它能力

- **独立可用**：不依赖桌面版也能用 —— `Alt+Shift+X` 呼出面板、`Alt+Shift+P` 拾取、
  面板内可校验 XPath、扫描页面、生成定位器。
- **桥接桌面版 AI**：扩展可调用本机桌面版 `/api/ai`，复用桌面版里已配置好的大模型。
- **样式隔离**：面板与覆盖层都渲染在 Shadow DOM 中，页面 CSS 污染不了 UI，UI 也不影响页面。

### 安装到正在使用的浏览器（默认方式）

打包后的 `XPathStudio.exe` **自带扩展**，不用手动找目录：

1. 点桌面版右上角的**连接状态胶囊**（显示「扩展未连接」的那个），或「浏览器抓取」面板里的
   **一键安装扩展**。
2. 弹窗列出本机浏览器，默认优先选择 **Chrome**，也可切换到 Edge / Brave / Chromium。
3. 点 **安装到现有浏览器**。桌面版请求打开扩展管理页，并把扩展目录复制到剪贴板。
4. 确认扩展页位于日常使用的窗口和个人资料，开启 **开发者模式**，点击 **加载已解压的扩展程序**，在目录选择框中粘贴路径。
5. 加载后打开或刷新要抓取的网页，回到桌面版检测连接。连接数是所有实例的总数，不能单独证明目标浏览器已安装。

本项目当前分发本地扩展，Chrome 需要用户完成手动加载。影刀RPA 的扩展已上架 [Chrome 应用商店](https://chromewebstore.google.com/detail/%E5%BD%B1%E5%88%80rpa/hofgfmmdolnmimplihglefekekfcfijf)，其商店安装渠道与本地扩展不同。

#### ⚠️ 先搞清楚「装到哪个浏览器」

默认 `auto` 和 `guided` 都打开**现有浏览器**的扩展页；多个人资料时请自行核对目标窗口。

高级选项中的 `flag` / `cdp` 会用**独立 profile**（专门的 `--user-data-dir`）启动新实例，与日常浏览器的登录态和扩展隔离。

| 方式 | 装到哪 | 是否持久 | 适用 |
| --- | --- | --- | --- |
| 启动参数加载 | **独立实例**（专用 profile） | 否，仅该次会话 | Edge / Chromium / Brave / Chrome ≤136 |
| 调试端口（CDP） | **独立实例**（专用 profile） | 否，重启即失效 | **品牌版 Chrome ≥137** |
| 引导安装 | **你现有的浏览器** | ✅ 永久（手动加载后） | 全部浏览器（需你手动点一下） |
| 企业策略强制安装 | 目标为**你现有的浏览器** | ⚠️ 受环境限制，见下 | Windows + Chrome / Edge / Brave / Chromium |

> 想在**现有浏览器**里长期使用，实际可行的有两条：**引导安装**（手动点一次
> 「加载已解压的扩展程序」，最稳、无副作用）或**企业策略强制安装**（写当前用户策略，
> 目标是全自动装进现有浏览器）。
>
> ⚠️ **企业策略不是在所有电脑上都「一键成功」**：自托管扩展强制安装对浏览器版本、设备管理
> 状态和组织安全策略有前提。写入策略**只是配置**，**不等于浏览器已接受策略、更不等于扩展已安装**。
> 被安全软件或设备管理拒绝时，**不要绕过**，请改用引导安装或联系管理员。

> ⚠️ **为什么品牌版 Chrome 需要 CDP**：Chrome 137 起**静默忽略** `--load-extension`
> —— 进程照常启动、不报错、退出码正常、工具栏什么都不显示，只有 Chrome 自己的日志里有一行
> `--load-extension is not allowed in Google Chrome, ignoring`。
> 到处流传的 `--disable-features=DisableLoadExtensionCommandLineSwitch` 也已失效（实测 Chrome 151）。
> 所以 Chrome 137+ 走 CDP，这是目前唯一可靠的编程安装路径（已在 Chrome 153 上实测通过）。
>
> 但要注意 **CDP 的 `Extensions.loadUnpacked` 不持久**：它只写 `Secure Preferences` 而不写
> `Preferences`，实测**浏览器重启后扩展就没了**（用 `chrome://extensions` 的 Shadow DOM 枚举
> 前后对比确认）。所以它只适合「当下用一次」，要长期生效请用策略或引导安装。

#### 企业策略强制安装（受管理环境限制，非普遍可用）

原理是 Windows 的企业策略 `ExtensionInstallForcelist`：桌面版生成一对自签名密钥，用纯标准库
（无第三方加密依赖）按 **CRX3** 规范签名打包出 `.crx`，再往**当前用户**注册表写入一条策略：

```
HKCU\Software\Policies\<厂商>\<产品>\ExtensionInstallForcelist
    "1" = "<扩展ID>;http://127.0.0.1:<端口>/extension/update.xml"
```

如果策略被浏览器接受，浏览器启动时会自己去这个地址拉 `update.xml` 和 `.crx`，静默装好并强制保留。
桌面版本身就是那个常驻的更新服务，所以不需要外网、不需要服务器。写的是 `HKCU`，**不需要管理员权限**，
也不碰 `HKLM`，并且会**保留你已有的其它策略条目**（只替换同一个扩展 ID 的那一条）。

> **为什么它不保证成功**：`ExtensionInstallForcelist` 是**受管设备/组织**用的策略。普通个人电脑上，
> 写入 `HKCU` 这一步可能被安全策略、组策略或安全软件**拒绝**（典型错误：`WinError 5 拒绝访问`）。
> 即使写入成功，也不代表浏览器接受了策略、更不代表扩展装上了 —— 这三件事是**不同状态**。
> 新版会把失败**具体阶段、系统错误类型和 Windows 错误码**显示出来，并提供**「复制安装诊断」**和
> **「改用引导安装」**兜底，而不是笼统报「安装失败」。被拒绝时**不要绕过安全限制**，
> 请改用引导安装，或在受管环境中联系管理员部署。

> **副作用（界面上会明确列出，确认后再装）**
> - 浏览器会显示「**由贵单位管理**」横幅（这是策略生效的正常标志，不是被入侵）。
> - 扩展被策略接管，**无法在扩展管理页直接删除** —— 要用桌面版弹窗里的 **「卸载策略」** 按钮。
> - 桌面版没运行时浏览器拉不到更新；**已经装上的版本仍然可以正常使用**。
> - 改完策略必须**完全退出浏览器**（含托盘/后台驻留进程）再重新打开才可能生效。

#### 关于 `host_permissions` 里的 `<all_urls>`

扩展的 `host_permissions` 必须包含 `<all_urls>`，否则会出现这个报错：

```
✕ Cannot access contents of the page. Extension manifest must request permission to access the respective host.
```

原因：MV3 里 `content_scripts.matches` **只决定「页面打开时自动注入」**，**不授予**程序化注入
的权限。当页面是在扩展加载**之前**就打开的（或 `document_idle` 没跑到），`background.js` 会用
`chrome.scripting.executeScript` 兜底补注入 —— 这一步需要 **host 权限**，光有 `matches` 不够。

> 顺带一提：`chrome.permissions.contains()` **不能**用来预判这个问题。它对 `matches` 覆盖的
> 来源会返回 `true`，但 `executeScript` 照样会失败。要判断只能真的跑一次 `executeScript`。

### 安装（手动，任何浏览器通用）

1. 打开 `chrome://extensions/`（Edge 为 `edge://extensions/`），右上角开启 **开发者模式**。
2. 点击 **加载已解压的扩展程序**，选择扩展目录（桌面版会把它复制到剪贴板，
   打包后位于 `%LOCALAPPDATA%\XPathStudio\extension`）。
3. 也可以直接用打包好的压缩包：`dist/xpath-studio-extension.zip`（解压后再加载）。

### 通信方式

桌面版与扩展之间用 **WebSocket 长连接**（`ws://127.0.0.1:<端口>/ws`）双向通信，
桌面版界面本身也是同一个通道的客户端，因此连接状态是实时的：

| 方向 | 消息 | 说明 |
| --- | --- | --- |
| 桌面版 → 扩展 | `start-pick` / `stop-pick` | 进入 / 退出拾取模式 |
| 扩展 → 桌面版 | `picked` | 回传选中元素的定位器与 HTML |
| 扩展 → 桌面版 | `hello` / `status` | 注册身份、回报异常 |

> 若 WebSocket 不可用，扩展会退化为 `POST /api/bridge/result` 的 HTTP 兜底通道。

### 打包扩展

```bash
python tools/pack_extension.py   # 产物：dist/xpath-studio-extension.zip
```

> 详细说明（权限、隐私、测试）见 [`extension/README.md`](extension/README.md)。

## ⚙️ AI 配置

点击右上角 **「AI 设置」**，填入 OpenAI 兼容服务的地址、模型与密钥。
桌面版将配置保存到本机 `~/.xpath_studio/config.json`，API 回显密钥时使用掩码。

| 服务 | Base URL | 模型示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com` | `gpt-4o-mini` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode` | `qwen-plus` |
| Moonshot | `https://api.moonshot.cn` | `moonshot-v1-8k` |
| 本地 Ollama | `http://localhost:11434` | `llama3.1` |

> 不配置 AI 也能用：规则引擎、离线检索、批量验证和页面扫描全部本地运行，无需大模型服务。

## 📊 稳定性评分说明

| 区间 | 评级 | 典型定位方式 |
| --- | --- | --- |
| 70–100 | 稳定 | `@data-testid` / 稳定 `@id` / `@aria-label` / `@name` |
| 45–69 | 一般 | class 定位 / 文本定位 / 父级+子级组合 |
| 0–44 | 脆弱 | 绝对路径、位置索引、深层嵌套、兄弟轴 |

扣分规则：绝对路径封顶 20；含位置索引封顶 40；兄弟轴封顶 50；`//body` 开头的深路径封顶 35；
路径层级过深逐步扣分；疑似动态 ID 大幅降权。

> 一条候选只有**同时满足「只匹配 1 个节点」和「那个节点就是目标本身」**才算「唯一」。
> 只看数量会把「唯一但指错了元素」的 XPath 误评为稳定 —— 比如
> `//label[...]/following-sibling::input[1]` 在 label 包裹写法下唯一，但指向的是**下一个** input。

## 🩹 定位器自愈建议

页面改版后老 XPath 会失配（匹配 0 个）。在 **批量验证** 里，失配的定位器下方会自动出现
替代建议 —— 从**选择器字符串本身**反推当初想找什么，再在现在的 DOM 里按相似度找最像的元素：

| 维度 | 权重 | 说明 |
| --- | --- | --- |
| 标签 | 0.25 | 标签不一致直接淘汰 |
| 属性 | 0.35 | 值相似度；属性被改名时还会尝试「值搬到了别的属性」 |
| class | 0.20 | token 重合度 + 字符串相似度；BEM 首词（`cart-link` / `cart-entry` 的 `cart`）命中加分 |
| 文案 | 0.20 | 文本相似度 |

相似度 ≥ **0.6**（Healenium 的默认阈值）才给建议，并按 ≥0.8 高 / ≥0.7 中 / 其余低 标注置信度。
点一下就替换 XPath 输入框、选中节点并重新校验。

```text
//button[@id='login-btn']        →  //button[@id='login-button']        中 79%
  理由：标签仍为 <button>、@id 值近似：login-button
//button[text()='登录']           →  //button[text()='立即登录']          高 84%
  理由：标签仍为 <button>、文案接近
```

> 字符串相似度用 Sørensen–Dice 二元组 + token Jaccard + 包含加成：
> `login-btn` vs `login-button` ≈ 0.63（同一个按钮改了命名），
> `login-btn` vs `register-btn` ≈ 0.42（不相干）。
> 两边引擎（Python / JS）实现完全一致，`test_engine_parity.py` 会逐条比对。

## 🗂 项目结构

```
xpath_tool/
├── app/
│   ├── main.py           # 入口：启动服务 + 打开原生窗口/浏览器
│   ├── server.py         # 本地 HTTP 服务 + JSON API + WebSocket 升级
│   ├── ws_bridge.py      # 极简 WebSocket 服务端/客户端（RFC 6455 子集，纯标准库）
│   ├── xpath_engine.py   # 定位引擎（解析/校验/生成/评分/扫描/批量验证/自愈）
│   ├── extension_installer.py  # 扩展一键安装（浏览器探测 + 五种安装策略）
│   ├── crx.py            # 纯标准库 CRX3 签名 / 打包（RSA + SPKI + protobuf，无第三方依赖）
│   ├── policy_install.py # 企业策略安装（ExtensionInstallForcelist 读写，HKCU）
│   ├── ai_client.py      # OpenAI 兼容协议客户端
│   └── web/              # 前端界面（index.html / style.css / app.js）
├── extension/            # 浏览器扩展（Chrome / Edge MV3）
│   ├── manifest.json     # 扩展清单（storage / activeTab / tabs / scripting / <all_urls>）
│   ├── background.js     # Service Worker：快捷键、桌面版桥接代理
│   ├── content.js        # 元素拾取 + 页内高亮
│   ├── ui.js             # Shadow DOM 面板（样式隔离）
│   ├── lib/engine.js     # 定位引擎的 JS 版（与 Python 端语义一致）
│   └── icons/            # 扩展图标
├── tools/
│   ├── make_icon.py            # 图标生成（桌面版 + 扩展）
│   ├── smoke_test.py           # 端到端冒烟测试
│   ├── verify_exe.py           # 对打包后的 exe 做真实进程验证
│   ├── live_install_check.py   # 真机验证一键安装（会开浏览器，验证完自动关）
│   ├── shot_install_modal.py   # 无头 Chrome 渲染安装弹窗 + 量真实像素几何 + 出图
│   ├── test_ws_bridge.py       # WebSocket 帧编解码 + 端到端桥接测试
│   ├── test_engine_parity.py   # JS ↔ Python 引擎一致性交叉验证（含自愈）
│   ├── test_extension_static.py# 扩展静态一致性检查
│   ├── test_extension_installer.py  # 安装器单测（浏览器探测 / 策略解析）
│   ├── test_extension_permissions.py# 真机验证 host 权限是否够 executeScript
│   ├── test_crx.py             # CRX3 签名 / SPKI / 扩展 ID 推导单测
│   ├── test_policy_install.py  # 企业策略读写单测（假 winreg，不碰真实注册表）
│   ├── diag_inject_before_install.py # 复现「安装前打开的页面注入失败」并验证修复
│   ├── diag_persistence.py     # 验证 CDP loadUnpacked 是否跨重启持久
│   ├── test_panel_render.js    # jsdom 面板渲染断言
│   ├── test_content_pick.js    # jsdom 拾取流程断言（Ctrl+左键）
│   ├── test_exe_ui.js          # jsdom 桌面版前端桥接断言
│   ├── test_install_ui.js      # jsdom 一键安装弹窗断言
│   ├── test_heal_ui.js         # jsdom 自愈建议渲染断言
│   ├── test_modal_css.js       # jsdom 解析真实 CSS 级联，断言「安装扩展」弹窗布局
│   └── pack_extension.py       # 打包扩展到 zip
├── build.py              # PyInstaller 打包脚本
├── run.py                # 开发启动入口
└── requirements.txt
```

## 🔌 API 一览

服务默认从 `127.0.0.1:8790` 启动，端口被占用时顺延，仅本机可访问。

| 接口 | 说明 |
| --- | --- |
| `POST /api/parse` | 解析 HTML，返回 DOM 树与文档 token |
| `POST /api/validate` | 校验 XPath，返回匹配节点列表 |
| `POST /api/gen` | 按节点索引生成候选 XPath / CSS / Playwright 定位器 |
| `POST /api/nl` | 自然语言离线检索 |
| `POST /api/scan` | 扫描页面所有可交互元素及最佳定位器 |
| `POST /api/verify` | 批量验证定位器（失配项自动附 `heal` 自愈建议） |
| `POST /api/fetch` | 抓取远程页面源码 |
| `POST /api/ai` | 调用大模型生成 XPath（未传 `config` 时自动读取本机已保存配置） |
| `POST /api/ai/test` | 测试 AI 接口连通性 |
| `GET /api/config` | 读取本机 AI 配置（`apiKey` 以 `***` 掩码返回） |
| `POST /api/config` | 保存 AI 配置（合并写入；`apiKey` 传 `***` 表示保持原值） |
| `GET /ws` | **WebSocket** 实时通道（桌面版界面与浏览器扩展都连这里） |
| `POST /api/bridge/pick` | 通知扩展进入拾取模式（桌面版「抓取元素」按钮） |
| `POST /api/bridge/stop` | 通知扩展退出拾取模式 |
| `POST /api/bridge/result` | 扩展回传抓取结果（WebSocket 不可用时的 HTTP 兜底） |
| `GET /api/bridge/last` | 读取最近一次抓取结果 |
| `GET /api/extension/browsers` | 探测本机浏览器 + 推荐安装方式 + 扩展目录 |
| `POST /api/extension/install` | 一键安装扩展（`strategy` = `auto`/`flag`/`cdp`/`guided`/`policy`，`browser` 指定 key） |
| `POST /api/extension/open-folder` | 在资源管理器里打开扩展目录 |
| `POST /api/extension/policy-status` | 查询企业策略安装状态（扩展 ID / 策略位置 / 是否有副作用） |
| `POST /api/extension/policy-remove` | 只移除**本扩展**的策略条目（保留用户其它策略） |
| `GET /extension/update.xml` | 企业策略用的更新清单（`update_url` 指向这里） |
| `GET /extension/extension.crx` | 企业策略用的 CRX3 安装包（桌面版现签现发） |

> 桌面版保存的 AI 配置会落盘到 `~/.xpath_studio/config.json`，浏览器扩展桥接时可直接复用。

## 📝 快捷键

**桌面版**

- `Ctrl + Enter`：解析当前文档
- `Esc`：关闭弹窗

**浏览器扩展**

- `Alt + Shift + X`：呼出 / 收起定位面板
- `Alt + Shift + P`：进入 / 退出元素拾取模式
- **`Ctrl` + 左键**：拾取模式下选中元素（Mac 为 `Cmd`）
- `Esc`：取消拾取

---

技术栈：Python 3.10+ / lxml / cssselect / pywebview / 原生 HTML·CSS·JS（无前端框架）/ Chrome MV3 浏览器扩展。

## 版本管理

仓库包含桌面版源码、浏览器扩展、测试与构建脚本。`build/`、`dist/`、
`output/`、`outputs/`、本地工作记录、虚拟环境和密钥文件由 `.gitignore` 忽略。
`Agent.MD` / `AGENT.md` 等大小写变体也不会提交。

Windows 可执行文件和扩展 ZIP 可通过上述构建命令在本机生成。
AI 服务密钥属于个人配置，请通过应用界面设置，避免写入源码或提交到仓库。
