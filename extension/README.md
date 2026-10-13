# XPath Studio · 浏览器扩展

在**真实网页**上直接拾取元素、生成稳健定位器，并把匹配到的节点**实时高亮**在页面上。

> 两种用法都支持：
> 1. **由桌面版驱动**（推荐）—— 桌面版点「抓取元素」，在浏览器里悬停高亮 + `Ctrl` 左键选中，
>    结果自动回传到桌面版。此时扩展**不弹面板**，只做助手。
> 2. **独立使用** —— 不装桌面版也能用：`Alt+Shift+X` 呼出面板，面板内完成校验 / 扫描 / 生成。
>
> 与桌面版共用同一套定位算法（已做逐项一致性交叉验证）。扩展**不联网**，
> 只会连接本机 `127.0.0.1` 上的桌面版。

## ✨ 功能

| 能力 | 说明 |
| --- | --- |
| **桌面版联动抓取** | 桌面版点「抓取元素」→ 页面上悬停**实时高亮** → **`Ctrl` + 左键**选中 → 定位器回传桌面版 |
| **元素拾取** | `Alt+Shift+P` 进入拾取模式，鼠标悬停实时高亮目标，`Ctrl` + 左键选中（`Esc` 取消） |
| **页面实时高亮** | 校验 XPath 后，页面上所有匹配节点即时描边高亮，选中目标为紫色，带序号角标 |
| **最短唯一 XPath** | Robula+ 思路：从绝对路径逐步削减前缀，得到既短又唯一的表达式 |
| **稳定祖先锚定** | 用稳定容器限定重复目标，跳过中间包装层；完整表达式必须唯一命中目标 |
| **稳定性评分** | 每条定位器给出 0–100 分与「稳定 / 一般 / 脆弱」评级 |
| **动态值识别** | JSF `j_idt88`、Vue `data-v-`、styled-components 哈希、UUID、裸哈希 class 自动降权并告警 |
| **测试属性优先** | `data-testid` / `data-test` / `data-cy` / `data-qa` **一律视为稳定**，即使值长得像哈希 |
| **表单标签锚定** | 控件没有稳定属性时，用 `<label>` 文案作锚点（`//label[normalize-space()='手机号']//input`） |
| **工具类不误杀** | Tailwind 的 `bg-red-500` / `text-2xl` / `rounded-full` 保留；`hover:` 这类状态变体剔除 |
| **多类型定位器** | 同时给出 XPath / CSS 选择器 / Playwright 定位器（`getByRole`、`getByTestId`…），点击即复制 |
| **匹配列表** | 列出所有匹配节点，点击可滚动定位 |
| **页面扫描** | 一键找出页面所有可交互元素及其最佳定位器 |
| **AI 生成**（可选） | 用自然语言描述元素，由本地桌面版调用大模型生成 |

> 拾取手势统一为 **`Ctrl` + 左键**（Mac 为 `Cmd`），避免误触页面上的链接和按钮。
> 拾取期间页面点击会被拦截，并显示操作提示条。

## 📦 安装（Chrome / Edge）

### 安装到现有浏览器（推荐）

装好桌面版后**不用手动找目录**：点桌面版右上角的连接状态胶囊（或「浏览器抓取」面板里的
**一键安装扩展**），在弹窗中默认选择 Chrome，点 **安装到现有浏览器**。桌面版打开扩展管理页并复制扩展目录；确认目标窗口和个人资料，开启开发者模式，点击「加载已解压的扩展程序」，粘贴目录完成加载。随后刷新要抓取的网页，并检测连接。

默认 `auto` / `guided` 使用**现有浏览器**；高级选项中的 `flag` / `cdp` 使用专用 `--user-data-dir` 启动**独立实例**，其中的扩展不会出现在日常浏览器里。企业策略另受管理环境限制。

| 方式 | 装到哪 | 持久 | 适用 |
| --- | --- | --- | --- |
| `--load-extension` + 独立 profile | 独立实例 | ❌ 仅本次会话 | Edge / Chromium / Brave / Chrome ≤136 |
| CDP `Extensions.loadUnpacked`（调试端口） | 独立实例 | ❌ 重启即失效 | **品牌版 Chrome ≥137**（该版本起静默忽略 `--load-extension`） |
| 引导安装（打开扩展页 + 复制目录到剪贴板） | **你现有的浏览器** | ✅ 手动加载后永久 | 全部浏览器兜底，最稳、无副作用 |
| 企业策略强制安装 | 目标为**你现有的浏览器** | ⚠️ 受环境限制 | Windows + Chrome / Edge / Brave / Chromium |

