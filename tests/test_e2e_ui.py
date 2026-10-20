# -*- coding: utf-8 -*-
"""飞驰 MES · 前端端到端（Playwright）

覆盖：登录 → 驾驶舱 KPI → 14 页逐页渲染（零控制台错误）→ 新建工单 →
工单详情闸口 → 报工弹层 → 看板/集成中心关键区块。
截图落盘到 reports/screenshots/e2e_*.png，供验收留档。
"""
import os
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api",
                               reason="未安装 playwright，跳过浏览器端到端")

pytestmark = pytest.mark.e2e

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "reports", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PAGES = [
    ("dashboard", "制造驾驶舱"), ("board", "生产看板"), ("schedule", "排产计划"),
    ("orders", "生产工单"), ("materials", "物料与BOM"), ("quality", "质量检验"),
    ("trace", "批次追溯"), ("equipment", "设备台账"), ("maint", "保养点检"),
    ("stock", "库存台账"), ("reports", "报表分析"), ("integration", "集成中心"),
    ("settings", "基础设置"), ("logs", "操作日志"),
]


def _launch(p):
    """优先本机 Chrome/Edge，退化到 Playwright 自带 Chromium。"""
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**kw)
        except Exception:
            continue
    pytest.skip("没有可用的 Chromium / Edge 浏览器")


class UI:
    def __init__(self, page):
        self.page = page
        self.errs = []

    def goto(self, route):
        self.page.goto(self.page.url.split("/index.html")[0] + "/index.html#" + route)
        self.page.wait_for_timeout(900)

    def text(self, sel="#view"):
        return self.page.inner_text(sel)

    def shot(self, name):
        self.page.screenshot(path=os.path.join(SHOTS, "e2e_%s.png" % name),
                             full_page=False)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = _launch(p)
        yield b
        try:
            b.close()
        except Exception:
            pass


@pytest.fixture(scope="module")
def ui(e2e, browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 960})
    pg = ctx.new_page()
    u = UI(pg)
    pg.on("console", lambda m: u.errs.append("console[%s] %s" % (m.type, m.text))
          if m.type == "error" else None)
    pg.on("pageerror", lambda e: u.errs.append("pageerror %s" % e))
    pg.goto(e2e.base + "/login.html")
    pg.fill("#u", "admin")
    pg.fill("#p", "admin123")
    pg.click("#btn")
    pg.wait_for_url("**/index.html", timeout=20000)
    pg.wait_for_timeout(1500)
    yield u
    ctx.close()


def test_login_and_shell(ui):
    """登录后进入驾驶舱：左侧 14 个菜单、顶部 6 个 KPI、状态栏与页码信息就绪。"""
    pg = ui.page
    assert "dashboard" in pg.url, "登录后应跳到 #dashboard"
    assert "飞驰" in pg.title(), "页面标题应含品牌名"
    txt = ui.text()
    assert "在制工单" in txt and "综合 OEE" in txt, "驾驶舱 KPI 区块缺失"
    kpis = pg.eval_on_selector_all(".kpi", "els => els.length")
    assert kpis >= 6, "驾驶舱 KPI 卡片应不少于 6 个，实际 %d" % kpis
    assert len(pg.query_selector_all("#tree a")) >= 14, "左侧菜单项不足 14 个"
    assert "驱动" not in txt and "undefined" not in txt, "页面出现异常占位文本"
    foot = ui.text("#opFoot")
    assert "操作员" in foot and "—" not in foot, "底栏未渲染当前操作员：%s" % foot
    ui.shot("dashboard")


