#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绿联 NAS 社区每日签到 · 青龙面板版

改造自 https://github.com/silence9527/MoviePilot-UgreenSignIn
原插件依赖 MoviePilot V3 的 Playwright 浏览器点击；青龙容器里通常没有浏览器，
因此本脚本默认改为「Cookie + HTTP 直连」：

    拉取签到页 → 用积分页当天签到流水前置确认状态
    ├─ 已签到 → 直接读积分与连续天数（一个签到请求都不发）
    └─ 未签到 → 探测端点 → 提交 → 复核（含积分流水兜底）→ 读积分 → 通知

保留原插件的三个关键约定：
  1. 不把「请求发出」或「按钮变化」当成功，必须复核持久化状态；
  2. 明确区分 Cookie 失效、页面结构变化、签到失败；
  3. 通知文案按原插件的人话排版，顺带读出积分余额、今日积分、连续天数。

签到提交接口已按 F12 抓包确认，作为默认首选端点（零配置即可命中）：

    POST https://club.ugnas.com/plugin.php?id=ugreen_checkin&action=sign
    Content-Type: application/x-www-form-urlencoded; charset=UTF-8
    X-Requested-With: XMLHttpRequest
    body: checkinsubmit=yes&formhash=<从签到页实时提取>

页面表单 / 按钮链接 / JS 地址探测，以及 Discuz「每日签到」(dsu_paulsign) 系的
operation=qiandao 候选，仅在官方接口改版失效时兜底；页面文案没变时再用积分页
当天的签到流水做二次确认，避免论坛改版后误报失败。

可选 UGREEN_SIGNIN_MODE=browser 走 Playwright 模式，逻辑与原插件一致（需自行安装
playwright + chromium），用于 HTTP 自动探测失效时兜底。

