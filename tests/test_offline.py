# -*- coding: utf-8 -*-
"""离线自测：不联网、不需要真实 Cookie 与 requests。

在青龙里执行： task tests/test_offline.py
本地执行：     python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest
import urllib.parse
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# 用假的 requests 模块，让脚本在未安装依赖时也能做纯逻辑测试
_fake_requests = types.ModuleType("requests")


class _FakeSession:
    def __init__(self):
        self.headers = {}


_fake_requests.Session = _FakeSession
_fake_requests.__version__ = "mock"
sys.modules.setdefault("requests", _fake_requests)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ugreen_signin as m  # noqa: E402

TODAY = datetime.now().strftime("%Y-%m-%d")
VALID_COOKIE = "6LQh_2132_saltkey=abc; 6LQh_2132_auth=secret; PHPSESSID=xyz"

READY_HTML = """
<html><body>
<input type="hidden" name="formhash" value="abc123def" />
<div>签到打卡 已连续签到 3 天</div>
<button class="pn">立即签到</button>
</body></html>
"""
ALREADY_HTML = """
<html><body>
<input type="hidden" name="formhash" value="abc123def" />
<div>签到打卡 已连续签到 4 天 今日已签到</div>
<button class="pn">今日已签到</button>
</body></html>
"""
LOGIN_HTML = "<html><body><p>抱歉，您尚未登录，无法进行此操作</p></body></html>"
CREDIT_HTML = """
<html><body>
<div class="credit">积分：78</div>
<table>
<tr><td>每日签到</td><td>积分 +1</td><td>每日签到</td><td>{d} 00:56</td></tr>
<tr><td>积分规则</td><td>积分 +2</td><td>每天登录</td><td>{d} 00:27</td></tr>
<tr><td>积分规则</td><td>积分 +2</td><td>每天登录</td><td>2026-11-09 20:08</td></tr>
</table>
</body></html>
""".format(d=TODAY)
# 未签到时的积分页：没有任何当天的签到流水
CREDIT_EMPTY_HTML = """
<html><body>
<div class="credit">积分：78</div>
<table>
<tr><td>积分规则</td><td>积分 +2</td><td>每天登录</td><td>2026-11-09 20:08</td></tr>
</table>
</body></html>
"""

FORM_HTML = """
<form method="post" action="plugin.php?id=ugreen_checkin&amp;ac=do">
  <input type="hidden" name="formhash" value="abc123def" />
  <input type="hidden" name="signsubmit" value="yes" />
  <button type="submit">立即签到</button>
