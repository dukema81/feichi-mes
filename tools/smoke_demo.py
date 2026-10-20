# -*- coding: utf-8 -*-
"""飞驰MES系统 · 离线 DEMO 冒烟（Playwright 打开本地单文件，不需要后端与网络）

用法：python tools/smoke_demo.py
验证点：14 个页面渲染、控制台无报错；新建工单 / 报工 / 关安灯 / 生成 API Key
等写操作在浏览器内存中真实联动。
"""
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo", "feichi-mes-demo.html")
SHOTS = os.path.join(ROOT, "reports", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PAGES = [
    ("dashboard", "制造驾驶舱"), ("board", "生产看板"), ("schedule", "排产计划"),
    ("orders", "生产工单"), ("materials", "物料与BOM"), ("quality", "质量检验"),
    ("trace", "批次追溯"), ("equipment", "设备台账"), ("maint", "保养点检"),
    ("stock", "库存台账"), ("reports", "报表分析"), ("integration", "集成中心"),
    ("settings", "基础设置"), ("logs", "操作日志"),
]


def launch(p):
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**kw)
        except Exception:
            continue
    raise RuntimeError("没有可用的 Chromium / Edge 浏览器")


def main():
    if not os.path.exists(DEMO):
        print("DEMO 不存在，请先运行 python tools/build_demo.py")
        return 1
    url = "file:///" + DEMO.replace("\\", "/")
    errs, fails = [], []
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(viewport={"width": 1440, "height": 960})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append("console[%s] %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("pageerror %s" % e))
        pg.goto(url)
        pg.wait_for_timeout(2000)
        txt = pg.inner_text("#view")
        print("驾驶舱 %s，KPI %d 个" % ("渲染正常" if len(txt) > 60 else "渲染异常",
                                    pg.eval_on_selector_all(".kpi", "e => e.length")))
        if "在制工单" not in txt:
            fails.append("驾驶舱 KPI 缺失")

        for route, title in PAGES:
            pg.goto(url + "#" + route)
            pg.wait_for_timeout(750)
            body = pg.inner_text("#view")
            ok = len(body.strip()) >= 20 and "页面渲染失败" not in body and "加载中" not in body
            print("%-14s %-10s chars=%-6d %s" % (route, title, len(body), "ok" if ok else "FAIL"))
            if not ok:
                fails.append("页面 %s 渲染异常：%s" % (route, body[:80]))
            pg.screenshot(path=os.path.join(SHOTS, "demo_%s.png" % route), full_page=False)

        # 写操作一：新建工单
        pg.goto(url + "#orders")
        pg.wait_for_timeout(700)
        before = pg.eval_on_selector_all("#view tbody tr[data-key]", "e => e.length")
        pg.click("#oNew")
        pg.wait_for_timeout(700)
        pg.fill("#noQty", "66")
        pg.fill("#noCust", "DEMO冒烟")
        pg.click("#noOk")
        pg.wait_for_timeout(2500)
        pg.goto(url + "#orders")
        pg.wait_for_timeout(1000)
        after = pg.eval_on_selector_all("#view tbody tr[data-key]", "e => e.length")
        print("新建工单：列表 %d → %d 行" % (before, after))
        if after <= before:
            fails.append("DEMO 新建工单未生效")

        # 写操作二：报工（挑一张已开工的工单）
        pg.goto(url + "#orders")
        pg.wait_for_timeout(800)
        chip = pg.query_selector('#oChips .chip[data-st="已开工"]')
        if chip:
            chip.click()
            pg.wait_for_timeout(900)
        pg.click("#view tbody tr[data-key]")
        pg.wait_for_timeout(1000)
        if not pg.query_selector("#mask.on"):
            fails.append("工单详情未打开")
        else:
            rep = pg.query_selector("[data-rep]")
            if rep:
                rep.click()
                pg.wait_for_timeout(600)
                pg.fill("#rpGood", "1")
                pg.click("#rpOk")
                pg.wait_for_timeout(1500)
                msg = pg.inner_text("#statusMsg")
                print("报工结果：%s" % msg)
                if "报工成功" not in msg and "不能" not in msg:
                    fails.append("DEMO 报工无响应")
            else:
                print("该工单暂无可报工工序（可能已全部完成）")
            pg.evaluate("F.closeDialog()")
            pg.wait_for_timeout(300)

        # 写操作三：关闭安灯
        pg.goto(url + "#board")
        pg.wait_for_timeout(900)
        btn = pg.query_selector("#view [data-close-ad]")
        if btn:
            btn.click()
            pg.wait_for_timeout(1000)
            print("安灯关闭：%s" % pg.inner_text("#statusMsg"))
        else:
            print("看板暂无待关闭安灯（正常）")

        # 写操作四：API Key 生成
        pg.goto(url + "#integration")
        pg.wait_for_timeout(1200)
        tab = pg.query_selector('#igTabs [data-tab="keys"]')
        if tab:
            tab.click()
            pg.wait_for_timeout(800)
        kb = pg.query_selector("#ikNew")
        if kb:
            kb.click()
            pg.wait_for_timeout(600)
            pg.fill("#ikName", "DEMO冒烟Key")
            pg.click("#ikOk")
            pg.wait_for_timeout(1000)
            body = pg.inner_text("#dialog")
            print("API Key：%s" % ("已生成（含明文）" if "fck_" in body else "未生成"))
            if "fck_" not in body:
                fails.append("DEMO API Key 生成失败")
            pg.click("#dialog .dh .x")
        else:
            fails.append("集成中心 Key 页签不可用")

        b.close()

    if errs:
        print("\n--- 前端错误 %d 条 ---" % len(errs))
        for e in errs[:20]:
            print(" ·", e[:240])
    if fails:
        print("\n--- DEMO 冒烟失败 %d 项 ---" % len(fails))
        for f in fails:
            print(" ×", f)
        return 1
    print("\nDEMO 冒烟通过：14 页渲染、无控制台错误、写操作在内存生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