环境变量见 README.md。日志与异常信息中永不打印 Cookie。
"""

from __future__ import annotations

import html as html_lib
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:  # 青龙一般自带 requests；缺失时给出明确提示
    requests = None

# ---------------------------------------------------------------- 常量

CHECKIN_URL = "https://club.ugnas.com/plugin.php?id=ugreen_checkin"
CREDIT_URL = "https://club.ugnas.com/home.php?mod=spacecp&ac=credit"
HOME_URL = "https://club.ugnas.com/"
COOKIE_DOMAIN = "club.ugnas.com"
DIVIDER = "────────────"
REWARD_STEP_FIRST = 7
REWARD_STEP_SECOND = 30

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_BALANCE_RE = re.compile(r"积分[：:]\s*([0-9][0-9,]*)")
_STREAK_RE = re.compile(r"已连续签到\s*([0-9]+)\s*天")
_CREDIT_ROW_RE = re.compile(
    r"^(?P<action>\S.*?)\s+积分\s*(?P<delta>[+-]\s*[0-9][0-9,]*)\s+"
    r"(?P<detail>.*?)\s+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\s+[0-9]{2}:[0-9]{2}$"
)

# 抓包确认的官方签到接口（F12 → Network → 点击「立即签到」）。
# 注意：formhash 只在表单体里、URL 上不带；它由脚本从签到页实时提取，
# 不能写死（每次登录会话都不同）。下面只记录接口形态，不含任何账号凭据。
OFFICIAL_SUBMIT_PATH = "plugin.php?id=ugreen_checkin&action=sign"
OFFICIAL_FORM = {"checkinsubmit": "yes"}

# Discuz「每日签到」系插件（DSU/dsu_paulsign）的提交形态，仅作官方接口失效后的兜底。
_CANDIDATE_PATHS = [
    "plugin.php?id=ugreen_checkin:sign&operation=qiandao&inajax=1&infloat=1&qdxq=kx&qdmode=2&todaysay=&fastreply=1&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&operation=qiandao&inajax=1&infloat=1&qdxq=kx&qdmode=2&todaysay=&fastreply=1&formhash={formhash}",
    "plugin.php?id=ugreen_checkin:sign&operation=qiandao&inajax=1&qdxq=kx&qdmode=2&todaysay=&fastreply=1&formhash={formhash}",
    "plugin.php?id=ugreen_checkin:sign&operation=qiandao&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&operation=qiandao&formhash={formhash}",
    # 其他常见 Discuz 签到插件参数形态（兜底）
    "plugin.php?id=ugreen_checkin&ac=sign&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&do=sign&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&op=sign&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&action=checkin&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&signsubmit=yes&formhash={formhash}",
    "plugin.php?id=ugreen_checkin:sign&signsubmit=yes&formhash={formhash}",
    "plugin.php?id=ugreen_checkin:sign&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&inajax=1&ac=sign&formhash={formhash}",
]

# POST 时参数在表单体里，URL 上只带 formhash
_DSU_POST_PATHS = [
    "plugin.php?id=ugreen_checkin:sign&operation=qiandao&inajax=1&infloat=1&formhash={formhash}",
    "plugin.php?id=ugreen_checkin&operation=qiandao&inajax=1&infloat=1&formhash={formhash}",
    "plugin.php?id=ugreen_checkin:sign&operation=qiandao&inajax=1&formhash={formhash}",
]
_DSU_FORM = {"qdxq": "kx", "qdmode": "2", "todaysay": "", "fastreply": "1"}

# 严格词直接判「已签到」；宽松词仅在「立即签到」按钮消失后生效，避免误报
_ALREADY_STRICT_WORDS = ("今日已签到", "今天已签到", "今日已签", "您今天已经签到")
_ALREADY_LOOSE_WORDS = ("已签到", "签到成功", "签到完成", "已经签到", "明日再来", "明天再来")
# 绿联自绘签到页未签到时写的是「今天还没有签到」（截图确认），按钮文案改版也能识别
_NOT_SIGNED_WORDS = ("今天还没有签到", "今日还未签到", "今天尚未签到", "今天还没签到")

_SIGN_ACTION_WORDS = ("sign", "checkin", "submit", "do=", "op=", "ac=", "action=", "mod=", "qiandao")


# ---------------------------------------------------------------- 基础工具


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print("[{}] {}".format(datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y", "开")


def env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(env(name, str(default))), high))
    except (TypeError, ValueError):
        return default


def _setup_timezone() -> None:
    """论坛按北京时间记「今日」；青龙容器没设 TZ 时统一到 Asia/Shanghai。

    Windows 的 CRT 不认 IANA 时区名，设置后反而会退回 UTC，因此直接沿用系统时区。
    """
    if os.environ.get("TZ") or sys.platform == "win32":
        return
    os.environ["TZ"] = "Asia/Shanghai"
    try:
        if hasattr(time, "tzset"):
            time.tzset()
    except Exception:
        pass


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def html_to_text(raw: str) -> str:
    """把 Discuz HTML 转成接近 innerText 的按行文本，保留表格行结构。"""
    s = str(raw or "")
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<script\b.*?</script>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<style\b.*?</style>", " ", s, flags=re.I | re.S)
    s = re.sub(r"</(?:tr|p|div|li|table|ul|ol|h[1-6]|section|dl|dt|dd)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(?:td|th|span|label)\s*>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    lines = []
    for line in s.splitlines():
        line = re.sub(r"[ \t\r\f\v\xa0\u3000]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _abs_url(url: str) -> str:
    url = html_lib.unescape(str(url or "").strip().strip("'\""))
    url = url.replace("\\/", "/")
    return urllib.parse.urljoin(CHECKIN_URL, url)


def _tag_attrs(fragment: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in re.finditer(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", fragment):
        out[m.group(1).lower()] = html_lib.unescape(
            m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else (m.group(4) or "")
        )
    return out


def extract_formhash(page_html: str) -> str:
    """从 Discuz 页面提取 formhash（隐藏域 / JS 变量 / 链接参数）。"""
    patterns = [
        r"<input\b[^>]*name=[\"']formhash[\"'][^>]*value=[\"']([^\"']+)[\"']",
        r"<input\b[^>]*value=[\"']([0-9a-zA-Z]{6,})[\"'][^>]*name=[\"']formhash[\"']",
        r"formhash\s*[=:]\s*[\"']([0-9a-zA-Z]{6,})[\"']",
        r"formhash=([0-9a-zA-Z]{6,})",
    ]
    for pat in patterns:
        m = re.search(pat, page_html or "", re.I)
        if m:
            return m.group(1)
    return ""


class CheckinError(Exception):
    """签到流程无法完成。"""


class CookieExpiredError(CheckinError):
    """Cookie 缺失、失效或未通过登录校验。"""


# ---------------------------------------------------------------- 配置与结果


@dataclass
class Config:
    cookies: List[str]
    notify: bool = True
    only_fail: bool = False
    mode: str = "http"
    timeout: int = 30
    submit_url: str = ""
    submit_body: str = ""
    method: str = ""
    debug: bool = False
    strict: bool = False
    force_direct: bool = False
    ua: str = DEFAULT_UA
    skip_cookie_check: bool = False
    browser_timeout: int = 90
    credit_verify: bool = True

    @classmethod
    def load(cls) -> "Config":
        raw = env("UGREEN_COOKIE") or env("UGREEN_SIGNIN_COOKIE") or env("UGREEN_COOKIES")
        cookies = [c.strip() for c in re.split(r"[&\n]", raw) if c.strip()]
        mode = env("UGREEN_SIGNIN_MODE", "http").lower()
        if mode not in ("http", "browser"):
            mode = "http"
        method = env("UGREEN_SIGNIN_METHOD", "").upper()
        if method not in ("GET", "POST"):
            method = ""
        return cls(
            cookies=cookies,
            notify=env_bool("UGREEN_SIGNIN_NOTIFY", True),
            only_fail=env_bool("UGREEN_SIGNIN_ONLY_FAIL", False),
            mode=mode,
            timeout=env_int("UGREEN_SIGNIN_TIMEOUT", 30, 5, 120),
            submit_url=env("UGREEN_SIGNIN_SUBMIT_URL"),
            submit_body=env("UGREEN_SIGNIN_SUBMIT_BODY"),
            method=method,
            debug=env_bool("UGREEN_SIGNIN_DEBUG", False),
            strict=env_bool("UGREEN_SIGNIN_STRICT", False),
            force_direct=env_bool("UGREEN_SIGNIN_FORCE_DIRECT", False),
            ua=env("UGREEN_SIGNIN_UA", DEFAULT_UA),
            skip_cookie_check=env_bool("UGREEN_SIGNIN_SKIP_COOKIE_CHECK", False),
            browser_timeout=env_int("UGREEN_SIGNIN_BROWSER_TIMEOUT", 90, 30, 180),
            credit_verify=env_bool("UGREEN_SIGNIN_CREDIT_VERIFY", True),
        )


@dataclass
class Stats:
    balance: Optional[int] = None
    today_gain: Optional[int] = None
    today_total: Optional[int] = None
    streak: Optional[int] = None


@dataclass
class Result:
    label: str
    status: str  # success / already / failed
    message: str
    stats: Stats = field(default_factory=Stats)
    time: str = ""
    extra: str = ""


@dataclass
class Target:
    url: str
    method: str = "GET"
    data: Dict[str, str] = field(default_factory=dict)
    origin: str = ""


@dataclass
class Page:
    url: str
    html: str
    text: str
    formhash: str


# ---------------------------------------------------------------- 页面解析


def parse_cookie_string(raw: str, skip_check: bool = False) -> Dict[str, str]:
    """解析请求头形式的 Cookie（沿用原插件校验：必须含 *_auth 登录凭证）。"""
    text = str(raw or "").strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    if not text:
        raise CookieExpiredError("请先配置论坛 Cookie")

    jar: Dict[str, str] = {}
    for item in text.split(";"):
        name, sep, value = item.strip().partition("=")
        if not sep or not name or not _COOKIE_NAME_RE.fullmatch(name):
            continue
        if name not in jar:
            jar[name] = value.strip()

    if not jar:
        raise CookieExpiredError("Cookie 格式无效，请复制完整请求头 Cookie")
    if not skip_check and not any(k.lower().endswith("_auth") for k in jar):
        raise CookieExpiredError("Cookie 中缺少登录凭证 *_auth，请重新复制完整 Cookie")
    return jar


def read_state(page: Page) -> str:
    """识别登录失效、已签到、可签到、未知页面四种状态。"""
    url = str(page.url or "")
    if "member.php?mod=logging" in url or "web.ugnas.com" in url:
        return "login"
    text = page.text or ""
    if "您尚未登录" in text or "抱歉，您尚未登录" in text:
        return "login"
    custom = [
        w.strip() for w in re.split(r"[,，|]", env("UGREEN_SIGNIN_ALREADY_KEYWORDS"))
        if w.strip()
    ]
    if any(w in text for w in tuple(custom) + _ALREADY_STRICT_WORDS):
        return "already"
    # 按钮还在 → 一定没签到，哪怕页面别处出现「签到成功」之类的提示
    if "立即签到" in text:
        return "ready"
    # 按钮消失且出现已签到类文案（部分模板签到后按钮变成「签到成功」）
    if any(w in text for w in _ALREADY_LOOSE_WORDS):
        return "already"
    # 按钮文案改版时，靠状态文字兜底识别「未签到」，避免误报 unknown 中断流程
    if any(w in text for w in _NOT_SIGNED_WORDS):
        return "ready"
    return "unknown"


def parse_streak(text: str) -> Optional[int]:
    m = _STREAK_RE.search(text or "")
    return int(m.group(1)) if m else None


def parse_credit_text(text: str, today: Optional[str] = None) -> Stats:
    """解析积分页：当前余额、今日签到积分、今日积分合计。"""
    body = str(text or "")
    if not body:
        return Stats()

    target_day = today or datetime.now().strftime("%Y-%m-%d")
    balance: Optional[int] = None
    m = _BALANCE_RE.search(body)
    if m:
        balance = _to_int(m.group(1))
    if balance is None:
        m = re.search(r"(?:我的|可用|当前)?积分(?:余额)?[^0-9\-]{0,8}([0-9][0-9,]*)", body)
        if m:
            balance = _to_int(m.group(1))

    today_gain = 0
    today_total = 0
    seen_gain = False
    seen_row = False
    for raw_line in body.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        row = _CREDIT_ROW_RE.match(line)
        if not row or row.group("date") != target_day:
            continue
        delta = _to_int(row.group("delta").replace(" ", ""))
        if delta is None:
            continue
        seen_row = True
        today_total += delta
        if "签到" in row.group("action") or "签到" in row.group("detail"):
            today_gain += delta
            seen_gain = True

    # 宽松兜底：HTML 转文本后表格列可能与原插件的 innerText 略有差异
    if not seen_gain:
        for raw_line in body.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if target_day not in line or "签到" not in line:
                continue
            m = re.search(r"积分\s*([+-]\s*[0-9][0-9,]*)", line)
            if m:
                delta = _to_int(m.group(1).replace(" ", ""))
                if delta is not None:
                    today_gain = delta
                    seen_gain = True
                    break

    return Stats(
        balance=balance,
        today_gain=today_gain if seen_gain else None,
        today_total=today_total if seen_row else None,
    )


def _page_urls(src: str) -> List[str]:
    """DEBUG 用：列出页面里所有 php / api 地址（含探测时被过滤掉的），便于抓包定位。"""
    out: List[str] = []
    for pat in (
        r"""["']((?:https?://club\.ugnas\.com)?/?[a-z0-9_.]+\.php\?[^"'<>\s]{4,300})["']""",
        r"""["']((?:https?://club\.ugnas\.com)?/api/[^"'<>\s]{4,300})["']""",
    ):
        for m in re.finditer(pat, src or "", re.I):
            u = html_lib.unescape(m.group(1)).replace("\\/", "/")
            if u not in out:
                out.append(u)
    return out


def _form_fields(inner: str) -> Dict[str, str]:
    """提取 form 内所有具名控件，而不只是 hidden。

    Discuz 签到表单常靠 <button name="signsubmit"> 或 qdxq / qdmode 等字段
    触发，只取 hidden 时请求虽发出但服务端会直接忽略，表现为「提交后未确认」。
    """
    fields: Dict[str, str] = {}
    for im in re.finditer(r"<input\b([^>]*)>", inner, re.I):
        raw, ia = im.group(1), _tag_attrs(im.group(1))
        name = ia.get("name")
        if not name:
            continue
        typ = ia.get("type", "").lower()
        if typ in ("radio", "checkbox") and not re.search(r"\bchecked\b", raw, re.I):
            continue
        if typ in ("image", "file", "reset"):
            continue
        fields[name] = ia.get("value", "")
    for bm in re.finditer(r"<button\b([^>]*)>", inner, re.I):
        ba = _tag_attrs(bm.group(1))
        if ba.get("name") and ba["name"] not in fields:
            fields[ba["name"]] = ba.get("value", "")
    for sm in re.finditer(r"<select\b([^>]*)>(.*?)</select>", inner, re.I | re.S):
        sa = _tag_attrs(sm.group(1))
        if not sa.get("name"):
            continue
        opt = re.search(r"<option\b([^>]*\bselected\b[^>]*)>", sm.group(2), re.I)
        fields[sa["name"]] = _tag_attrs(opt.group(1)).get("value", "") if opt else ""
    for tm in re.finditer(r"<textarea\b([^>]*)>(.*?)</textarea>", inner, re.I | re.S):
        ta = _tag_attrs(tm.group(1))
        if ta.get("name"):
            fields[ta["name"]] = html_to_text(tm.group(2))
    return fields


def discover_targets(page: Page, cfg: Config) -> List[Target]:
    """从签到页还原「立即签到」按钮背后的提交请求。

    优先级：手动指定 > 抓包确认的官方接口 > 页面 form > a[href]
            > 页面 JS/AJAX URL > 猜测候选。
    """
    targets: List[Target] = []
    src = page.html or ""
    fh = page.formhash

    # 1) 手动指定（抓包得到的真实接口，最可靠）
    if cfg.submit_url:
        url = cfg.submit_url.replace("{formhash}", fh)
        if fh and "formhash=" not in url:
            url += ("&" if "?" in url else "?") + "formhash=" + fh
        data: Dict[str, str] = {}
        for pair in cfg.submit_body.replace("{formhash}", fh).split("&"):
            k, sep, v = pair.partition("=")
            if sep and k.strip():
                data[k.strip()] = v.strip()
        method = cfg.method or ("POST" if data else "GET")
        targets.append(Target(_abs_url(url), method, data, "手动指定"))
        return targets

    # 2) 抓包确认的官方接口：默认首选，零配置即可命中。
    #    strict 只关「猜测候选」，官方接口始终保留；提交后仍会重新拉页复核。
    official_method = cfg.method or "POST"
    official_url = _abs_url(OFFICIAL_SUBMIT_PATH)
    official_data: Dict[str, str] = {}
    if official_method == "POST":
        official_data = dict(OFFICIAL_FORM)
        if fh:
            official_data["formhash"] = fh
    elif fh:
        # 用户强制 GET 时把 formhash 移到 URL（不推荐，仅作兼容）
        official_url += ("&" if "?" in official_url else "?") + "formhash=" + fh
    targets.append(Target(official_url, official_method, official_data, "官方接口"))

    # 3) 按钮所在的 <form>
    for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", src, re.I | re.S):
        attrs, inner = _tag_attrs(m.group(1)), m.group(2)
        if "立即签到" not in html_to_text(inner):
            continue
        hidden = _form_fields(inner)
        if fh:
            hidden.setdefault("formhash", fh)
        method = cfg.method or (attrs.get("method", "get").upper() or "GET")
        if method not in ("GET", "POST"):
            method = "GET"
        targets.append(Target(_abs_url(attrs.get("action") or CHECKIN_URL), method, hidden, "页面表单"))

    # 4) <a href> 按钮
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", src, re.I | re.S):
        attrs = _tag_attrs(m.group(1))
        if "立即签到" not in html_to_text(m.group(2)):
            continue
        href = attrs.get("href", "")
        if not href or href.lower().startswith(("javascript:", "#")):
            continue
        url = _abs_url(href)
        if fh and "formhash=" not in url:
            url += ("&" if "?" in url else "?") + "formhash=" + fh
        targets.append(Target(url, cfg.method or "GET", {}, "按钮链接"))

    # 5) 页面里的 JS / AJAX URL（全页扫描：接口可能写在页尾脚本或独立 block）
    found: List[str] = []
    for pat in (
        r"""["']((?:https?://club\.ugnas\.com/)?/?plugin\.php\?[^"'<>\s]{6,300})["']""",
        r"""["']((?:https?://club\.ugnas\.com/)?/?[a-z0-9_]+\.php\?[^"'<>\s]{6,300})["']""",
        r"""["']((?:https?://club\.ugnas\.com)?/api/[^"'<>\s]{4,300})["']""",
    ):
        for m in re.finditer(pat, src[:200000], re.I):
            u = m.group(1)
            low = u.lower()
            if not any(w in low for w in ("ugreen_checkin", "checkin", "sign", "qiandao")):
                continue
            # /api/ 路径通常自带动作语义，不要求再命中 sign/ac 等参数词
            if "/api/" not in low and not any(w in low for w in _SIGN_ACTION_WORDS):
                continue
            if u not in found:
                found.append(u)
    for u in found[:8]:
        url = _abs_url(u)
        if fh and "formhash=" not in url:
            url += ("&" if "?" in url else "?") + "formhash=" + fh
        targets.append(Target(url, cfg.method or "GET", {}, "页面脚本"))

    # 6) 常见 Discuz 签到插件形态兜底（可用 UGREEN_SIGNIN_STRICT=1 关闭）
    if not cfg.strict:
        # DSU 系插件最常见的是 POST（参数在表单体），优先尝试以尽快命中
        if not cfg.method:
            for tpl in _DSU_POST_PATHS:
                path = tpl.format(formhash=fh or "")
                if not fh:
                    path = path.replace("&formhash=", "").replace("?formhash=", "")
                data = dict(_DSU_FORM)
                if fh:
                    data["formhash"] = fh
                targets.append(Target(_abs_url(path), "POST", data, "候选接口"))
        for tpl in _CANDIDATE_PATHS:
            path = tpl.format(formhash=fh or "")
            if not fh:
                path = path.replace("&formhash=", "").replace("?formhash=", "")
            targets.append(Target(_abs_url(path), cfg.method or "GET", {}, "候选接口"))

    # 去重
    seen = set()
    unique: List[Target] = []
    for t in targets:
        key = (t.url, t.method, tuple(sorted(t.data.items())))
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


# ---------------------------------------------------------------- 客户端


class UgreenHttp:
    """纯 HTTP 签到客户端，用 requests.Session 维持 Cookie 会话。"""

    def __init__(self, raw_cookie: str, cfg: Config) -> None:
        if requests is None:
            raise CheckinError("缺少 requests 依赖，请在青龙【依赖管理 → Python3】安装 requests")
        self.cfg = cfg
        self.jar = parse_cookie_string(raw_cookie, cfg.skip_cookie_check)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": HOME_URL,
            "Cookie": self._cookie_header(),
        })
        self.formhash = ""
        self._credit_page: Optional[Page] = None

    def _cookie_header(self) -> str:
        return "; ".join("{}={}".format(k, v) for k, v in self.jar.items())

    def _get(self, url: str, **kwargs: Any) -> Any:
        return self.session.get(url, timeout=self.cfg.timeout, allow_redirects=True, **kwargs)

    def _post(self, url: str, data: Dict[str, str], **kwargs: Any) -> Any:
        return self.session.post(url, data=data, timeout=self.cfg.timeout, allow_redirects=True, **kwargs)

    def fetch(self, url: str, cache_bust: bool = False) -> Page:
        if cache_bust:
            url += ("&" if "?" in url else "?") + "_t=" + str(int(time.time() * 1000))
        resp = self._get(url)
        # 响应头未带 charset 时 requests 对 text/html 默认 ISO-8859-1，会中文乱码
        ctype = str(resp.headers.get("Content-Type", "")).lower()
        if "charset" not in ctype and str(getattr(resp, "encoding", "")).lower() == "iso-8859-1":
            resp.encoding = "utf-8"
        raw = resp.text or ""
        text = html_to_text(raw)
        if not self.formhash:
            self.formhash = extract_formhash(raw)
        return Page(url=str(getattr(resp, "url", "") or url), html=raw, text=text, formhash=self.formhash)

    def submit(self, target: Target) -> str:
        # 复刻抓包请求头：绿联签到是 AJAX 提交，Origin / X-Requested-With 需要带上
        headers = {
            "Referer": CHECKIN_URL,
            "Origin": "https://club.ugnas.com",
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
        }
        if target.method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            resp = self._post(target.url, target.data, headers=headers)
        else:
            resp = self._get(target.url, headers=headers)
        text = html_to_text(resp.text or "")
        if self.cfg.debug:
            snippet = re.sub(r"\s+", " ", text).strip()[:160] or "(空响应)"
            log("DEBUG 提交 {} {} -> HTTP {} | {}".format(
                target.method, target.url.split("?", 1)[-1][:110],
                getattr(resp, "status_code", "?"), snippet))
        return text

    def credit_confirms_today(self) -> bool:
        """积分页出现「当天 + 签到 + 积分」记录 = 签到已落库。

        比页面文案可靠：论坛改版后按钮文字变了也能确认，避免误报失败。
        """
        self._credit_page = None
        try:
            page = self.fetch(CREDIT_URL, cache_bust=True)
        except Exception as err:
            if self.cfg.debug:
                log("DEBUG 积分页读取失败：{}".format(err))
            return False
        self._credit_page = page
        day = datetime.now().strftime("%Y-%m-%d")
        short = datetime.now().strftime("%m-%d")
        for line in (page.text or "").splitlines():
            if "签到" not in line or (day not in line and short not in line):
                continue
            if re.search(r"[+\-]\s*[0-9]|[0-9]\s*积分|积分\s*[+\-]", line):
                return True
        return False

    def read_stats(self, checkin_page: Page, credit_page: Optional[Page] = None) -> Stats:
        stats = Stats()
        try:
            stats.streak = parse_streak(checkin_page.text)
        except Exception:
            pass
        try:
            # 已签到分支复用前置确认时拉过的积分页，避免重复请求；
            # 刚提交完则必须重新拉，才能读到签到后的最新积分。
            credit = credit_page or self.fetch(CREDIT_URL)
            parsed = parse_credit_text(credit.text)
            stats.balance = parsed.balance
            stats.today_gain = parsed.today_gain
            stats.today_total = parsed.today_total
        except Exception as err:
            log("积分页读取失败（不影响签到结果）：{}".format(err))
        return stats

    def dump_debug(self, page: Page, label: str) -> None:
        if not self.cfg.debug:
            return
        try:
            path = env("UGREEN_SIGNIN_DEBUG_FILE") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "ugreen_signin_debug.html"
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write("<h2>{}</h2><pre>".format(label))
                f.write(html_lib.escape(page.html[:200000]))
                f.write("</pre>")
            log("DEBUG 页面已保存：{}（请勿公开发布，可能含账号昵称）".format(path))
        except Exception as err:
            log("DEBUG 页面保存失败：{}".format(err))
        # 把页面里出现过的请求地址都列出来，一次运行即可判断真实接口藏在何处
        urls = _page_urls(page.html or "")
        if urls:
            log("DEBUG 页面内共发现 {} 个 php/api 地址：".format(len(urls)))
            for u in urls[:20]:
                log("DEBUG   " + u[:180])
        else:
            log("DEBUG 页面内没有 php/api 地址，签到请求可能在外部 JS 里，需 F12 抓包")

    def run(self, label: str) -> Result:
        # 1) 先看签到页状态
        page = self.fetch(CHECKIN_URL)
        state = read_state(page)
        self.dump_debug(page, label + " 签到页")

        if state == "login":
            raise CookieExpiredError("论坛登录已失效，请更新 Cookie")

        # 2) 前置状态确认：按钮文案可能被缓存或改版，积分页当天的签到流水更可靠。
        #    已签到就到此为止，一个签到请求都不发。
        stats_credit: Optional[Page] = None
        if state != "already" and self.cfg.credit_verify:
            if self.credit_confirms_today():
                stats_credit = self._credit_page
                state = "already"
                log("{} 积分页显示今日已有签到记录，跳过提交".format(label))

        if state == "unknown":
            # 再看一眼首页，区分「Cookie 失效」和「页面结构变化」
            try:
                home = self.fetch(HOME_URL)
                if "登录" in home.text and "退出" not in home.text:
                    raise CookieExpiredError("Cookie 未通过论坛登录校验，请更新 Cookie")
            except CookieExpiredError:
                raise
            except Exception:
                pass
            raise CheckinError("未识别到签到按钮，论坛页面结构可能已变化（可开 DEBUG 导出页面排查）")

        extra = ""
        if state == "already":
            # 3) 已签到：直接读积分与连续天数，不发任何签到请求
            status, message = "already", "今日已签到"
            log("{} 今日已签到，跳过提交，直接读取积分与连续天数".format(label))
        else:
            # 4) 确认未签到才提交
            log("{} 今日尚未签到，开始尝试签到".format(label))
            targets = discover_targets(page, self.cfg)
            log("{} 共 {} 个提交端点（首选：{}｜formhash：{}）".format(
                label, len(targets), targets[0].origin if targets else "无",
                "已获取" if page.formhash else "未获取"))
            status = ""
            last_after: Optional[Page] = None
            for i, t in enumerate(targets, 1):
                try:
                    reply = self.submit(t)
                except Exception as err:
                    log("{} 第 {} 个端点请求异常：{}".format(label, i, err))
                    continue
                # 关键：重新拉页复核持久化状态，不把请求发出当成功
                after = self.fetch(CHECKIN_URL, cache_bust=True)
                last_after = after
                new_state = read_state(after)
                if new_state == "login":
                    raise CookieExpiredError("签到过程中登录失效，请更新 Cookie")
                if new_state == "already":
                    status, message = "success", "签到成功"
                    # 用复核后的页面读连续天数，避免拿到签到前的旧值
                    page = after
                    extra = "提交方式：{}（第 {} 个端点）".format(t.origin, i)
                    log("{} 复核通过：今日已签到（{}）".format(label, extra))
                    break
                if self.cfg.debug:
                    snippet = re.sub(r"\s+", " ", reply or "").strip()[:80] or "(空)"
                    log("{} 第 {} 个端点未改变状态（{}｜复核页 {}｜响应 {}）".format(
                        label, i, t.url.split("?", 1)[-1][:100], new_state, snippet))
            # 页面文案没变时用积分流水兜底复核：论坛改版换文案也不会误报失败
            if not status and self.cfg.credit_verify:
                if self.credit_confirms_today():
                    status, message = "success", "签到成功"
                    extra = "提交方式：积分记录确认（页面文案未变化）"
                    stats_credit = self._credit_page
                    if last_after is not None:
                        page = last_after
                    log("{} 复核通过：积分页出现当日签到记录".format(label))
            if not status:
                if self.cfg.debug and last_after is not None:
                    snippet = re.sub(r"\s+", " ", last_after.text or "").strip()[:300]
                    log("{} DEBUG 最后一次复核页文本：{}".format(label, snippet or "(空)"))
                raise CheckinError(
                    "提交后未确认签到成功（官方接口已尝试），请开 DEBUG 查看响应，"
                    "或重新抓包配置 UGREEN_SIGNIN_SUBMIT_URL"
                )

        # 5) 统一读积分信息；已签到分支复用前置确认时拉过的积分页
        stats = self.read_stats(page, credit_page=stats_credit)
        return Result(label, status, message, stats, _now(), extra)


def run_browser(raw_cookie: str, cfg: Config, label: str) -> Result:
    """可选：Playwright 模式，流程与 MoviePilot 原插件一致。需自行安装 playwright + chromium。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise CheckinError("browser 模式需要 playwright，请在青龙安装依赖并下载 chromium")

    jar = parse_cookie_string(raw_cookie, cfg.skip_cookie_check)
    cookies = [
        {"name": k, "value": v, "domain": COOKIE_DOMAIN, "path": "/", "secure": True, "httpOnly": False}
        for k, v in jar.items()
    ]
    timeout_ms = cfg.browser_timeout * 1000
    try:
        # sync_playwright 的上下文退出时会自动关闭 browser/context，无需额外 finally
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent=cfg.ua, viewport={"width": 1280, "height": 900})
            context.add_cookies(cookies)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)
            page.goto(CHECKIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            def snapshot() -> Page:
                try:
                    text = str(page.locator("body").inner_text(timeout=5000) or "")
                except Exception:
                    text = html_to_text(page.content())
                raw = ""
                try:
                    raw = page.content()
                except Exception:
                    pass
                return Page(str(page.url or ""), raw, text, extract_formhash(raw))

            cur = snapshot()
            state = read_state(cur)
            if state == "login":
                raise CookieExpiredError("论坛登录已失效，请更新 Cookie")
            if state == "unknown":
                raise CheckinError("未识别到签到按钮，论坛页面结构可能已变化")

            if state == "ready":
                page.locator('button:has-text("立即签到")').first.click(timeout=timeout_ms)
                try:
                    page.wait_for_function(
                        "() => { const t = document.body ? document.body.innerText : ''; "
                        "return t.includes('今日已签到') || t.includes('签到成功'); }",
                        timeout=timeout_ms,
                    )
                except Exception:
                    pass
                page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                cur = snapshot()
                if read_state(cur) == "login":
                    raise CookieExpiredError("签到过程中登录失效，请更新 Cookie")
                if read_state(cur) != "already":
                    raise CheckinError("点击后未确认签到成功，请稍后重试或检查 Cookie")
                status, message = "success", "签到成功"
            else:
                status, message = "already", "今日已签到"

            stats = Stats()
            try:
                stats.streak = parse_streak(cur.text)
            except Exception:
                pass
            try:
                page.goto(CREDIT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                credit = snapshot()
                parsed = parse_credit_text(credit.text)
                stats.balance = parsed.balance
                stats.today_gain = parsed.today_gain
                stats.today_total = parsed.today_total
            except Exception:
                pass
            return Result(label, status, message, stats, _now(), "browser 模式")
    except (CookieExpiredError, CheckinError):
        raise
    except Exception as err:
        raise CheckinError("浏览器签到异常：{}".format(err))


def run_account(raw_cookie: str, cfg: Config, label: str) -> Result:
    try:
        if cfg.mode == "browser":
            return run_browser(raw_cookie, cfg, label)
        return UgreenHttp(raw_cookie, cfg).run(label)
    except (CookieExpiredError, CheckinError) as err:
        return Result(label, "failed", str(err), Stats(), _now())
    except Exception as err:
        return Result(label, "failed", "签到异常：{}".format(err), Stats(), _now())


# ---------------------------------------------------------------- 通知文案


def _row(icon: str, label: str, value: str) -> str:
    return "{} {}　{}".format(icon, label, value)


def _gain_text(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    if value > 0:
        return "+{} 积分".format(value)
    if value == 0:
        return "0 积分"
    return "{} 积分".format(value)


def _reward_hint(streak: Optional[int]) -> str:
    if not streak or streak <= 0:
        return ""
    if streak < REWARD_STEP_FIRST:
        return "再签 {} 天可得 +5 积分".format(REWARD_STEP_FIRST - streak)
    if streak < REWARD_STEP_SECOND:
        return "再签 {} 天可得 +20 积分".format(REWARD_STEP_SECOND - streak)
    return "已连续满 30 天，奖励到手"


def _short_time(value: Any) -> str:
    text = str(value or "").strip()
    parts = text.split(" ")
    if len(parts) == 2 and len(parts[0]) == 10:
        return "{} {}".format(parts[0][5:], parts[1][:5])
    return text or "未知"


def build_record(r: Result) -> Dict[str, Any]:
    return {
        "status": r.status,
        "message": r.message,
        "balance": r.stats.balance,
        "today_gain": r.stats.today_gain,
        "today_total": r.stats.today_total,
        "streak": r.stats.streak,
        "time": r.time,
    }


def build_text(record: Dict[str, Any]) -> str:
    """与原插件 message.build_text 一致的纯文本卡片。"""
    status = str(record.get("status") or "unknown")
    lines: List[str] = [DIVIDER]
    if status == "failed":
        lines.append(_row("❌", "状态", "签到失败"))
        lines.append(_row("💬", "原因", str(record.get("message") or "原因未知").strip()))
    else:
        lines.append(_row("✅", "状态", str(record.get("message") or "已处理")))
        gain = _gain_text(record.get("today_gain"))
        if gain:
            lines.append(_row("💰", "本次", gain))
        balance = record.get("balance")
        if isinstance(balance, int):
            lines.append(_row("🏅", "余额", "{} 积分".format(balance)))
        streak = record.get("streak")
        if isinstance(streak, int):
            lines.append(_row("🔥", "连续", "{} 天".format(streak)))
    lines.append(_row("🕘", "时间", _short_time(record.get("time"))))
    lines.append(DIVIDER)
    if status == "failed":
        lines.append("更新 Cookie 后可手动重跑一次任务")
    else:
        hint = _reward_hint(record.get("streak"))
        if hint:
            lines.append(hint)
    return "\n".join(lines)


def build_notification(results: List[Result]) -> Tuple[str, str]:
    """返回 (标题, 正文)。多账号汇总成一条通知。"""
    failed = [r for r in results if r.status == "failed"]
    if len(results) == 1:
        r = results[0]
        rec = build_record(r)
        if r.status == "failed":
            title = "绿联社区签到失败"
        else:
            title = "绿联社区签到"
            if isinstance(rec["today_gain"], int):
                title += " · +{} 积分".format(rec["today_gain"])
            if isinstance(rec["balance"], int):
                title += " · 余额 {}".format(rec["balance"])
        return title, build_text(rec)

    title = "绿联社区签到 · {} 个账号".format(len(results))
    if failed:
        title += " · {} 失败".format(len(failed))
    parts = []
    for r in results:
        parts.append("【{}】{}".format(r.label, r.message))
        parts.append(build_text(build_record(r)))
        if r.extra:
            parts.append("· {}".format(r.extra))
        parts.append("")
    return title, "\n".join(parts).strip()


# ---------------------------------------------------------------- 通知发送


class Notifier:
    """通知优先级：青龙 notify.py → 青龙系统通知 API → 内置多渠道直推。"""

    def __init__(self) -> None:
        self.session = None
        if requests is not None:
            self.session = requests.Session()
            # 不预设 Content-Type：让 requests 按 json= / data= 自动选择，
            # 否则 Server酱 这类表单 POST 会被错误地标记成 application/json。
            self.session.headers.update({"User-Agent": DEFAULT_UA})

    def _post(self, url: str, payload: Dict[str, Any], timeout: int = 8) -> bool:
        if self.session is None:
            return False
        r = self.session.post(url, json=payload, timeout=timeout)
        return getattr(r, "status_code", 0) < 400

    def _post_form(self, url: str, payload: Dict[str, Any], timeout: int = 8) -> bool:
        if self.session is None:
            return False
        r = self.session.post(url, data=payload, timeout=timeout)
        return getattr(r, "status_code", 0) < 400

    def send(self, title: str, content: str) -> None:
        ok = False
        # 1) 青龙 notify.py（复用青龙面板里已配置好的全部推送渠道）
        # 成功即返回，避免与内置渠道重复推送；FORCE_DIRECT=1 时可完全跳过这一层。
        if not env_bool("UGREEN_SIGNIN_FORCE_DIRECT", False):
            if self._via_ql_module(title, content):
                return
            if self._via_ql_api(title, content):
                return
        # 2) 内置直推：青龙 notify.py / 系统通知不可用时的兜底
        for name, fn in (
            ("PushPlus", self._pushplus),
            ("Server酱", self._serverchan),
            ("企业微信机器人", self._qywx_bot),
            ("企业微信应用", self._qywx_app),
            ("Telegram", self._telegram),
            ("Bark", self._bark),
            ("钉钉", self._dingtalk),
            ("飞书", self._feishu),
            ("Gotify", self._gotify),
            ("ntfy", self._ntfy),
            ("自定义 Webhook", self._webhook),
        ):
            try:
                if fn(title, content):
                    ok = True
                    log("通知已发送：{}".format(name))
            except Exception as err:
                log("通知渠道 {} 失败：{}".format(name, err))
        if not ok:
            log("未检测到可用的通知渠道：建议配置青龙 notify.py，或设置 PUSHPLUS_TOKEN / BARK_URL / QYWX_KEY 等变量")

    def _via_ql_module(self, title: str, content: str) -> bool:
        here = os.path.dirname(os.path.abspath(__file__))
        for path in (here, "/ql/data/scripts", "/ql/scripts", "/ql"):
            if path and path not in sys.path and os.path.isdir(path):
                sys.path.insert(0, path)
        try:
            import notify  # type: ignore
        except Exception:
            return False
        fn = getattr(notify, "send", None) or getattr(notify, "sendNotify", None)
        if not callable(fn):
            return False
        try:
            fn(title, content)
            log("通知已交由青龙 notify.py 发送")
            return True
        except TypeError:
            try:
                fn(title, content, "")
                log("通知已交由青龙 notify.py 发送")
                return True
            except Exception:
                return False
        except Exception as err:
            log("青龙 notify.py 调用失败：{}".format(err))
            return False

    def _via_ql_api(self, title: str, content: str) -> bool:
        """青龙系统通知：PUT /api/system/notify，需 QL_TOKEN 或应用凭据。"""
        if self.session is None:
            return False
        token = env("QL_TOKEN")
        base = env("QL_URL") or env("QINGLONG_URL") or "http://127.0.0.1:5700"
        cid, secret = env("QL_CLIENT_ID"), env("QL_CLIENT_SECRET")
        if not token and not (cid and secret):
            return False
        try:
            base = base.rstrip("/")
            if not token:
                resp = self.session.get(
                    base + "/open/auth/token",
                    params={"client_id": cid, "client_secret": secret},
                    timeout=6,
                )
                token = (resp.json() or {}).get("data", {}).get("token", "")
            if not token:
                return False
            resp = self.session.put(
                base + "/api/system/notify",
                json={"title": title, "content": content},
                headers={"Authorization": "Bearer " + token},
                timeout=8,
            )
            if getattr(resp, "status_code", 0) == 200:
                log("通知已通过青龙系统通知发送")
                return True
        except Exception as err:
            log("青龙系统通知失败：{}".format(err))
        return False

    # ---- 内置渠道（按环境变量自动启用，全部 best-effort） ----

    def _pushplus(self, t: str, c: str) -> bool:
        token = env("PUSHPLUS_TOKEN") or env("PUSH_PLUS_TOKEN")
        if not token:
            return False
        return self._post("https://www.pushplus.plus/send", {
            "token": token, "title": t, "content": c.replace("\n", "<br/>"), "template": "html",
        })

    def _serverchan(self, t: str, c: str) -> bool:
        key = env("SCKEY") or env("SERVERCHAN_SCKEY") or env("PUSH_KEY")
        if not key:
            return False
        url = "https://sctapi.ftqq.com/{}.send".format(key) if key.startswith("SCT") else "https://sc.ftqq.com/{}.send".format(key)
        return self._post_form(url, {"title": t, "desp": c})

    def _qywx_bot(self, t: str, c: str) -> bool:
        key = env("QYWX_KEY")
        if not key:
            return False
        return self._post(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + key,
            {"msgtype": "text", "text": {"content": "{}\n\n{}".format(t, c)}},
        )

    def _qywx_app(self, t: str, c: str) -> bool:
        raw = env("QYWX_AM")
        if not raw or self.session is None:
            return False
        parts = [x.strip() for x in raw.split(",")]
        if len(parts) < 4:
            return False
        corpid, corpsecret, touser, agentid = parts[:4]
        r = self.session.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": corpid, "corpsecret": corpsecret}, timeout=8,
        )
        token = (r.json() or {}).get("access_token", "")
        if not token:
            return False
        return self._post(
            "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=" + token,
            {"touser": touser, "agentid": agentid, "msgtype": "text",
             "text": {"content": "{}\n\n{}".format(t, c)}, "safe": 0},
        )

    def _telegram(self, t: str, c: str) -> bool:
        token, uid = env("TG_BOT_TOKEN"), env("TG_USER_ID")
        if not token or not uid or self.session is None:
            return False
        host = env("TG_API_HOST") or "api.telegram.org"
        url = "https://{}/bot{}/sendMessage".format(host, token)
        r = self.session.post(url, json={"chat_id": uid, "text": "{}\n\n{}".format(t, c)}, timeout=8)
        return getattr(r, "status_code", 0) < 400

    def _bark(self, t: str, c: str) -> bool:
        url = env("BARK_URL") or env("BARK")
        if not url:
            return False
        url = url.rstrip("/")
        return self._post(url, {"title": t, "body": c, "group": "绿联签到"})

    def _dingtalk(self, t: str, c: str) -> bool:
        token = env("DD_BOT_TOKEN")
        if not token or self.session is None:
            return False
        url = "https://oapi.dingtalk.com/robot/send?access_token=" + token
        secret = env("DD_BOT_SECRET")
        if secret:
            import base64
            import hashlib
            import hmac
            ts = str(round(time.time() * 1000))
            sign = base64.b64encode(
                hmac.new(secret.encode(), (ts + "\n" + secret).encode(), hashlib.sha256).digest()
            ).decode()
            url += "&timestamp={}&sign={}".format(ts, urllib.parse.quote(sign))
        return self._post(url, {"msgtype": "text", "text": {"content": "{}\n\n{}".format(t, c)}})

    def _feishu(self, t: str, c: str) -> bool:
        key = env("FSKEY")
        if not key:
            return False
        return self._post(
            "https://open.feishu.cn/open-apis/bot/v2/hook/" + key,
            {"msg_type": "text", "content": {"text": "{}\n\n{}".format(t, c)}},
        )

    def _gotify(self, t: str, c: str) -> bool:
        base, token = env("GOTIFY_URL"), env("GOTIFY_TOKEN")
        if not base or not token:
            return False
        return self._post(base.rstrip("/") + "/message?token=" + token, {"title": t, "message": c, "priority": 5})

    def _ntfy(self, t: str, c: str) -> bool:
        base, topic = env("NTFY_URL"), env("NTFY_TOPIC")
        if not base or not topic or self.session is None:
            return False
        r = self.session.post(
            base.rstrip("/") + "/" + topic,
            data=c.encode("utf-8"),
            headers={"Title": t, "Content-Type": "text/plain; charset=utf-8"},
            timeout=8,
        )
        return getattr(r, "status_code", 0) < 400

    def _webhook(self, t: str, c: str) -> bool:
        url = env("UGREEN_SIGNIN_WEBHOOK")
        if not url:
            return False
        return self._post(url, {"title": t, "content": c, "text": "{}\n\n{}".format(t, c)})


# ---------------------------------------------------------------- 入口


def main() -> int:
    _setup_timezone()
    cfg = Config.load()
    log("绿联社区签到开始 · 模式 {} · 账号 {} 个".format(cfg.mode, len(cfg.cookies)))

    if not cfg.cookies:
        msg = "未配置环境变量 UGREEN_COOKIE，请复制论坛完整 Cookie 后重试"
        log("❌ " + msg)
        if cfg.notify:
            Notifier().send("绿联社区签到失败", build_text({
                "status": "failed", "message": msg, "time": _now(),
            }))
        return 1

    results: List[Result] = []
    for i, cookie in enumerate(cfg.cookies, 1):
        label = "账号{}".format(i) if len(cfg.cookies) > 1 else "默认账号"
        log("开始处理 {}".format(label))
        r = run_account(cookie, cfg, label)
        results.append(r)
        tail = ""
        if r.stats.balance is not None:
            tail += " · 余额 {}".format(r.stats.balance)
        if r.stats.today_gain is not None:
            tail += " · 今日 +{}".format(r.stats.today_gain)
        if r.stats.streak is not None:
            tail += " · 连续 {} 天".format(r.stats.streak)
        suffix = "（{}）".format(r.extra) if r.extra else ""
        log("{} {} · {}{}{}".format(
            "✅" if r.status != "failed" else "❌", label, r.message, tail, suffix
        ))

    failed = [r for r in results if r.status == "failed"]
    title, content = build_notification(results)
    if cfg.notify:
        if cfg.only_fail and not failed:
            log("仅失败通知已开启，本次全部正常，跳过推送")
        else:
            Notifier().send(title, content)

    log("签到结束：成功/已签到 {} 个，失败 {} 个".format(len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