</form>
"""
LINK_HTML = """<a href="plugin.php?id=ugreen_checkin&do=sign" class="btn">立即签到</a>"""
JS_HTML = """<button onclick="ajaxget('plugin.php?id=ugreen_checkin&ac=do_sign')">立即签到</button>"""


class _Resp:
    def __init__(self, body, url):
        self.text = body
        self.url = url
        self.encoding = "utf-8"
        self.status_code = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class ScriptedClient(m.UgreenHttp):
    """按脚本化状态机返回页面，模拟论坛服务端。"""

    def __init__(self, cfg, signed=False, login=False, never_sign=False,
                 credit_signed=None, credit_signed_after_submit=False):
        super().__init__(VALID_COOKIE, cfg)
        self.signed = signed
        self.login = login
        self.never_sign = never_sign
        # None = 积分流水跟随页面状态；True/False 用于单独验证前置确认
        self.credit_signed = credit_signed
        # 模拟「提交之后积分流水才出现」：用于验证提交后的兜底复核
        self.credit_signed_after_submit = credit_signed_after_submit
        self.submits = []
        self.submit_headers = []

    def _get(self, url, **kwargs):
        return self._reply(url, "GET")

    def _post(self, url, data=None, **kwargs):
        self.submit_headers.append(kwargs.get("headers") or {})
        return self._reply(url, "POST", data)

    def _reply(self, url, method, data=None):
        parts = urllib.parse.urlsplit(url)
        query = parts.query
        if self.login:
            return _Resp(LOGIN_HTML, url)
        if "ac=credit" in query:
            if self.credit_signed_after_submit and self.submits:
                return _Resp(CREDIT_HTML, url)
            show = self.credit_signed if self.credit_signed is not None else self.signed
            return _Resp(CREDIT_HTML if show else CREDIT_EMPTY_HTML, url)
        if "_t=" in query:  # 复核请求
            return _Resp(ALREADY_HTML if self.signed else READY_HTML, url)
        is_submit = any(k in query for k in (
            "ac=sign", "do=sign", "op=sign", "action=sign", "action=checkin",
            "signsubmit", "ugreen_checkin:sign", "ac=do_sign", "ac=do",
            "operation=qiandao",
        ))
        if is_submit:
            self.submits.append((method, url))
            if not self.never_sign:
                self.signed = True
            return _Resp("签到成功", url)
        return _Resp(ALREADY_HTML if self.signed else READY_HTML, url)


def _page(html, url=m.CHECKIN_URL):
    return m.Page(url, html, m.html_to_text(html), m.extract_formhash(html))


class TestParsing(unittest.TestCase):
    def test_cookie_validation(self):
        jar = m.parse_cookie_string("Cookie: " + VALID_COOKIE)
        self.assertEqual(jar["6LQh_2132_auth"], "secret")
        with self.assertRaises(m.CookieExpiredError):
            m.parse_cookie_string("")
        with self.assertRaises(m.CookieExpiredError):
            m.parse_cookie_string("a=1; b=2")
        self.assertIn("a", m.parse_cookie_string("a=1", skip_check=True))

    def test_formhash_and_state(self):
        self.assertEqual(m.extract_formhash(READY_HTML), "abc123def")
        self.assertEqual(m.read_state(_page(READY_HTML)), "ready")
        self.assertEqual(m.read_state(_page(ALREADY_HTML)), "already")
        self.assertEqual(m.read_state(_page(LOGIN_HTML)), "login")
        self.assertEqual(
            m.read_state(m.Page("https://club.ugnas.com/member.php?mod=logging&action=login", "", "", "")),
            "login",
        )
        self.assertEqual(m.read_state(_page("<div>什么都没有</div>")), "unknown")

    def test_html_to_text_keeps_table_rows(self):
        text = m.html_to_text(CREDIT_HTML)
        self.assertIn("积分：78", text)
        self.assertIn("每日签到 积分 +1 每日签到 {} 00:56".format(TODAY), text)

    def test_parse_credit_text(self):
        stats = m.parse_credit_text(m.html_to_text(CREDIT_HTML))
        self.assertEqual(stats.balance, 78)
        self.assertEqual(stats.today_gain, 1)
        self.assertEqual(stats.today_total, 3)
        # 原插件的纯文本样本同样适用
        raw = "\n".join([
            "积分：78",
            "每日签到\t积分 +1\t每日签到\t{} 00:56".format(TODAY),
            "积分规则\t积分 +2\t每天登录\t{} 00:27".format(TODAY),
        ])
        self.assertEqual(m.parse_credit_text(raw).today_gain, 1)

    def test_streak(self):
        self.assertEqual(m.parse_streak("签到打卡 已连续签到 3 天"), 3)
        self.assertIsNone(m.parse_streak("无"))

    def test_state_variants(self):
        # 签到后按钮变成「签到成功」：按钮消失 + 宽松文案 → 已签到
        html = "<div>已连续签到 4 天</div><button>签到成功</button>"
        self.assertEqual(m.read_state(_page(html)), "already")
        # 按钮还在，别处的「签到成功」提示不能算已签到
        html2 = "<div>上次签到成功</div><button>立即签到</button>"
        self.assertEqual(m.read_state(_page(html2)), "ready")
        # 绿联自绘页未签到文案：即使按钮文字改版也能识别
        self.assertEqual(m.read_state(_page("<div>今天还没有签到</div>")), "ready")
        # 论坛改版后可自定义已签到文案
        with patch.dict(os.environ, {"UGREEN_SIGNIN_ALREADY_KEYWORDS": "今日已打卡,明天见"}, clear=True):
            self.assertEqual(m.read_state(_page("<div>今日已打卡</div>")), "already")


class TestDiscover(unittest.TestCase):
    def test_official_endpoint_is_first(self):
        """抓包确认的官方接口必须是默认首选，且 formhash 只在表单体里。"""
        cfg = m.Config(cookies=[VALID_COOKIE])
        targets = m.discover_targets(_page(READY_HTML), cfg)
        t = targets[0]
        self.assertEqual(t.origin, "官方接口")
        self.assertEqual(t.method, "POST")
        self.assertEqual(t.url, "https://club.ugnas.com/plugin.php?id=ugreen_checkin&action=sign")
        self.assertEqual(t.data["checkinsubmit"], "yes")
        self.assertEqual(t.data["formhash"], "abc123def")
        self.assertNotIn("formhash", t.url, "抓包确认 formhash 只在 POST 表单体里")

    def test_official_endpoint_survives_strict(self):
        cfg = m.Config(cookies=[VALID_COOKIE], strict=True)
        targets = m.discover_targets(_page(READY_HTML), cfg)
        self.assertTrue(any(t.origin == "官方接口" for t in targets))
        self.assertFalse(any(t.origin == "候选接口" for t in targets))

    def test_official_endpoint_can_be_forced_get(self):
        cfg = m.Config(cookies=[VALID_COOKIE], method="GET", strict=True)
        t = m.discover_targets(_page(READY_HTML), cfg)[0]
        self.assertEqual(t.method, "GET")
        self.assertIn("formhash=abc123def", t.url)
        self.assertEqual(t.data, {})

    def test_form(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        targets = m.discover_targets(_page(FORM_HTML), cfg)
        form = [t for t in targets if t.origin == "页面表单"]
        self.assertEqual(len(form), 1)
        self.assertEqual(form[0].method, "POST")
        self.assertEqual(form[0].data.get("formhash"), "abc123def")
        self.assertEqual(form[0].data.get("signsubmit"), "yes")

    def test_link(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        targets = m.discover_targets(_page(LINK_HTML), cfg)
        links = [t for t in targets if t.origin == "按钮链接"]
        self.assertEqual(len(links), 1)
        self.assertIn("do=sign", links[0].url)

    def test_js_url(self):
        cfg = m.Config(cookies=[VALID_COOKIE], strict=True)
        targets = m.discover_targets(_page(JS_HTML), cfg)
        scripts = [t for t in targets if t.origin == "页面脚本"]
        self.assertTrue(scripts, "应能从 onclick 中还原签到 URL")
        self.assertIn("ac=do_sign", scripts[0].url)

    def test_manual_override(self):
        cfg = m.Config(
            cookies=[VALID_COOKIE], strict=True,
            submit_url="plugin.php?id=ugreen_checkin&ac=real&formhash={formhash}",
            submit_body="qdxq=1&todaysay=hi", method="POST",
        )
        targets = m.discover_targets(_page(READY_HTML), cfg)
        self.assertEqual(len(targets), 1, "手动指定应独占端点列表")
        self.assertEqual(targets[0].origin, "手动指定")
        self.assertEqual(targets[0].method, "POST")
        self.assertIn("formhash=abc123def", targets[0].url)
        self.assertEqual(targets[0].data["qdxq"], "1")

    def test_strict_disables_candidates(self):
        cfg = m.Config(cookies=[VALID_COOKIE], strict=True)
        self.assertFalse(any(t.origin == "候选接口" for t in m.discover_targets(_page(READY_HTML), cfg)))
        cfg2 = m.Config(cookies=[VALID_COOKIE])
        self.assertTrue(any(t.origin == "候选接口" for t in m.discover_targets(_page(READY_HTML), cfg2)))

    def test_form_fields_include_named_controls(self):
        html = """
        <form method="post" action="plugin.php?id=ugreen_checkin:sign&amp;operation=qiandao">
          <input type="hidden" name="formhash" value="abc123def" />
          <input type="radio" name="qdxq" value="kx" checked />
          <input type="radio" name="qdxq" value="ng" />
          <select name="qdmode"><option value="1">1</option><option value="2" selected>2</option></select>
          <textarea name="todaysay">hi</textarea>
          <button type="submit" name="signsubmit" value="yes">立即签到</button>
        </form>
        """
        cfg = m.Config(cookies=[VALID_COOKIE], strict=True)
        form = [t for t in m.discover_targets(_page(html), cfg) if t.origin == "页面表单"]
        self.assertEqual(len(form), 1)
        self.assertEqual(form[0].method, "POST")
        self.assertEqual(form[0].data["formhash"], "abc123def")
        self.assertEqual(form[0].data["qdxq"], "kx", "只取 checked 的单选")
        self.assertEqual(form[0].data["qdmode"], "2")
        self.assertEqual(form[0].data["todaysay"], "hi")
        self.assertEqual(form[0].data["signsubmit"], "yes", "提交按钮参数不能丢")

    def test_dsu_post_candidates(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        targets = m.discover_targets(_page(READY_HTML), cfg)
        posts = [t for t in targets if t.origin == "候选接口" and t.method == "POST"]
        self.assertTrue(posts, "应包含 DSU operation=qiandao 的 POST 形态")
        self.assertTrue(any("operation=qiandao" in t.url for t in posts))
        self.assertEqual(posts[0].data["qdxq"], "kx")
        self.assertEqual(posts[0].data["formhash"], "abc123def")


class TestFlow(unittest.TestCase):
    def test_success_with_recheck(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        client = ScriptedClient(cfg)
        r = client.run("账号1")
        self.assertEqual(r.status, "success")
        self.assertEqual(r.stats.balance, 78)
        self.assertEqual(r.stats.today_gain, 1)
        self.assertEqual(r.stats.streak, 4, "连续天数必须来自签到后的复核页")
        self.assertEqual(len(client.submits), 1, "官方接口应第一个命中，不再盲试猜测端点")
        self.assertEqual(client.submits[0][0], "POST")
        self.assertIn("action=sign", client.submits[0][1])
        self.assertIn("官方接口", r.extra)

    def test_official_submit_headers(self):
        """提交头需复刻抓包：AJAX / Origin / 表单编码。"""
        cfg = m.Config(cookies=[VALID_COOKIE], strict=True)
        client = ScriptedClient(cfg)
        client.run("账号1")
        self.assertTrue(client.submit_headers)
        h = client.submit_headers[0]
        self.assertEqual(h.get("X-Requested-With"), "XMLHttpRequest")
        self.assertEqual(h.get("Origin"), "https://club.ugnas.com")
        self.assertEqual(h.get("Referer"), m.CHECKIN_URL)
        self.assertIn("application/x-www-form-urlencoded", h.get("Content-Type", ""))

    def test_already_no_submit(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        client = ScriptedClient(cfg, signed=True)
        r = client.run("账号1")
        self.assertEqual(r.status, "already")
        self.assertEqual(client.submits, [])

    def _via_entry(self, cfg, **kwargs):
        """走真实入口 run_account，验证异常被收敛成 failed 结果。"""
        with patch.object(m, "UgreenHttp", lambda cookie, c: ScriptedClient(c, **kwargs)):
            return m.run_account(VALID_COOKIE, cfg, "账号1")

    def test_cookie_expired(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        r = self._via_entry(cfg, login=True)
        self.assertEqual(r.status, "failed")
        self.assertIn("登录已失效", r.message)
        # 客户端本身按约定抛异常，由入口统一转成结果
        with self.assertRaises(m.CookieExpiredError):
            ScriptedClient(cfg, login=True).run("账号1")

    def test_submit_not_confirmed(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        r = self._via_entry(cfg, never_sign=True)
        self.assertEqual(r.status, "failed")
        self.assertIn("未确认签到成功", r.message)

    def test_credit_fallback_confirms(self):
        """前置检查时没签到，提交后积分流水才出现 → 兜底复核判成功。"""
        cfg = m.Config(cookies=[VALID_COOKIE])
        client = ScriptedClient(cfg, never_sign=True, credit_signed_after_submit=True)
        r = client.run("账号1")
        self.assertEqual(r.status, "success")
        self.assertIn("积分记录确认", r.extra)
        self.assertTrue(client.submits)

    def test_precheck_skips_submit(self):
        """按钮还在但积分流水已有当天签到 → 前置确认后直接读积分，一个请求都不发。"""
        cfg = m.Config(cookies=[VALID_COOKIE])
        client = ScriptedClient(cfg, never_sign=True, credit_signed=True)
        r = client.run("账号1")
        self.assertEqual(r.status, "already")
        self.assertEqual(client.submits, [])
        self.assertEqual(r.stats.balance, 78)
        self.assertEqual(r.stats.today_gain, 1)
        self.assertEqual(r.stats.streak, 3)

    def test_page_urls_debug_listing(self):
        html = """<script>var a="plugin.php?id=ugreen_checkin&amp;ac=ajax";
        fetch('/api/checkin/sign?day=1');</script>"""
        urls = m._page_urls(html)
        self.assertTrue(any("plugin.php" in u for u in urls))
        self.assertTrue(any("/api/checkin/sign" in u for u in urls))

    def test_credit_confirms_today_detects_record(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        self.assertTrue(ScriptedClient(cfg, credit_signed=True).credit_confirms_today())
        self.assertFalse(ScriptedClient(cfg, credit_signed=False).credit_confirms_today())

    def test_credit_verify_can_be_disabled(self):
        cfg = m.Config(cookies=[VALID_COOKIE], credit_verify=False)
        r = self._via_entry(cfg, never_sign=True, credit_signed=True)
        self.assertEqual(r.status, "failed")

    def test_run_account_never_raises(self):
        cfg = m.Config(cookies=[VALID_COOKIE])
        r = m.run_account("bad-cookie", cfg, "账号1")
        self.assertEqual(r.status, "failed")
        self.assertIn("格式无效", r.message)
        r2 = m.run_account("a=1; b=2", cfg, "账号1")
        self.assertEqual(r2.status, "failed")
        self.assertIn("_auth", r2.message)

    def test_config_load_multi_account(self):
        with patch.dict(os.environ, {
            "UGREEN_COOKIE": VALID_COOKIE + "\n" + VALID_COOKIE,
            "UGREEN_SIGNIN_MODE": "browser",
            "UGREEN_SIGNIN_TIMEOUT": "999",
            "UGREEN_SIGNIN_NOTIFY": "false",
        }, clear=True):
            cfg = m.Config.load()
        self.assertEqual(len(cfg.cookies), 2)
        self.assertEqual(cfg.mode, "browser")
        self.assertEqual(cfg.timeout, 120)
        self.assertFalse(cfg.notify)


# ---------------------------------------------------------------- browser 模式
# 用假的 playwright 模块驱动真实 run_browser 流程，不联网、不需要 chromium。

class _FakeForum:
    """模拟论坛服务端状态：页面文案、积分流水、接口响应。"""

    def __init__(self, signed=False, login=False, credit_signed=None,
                 evaluate_fails=False, fetch_status=200, never_sign=False,
                 credit_signed_after_submit=False):
        self.signed = signed
        self.login = login
        self.credit_signed = credit_signed
        self.evaluate_fails = evaluate_fails
        self.fetch_status = fetch_status
        self.never_sign = never_sign
        self.credit_signed_after_submit = credit_signed_after_submit
        self.fetches = []
        self.clicks = []
        self.current = m.CHECKIN_URL

    def html_for(self, url):
        if self.login:
            return LOGIN_HTML
        if "ac=credit" in url:
            if self.credit_signed_after_submit and (self.fetches or self.clicks):
                return CREDIT_HTML
            show = self.credit_signed if self.credit_signed is not None else self.signed
            return CREDIT_HTML if show else CREDIT_EMPTY_HTML
        return ALREADY_HTML if self.signed else READY_HTML


class _FakeLocator:
    def __init__(self, forum, selector):
        self.forum = forum
        self.selector = selector

    @property
    def first(self):
        return self

    def click(self, timeout=None):
        self.forum.clicks.append(self.selector)
        if not self.forum.never_sign:
            self.forum.signed = True


class _FakePage:
    def __init__(self, forum):
        self.forum = forum
        self.url = forum.current

    def set_default_timeout(self, ms):
        pass

    def set_default_navigation_timeout(self, ms):
        pass

    def goto(self, url, **kwargs):
        self.forum.current = url
        self.url = url

    def content(self):
        return self.forum.html_for(self.forum.current or self.url)

    def reload(self, **kwargs):
        pass

    def evaluate(self, js, arg=None):
        if self.forum.evaluate_fails:
            raise RuntimeError("fetch blocked")
        self.forum.fetches.append(arg or {})
        if not self.forum.never_sign:
            self.forum.signed = True
        return {"status": self.forum.fetch_status, "text": "签到成功"}

    def locator(self, selector):
        return _FakeLocator(self.forum, selector)

    def wait_for_timeout(self, ms):
        pass

    def wait_for_function(self, *args, **kwargs):
        pass


class _FakeContext:
    def __init__(self, forum):
        self.forum = forum
        self.page = _FakePage(forum)

    def add_cookies(self, cookies):
        self.forum.cookies = cookies

    def new_page(self):
        return self.page


class _FakeBrowser:
    def __init__(self, forum):
        self.forum = forum

    def new_context(self, **kwargs):
        return _FakeContext(self.forum)


class _FakeChromium:
    def __init__(self, forum):
        self.forum = forum

    def launch(self, **kwargs):
        return _FakeBrowser(self.forum)


class _FakePlaywright:
    def __init__(self, forum):
        self.forum = forum

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def chromium(self):
        return _FakeChromium(self.forum)


def _install_fake_playwright(forum):
    pkg = types.ModuleType("playwright")
    sync = types.ModuleType("playwright.sync_api")
    sync.sync_playwright = lambda: _FakePlaywright(forum)
    pkg.sync_api = sync
    return {"playwright": pkg, "playwright.sync_api": sync}


class TestBrowserMode(unittest.TestCase):
    def _run(self, forum, **cfgkw):
        cfg = m.Config(cookies=[VALID_COOKIE], mode="browser", **cfgkw)
        with patch.dict(sys.modules, _install_fake_playwright(forum)):
            return m.run_browser(VALID_COOKIE, cfg, "账号1")

    def test_shared_helpers(self):
        t = m.official_submit("abc123def")
        self.assertEqual(t.method, "POST")
        self.assertEqual(t.data, {"checkinsubmit": "yes", "formhash": "abc123def"})
        g = m.official_submit("abc123def", "GET")
        self.assertIn("formhash=abc123def", g.url)
        self.assertEqual(g.data, {})
        self.assertTrue(m.credit_text_confirms_today(m.html_to_text(CREDIT_HTML)))
        self.assertFalse(m.credit_text_confirms_today(m.html_to_text(CREDIT_EMPTY_HTML)))

    def test_official_endpoint_in_browser(self):
        forum = _FakeForum()
        r = self._run(forum)
        self.assertEqual(r.status, "success")
        self.assertIn("官方接口", r.extra)
        self.assertEqual(len(forum.fetches), 1)
        arg = forum.fetches[0]
        self.assertEqual(arg["method"], "POST")
        self.assertIn("action=sign", arg["url"])
        self.assertIn("checkinsubmit=yes", arg["body"])
        self.assertIn("formhash=abc123def", arg["body"])
        self.assertEqual(forum.clicks, [], "接口成功时不应再点按钮")
        self.assertEqual(r.stats.balance, 78)
        self.assertEqual(r.stats.today_gain, 1)
        self.assertEqual(r.stats.streak, 4, "连续天数来自复核后的页面")

    def test_already_no_submit(self):
        forum = _FakeForum(signed=True)
        r = self._run(forum)
        self.assertEqual(r.status, "already")
        self.assertEqual(forum.fetches, [])
        self.assertEqual(forum.clicks, [])

    def test_precheck_skips_submit(self):
        forum = _FakeForum(credit_signed=True, never_sign=True)
        r = self._run(forum)
        self.assertEqual(r.status, "already")
        self.assertEqual(forum.fetches, [])
        self.assertEqual(forum.clicks, [])
        self.assertEqual(r.stats.balance, 78)

    def test_falls_back_to_click_when_fetch_fails(self):
        forum = _FakeForum(evaluate_fails=True)
        r = self._run(forum)
        self.assertEqual(r.status, "success")
        self.assertIn("点击按钮", r.extra)
        self.assertTrue(forum.clicks)

    def test_falls_back_to_click_on_non_2xx(self):
        forum = _FakeForum(fetch_status=404)
        r = self._run(forum)
        self.assertEqual(r.status, "success")
        self.assertTrue(forum.clicks)

    def test_credit_fallback_confirms(self):
        forum = _FakeForum(never_sign=True, credit_signed_after_submit=True)
        r = self._run(forum)
        self.assertEqual(r.status, "success")
        self.assertIn("积分记录确认", r.extra)
        self.assertEqual(forum.clicks, [])

    def test_not_confirmed_raises(self):
        forum = _FakeForum(never_sign=True)
        with self.assertRaises(m.CheckinError) as ctx:
            self._run(forum)
        self.assertIn("未确认签到成功", str(ctx.exception))

    def test_login_expired(self):
        with self.assertRaises(m.CookieExpiredError):
            self._run(_FakeForum(login=True))

    def test_manual_endpoint_respected(self):
        forum = _FakeForum()
        cfg = m.Config(
            cookies=[VALID_COOKIE], mode="browser", method="POST",
            submit_url="plugin.php?id=ugreen_checkin&ac=custom&formhash={formhash}",
            submit_body="x=1",
        )
        with patch.dict(sys.modules, _install_fake_playwright(forum)):
            r = m.run_browser(VALID_COOKIE, cfg, "账号1")
        self.assertEqual(r.status, "success")
        self.assertIn("ac=custom", forum.fetches[0]["url"])
        self.assertEqual(forum.fetches[0]["body"], "x=1")

    def test_missing_playwright(self):
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(m.CheckinError) as ctx:
                m.run_browser(VALID_COOKIE, m.Config(cookies=[VALID_COOKIE], mode="browser"), "账号1")
        self.assertIn("playwright", str(ctx.exception))

    def test_missing_chromium_gives_install_hint(self):
        class _BrokenChromium(_FakeChromium):
            def launch(self, **kwargs):
                raise RuntimeError(
                    "Executable doesn't exist at /root/.cache/ms-playwright/chrome ... "
                    "Please run: playwright install chromium"
                )

        class _PW(_FakePlaywright):
            @property
            def chromium(self):
                return _BrokenChromium(self.forum)

        forum = _FakeForum()
        pkg = types.ModuleType("playwright")
        sync = types.ModuleType("playwright.sync_api")
        sync.sync_playwright = lambda: _PW(forum)
        pkg.sync_api = sync
        with patch.dict(sys.modules, {"playwright": pkg, "playwright.sync_api": sync}):
            with self.assertRaises(m.CheckinError) as ctx:
                m.run_browser(VALID_COOKIE, m.Config(cookies=[VALID_COOKIE], mode="browser"), "账号1")
        self.assertIn("playwright install chromium", str(ctx.exception))

    def test_via_run_account(self):
        forum = _FakeForum()
        cfg = m.Config(cookies=[VALID_COOKIE], mode="browser")
        with patch.dict(sys.modules, _install_fake_playwright(forum)):
            r = m.run_account(VALID_COOKIE, cfg, "账号1")
        self.assertEqual(r.status, "success")
        self.assertIn("browser", r.extra)


class TestNotification(unittest.TestCase):
    def test_success_text(self):
        r = m.Result("账号1", "success", "签到成功", m.Stats(78, 1, 3, 3), "2026-11-16 08:00:12")
        title, body = m.build_notification([r])
        self.assertEqual(title, "绿联社区签到 · +1 积分 · 余额 78")
        self.assertIn("✅ 状态　签到成功", body)
        self.assertIn("💰 本次　+1 积分", body)
        self.assertIn("🏅 余额　78 积分", body)
        self.assertIn("🔥 连续　3 天", body)
        self.assertIn("🕘 时间　11-16 08:00", body)
        self.assertIn("再签 4 天可得 +5 积分", body)

    def test_failed_text(self):
        r = m.Result("账号1", "failed", "论坛登录已失效，请更新 Cookie", m.Stats(), "2026-11-16 08:00:12")
        title, body = m.build_notification([r])
        self.assertEqual(title, "绿联社区签到失败")
        self.assertIn("❌ 状态　签到失败", body)
        self.assertIn("💬 原因　论坛登录已失效", body)

    def test_multi_account(self):
        a = m.Result("账号1", "success", "签到成功", m.Stats(78, 1, 3, 3), "2026-11-16 08:00:12")
        b = m.Result("账号2", "failed", "Cookie 失效", m.Stats(), "2026-11-16 08:00:13")
        title, body = m.build_notification([a, b])
        self.assertIn("2 个账号", title)
        self.assertIn("1 失败", title)
        self.assertIn("【账号1】", body)
        self.assertIn("【账号2】", body)

    def test_notifier_no_channel_is_safe(self):
        with patch.dict(os.environ, {}, clear=True):
            m.Notifier().send("标题", "正文")  # 不应抛异常


if __name__ == "__main__":
    unittest.main(verbosity=2)