> **企业策略强制安装**会写一条当前用户注册表策略
> （`HKCU\...\Policies\<厂商>\<产品>\ExtensionInstallForcelist`），若被浏览器接受，启动时会自动从
> 桌面版拉取 `update.xml` 与 `.crx` 静默安装。**但它不保证成功**：写入 `HKCU` 这一步可能被安全策略
> 或安全软件**拒绝**（典型 `WinError 5 拒绝访问`），且**写入成功 ≠ 浏览器已接受策略 ≠ 扩展已安装**。
> **副作用**：浏览器会出现「由贵单位管理」横幅，且扩展无法在扩展管理页直接删除 —— 要用桌面版弹窗里的
> **「卸载策略」** 按钮移除。改完策略需**完全退出浏览器**再重开才可能生效。被拒绝时**不要绕过安全限制**，
> 改用引导安装或在受管环境联系管理员。

### 手动安装

1. 打开 `chrome://extensions/`（Edge 为 `edge://extensions/`）
2. 右上角开启 **开发者模式**
3. 点击 **加载已解压的扩展程序**，选择扩展目录
   （源码运行是项目里的 `extension/`；打包后桌面版会把它释放到
   `%LOCALAPPDATA%\XPathStudio\extension` 并复制路径到剪贴板）
4. 完成后会打开欢迎页；把扩展图标固定到工具栏更方便使用

> 也可直接使用打包好的 `xpath-studio-extension.zip`（解压后按上述步骤加载）。

## 🚀 使用

### 桌面 XPath 工作台同步高亮（1.3.0）

抓取并确认元素后，在桌面工作台编辑 XPath，点击“校验”或按 Enter。
扩展在原标签页的原文档中实时校验并高亮匹配元素，自动滚动到首个匹配；
多节点会同时描边，零匹配或无效表达式会清除旧高亮。桌面“清空”也会清除浏览器高亮。

iframe 抓取会在对应框架内校验；切换标签不会改换目标。原页面刷新、关闭或扩展重启后，
请重新抓取。桌面版已移除数据源、DOM 树与离线面板，不再通过整页 HTML 快照校验。

### 方式一：由桌面版驱动（推荐）

1. 启动桌面版 **XPath Studio**，点右上角 **「抓取元素」**。
2. 切到浏览器，鼠标移到目标元素上 —— 页面上会实时高亮并显示元素描述。
3. 用 **↑ / ↓** 在当前元素及其祖先链上切换；**Ctrl（Mac 为 Cmd）＋左键**锁定目标，预览 XPath 后点击「确认抓取」或按 Enter，结果才会回传。
4. 锁定卡片支持父元素、返回子元素和重新选择；`Esc` 取消整次抓取。
5. 1.2.0 支持有访问权限的跨域 iframe：启动时枚举该标签页框架并逐一启用，确认/取消统一清理。动态新建或导航后的框架请重新开始抓取。
6. 框架内生成的 XPath/CSS/Playwright 是**框架局部定位器**。桌面版显示来源 URL、frameId、顶层页面，并提示先切换框架；目前不会生成可跨重启复用的完整 frameLocator 链。

> 这条链路走 WebSocket 长连接（`ws://127.0.0.1:<端口>/ws`）；连接断了会自动重连，
> 并且每 30 秒兜底检查一次。桌面版界面右上角会显示「扩展已连接 / 等待扩展…」。

### 方式二：在浏览器里独立使用

| 操作 | 方式 |
| --- | --- |
| 开关面板 | 点击工具栏图标 / `Alt+Shift+X` |
| 元素拾取 | `Alt+Shift+P` 或点面板上的 **◎** |
| 选中元素 | **`Ctrl` + 左键**（Mac 为 `Cmd`） |
| 取消拾取 | `Esc` |
| 校验 XPath | 在面板输入框回车，或点「校验」 |
| 复制定位器 | 点击任意候选条目（CSS / Playwright 同样点击即复制） |

快捷键可在 `chrome://extensions/shortcuts` 中修改。

## 🤖 关于 AI 生成（可选）

扩展本身**完全离线可用**。若想用自然语言生成 XPath：

1. 启动桌面版 **XPath Studio**（默认监听 `http://127.0.0.1:8790`）
2. 在桌面版右上角「AI 设置」里填好模型接口并保存（会写入本机 `~/.xpath_studio/config.json`）
3. 回到扩展面板的 **AI** 标签页，点「测试」确认连通，然后输入描述生成

> 说明：浏览器扩展的后台 Service Worker 才能跨域访问本机服务，因此请求由后台代发；
> 桌面版只监听 `127.0.0.1`，不对外开放。

## 🔒 隐私

- 扩展**不发送任何数据到外部服务器**，所有定位计算都在你的浏览器本地完成。
- 权限：`storage`（存面板状态）/ `activeTab`（点图标时访问当前页）/ `tabs`（读标签页 URL 以便
  给出可读的失败提示）/ `scripting`（兜底补注入内容脚本）/ `alarms`（保活与重连）/
  `webNavigation`（枚举抓取标签页的框架，定向投递消息）。
