# -*- coding: utf-8 -*-
"""飞驰 MES · 业务内核单元测试（mes.py 纯函数）"""
import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "backend"))

from mes import (EQUIP_STATES, abc_classify, add_days, batch_state, bottleneck, can, can_move_wo,
                 availability, capacity_load, clamp, cpk, cpk_level, days_between, doc_no, downtime_top,
                 dumps, due_state, equip_available, equip_health, fai_conclusion, human_minutes,
                 inspect_conclusion, kit_rate, line_balance, loss_minutes, maint_health,
                 maint_state, manpower_efficiency, minutes_between, mtbf, mttr, norm_text, oee,
                 weighted_avg,
                 oee_level, pareto, parse_date, parse_time, patrol_conclusion, performance,
                 ppm, progress, quality_rate, r2, r4, ratio, scrap_rate, sha256, shift_of,
                 short_qty, sign_payload, sum_amount, takt_time, trace_chain, trace_up,
                 wo_gate, wo_index, wo_next, wo_stage_by_qty, yield_rate)


class TestNum:
    def test_r2_r4(self):
        assert r2("3.14159") == 3.14
        assert r4(0.123456) == 0.1235
        assert r2(None) == 0.0

    def test_ratio_zero_den(self):
        assert ratio(10, 0) == 0.0
        assert ratio(1, 4) == 0.25

    def test_clamp(self):
        assert clamp(1.5) == 1.0
        assert clamp(-0.2) == 0.0
        assert clamp(0.5) == 0.5

    def test_parse_date(self):
        assert parse_date("2026-10-20").isoformat() == "2026-10-20"
        assert parse_date("") is None
        assert parse_date("bad") is None

    def test_parse_time(self):
        t = parse_time("2026-10-20 08:30:00")
        assert t.hour == 8 and t.minute == 30
        assert parse_time("bad") is None

    def test_days_between(self):
        assert days_between("2026-10-01", "2026-10-20") == 19
        assert days_between("2026-10-20", "2026-10-01") == -19

    def test_minutes_between(self):
        assert minutes_between("2026-10-20 08:00:00", "2026-10-20 09:30:00") == 90

    def test_add_days(self):
        assert add_days("2026-10-20", 5) == "2026-10-25"
        assert add_days("2026-10-20", -25) == "2026-09-25"

    def test_doc_no(self):
        assert doc_no("WO", "2026-10-20", 3) == "WO20261020-0003"

    def test_norm_text(self):
        assert norm_text("  A B（C） ") == "ab(c)"

    def test_sha256(self):
        assert sha256("abc") == hashlib.sha256(b"abc").hexdigest()

    def test_dumps_sorted(self):
        assert dumps({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'

    def test_sign_payload(self):
        sig = sign_payload("sec", "123", "hello")
        expect = hmac.new(b"sec", b"123.hello", hashlib.sha256).hexdigest()
        assert sig == expect

    def test_sum_amount(self):
        assert sum_amount([{"amount": 1.5}, {"amount": 2.25}]) == 3.75


class TestPerm:
    def test_admin_all(self):
        for p in ("read", "write", "approve", "report", "inspect", "equip", "stock", "admin"):
            assert can("admin", p)

    def test_viewer_read_only(self):
        assert can("viewer", "read")
        assert not can("viewer", "write")

    def test_roles_defined(self):
        from mes import ROLE_LABEL, _PERM
        assert set(ROLE_LABEL) == set(_PERM)
        assert len(ROLE_LABEL) == 8


class TestWoMachine:
    def test_index(self):
        assert wo_index("草稿") == 0
        assert wo_index("已关闭") == 5
        assert wo_index("不存在") == -1

    def test_forward_only(self):
        assert can_move_wo("草稿", "已下达")
        assert can_move_wo("草稿", "已开工")          # 可跨级
        assert not can_move_wo("已开工", "已下达")     # 不能回退
        assert not can_move_wo("已关闭", "已开工")     # 终态锁定
        assert can_move_wo("已入库", "已关闭")

    def test_cancel_rules(self):
        assert can_move_wo("草稿", "已取消")
        assert can_move_wo("已开工", "已取消")
        assert not can_move_wo("已完工", "已取消")
        assert not can_move_wo("已入库", "已取消")

    def test_next(self):
        assert wo_next("草稿") == ["已下达", "已开工", "已完工", "已入库", "已关闭"]
        assert wo_next("已关闭") == []

    def test_gate_release(self):
        miss = wo_gate("已下达", {"qty": 0, "kitRate": 1, "bomOk": True, "routingOk": True})
        assert any("数量" in m for m in miss)
        miss2 = wo_gate("已下达", {"qty": 10, "kitRate": 0.9, "bomOk": True, "routingOk": True})
        assert any("齐套率" in m for m in miss2)
        assert wo_gate("已下达", {"qty": 10, "kitRate": 1.0, "bomOk": True, "routingOk": True}) == []

    def test_gate_start(self):
        base = {"status": "已下达", "qty": 10, "kitRate": 1, "bomOk": True, "routingOk": True,
                "faiPass": False, "equipOk": True, "hasOperator": True, "opsDone": False,
                "reportedQty": 0, "inspPass": False, "batchNo": "", "defects": 0}
        miss = wo_gate("已开工", base)
        assert any("首件" in m for m in miss)
        base["faiPass"] = True
        base["equipOk"] = False
        miss2 = wo_gate("已开工", base)
        assert any("设备" in m for m in miss2)

    def test_gate_finish(self):
        base = {"status": "已开工", "qty": 100, "reportedQty": 80, "opsDone": False}
        miss = wo_gate("已完工", base)
        assert len(miss) == 2

    def test_gate_stockin(self):
        base = {"status": "已完工", "inspPass": False, "batchNo": ""}
        miss = wo_gate("已入库", base)
        assert len(miss) == 2

    def test_gate_close(self):
        base = {"status": "已入库", "defects": 3}
        miss = wo_gate("已关闭", base)
        assert any("不良" in m for m in miss)

    def test_stage_by_qty(self):
        assert wo_stage_by_qty(100, 0, 0) == "已下达"
        assert wo_stage_by_qty(100, 50, 49) == "已开工"
        assert wo_stage_by_qty(100, 100, 98) == "已完工"

    def test_progress(self):
        assert progress(100, 50) == 0.5
        assert progress(100, 150) == 1.5  # 允许展示超产
        assert progress(0, 10) == 0.0

    def test_due_state(self):
        assert due_state("2026-10-01", "2026-10-20") == "逾期"
        assert due_state("2026-10-21", "2026-10-20") == "临期"
        assert due_state("2026-11-01", "2026-10-20") == "正常"
        assert due_state("", "2026-10-20") == "未排期"


class TestOee:
    def test_full(self):
        o = oee(480, 450, 60, 400, 396)
        assert o["availability"] == 0.9375
        assert o["performance"] == 0.8889
        assert o["quality"] == 0.99
        assert o["oee"] == 0.825
        assert o["downMin"] == 30

    def test_performance_clamp(self):
        assert performance(60, 200, 100) == 1.0

    def test_zero_guard(self):
        assert oee(0, 0, 0, 0, 0)["oee"] == 0.0
        assert availability(0, 100) == 0.0

    def test_loss(self):
        assert loss_minutes(480, 450) == 30
        assert loss_minutes(100, 500) == 0

    def test_level(self):
        assert oee_level(0.86) == "达标"
        assert oee_level(0.80) == "预警"
        assert oee_level(0.5) == "未达标"

    def test_quality_rate(self):
        assert quality_rate(98, 100) == 0.98


class TestQuality:
    def test_yield_scrap_ppm(self):
        assert yield_rate(99, 100) == 0.99
        assert scrap_rate(3, 100) == 0.03
        assert ppm(5, 10000) == 500

    def test_inspect_conclusion(self):
        assert inspect_conclusion(0, 0) == "待检"
        assert inspect_conclusion(50, 0) == "合格"
        assert inspect_conclusion(50, 1) == "让步接收"
        assert inspect_conclusion(50, 2) == "退货"

    def test_fai(self):
        assert fai_conclusion(0, 0) == "待检"
        assert fai_conclusion(5, 0) == "合格"
        assert fai_conclusion(5, 1) == "不合格"

    def test_patrol(self):
        assert patrol_conclusion(0) == "正常"
        assert patrol_conclusion(1) == "异常"

    def test_cpk_centered_high(self):
        v = cpk([99.7, 100.3], 99.7, 100.3)
        assert v == 0.2357
        assert cpk_level(v) == "不足"

    def test_cpk_insufficient_data(self):
        assert cpk([100], 0, 1) is None
        assert cpk([], 0, 1) is None
        assert cpk([5, 5, 5], 0, 10) is None

    def test_cpk_level(self):
        assert cpk_level(1.5) == "充足"
        assert cpk_level(1.1) == "偏低"

    def test_pareto(self):
        out = pareto([{"name": "a", "qty": 50}, {"name": "b", "qty": 30},
                      {"name": "c", "qty": 20}])
        assert [x["name"] for x in out] == ["a", "b", "c"]
        assert out[0]["cum"] == 0.5
        assert out[1]["cum"] == 0.8
        assert out[0]["key"] and out[1]["key"] and not out[2]["key"]


class TestKit:
    def test_all_ready(self):
        k = kit_rate([{"need": 10, "avail": 10}, {"need": 5, "avail": 8}])
        assert k["rate"] == 1.0 and k["qtyRate"] == 1.0 and not k["shortages"]

    def test_partial(self):
        k = kit_rate([{"need": 10, "avail": 10, "materialCode": "A"},
                      {"need": 5, "avail": 3, "materialCode": "B", "materialName": "乙", "unit": "件"}])
        assert k["rate"] == 0.5
        assert k["qtyRate"] == 0.8667
        assert k["shortages"][0]["short"] == 2

    def test_empty(self):
        assert kit_rate([])["rate"] == 0.0

    def test_short_qty(self):
        assert short_qty(10, 4) == 6
        assert short_qty(4, 10) == 0

    def test_abc(self):
        out = abc_classify([{"code": "a", "amount": 50}, {"code": "b", "amount": 25},
                            {"code": "c", "amount": 15}, {"code": "d", "amount": 10}])
        m = {x["code"]: x["abc"] for x in out}
        assert m["a"] == "A" and m["b"] == "A" and m["c"] == "B" and m["d"] == "C"
        assert out[0]["share"] == 0.5


class TestEquip:
    def test_states(self):
        assert set(EQUIP_STATES) == {"运行", "待机", "故障", "保养", "停机"}
        assert not equip_available("故障")
        assert equip_available("运行")

    def test_maint_state(self):
        assert maint_state("", "2026-10-20") == "未排程"
        assert maint_state("2026-10-15", "2026-10-20") == "逾期"
        assert maint_state("2026-10-24", "2026-10-20", 7) == "临期"
        assert maint_state("2026-12-01", "2026-10-20") == "正常"

    def test_maint_health(self):
        assert maint_health(2, 1) == "逾期"
        assert maint_health(0, 3) == "临期"
        assert maint_health(0, 0) == "正常"

    def test_equip_health(self):
        assert equip_health("故障", 0, 0) == "异常"
        assert equip_health("运行", 1, 0) == "待保养"
        assert equip_health("运行", 0, 2) == "异常"
        assert equip_health("运行", 0, 0) == "正常"

    def test_downtime_top(self):
        out = downtime_top([{"reason": "待料", "minutes": 60}, {"reason": "设备故障", "minutes": 30}])
        assert out[0]["reason"] == "待料"
        assert out[0]["share"] == 0.6667

    def test_mtbf_mttr(self):
        assert mtbf(1000, 4) == 250
        assert mtbf(500, 0) == 500
        assert mttr(120, 4) == 30
        assert mttr(120, 0) == 0


class TestLine:
    def test_takt(self):
        assert takt_time(480, 100) == 4.8
        assert takt_time(480, 0) == 0.0

    def test_balance(self):
        assert line_balance([10, 20, 30]) == 0.6667
        assert line_balance([]) == 0.0

    def test_bottleneck(self):
        assert bottleneck([10, 20, 30]) == 30

    def test_capacity(self):
        assert capacity_load(200, 400) == 0.5

    def test_efficiency(self):
        assert manpower_efficiency(90, 100) == 0.9
        assert manpower_efficiency(0, 0) == 0.0


class TestTrace:
    def test_batch_state(self):
        assert batch_state(0, 0, "", "2026-10-20") == "已耗尽"
        assert batch_state(10, 9, "2026-10-01", "2026-10-20") == "已过期"
        assert batch_state(10, 9, "2026-11-05", "2026-10-20") == "临期"
        assert batch_state(10, 9, "2027-10-01", "2026-10-20") == "正常"

    def test_trace_chain(self):
        edges = [{"parent": "B1", "child": "C1"}, {"parent": "B1", "child": "C2"},
                 {"parent": "C1", "child": "R1"}]
        out = trace_chain(edges, "B1")
        assert [x["batch"] for x in out] == ["B1", "C1", "C2", "R1"]
        depths = {x["batch"]: x["depth"] for x in out}
        assert depths["R1"] == 2

    def test_trace_chain_cycle_guard(self):
        edges = [{"parent": "A", "child": "B"}, {"parent": "B", "child": "A"}]
        assert len(trace_chain(edges, "A")) == 2

    def test_trace_up(self):
        edges = [{"parent": "B1", "child": "C1"}, {"parent": "C1", "child": "R1"}]
        assert trace_up(edges, "R1") == ["C1", "B1"]
        assert trace_up(edges, "B1") == []


class TestMisc:
    def test_shift(self):
        assert shift_of("2026-10-20 09:00:00") == "白班"
        assert shift_of("2026-10-20 17:30:00") == "中班"
        assert shift_of("2026-10-20 03:00:00") == "夜班"

    def test_weighted(self):
        assert weighted_avg([{"v": 10, "w": 2}, {"v": 20, "w": 2}], "v", "w") == 15

    def test_human_minutes(self):
        assert human_minutes(90) == "1 小时 30 分"
        assert human_minutes(45) == "45 分钟"
