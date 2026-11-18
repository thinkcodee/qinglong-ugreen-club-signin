# 绿联 NAS 论坛签到 · 青龙面板版

**仓库**：[thinkcodee/qinglong-ugreen-club-signin](https://github.com/thinkcodee/qinglong-ugreen-club-signin)

把 [silence9527/MoviePilot-UgreenSignIn](https://github.com/silence9527/MoviePilot-UgreenSignIn) 改造成青龙面板可直接跑的签到脚本，带通知。

## 改了什么

原插件是 MoviePilot V3 插件，通过宿主的 Playwright 浏览器**点击「立即签到」按钮**完成签到。青龙容器里一般没有浏览器，所以这里把点击还原成了 HTTP 请求。

| | 原 MoviePilot 插件 | 本青龙脚本 |
| --- | --- | --- |
| 调度 | 宿主调度器 | 青龙定时任务 `0 8 * * *` |
| 签到 | 浏览器点击按钮 | Cookie + HTTP 直连，自动探测提交端点 |
| 状态判定 | 点击后 reload 复核 | 提交后**重新拉页复核**＋积分流水兜底，不把「请求已发出」当成功 |
| 积分信息 | 余额 / 今日积分 / 连续天数 | 一致，沿用原解析规则 |
| 通知 | MoviePilot 结构化渠道 | 青龙 notify.py → 青龙系统通知 → 11 种内置直推渠道 |
| Cookie | 插件配置页 | 青龙环境变量 `UGREEN_COOKIE` |
| 多账号 | 单账号 | 多 Cookie 顺序执行，汇总成一条通知 |
| 失败区分 | Cookie 失效 / 页面变化 / 签到失败 | 一致 |

保留原插件的三条底线：**必须复核持久化状态**、**明确区分失败原因**、**日志和通知里不出现 Cookie**。

> 说明：仓库里的签到页在未登录时只返回「抱歉，您尚未登录」，本次改造无法拿到登录后页面的真实按钮请求。脚本因此采用「自动探测 + 常见 Discuz 签到接口兜底 + 抓包手动指定 + Playwright 浏览器模式」四层保障，任何一层命中都会重新拉页复核后才判定成功。

## 文件

```
ugreen_signin.py          主脚本（单文件，放到青龙 scripts 目录即可）
tests/test_offline.py     离线自测（不联网、不需要真实 Cookie）
```

## 执行流程

脚本不会盲发签到请求，顺序是：

1. 拉取签到页，判断登录态与「今日是否已签到」；
2. **前置确认**：再用积分页当天的签到流水核对一次（按钮文案可能被缓存或改版，积分流水是持久化证据）；
3. 确认**已签到** → 直接读取积分余额、今日积分、连续天数，**一个签到请求都不发**；
4. 确认**未签到** → 探测端点并提交 → 重新拉页复核 → 读最新积分；
5. 若提交后页面文案没变，再用积分流水兜底复核一次，避免论坛改版误报失败。

> 只有第 4 步会产生签到请求；重复运行、已签到、按钮文案没变都不会重复提交。日志会明确打印「今日已签到，跳过提交」或「今日尚未签到，开始尝试签到」。

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

> ⚠️ **时区**：青龙的 cron 用的是**容器时区**，不是脚本内部时区。请在容器 / 青龙环境变量里设置 `TZ=Asia/Shanghai`，否则 `0 8 * * *` 会变成北京时间 16:00。脚本内部在未设置 `TZ` 时会自行按北京时间判断「今日」，但改不了 cron 的触发时刻。

## 获取 Cookie

1. 浏览器登录 <https://club.ugnas.com/>。
2. `F12 → Network`，刷新页面，选中 `club.ugnas.com` 的文档请求。
3. 在 `Request Headers` 里复制完整的 `Cookie` 值（不是其他请求头）。

Cookie 必须包含以 `_auth` 结尾的登录凭证，常见形式 `6LQh_2132_auth=...`，前缀可能变化。**多账号**用换行分隔（推荐）或 `&` 分隔：

```
6LQh_2132_saltkey=xxx; 6LQh_2132_auth=yyy; ...
6LQh_2132_saltkey=aaa; 6LQh_2132_auth=bbb; ...
```

Cookie 等同于账号登录态，不要提交到公开仓库或发到群里。脚本日志、异常、DEBUG 文件都不会写入请求头 Cookie。

## 环境变量

### 主配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `UGREEN_COOKIE` | **必填** | 论坛完整 Cookie，多账号换行分隔。兼容 `UGREEN_SIGNIN_COOKIE` / `UGREEN_COOKIES` |
| `UGREEN_SIGNIN_MODE` | `http` | `http` 纯 HTTP（默认）；`browser` 走 Playwright，逻辑与原插件一致 |
| `UGREEN_SIGNIN_NOTIFY` | `true` | 是否发送通知 |
| `UGREEN_SIGNIN_ONLY_FAIL` | `false` | 设为 `true` 时仅在失败时推送 |
| `UGREEN_SIGNIN_TIMEOUT` | `30` | HTTP 超时秒数（5–120） |
| `UGREEN_SIGNIN_SUBMIT_URL` | 空 | 抓包得到的真实签到接口，支持 `{formhash}` 占位符 |
| `UGREEN_SIGNIN_SUBMIT_BODY` | 空 | POST 表单体，格式 `k1=v1&k2=v2`，支持 `{formhash}` |
| `UGREEN_SIGNIN_METHOD` | 自动 | 强制 `GET` / `POST`，覆盖自动判断 |
| `UGREEN_SIGNIN_STRICT` | `false` | `true` 时禁用内置候选接口，只用页面探测结果 |
| `UGREEN_SIGNIN_CREDIT_VERIFY` | `true` | 用积分页**当天的签到流水**做前置状态确认与提交后兜底复核；设 `false` 完全关闭（退回只看按钮文案） |
| `UGREEN_SIGNIN_ALREADY_KEYWORDS` | 空 | 论坛改版后自定义「已签到」文案，逗号或竖线分隔，如 `今日已打卡,明天见` |
| `UGREEN_SIGNIN_DEBUG` | `false` | 打印每个端点的响应摘要、复核页状态，并把签到页 HTML 存成文件 |
| `UGREEN_SIGNIN_DEBUG_FILE` | 脚本同目录 `ugreen_signin_debug.html` | DEBUG 页面输出路径 |
| `UGREEN_SIGNIN_FORCE_DIRECT` | `false` | `true` 时跳过青龙 notify.py / 系统通知，只用内置直推 |
| `UGREEN_SIGNIN_UA` | 内置 Chrome UA | 自定义 User-Agent |
| `UGREEN_SIGNIN_SKIP_COOKIE_CHECK` | `false` | 跳过 `_auth` 校验（一般不用） |
| `UGREEN_SIGNIN_BROWSER_TIMEOUT` | `90` | browser 模式超时秒数 |
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

## 如果自动探测没签到成功

脚本按这个顺序找「立即签到」背后的请求：

1. 你手动配置的 `UGREEN_SIGNIN_SUBMIT_URL`（最可靠）
2. 按钮所在的 `<form>`：`action` / `method`，以及**全部具名控件**（隐藏域、提交按钮、单选、下拉、文本域，含 `formhash`）
3. 按钮的 `<a href>`
4. 按钮附近 JS / AJAX 里的 `plugin.php?...` 地址
5. 内置 Discuz「每日签到」(dsu_paulsign) 系接口：优先 `operation=qiandao` 的 **POST**（表单带 `qdxq` / `qdmode` / `todaysay` / `fastreply`），再试常见参数形态的 GET（`UGREEN_SIGNIN_STRICT=true` 可关闭）

**每一次提交后都会重新拉签到页复核**，页面变成「今日已签到」/「签到成功」等已签到状态才判成功；若论坛改版导致文案没变，脚本会再查一次积分页，**当天出现签到积分流水也算成功**。所有判定都基于持久化状态，候选接口不会造成重复签到。

> 仍然失败时设 `UGREEN_SIGNIN_DEBUG=true`：会打印每个端点的 HTTP 状态与响应片段、复核页状态、最后一次复核页文本，**并列出页面 HTML 里出现过的所有 `php` / `/api/` 地址**。把这段日志发出来即可定位真实接口；若日志显示「页面内没有 php/api 地址」，说明签到请求写在外部 JS 里，必须 F12 抓包。

如果日志出现「提交后未确认签到成功」，按下面抓一次包即可永久锁定接口：

1. 浏览器打开并登录 <https://club.ugnas.com/plugin.php?id=ugreen_checkin>，`F12 → Network` 勾选 `Preserve log`。
2. 点击「立即签到」，找到新出现的 `plugin.php?...` 请求。
3. 复制完整 **Request URL**，把里面 `formhash=` 的值换成 `{formhash}`，填到 `UGREEN_SIGNIN_SUBMIT_URL`。
4. 若该请求是 `POST`，同时设 `UGREEN_SIGNIN_METHOD=POST`，并把 **Form Data 里的全部字段**填到 `UGREEN_SIGNIN_SUBMIT_BODY`（同样用 `{formhash}` 占位）。提交按钮的 `name=value`、心情 `qdxq`、模式 `qdmode` 等一个都别漏——少一个服务端可能直接忽略这次请求。
5. 重跑任务。日志会显示「提交方式：手动指定」。

> 绿联的签到插件很可能是 Discuz「每日签到」系定制版，真实请求通常长这样：
> `POST plugin.php?id=ugreen_checkin:sign&operation=qiandao&inajax=1&infloat=1&formhash={formhash}`
> 表单体：`formhash={formhash}&qdxq=kx&qdmode=2&todaysay=&fastreply=1`（插件 id 与参数以你抓到的为准）。脚本已内置这类候选，一般无需手动配置。

也可设 `UGREEN_SIGNIN_DEBUG=true`，脚本会把签到页 HTML 存到 `ugreen_signin_debug.html`，方便查看按钮结构（文件可能含账号昵称，别公开发布）。

**终极兜底**：`UGREEN_SIGNIN_MODE=browser`，先在青龙装依赖：

```bash
pip install playwright
playwright install chromium
# 若报缺少系统库，再装 chromium 的系统依赖：playwright install-deps chromium
```

该模式完全复刻原插件的浏览器点击 + reload 复核流程，不依赖 HTTP 接口探测。

## 日志与排查

| 日志 / 通知原因 | 含义与处理 |
| --- | --- |
| `论坛登录已失效，请更新 Cookie` | 重新复制 Cookie；检查是否含 `*_auth` |
| `Cookie 中缺少登录凭证 *_auth` | 复制的是不完整 Cookie，重新取完整请求头 |
| `未识别到签到按钮，论坛页面结构可能已变化` | 开 `DEBUG` 导出页面，或改 `browser` 模式 |
| `提交后未确认签到成功` | 开 `DEBUG` 看端点响应；按上文抓包配置 `UGREEN_SIGNIN_SUBMIT_URL`（POST 别漏表单字段），或改 `browser` 模式 |
| `复核通过：积分页出现当日签到记录` | 签到其实成功了，只是页面文案已改版；可用 `UGREEN_SIGNIN_ALREADY_KEYWORDS` 补上新文案 |
| `积分页读取失败（不影响签到结果）` | 积分页结构变化，签到本身仍成功，通知里只省略积分行 |
| `未检测到可用的通知渠道` | 配置青龙 notify.py，或填任一推送变量 |
| `缺少 requests 依赖` | 青龙依赖管理 → Python3 → 添加 `requests` |

正常日志示例：

```
[08:00:02] 绿联社区签到开始 · 模式 http · 账号 1 个
[08:00:03] 默认账号 今日尚未签到，开始尝试签到
[08:00:03] 默认账号 共探测到 16 个候选签到端点（formhash：已获取）
[08:00:05] 默认账号 复核通过：今日已签到（提交方式：候选接口（第 1 个端点））
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

不需要联网、不需要真实 Cookie：

```bash
python -m unittest discover -s tests -v
```

覆盖：Cookie 校验、页面状态识别（含改版文案与自定义关键词）、formhash 提取、积分表格解析、四种端点探测方式、DSU POST 候选、表单具名控件、页面 URL 清单、前置状态确认（已签到不提交）、签到成功 / 今日已签到 / Cookie 失效 / 提交未确认 / 积分流水兜底复核、多账号通知文案。共 28 项。

## 注意

- 仅供自己的账号使用，遵守绿联社区的用户协议与积分规则。
- 原插件与本脚本均为非官方工具，论坛改版后签到接口可能变化。
- 上游插件仓库 [silence9527/MoviePilot-UgreenSignIn](https://github.com/silence9527/MoviePilot-UgreenSignIn) 为 MIT 许可；本改造沿用其状态判定与文案设计。
