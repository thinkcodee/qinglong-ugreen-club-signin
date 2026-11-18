# 绿联 NAS 论坛签到 · 青龙面板版

**仓库**：[thinkcodee/qinglong-ugreen-club-signin](https://github.com/thinkcodee/qinglong-ugreen-club-signin)

把 [silence9527/MoviePilot-UgreenSignIn](https://github.com/silence9527/MoviePilot-UgreenSignIn) 改造成青龙面板可直接跑的签到脚本，带通知。

## 改了什么

原插件是 MoviePilot V3 插件，通过宿主的 Playwright 浏览器**点击「立即签到」按钮**完成签到。青龙容器里一般没有浏览器，所以这里把点击还原成了 HTTP 请求。**签到接口已按浏览器 F12 抓包确认并内置为默认端点，无需额外配置即可命中。**

| | 原 MoviePilot 插件 | 本青龙脚本 |
| --- | --- | --- |
| 调度 | 宿主调度器 | 青龙定时任务 `0 8 * * *` |
| 签到 | 浏览器点击按钮 | `http` 模式：Cookie + HTTP 直连；`browser` 模式：浏览器会话内提交同一接口 |
| 状态判定 | 点击后 reload 复核 | 提交后**重新拉页复核**＋积分流水兜底，不把「请求已发出」当成功 |
| 积分信息 | 余额 / 今日积分 / 连续天数 | 一致，沿用原解析规则 |
| 通知 | MoviePilot 结构化渠道 | 青龙 notify.py → 青龙系统通知 → 11 种内置直推渠道 |
| Cookie | 插件配置页 | 青龙环境变量 `UGREEN_COOKIE` |
| 多账号 | 单账号 | 多 Cookie 顺序执行，汇总成一条通知 |
| 失败区分 | Cookie 失效 / 页面变化 / 签到失败 | 一致 |

两种运行模式 `http`（默认）与 `browser`（可选）**共用同一套官方接口、状态判定、积分流水复核、积分解析与通知**，区别只在于由谁发出那个请求。

保留原插件的三条底线：**必须复核持久化状态**、**明确区分失败原因**、**日志和通知里不出现 Cookie**。

> 早期版本只能靠猜测 Discuz 签到接口，实测 19 个候选端点全部落空；现已按真实抓包结果锁定接口（见下节），猜测候选降级为「官方接口失效时的兜底」，可用 `UGREEN_SIGNIN_STRICT=true` 完全关闭。

## 真实签到接口（已抓包确认）

浏览器登录后打开签到页，F12 → Network → 勾选 `Preserve log` → 点击绿色「立即签到」，捕获到的请求形态：

```http
POST https://club.ugnas.com/plugin.php?id=ugreen_checkin&action=sign
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest
Origin: https://club.ugnas.com
Referer: https://club.ugnas.com/plugin.php?id=ugreen_checkin

checkinsubmit=yes&formhash={formhash}
```

几个容易踩坑的点，脚本已按此实现：

- **`action=sign`，不是 `ac=sign` / `do=sign` / `operation=qiandao`** —— 这也是早期猜测端点全军覆没的原因。
- **必须是 POST**，且 `checkinsubmit=yes` 在**表单体**里；URL 上不带 `formhash`。
- `formhash` 每次登录会话都不同，由脚本从签到页 `<input name="formhash">` 实时提取，**不能写死**。
- 这是 AJAX 提交，需要带 `X-Requested-With` / `Origin`；响应内容不作为成功依据，仍以重新拉页复核为准。

两种模式都默认第一个请求就是它，命中后立刻停止，**不会**继续打后面的兜底端点。仓库和日志里不包含任何真实 Cookie 或 formhash 值。

## 文件

```
ugreen_signin.py          主脚本（单文件，放到青龙 scripts 目录即可）
tests/test_offline.py     离线自测（不联网、不需要真实 Cookie、不需要 chromium）
```

## 执行流程

以下流程对 `http` / `browser` 两种模式完全一致，差别只在第 4 步「由谁提交请求」：

1. 拉取签到页，判断登录态与「今日是否已签到」；
2. **前置确认**：再用积分页当天的签到流水核对一次（按钮文案可能被缓存或改版，积分流水是持久化证据）；
3. 确认**已签到** → 直接读取积分余额、今日积分、连续天数，**一个签到请求都不发**；
4. 确认**未签到** → 首选 POST 官方接口提交 → 重新拉页复核 → 读最新积分；
5. 若提交后页面文案没变，再用积分流水兜底复核一次，避免论坛改版误报失败；
6. 官方接口万一失效：`http` 模式依次尝试剩余候选端点；`browser` 模式降级为点击「立即签到」按钮。

> 只有第 4 步会产生签到请求；重复运行、已签到、按钮文案没变都不会重复提交。日志会明确打印「今日已签到，跳过提交」或「今日尚未签到，开始尝试签到」。状态识别同时支持「立即签到」按钮和「今天还没有签到」文案。

## 快速开始

1. **依赖**：青龙 `依赖管理 → Python3 → 新建依赖` 填 `requests`（大多数青龙镜像已自带）。缺依赖时脚本会明确提示，不会静默失败。
2. **放脚本**：在 `脚本管理` 新建 `ugreen_signin.py` 并粘贴主脚本内容（推荐，私有仓库也无需额外鉴权）。

   仓库地址：<https://github.com/thinkcodee/qinglong-ugreen-club-signin>

   若仓库设为公开，也可用订阅管理拉取 raw 链接：`https://raw.githubusercontent.com/thinkcodee/qinglong-ugreen-club-signin/main/ugreen_signin.py`；私有仓库的 raw 链接需要鉴权，青龙订阅通常拉不到，直接粘贴文件内容最省事。
3. **配 Cookie**：`环境变量 → 新建变量`，名称 `UGREEN_COOKIE`，值填论坛完整 Cookie。
4. **建任务**：`定时任务 → 新建任务`
   - 名称：`绿联社区签到`
   - 命令：`task ugreen_signin.py`
   - 定时规则：`0 8 * * *`
5. **手动运行一次**，看日志和通知是否正常。

默认就是 `http` 模式，以上五步即可跑通。可选：设 `UGREEN_SIGNIN_STRICT=true`，端点列表会从 17 个精简到「官方接口 + 页面探测」的几个，失败时也只打少量请求，更快更安全（官方接口**不受** strict 影响）。若要改用浏览器模式，见下一章。

> ⚠️ **时区**：青龙的 cron 用的是**容器时区**，不是脚本内部时区。请在容器 / 青龙环境变量里设置 `TZ=Asia/Shanghai`，否则 `0 8 * * *` 会变成北京时间 16:00。脚本内部在未设置 `TZ` 时会自行按北京时间判断「今日」，但改不了 cron 的触发时刻。

## browser 模式（可选）

设 `UGREEN_SIGNIN_MODE=browser` 即启用。它不是简单地"用浏览器点按钮"——**仍然提交同一个抓包确认的官方接口**，只是把请求交给已登录的浏览器上下文发出，因此 Cookie / Origin / Referer / Sec-Fetch-* 等请求头由浏览器自动生成，最贴近真实点击；接口失败时才降级为点击按钮。

### 什么时候用

| | `http`（默认） | `browser` |
| --- | --- | --- |
| 额外依赖 | 无（只要 `requests`） | `playwright` + chromium 浏览器 |
| 单次耗时 / 内存 | 秒级 / 极小 | 约 10–30 秒 / 200MB+ |
| 请求来源 | Python 会话手动带 Cookie | 浏览器同源 `fetch()`，头部最真实 |
| 提交端点 | 官方接口首选，失败继续试其余候选 | 官方接口首选，失败改为点击按钮 |
| 复核 / 积分 / 通知 | 完全一致 | 完全一致 |
| 适用场景 | **日常默认推荐** | http 被风控、论坛接口改版、想完全复刻真实浏览器 |

### 安装依赖

在**青龙容器内部**执行（宿主机上装不算）：

```bash
pip install playwright
playwright install chromium
# 若启动报缺少 libnss3 / libatk 等系统库（Debian/Ubuntu 基础镜像）：
playwright install-deps chromium
```

`pip install playwright` 可以在青龙「依赖管理 → Python3」里加；但 `playwright install chromium` 需要进容器终端：

```bash
docker exec -it qinglong bash -c "playwright install chromium"
```

不方便进容器时，也可以在青龙「定时任务」里临时建一个命令为 `playwright install chromium` 的任务手动跑一次，成功后删掉即可。

### 配置

| 变量 | 值 | 说明 |
| --- | --- | --- |
| `UGREEN_SIGNIN_MODE` | `browser` | 切换到浏览器模式 |
| `UGREEN_COOKIE` | 不变 | 仍必填，脚本把它注入浏览器 context |
| `UGREEN_SIGNIN_BROWSER_TIMEOUT` | `90` | 页面加载 / 元素等待超时秒数（30–180） |
| `UGREEN_SIGNIN_STRICT` | `true` | 建议开启，端点列表只留官方接口 + 页面探测 |
| `UGREEN_SIGNIN_DEBUG` | `true` | 排查时开启，导出签到页 HTML 并打印接口响应 |

其余变量（通知、`CREDIT_VERIFY`、`ALREADY_KEYWORDS`、`SUBMIT_URL` / `SUBMIT_BODY` / `METHOD`、`UA` 等）**两种模式通用**，含义见下方环境变量表。若配置了 `UGREEN_SIGNIN_SUBMIT_URL`，`browser` 模式同样会优先使用它（在浏览器里以 `fetch` 发出）。

### 工作原理

1. 用 `UGREEN_COOKIE` 建一个 headless chromium 上下文（自动带 `--no-sandbox --disable-dev-shm-usage`，容器 root 运行必需）。
2. 打开签到页 → `read_state` 判状态 → 积分页当天流水做前置确认；已签到则直接读积分、不发请求。
3. 回到签到页，取最新 `formhash`，在**页面上下文**执行同源 `fetch()` 提交官方接口；`UGREEN_SIGNIN_DEBUG=true` 会打印 HTTP 状态与响应片段。
4. 若 `fetch` 抛异常或返回非 2xx/3xx，依次尝试 `button` / `a` / `[role=button]` / `text=立即签到` 四种选择器点击按钮。
5. `reload` 复核「今日已签到」；文案没变时查积分页当天签到流水兜底；两者都认不出才判失败。
6. 读余额 / 今日积分 / 连续天数，走与 `http` 模式完全相同的通知渠道。

浏览器里所有页面统一走 `html_to_text()`，因此状态判定、`parse_credit_text`、`parse_streak` 与 `http` 模式共用同一套规则，不会出现"浏览器模式认不出页面"的情况。

正常日志示例：

```
[08:00:02] 绿联社区签到开始 · 模式 browser · 账号 1 个
[08:00:04] 默认账号 今日尚未签到，开始尝试签到（browser）
[08:00:04] 默认账号 选用端点：官方接口 · POST（formhash：已获取）
[08:00:05] 默认账号 已提交签到请求（官方接口）
[08:00:06] 默认账号 复核通过：今日已签到（browser 模式 · 官方接口）
[08:00:07] ✅ 默认账号 · 签到成功 · 余额 78 · 今日 +1 · 连续 3 天
[08:00:08] 签到结束：成功/已签到 1 个，失败 0 个
```

接口提交失败而按钮点击成功时，`extra` 会显示 `browser 模式 · 点击按钮`；页面文案没变但积分流水确认时会显示 `browser 模式 · 官方接口 · 积分记录确认`。

### 注意事项

- 多账号时**每个账号各起一个浏览器 context**，串行执行；账号多或容器内存小（< 1GB）时建议仍用 `http` 模式。
- chromium 首次下载约 150MB，且需要容器有对应系统库；镜像精简、无法装依赖时 `http` 模式更省事。
- 浏览器模式固定 headless，不依赖任何桌面环境或 `DISPLAY`。
- 私有仓库的 raw 订阅拉不到，脚本仍需在青龙「脚本管理」里粘贴，与模式无关。

## 获取 Cookie

1. 浏览器登录 <https://club.ugnas.com/>。
2. `F12 → Network`，刷新页面，选中 `club.ugnas.com` 的文档请求。
3. 在 `Request Headers` 里复制完整的 `Cookie` 值（不是其他请求头）。

Cookie 必须包含以 `_auth` 结尾的登录凭证，常见形式 `6LQh_2132_auth=...`，前缀可能变化。**多账号**用换行分隔（推荐）或 `&` 分隔：

```
6LQh_2132_saltkey=xxx; 6LQh_2132_auth=yyy; ...
6LQh_2132_saltkey=aaa; 6LQh_2132_auth=bbb; ...
```

Cookie 等同于账号登录态，不要提交到公开仓库、贴到聊天里或发到群里。脚本日志、异常、DEBUG 文件都不会写入请求头 Cookie。

> ⚠️ 如果 Cookie 曾经明文出现在聊天、截图或日志里，请到论坛**退出登录后重新登录**（必要时改密码），让旧会话立即失效，再重新复制一份填进青龙。

## 环境变量

### 主配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `UGREEN_COOKIE` | **必填** | 论坛完整 Cookie，多账号换行分隔。兼容 `UGREEN_SIGNIN_COOKIE` / `UGREEN_COOKIES` |
| `UGREEN_SIGNIN_MODE` | `http` | `http` 纯 HTTP（默认）；`browser` 浏览器会话提交，见上章 |
| `UGREEN_SIGNIN_NOTIFY` | `true` | 是否发送通知 |
| `UGREEN_SIGNIN_ONLY_FAIL` | `false` | 设为 `true` 时仅在失败时推送 |
| `UGREEN_SIGNIN_TIMEOUT` | `30` | HTTP 模式超时秒数（5–120） |
| `UGREEN_SIGNIN_BROWSER_TIMEOUT` | `90` | browser 模式页面 / 元素超时秒数（30–180） |
| `UGREEN_SIGNIN_SUBMIT_URL` | 空 | **仅论坛改版时需要**：覆盖签到接口，支持 `{formhash}` 占位符；两种模式通用 |
| `UGREEN_SIGNIN_SUBMIT_BODY` | 空 | 同上，POST 表单体 `k1=v1&k2=v2`，支持 `{formhash}` |
| `UGREEN_SIGNIN_METHOD` | 自动 | 强制 `GET` / `POST`，覆盖自动判断（官方接口默认是 POST） |
| `UGREEN_SIGNIN_STRICT` | `false` | `true` 时禁用猜测候选接口，**官方接口与页面探测仍保留**（推荐开启） |
| `UGREEN_SIGNIN_CREDIT_VERIFY` | `true` | 用积分页**当天的签到流水**做前置状态确认与提交后兜底复核；设 `false` 完全关闭（退回只看按钮文案） |
| `UGREEN_SIGNIN_ALREADY_KEYWORDS` | 空 | 论坛改版后自定义「已签到」文案，逗号或竖线分隔，如 `今日已打卡,明天见` |
| `UGREEN_SIGNIN_DEBUG` | `false` | 打印每个端点的响应摘要、复核页状态，并把签到页 HTML 存成文件 |
| `UGREEN_SIGNIN_DEBUG_FILE` | 脚本同目录 `ugreen_signin_debug.html` | DEBUG 页面输出路径 |
| `UGREEN_SIGNIN_FORCE_DIRECT` | `false` | `true` 时跳过青龙 notify.py / 系统通知，只用内置直推 |
| `UGREEN_SIGNIN_UA` | 内置 Chrome UA | 自定义 User-Agent（两种模式通用） |
| `UGREEN_SIGNIN_SKIP_COOKIE_CHECK` | `false` | 跳过 `_auth` 校验（一般不用） |
| `UGREEN_SIGNIN_WEBHOOK` | 空 | 自定义 Webhook，POST JSON `{title, content, text}` |

### 通知配置（按需任选）

通知优先级：**青龙 `notify.py` → 青龙系统通知 API → 内置直推渠道**。前一层成功即停止，不会重复推送；若青龙 `notify.py` 存在但没配渠道导致收不到，设 `UGREEN_SIGNIN_FORCE_DIRECT=true` 强制走内置直推。

青龙系统通知：`QL_TOKEN`，或 `QL_CLIENT_ID` + `QL_CLIENT_SECRET`（可选 `QL_URL`，默认 `http://127.0.0.1:5700`）。

内置直推渠道（配了对应变量就自动启用，各渠道互不影响）：

| 渠道 | 变量 |
| --- | --- |
| PushPlus | `PUSHPLUS_TOKEN` / `PUSH_PLUS_TOKEN` |
| Server酱 | `SCKEY` / `SERVERCHAN_SCKEY` / `PUSH_KEY` |
| 企业微信群机器人 | `QYWX_KEY` |
| 企业微信应用 | `QYWX_AM` = `corpid,corpsecret,touser,agentid` |
| Telegram | `TG_BOT_TOKEN` + `TG_USER_ID`，可选 `TG_API_HOST` |
| Bark | `BARK_URL` / `BARK` |
| 钉钉 | `DD_BOT_TOKEN`，可选 `DD_BOT_SECRET` |
| 飞书 | `FSKEY` |
| Gotify | `GOTIFY_URL` + `GOTIFY_TOKEN` |
| ntfy | `NTFY_URL` + `NTFY_TOPIC` |
| 自定义 Webhook | `UGREEN_SIGNIN_WEBHOOK` |

通知文案沿用原插件排版，例如：

```
绿联社区签到 · +1 积分 · 余额 78
────────────
✅ 状态　签到成功
💰 本次　+1 积分
🏅 余额　78 积分
🔥 连续　3 天
🕘 时间　11-16 08:00
────────────
再签 4 天可得 +5 积分
```

## 接口改版时怎么办

官方接口已内置，日常无需任何手动配置。若论坛改版导致它失效，脚本按这个顺序兜底：

1. 你手动配置的 `UGREEN_SIGNIN_SUBMIT_URL`（设了就独占端点列表）
2. **抓包确认的官方接口** `POST plugin.php?id=ugreen_checkin&action=sign`（默认首选，严格模式也保留）
3. 按钮所在的 `<form>`：`action` / `method`，以及**全部具名控件**（隐藏域、提交按钮、单选、下拉、文本域，含 `formhash`）
4. 按钮的 `<a href>`
5. 页面 JS / AJAX 里的 `plugin.php?...` 地址
6. 内置 Discuz「每日签到」(dsu_paulsign) 系猜测候选：`operation=qiandao` 的 POST + 常见参数形态的 GET（`UGREEN_SIGNIN_STRICT=true` 可关闭）；`browser` 模式不走这一步，改为点击按钮

**每一次提交后都会重新拉签到页复核**，页面变成「今日已签到」/「签到成功」等已签到状态才判成功；若论坛改版导致文案没变，脚本会再查一次积分页，**当天出现签到积分流水也算成功**。所有判定都基于持久化状态，兜底端点不会造成重复签到。

> 仍失败时设 `UGREEN_SIGNIN_DEBUG=true`：会打印每个端点的 HTTP 状态与响应片段、复核页状态、最后一次复核页文本，**并列出页面 HTML 里出现过的所有 `php` / `/api/` 地址**。把这段日志发出来即可定位新接口。

重新抓包锁定新接口的方法：

1. 浏览器打开并登录 <https://club.ugnas.com/plugin.php?id=ugreen_checkin>，`F12 → Network` 勾选 `Preserve log`。
2. 点击「立即签到」，找到新出现的 `plugin.php?...` 请求。
3. 复制完整 **Request URL**，把里面 `formhash=` 的值换成 `{formhash}`，填到 `UGREEN_SIGNIN_SUBMIT_URL`。
4. 若该请求是 `POST`，同时设 `UGREEN_SIGNIN_METHOD=POST`，并把 **Form Data 里的全部字段**填到 `UGREEN_SIGNIN_SUBMIT_BODY`（同样用 `{formhash}` 占位）。提交按钮的 `name=value` 等一个都别漏——少一个服务端可能直接忽略这次请求。
5. 重跑任务。日志会显示「提交方式：手动指定」（browser 模式显示「选用端点：手动指定」）。

> 注意：`formhash` 是会话级令牌，抓包里的值**不要**写进环境变量，交给脚本从页面实时提取即可。分享抓包内容时记得删掉 `Cookie` 请求头。

也可设 `UGREEN_SIGNIN_DEBUG=true`，脚本会把签到页 HTML 存到 `ugreen_signin_debug.html`，方便查看按钮结构（文件可能含账号昵称，别公开发布）。不想抓包时，切 `UGREEN_SIGNIN_MODE=browser` 让浏览器点击按钮也是一条现成的兜底路径，见「browser 模式」一章。

## 日志与排查

| 日志 / 通知原因 | 含义与处理 |
| --- | --- |
| `论坛登录已失效，请更新 Cookie` | 重新复制 Cookie；检查是否含 `*_auth` |
| `Cookie 中缺少登录凭证 *_auth` | 复制的是不完整 Cookie，重新取完整请求头 |
| `未识别到签到按钮，论坛页面结构可能已变化` | 开 `DEBUG` 导出页面，或改 `browser` 模式 |
| `提交后未确认签到成功（官方接口已尝试）` | 开 `DEBUG` 看响应片段：多为 Cookie 失效或接口改版；按上文重新抓包，或改 `browser` 模式 |
| `复核通过：积分页出现当日签到记录` | 签到其实成功了，只是页面文案已改版；可用 `UGREEN_SIGNIN_ALREADY_KEYWORDS` 补上新文案 |
| `积分页读取失败（不影响签到结果）` | 积分页结构变化，签到本身仍成功，通知里只省略积分行 |
| `browser 模式需要 playwright` | 青龙依赖管理 → Python3 → 添加 `playwright` |
| `浏览器启动失败：未下载 chromium` | 容器内执行 `playwright install chromium`（缺系统库再加 `playwright install-deps chromium`） |
| `浏览器签到异常：... libnss3 / libatk ...` | 缺系统库，执行 `playwright install-deps chromium` |
| `接口未提交成功，且未找到「立即签到」按钮` | 论坛页面结构大改，开 `DEBUG` 导出页面重新确认按钮文案 |
| `未检测到可用的通知渠道` | 配置青龙 notify.py，或填任一推送变量 |
| `缺少 requests 依赖` | 青龙依赖管理 → Python3 → 添加 `requests` |

正常日志示例（`http` 模式 + `UGREEN_SIGNIN_STRICT=true` 时只有 1 个端点）：

```
[08:00:02] 绿联社区签到开始 · 模式 http · 账号 1 个
[08:00:03] 默认账号 今日尚未签到，开始尝试签到
[08:00:03] 默认账号 共 1 个提交端点（首选：官方接口｜formhash：已获取）
[08:00:05] 默认账号 复核通过：今日已签到（提交方式：官方接口（第 1 个端点））
[08:00:06] ✅ 默认账号 · 签到成功 · 余额 78 · 今日 +1 · 连续 3 天
[08:00:07] 签到结束：成功/已签到 1 个，失败 0 个
```

已签到时完全不发请求：

```
[08:00:03] 默认账号 今日已签到，跳过提交，直接读取积分与连续天数
[08:00:04] ✅ 默认账号 · 今日已签到 · 余额 78 · 今日 +1 · 连续 3 天
```

有账号失败时脚本退出码为 `1`，方便青龙任务日志识别。

## 离线自测

不需要联网、不需要真实 Cookie、不需要 chromium（用假的 playwright 模块驱动真实流程）：

```bash
python -m unittest discover -s tests -v
```

覆盖：Cookie 校验、页面状态识别（含「今天还没有签到」与自定义关键词）、formhash 提取、积分表格解析、官方接口形态与请求头、四种端点探测方式、DSU POST 候选、表单具名控件、页面 URL 清单、前置状态确认（已签到不提交）、签到成功 / 今日已签到 / Cookie 失效 / 提交未确认 / 积分流水兜底复核、**browser 模式（官方接口提交、已签到、前置确认、点击按钮兜底、非 2xx 回退、缺 chromium 提示、手动端点、缺依赖）**、多账号通知文案。共 **45 项**。

## 注意

- 仅供自己的账号使用，遵守绿联社区的用户协议与积分规则。
- 原插件与本脚本均为非官方工具，论坛改版后签到接口可能变化。
- Cookie 与 Token 属于账号凭据，切勿提交到仓库或公开分享。
- 上游插件仓库 [silence9527/MoviePilot-UgreenSignIn](https://github.com/silence9527/MoviePilot-UgreenSignIn) 为 MIT 许可；本改造沿用其状态判定与文案设计。