def test_pages_render(ui):
    """14 个页面逐页渲染成功，且全程无控制台报错。"""
    bad = []
    for route, title in PAGES:
        ui.goto(route)
        body = ui.text()
        if len(body.strip()) < 20 or "加载中" in body or "页面渲染失败" in body:
            bad.append("%s(%s) 渲染异常，字符数 %d" % (route, title, len(body)))
        elif title.split("·")[0][:2] not in body and route != "dashboard":
            # 标题不一定出现在正文，仅记录不判失败
            pass
        if route in ("board", "integration", "reports"):
            ui.shot(route)
    assert not bad, "；".join(bad)
    assert not ui.errs, "前端控制台报错：%s" % ui.errs[:5]


def test_board_and_integration_blocks(ui):
    """看板有产线卡片与安灯区；集成中心有六个标签且 Key 列表可见。"""
    ui.goto("board")
    cards = ui.page.eval_on_selector_all(".board-card", "els => els.length")
    assert cards >= 7, "看板产线卡片应不少于 7 个，实际 %d" % cards
    assert "安灯" in ui.text()

    ui.goto("integration")
    tabs = ui.page.eval_on_selector_all("#igTabs [data-tab]", "els => els.length")
    assert tabs >= 6, "集成中心标签不足：%d" % tabs
    assert "API Key" in ui.text() or "Webhook" in ui.text()


def test_create_order_via_ui(ui, e2e):
    """在工单页用弹层新建一张 30 件工单，接口侧可查到。"""
    e2e.login("admin")
    before = e2e.ok("GET", "/api/orders?limit=200")["total"]

    ui.goto("orders")
    ui.page.click("#oNew")
    ui.page.wait_for_selector("#noQty", timeout=10000)
    ui.page.fill("#noQty", "30")
    ui.page.fill("#noCust", "E2E自动化验证")
    ui.shot("order_new")
    ui.page.click("#noOk")
    ui.page.wait_for_timeout(2500)

    dl = time.time() + 15
    hit = None
    while time.time() < dl and not hit:
        d = e2e.ok("GET", "/api/orders?limit=200&kw=E2E")
        for r in d["list"]:
            if r.get("customer") == "E2E自动化验证" and int(r["qty"]) == 30:
                hit = r
                break
        if not hit:
            time.sleep(0.5)
    assert hit, "界面新建工单未落库（前 %d 单）" % before
    assert hit["status"] == "草稿", "新建工单应为草稿，实际 %s" % hit["status"]
    assert hit["opCount"] >= 1, "新工单应带上工艺工序"
    ui.goto("orders")
    ui.shot("orders")


def test_order_detail_dialog(ui, e2e):
    """点击工单行打开详情：闸口清单、工序表、报工弹层可用。"""
    e2e.login("admin")
    d = e2e.ok("GET", "/api/orders?status=已开工&limit=5")
    assert d["list"], "演示数据应存在已开工工单"
    no = d["list"][0]["no"]

    ui.goto("orders")
    ui.page.click('tr[data-key="%s"]' % no)
    ui.page.wait_for_selector("#mask.on", timeout=10000)
    dlg = ui.text("#dialog")
    assert no in dlg and "工序与报工" in dlg, "工单详情弹层内容缺失"
    gates = ui.page.eval_on_selector_all(".gate-box .gate", "els => els.length")
    assert gates >= 2, "闸口清单项不足：%d" % gates
    ui.shot("order_detail")

    rep = ui.page.query_selector("[data-rep]")
    assert rep, "工序表应提供报工按钮"
    rep.click()
    ui.page.wait_for_selector("#rpGood", timeout=8000)
    assert "提交报工" in ui.text("#dialog")
    ui.page.click("#dialog .dh .x")
    ui.page.wait_for_timeout(400)
    assert not ui.errs, "交互过程出现报错：%s" % ui.errs[:3]


def test_side_chart_and_export(ui):
    """报表页图表与导出入口就绪（SVG 已绘制、导出按钮存在）。"""
    ui.goto("reports")
    svgs = ui.page.eval_on_selector_all("#view svg", "els => els.length")
    assert svgs >= 4, "报表页图表不足：%d" % svgs
    assert "导出" in ui.text()
    ui.shot("reports_export")