- `host_permissions` 含 `<all_urls>`，另有 `ws://127.0.0.1/*` / `ws://localhost/*`。
  - **为什么需要 `<all_urls>`**：扩展要能在**任意网页**上拾取元素。而 MV3 里
    `content_scripts.matches` 只决定「页面打开时自动注入」，**不授予程序化注入权限**。
    当页面是在扩展加载**之前**打开的，就需要 `chrome.scripting.executeScript` 兜底补注入 ——
    这一步必须有 host 权限，否则报
    `Cannot access contents of the page. Extension manifest must request permission to access the respective host.`
  - 这只是**权限声明**，扩展**不会**主动把页面内容发往任何外部地址；数据只在
    「你点了拾取」时回传给本机桌面版。
- `file://` 页面还需在扩展详情页手动开启 **「允许访问文件网址」**（浏览器安全限制，无法由扩展自动开启）。
- `chrome://` / `edge://` / `about:` / 扩展商店等内置页面**永远无法注入**（浏览器硬限制），
  扩展会提前拦截并给出中文提示，不会抛异常。
- 内容脚本需要注入页面才能拾取元素，因此匹配 `http/https/file` 页面，但**只读取当前页 DOM 用于本地计算**。
- 使用「桌面版联动抓取」时，会把你选中的元素 HTML 与**整页 HTML（上限 200 KB）**
  通过本机 WebSocket 发给桌面版，用于在桌面版里生成定位器与进一步分析。**数据不出本机**。
- 如需在 `file://` 本地文件页使用，请在扩展详情页开启「允许访问文件网址」。
- 浏览器内置页面（`chrome://`、扩展商店等）禁止注入脚本，面板不可用。

## 🧪 测试

扩展无法在无桌面环境自动启动浏览器，因此用以下多层测试覆盖：

```bash
# 1) 引擎一致性：JS 引擎 vs 桌面版 Python 引擎，同一 HTML 逐项比对
python tools/test_engine_parity.py

# 2) 面板渲染：Node + jsdom 真实构建 Shadow DOM 面板并断言渲染结果
node tools/test_panel_render.js

# 3) 拾取流程：jsdom 里跑 start-pick -> 悬停高亮 -> Ctrl+左键 -> 回传负载
node tools/test_content_pick.js

# 4) 静态一致性：manifest 文件引用、权限、消息 type、导出与回调对接、WS 桥接
python tools/test_extension_static.py

# 5) 桥接联调：WebSocket 帧编解码 + Node 原生 WebSocket 客户端 <-> 桌面版服务
python tools/test_ws_bridge.py

# 6) 桌面版前端：jsdom 加载 index.html + app.js，验证连接状态与抓取结果渲染
node tools/test_exe_ui.js

# 7) 真机权限：起无头 Chrome 加载扩展，在 Service Worker 里真跑一次
#    chrome.scripting.executeScript，确认 host 权限真的够（不是只看声明）
python tools/test_extension_permissions.py

# 8) 回归复现：先在目标页「安装前」打开，再加载扩展，验证兜底补注入仍成功
python tools/diag_inject_before_install.py
```

> 第 7、8 项是这次修 `Cannot access contents of the page` 时补的：**静态检查 manifest 不够**，
> 因为 `chrome.permissions.contains()` 对 `content_scripts.matches` 覆盖的来源也会返回 `true`，
> 但 `executeScript` 照样失败。只有真的跑一次 `executeScript` 才算验证。
>
> 另外，**别用 `window.__XPS_CONTENT_LOADED__` 这类全局变量判断「扩展装没装上」**：内容脚本跑在
> isolated world，CDP 的 `Runtime.evaluate` 在主世界看不到它，会误判成「没装」。可靠做法是枚举
> `chrome://extensions` 的 Shadow DOM（`extensions-manager` → `extensions-item-list` →
> `extensions-item` → `#name`）。

## 📁 结构

```
extension/
├── manifest.json      # MV3 清单（storage / activeTab / tabs / scripting / alarms / <all_urls>）
├── background.js      # Service Worker：图标/快捷键、WebSocket 长连接、AI 代理
├── content.js         # 内容脚本：拾取器（Ctrl+左键）、独立高亮覆盖层、结果回传
├── ui.js              # 面板 UI（Shadow DOM 隔离样式，可静默挂载）
├── lib/engine.js      # 定位引擎（Python 版的浏览器移植）
├── welcome.html       # 安装后引导页
└── icons/             # 16/32/48/128 图标
```

### 覆盖层为什么要独立

拾取/高亮用的覆盖层是**独立**于面板的 Shadow DOM 宿主（`#__xpath_studio_overlay__`），
不依赖面板是否打开。这样桌面版驱动抓取时可以完全不弹面板，
同时高亮、提示条、尺寸角标仍然正常工作。
