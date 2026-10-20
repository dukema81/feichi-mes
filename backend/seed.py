# -*- coding: utf-8 -*-
"""飞驰 MES · 确定性演示数据（SEED 固定，每次重建结果一致）

数据规模：4 车间 / 7 产线 / 22 工位 / 24 设备 / 26 物料 / 12 BOM / 12 工艺路线 /
34 生产工单（覆盖 7 种状态）/ 120+ 报工 / 40+ 检验 / 30+ 不良 / 30 批次 / 340 设备日指标。
"""
import random
from datetime import date, datetime, time, timedelta

import db
import mes

SEED = 20261020
TODAY = date(2026, 10, 20)
RND = random.Random(SEED)


def d(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def t(offset, hour=8, minute=0):
    dt = datetime.combine(TODAY + timedelta(days=offset), time(0, 0)) + timedelta(hours=hour, minutes=minute)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


USERS = [
    ("admin", "admin123", "系统管理员", "admin", "信息部", "13800000000"),
    ("qianwei", "fc@2026", "钱伟", "plant_manager", "生产部", "13800000001"),
    ("liyun", "fc@2026", "李允", "planner", "计划部", "13800000002"),
    ("zhaolei", "fc@2026", "赵磊", "operator", "机加工车间", "13800000003"),
    ("sunqi", "fc@2026", "孙琪", "quality", "质量部", "13800000004"),
    ("zhouhang", "fc@2026", "周航", "equipment", "设备部", "13800000005"),
    ("wuping", "fc@2026", "吴萍", "warehouse", "仓储部", "13800000006"),
    ("chenmo", "fc@2026", "陈默", "planner", "计划部", "13800000007"),
    ("zhengguan", "fc@2026", "郑观", "viewer", "综合办", "13800000008"),
]

WORKSHOPS = [
    ("WS-01", "机加工车间", "赵磊", 48000, "启用", "CNC 加工、钣金成形"),
    ("WS-02", "SMT车间", "刘敏", 38400, "启用", "贴片、回流焊、插件"),
    ("WS-03", "总装车间", "王强", 52800, "启用", "整机装配、测试、老化"),
    ("WS-04", "包装车间", "陈静", 24000, "启用", "包装、打标、码垛"),
]

LINES = [
    ("LN-101", "精密加工线", "WS-01", "赵磊", 60, "运行", "CNC 四台"),
    ("LN-102", "钣金线", "WS-01", "孙鹏", 45, "运行", "冲压 + 折弯"),
    ("LN-201", "SMT-A线", "WS-02", "刘敏", 25, "运行", "高速贴片"),
    ("LN-202", "SMT-B线", "WS-02", "何芳", 30, "运行", "多品种小批量"),
    ("LN-301", "总装一线", "WS-03", "王强", 90, "运行", "网关类产品"),
    ("LN-302", "总装二线", "WS-03", "张勇", 110, "运行", "相机与控制器"),
    ("LN-401", "包装线", "WS-04", "陈静", 40, "运行", "成品包装"),
]

STATIONS = [
    ("ST-1011", "CNC 加工一工位", "LN-101", 10, "机加工"),
    ("ST-1012", "CNC 加工二工位", "LN-101", 20, "机加工"),
    ("ST-1013", "去毛刺工位", "LN-101", 30, "手工"),
    ("ST-1021", "冲压工位", "LN-102", 10, "冲压"),
    ("ST-1022", "折弯工位", "LN-102", 20, "钣金"),
    ("ST-1023", "焊接工位", "LN-102", 30, "焊接"),
    ("ST-2011", "锡膏印刷", "LN-201", 10, "SMT"),
    ("ST-2012", "高速贴片", "LN-201", 20, "SMT"),
    ("ST-2013", "回流焊", "LN-201", 30, "SMT"),
    ("ST-2014", "AOI 检测", "LN-201", 40, "检测"),
    ("ST-2021", "锡膏印刷", "LN-202", 10, "SMT"),
    ("ST-2022", "多功能贴片", "LN-202", 20, "SMT"),
    ("ST-2023", "回流焊", "LN-202", 30, "SMT"),
    ("ST-2024", "插件工位", "LN-202", 40, "手工"),
    ("ST-3011", "机壳预装", "LN-301", 10, "装配"),
    ("ST-3012", "主板装配", "LN-301", 20, "装配"),
    ("ST-3013", "整机测试", "LN-301", 30, "检测"),
    ("ST-3014", "老化", "LN-301", 40, "检测"),
    ("ST-3021", "镜头装配", "LN-302", 10, "装配"),
    ("ST-3022", "整机装配", "LN-302", 20, "装配"),
    ("ST-3023", "标定测试", "LN-302", 30, "检测"),
    ("ST-3024", "包装前检验", "LN-302", 40, "检测"),
    ("ST-4011", "装箱工位", "LN-401", 10, "包装"),
    ("ST-4012", "打标工位", "LN-401", 20, "包装"),
    ("ST-4013", "码垛工位", "LN-401", 30, "包装"),
]

EQUIP = [
    # code, name, type, line, station, vendor, model, buy_date, status
    ("EQ-0001", "立式加工中心 1#", "加工中心", "LN-101", "ST-1011", "海天精工", "VMC-850", "2022-03-15", "运行"),
    ("EQ-0002", "立式加工中心 2#", "加工中心", "LN-101", "ST-1012", "海天精工", "VMC-850", "2022-03-15", "运行"),
    ("EQ-0003", "数控车床 1#", "数控车床", "LN-101", "ST-1011", "沈阳机床", "CK-6150", "2021-06-20", "运行"),
    ("EQ-0004", "平面磨床", "磨床", "LN-101", "ST-1013", "无锡机床", "M7130", "2020-11-02", "待机"),
    ("EQ-0005", "气动冲床 160T", "冲床", "LN-102", "ST-1021", "扬力集团", "JH21-160", "2019-08-12", "运行"),
    ("EQ-0006", "数控折弯机", "折弯机", "LN-102", "ST-1022", "亚威股份", "PB-135", "2021-01-08", "运行"),
    ("EQ-0007", "激光焊接机", "焊接机", "LN-102", "ST-1023", "大族激光", "HW-1500", "2023-04-18", "故障"),
    ("EQ-0008", "全自动锡膏印刷机", "印刷机", "LN-201", "ST-2011", "DEK", "Horizon-03", "2022-07-01", "运行"),
    ("EQ-0009", "高速贴片机 1#", "贴片机", "LN-201", "ST-2012", "Yamaha", "YSM-20", "2022-07-01", "运行"),
    ("EQ-0010", "高速贴片机 2#", "贴片机", "LN-201", "ST-2012", "Yamaha", "YSM-20", "2022-07-01", "运行"),
    ("EQ-0011", "十温区回流焊", "回流焊", "LN-201", "ST-2013", "劲拓", "NS-1000", "2022-07-01", "运行"),
    ("EQ-0012", "在线 AOI", "AOI", "LN-201", "ST-2014", "德律", "TR-7500", "2023-02-14", "运行"),
    ("EQ-0013", "锡膏印刷机 B", "印刷机", "LN-202", "ST-2021", "DEK", "Horizon-02", "2020-05-09", "运行"),
    ("EQ-0014", "多功能贴片机", "贴片机", "LN-202", "ST-2022", "JUKI", "RS-1R", "2021-09-30", "保养"),
    ("EQ-0015", "八温区回流焊", "回流焊", "LN-202", "ST-2023", "劲拓", "NS-800", "2020-05-09", "运行"),
    ("EQ-0016", "自动插件线", "插件线", "LN-202", "ST-2024", "自研", "AI-200", "2019-12-01", "运行"),
    ("EQ-0017", "伺服拧紧机", "拧紧机", "LN-301", "ST-3011", "阿特拉斯", "QST-50", "2023-03-20", "运行"),
    ("EQ-0018", "伺服压装机", "压装机", "LN-301", "ST-3012", "TOX", "PC-30", "2022-10-11", "运行"),
    ("EQ-0019", "整机功能测试台", "测试台", "LN-301", "ST-3013", "自研", "FT-300", "2021-04-06", "运行"),
    ("EQ-0020", "高温老化柜", "老化柜", "LN-301", "ST-3014", "东莞宏展", "OZ-2000", "2020-02-25", "运行"),
    ("EQ-0021", "镜头装配台", "装配台", "LN-302", "ST-3021", "自研", "LA-100", "2022-08-08", "运行"),
    ("EQ-0022", "光学标定台", "标定台", "LN-302", "ST-3023", "自研", "CAL-50", "2023-06-15", "待机"),
    ("EQ-0023", "自动封箱机", "封箱机", "LN-401", "ST-4011", "永创", "FX-50", "2021-11-19", "运行"),
    ("EQ-0024", "激光打标机", "打标机", "LN-401", "ST-4012", "大族激光", "FM-20", "2022-01-25", "运行"),
    ("EQ-0025", "自动码垛机", "码垛机", "LN-401", "ST-4013", "发那科", "M-410", "2023-09-01", "停机"),
]

CYCLE = {
    "加工中心": 52, "数控车床": 38, "磨床": 30, "冲床": 18, "折弯机": 42, "焊接机": 55,
    "印刷机": 12, "贴片机": 9, "回流焊": 24, "AOI": 15, "插件线": 20, "拧紧机": 35,
    "压装机": 40, "测试台": 95, "老化柜": 120, "装配台": 60, "标定台": 150,
    "封箱机": 12, "打标机": 8, "码垛机": 10,
}

MATERIALS = [
    # code, name, spec, unit, category, mtype, safety, on_hand, cost, lead
    ("MT-1001", "铝合金板 6061-T6", "2.0×1220×2440", "张", "金属材料", "原材料", 120, 260, 185.0, 7),
    ("MT-1002", "冷轧钢板 SPCC", "1.2×1250×2500", "张", "金属材料", "原材料", 100, 180, 132.0, 7),
    ("MT-1003", "不锈钢板 SUS304", "1.5×1219×2438", "张", "金属材料", "原材料", 60, 74, 268.0, 10),
    ("MT-1004", "注塑外壳料 ABS", "本色 25kg/包", "包", "塑胶材料", "原材料", 40, 62, 320.0, 5),
    ("MT-1005", "PCB 板 4 层", "180×120mm", "片", "电子料", "原材料", 500, 820, 26.5, 12),
    ("MT-1006", "贴片电阻 0603", "10kΩ ±1%", "只", "电子料", "原材料", 20000, 86000, 0.012, 10),
    ("MT-1007", "贴片电容 0805", "100nF 50V", "只", "电子料", "原材料", 15000, 42000, 0.018, 10),
    ("MT-1008", "MCU 主控芯片", "STM32F407", "只", "电子料", "原材料", 800, 1260, 42.0, 28),
    ("MT-1009", "工业连接器", "RJ45 带屏蔽", "只", "电子料", "原材料", 1200, 980, 6.8, 14),
    ("MT-1010", "线束 300mm", "4P 端子", "根", "电子料", "原材料", 1000, 640, 4.2, 7),
    ("MT-1011", "内六角螺钉 M3×8", "不锈钢", "只", "标准件", "原材料", 30000, 128000, 0.08, 5),
    ("MT-1012", "包装彩盒", "240×180×90", "个", "包装材料", "原材料", 600, 1450, 3.6, 6),
    ("MT-2001", "机壳组件", "压铸 + 喷涂", "套", "结构件", "半成品", 200, 340, 78.0, 5),
    ("MT-2002", "控制板 PCBA", "4 层板贴装", "块", "电子组件", "半成品", 300, 520, 168.0, 5),
    ("MT-2003", "电源模块", "12V/2A", "个", "电子组件", "半成品", 250, 380, 62.0, 7),
    ("MT-2004", "传感器组件", "温湿度 + 震动", "套", "电子组件", "半成品", 180, 265, 145.0, 7),
    ("MT-2005", "显示屏组件", "4.3 寸 IPS", "套", "电子组件", "半成品", 150, 205, 128.0, 10),
    ("MT-2006", "线束总成", "整机内部走线", "套", "电子组件", "半成品", 300, 460, 32.0, 5),
    ("MT-2007", "包装组件", "彩盒 + 泡棉 + 说明书", "套", "包装材料", "半成品", 400, 690, 12.5, 4),
    ("MT-3001", "智能网关 GW-100", "4G + 双网口", "台", "整机", "成品", 120, 210, 880.0, 0),
    ("MT-3002", "智能网关 GW-200", "5G + 边缘计算", "台", "整机", "成品", 80, 96, 1680.0, 0),
    ("MT-3003", "工业相机 CAM-50", "500 万像素", "台", "整机", "成品", 60, 78, 2350.0, 0),
    ("MT-3004", "运动控制器 CTR-10", "8 轴脉冲", "台", "整机", "成品", 50, 64, 1980.0, 0),
    ("MT-3005", "传感器节点 SN-20", "LoRa 无线", "台", "整机", "成品", 150, 188, 460.0, 0),
    ("MT-3006", "边缘计算盒 EB-30", "4 核 8G", "台", "整机", "成品", 40, 32, 3200.0, 0),
    ("MT-3007", "配件包 ACC-01", "电源 + 支架 + 线缆", "套", "整机", "成品", 200, 320, 68.0, 0),
]

# 成品 BOM（半成品 / 原材料组合）
BOMS = {
    "MT-3001": [("MT-2001", 1), ("MT-2002", 1), ("MT-2003", 1), ("MT-2006", 1), ("MT-2007", 1)],
    "MT-3002": [("MT-2001", 1), ("MT-2002", 2), ("MT-2003", 1), ("MT-2006", 1), ("MT-2007", 1)],
    "MT-3003": [("MT-2001", 1), ("MT-2002", 1), ("MT-2004", 1), ("MT-2005", 1), ("MT-2007", 1)],
    "MT-3004": [("MT-2001", 1), ("MT-2002", 2), ("MT-2003", 2), ("MT-2006", 1), ("MT-2007", 1)],
    "MT-3005": [("MT-2001", 1), ("MT-2002", 1), ("MT-2004", 1), ("MT-2006", 1), ("MT-2007", 1)],
    "MT-3006": [("MT-2001", 1), ("MT-2002", 2), ("MT-2003", 1), ("MT-2004", 1), ("MT-2006", 1), ("MT-2007", 1)],
    "MT-3007": [("MT-2007", 1), ("MT-2003", 1), ("MT-2006", 1)],
    "MT-2001": [("MT-1001", 0.35), ("MT-1002", 0.2), ("MT-1011", 12)],
    "MT-2002": [("MT-1005", 1), ("MT-1006", 86), ("MT-1007", 42), ("MT-1008", 1), ("MT-1009", 4)],
    "MT-2003": [("MT-1005", 1), ("MT-1007", 28), ("MT-1008", 1), ("MT-1009", 2)],
    "MT-2004": [("MT-1005", 1), ("MT-1006", 64), ("MT-1007", 36), ("MT-1008", 1), ("MT-1010", 2)],
    "MT-2005": [("MT-1005", 1), ("MT-1007", 30), ("MT-1010", 1)],
    "MT-2006": [("MT-1010", 1), ("MT-1009", 3), ("MT-1011", 8)],
    "MT-2007": [("MT-1012", 1), ("MT-1004", 0.02)],
}

ROUTINGS = {
    "MT-3001": [("SMT 贴片", "ST-2012", "贴片机", 6.5, 9, 1),
                ("回流焊", "ST-2013", "回流焊", 4.0, 24, 0),
                ("整机装配", "ST-3012", "压装机", 8.0, 40, 1),
                ("功能测试", "ST-3013", "测试台", 5.0, 95, 1),
                ("包装入库", "ST-4011", "封箱机", 3.0, 12, 0)],
    "MT-3002": [("SMT 贴片", "ST-2012", "贴片机", 9.0, 9, 1),
                ("回流焊", "ST-2013", "回流焊", 5.0, 24, 0),
                ("整机装配", "ST-3012", "压装机", 11.0, 40, 1),
                ("功能测试", "ST-3013", "测试台", 7.0, 95, 1),
                ("包装入库", "ST-4011", "封箱机", 3.5, 12, 0)],
    "MT-3003": [("镜头装配", "ST-3021", "装配台", 8.0, 60, 1),
                ("整机装配", "ST-3022", "装配台", 10.0, 60, 1),
                ("标定测试", "ST-3023", "标定台", 12.0, 150, 1),
                ("包装入库", "ST-4011", "封箱机", 4.0, 12, 0)],
    "MT-3004": [("SMT 贴片", "ST-2012", "贴片机", 8.0, 9, 1),
                ("回流焊", "ST-2013", "回流焊", 4.5, 24, 0),
                ("整机装配", "ST-3012", "压装机", 9.0, 40, 1),
                ("老化", "ST-3014", "老化柜", 6.0, 120, 0),
                ("包装入库", "ST-4011", "封箱机", 3.5, 12, 0)],
    "MT-3005": [("SMT 贴片", "ST-2022", "贴片机", 5.0, 9, 1),
                ("回流焊", "ST-2023", "回流焊", 3.0, 24, 0),
                ("整机装配", "ST-3012", "压装机", 5.5, 40, 1),
                ("功能测试", "ST-3013", "测试台", 4.0, 95, 1),
                ("包装入库", "ST-4011", "封箱机", 2.5, 12, 0)],
    "MT-3006": [("SMT 贴片", "ST-2012", "贴片机", 10.0, 9, 1),
                ("回流焊", "ST-2013", "回流焊", 5.5, 24, 0),
                ("整机装配", "ST-3012", "压装机", 12.0, 40, 1),
                ("老化", "ST-3014", "老化柜", 8.0, 120, 0),
                ("包装入库", "ST-4011", "封箱机", 4.0, 12, 0)],
    "MT-3007": [("配件分装", "ST-3011", "拧紧机", 3.0, 35, 0),
                ("装箱", "ST-4011", "封箱机", 2.0, 12, 0)],
    "MT-2001": [("CNC 粗加工", "ST-1011", "加工中心", 7.0, 52, 1),
                ("CNC 精加工", "ST-1012", "加工中心", 9.0, 52, 1),
                ("去毛刺", "ST-1013", "磨床", 3.0, 30, 0)],
    "MT-2002": [("锡膏印刷", "ST-2011", "印刷机", 2.0, 12, 0),
                ("高速贴片", "ST-2012", "贴片机", 4.0, 9, 1),
                ("回流焊", "ST-2013", "回流焊", 3.0, 24, 0),
                ("AOI 检测", "ST-2014", "AOI", 2.0, 15, 1)],
    "MT-2003": [("锡膏印刷", "ST-2011", "印刷机", 1.5, 12, 0),
                ("高速贴片", "ST-2012", "贴片机", 3.0, 9, 1),
                ("回流焊", "ST-2013", "回流焊", 2.5, 24, 0)],
    "MT-2004": [("锡膏印刷", "ST-2021", "印刷机", 2.0, 12, 0),
                ("多功能贴片", "ST-2022", "贴片机", 4.5, 9, 1),
                ("回流焊", "ST-2023", "回流焊", 3.0, 24, 0)],
    "MT-2007": [("配件分装", "ST-3011", "拧紧机", 2.0, 35, 0),
                ("装箱", "ST-4011", "封箱机", 1.5, 12, 0)],
}

DEFECT_CODES = [
    ("DC-01", "尺寸超差", "机加工", "严重"),
    ("DC-02", "表面划伤", "外观", "一般"),
    ("DC-03", "虚焊", "焊接", "严重"),
    ("DC-04", "偏位", "贴装", "一般"),
    ("DC-05", "元件缺失", "贴装", "严重"),
    ("DC-06", "极性反", "贴装", "严重"),
    ("DC-07", "功能不良", "测试", "严重"),
    ("DC-08", "装配间隙", "装配", "一般"),
    ("DC-09", "螺丝滑牙", "装配", "一般"),
    ("DC-10", "标定超差", "测试", "严重"),
    ("DC-11", "包装破损", "包装", "轻微"),
    ("DC-12", "标签错误", "包装", "轻微"),
]

RULES = [
    ("oee_target", "OEE 目标值", "效率", 0.85, "", 1, "低于目标的 85% 触发预警"),
    ("scrap_warn_rate", "报废率预警", "质量", 0.03, "", 1, "单工单报废率超过即预警"),
    ("fai_required", "首件必检", "质量", 1, "", 1, "1=未做首件不得开工"),
    ("patrol_interval_min", "巡检间隔", "质量", 120, "分钟", 1, "超过间隔未巡检提示"),
    ("kit_block", "缺料禁止下达", "计划", 1, "", 1, "1=齐套率不足 100% 不允许下达"),
    ("maint_warn_days", "保养提前提醒", "设备", 7, "天", 1, "距下次保养日期小于该值提示临期"),
    ("cpk_min", "Cpk 下限", "质量", 1.33, "", 1, "关键特性过程能力下限"),
    ("over_report_tol", "超产容差", "生产", 0.05, "", 1, "报工累计超出计划数量的允许比例"),
]

# 工单模板：物料、数量、状态、计划开始偏移、产线、客户
WO_PLAN = [
    ("MT-3001", 200, "已入库", -26, "LN-301", "苏州智联科技"),
    ("MT-3001", 150, "已关闭", -32, "LN-301", "宁波华工自动化"),
    ("MT-3002", 80, "已入库", -22, "LN-301", "上海景行智能"),
    ("MT-3002", 60, "已完工", -12, "LN-301", "杭州锐驰"),
    ("MT-3003", 50, "已入库", -20, "LN-302", "苏州视觉检测"),
    ("MT-3003", 40, "已开工", 0, "LN-302", "无锡精密仪器"),
    ("MT-3004", 60, "已入库", -18, "LN-302", "常州华数"),
    ("MT-3004", 45, "已开工", -2, "LN-302", "南京工控"),
    ("MT-3005", 300, "已入库", -24, "LN-301", "广东物联"),
    ("MT-3005", 240, "已完工", -8, "LN-301", "佛山智造"),
    ("MT-3006", 30, "已入库", -16, "LN-301", "北京算力"),
    ("MT-3006", 25, "已开工", -1, "LN-301", "深圳边缘"),
    ("MT-3007", 400, "已入库", -14, "LN-401", "随整机发货"),
    ("MT-3007", 350, "已关闭", -28, "LN-401", "随整机发货"),
    ("MT-3001", 180, "已下达", 1, "LN-301", "苏州智联科技"),
    ("MT-3002", 70, "已下达", 2, "LN-301", "上海景行智能"),
    ("MT-3003", 45, "已下达", 3, "LN-302", "杭州视觉"),
    ("MT-3005", 260, "已下达", 1, "LN-301", "东莞智联"),
    ("MT-3004", 55, "已下达", 4, "LN-302", "常州华数"),
    ("MT-3006", 28, "已下达", 5, "LN-301", "北京算力"),
    ("MT-3001", 220, "已开工", -1, "LN-301", "苏州智联科技"),
    ("MT-3003", 35, "已开工", -2, "LN-302", "无锡精密仪器"),
    ("MT-3005", 280, "已开工", -1, "LN-301", "广东物联"),
    ("MT-3002", 55, "已开工", 0, "LN-301", "上海景行智能"),
    ("MT-3007", 300, "已完工", -5, "LN-401", "随整机发货"),
    ("MT-3001", 160, "已完工", -6, "LN-301", "宁波华工自动化"),
    ("MT-3004", 50, "已完工", -7, "LN-302", "南京工控"),
    ("MT-3006", 20, "已完工", -9, "LN-301", "深圳边缘"),
    ("MT-2002", 500, "已开工", -1, "LN-201", "半成品备库"),
    ("MT-2001", 300, "已完工", -4, "LN-101", "半成品备库"),
    ("MT-2003", 400, "已下达", 2, "LN-201", "半成品备库"),
    ("MT-3005", 150, "已完工", -4, "LN-301", "东莞智联"),
    ("MT-3002", 40, "已完工", -2, "LN-301", "上海景行智能"),
    ("MT-3001", 120, "草稿", 6, "LN-301", "待评审订单"),
    ("MT-3002", 40, "草稿", 7, "LN-301", "待评审订单"),
    ("MT-3003", 30, "草稿", 8, "LN-302", "待评审订单"),
    ("MT-2007", 500, "已取消", -10, "LN-401", "合并至 WO 后续批次"),
]

FINISHED = {"MT-3001", "MT-3002", "MT-3003", "MT-3004", "MT-3005", "MT-3006", "MT-3007"}


def load(cn):
    for u in USERS:
        cn.execute("INSERT INTO users(username,password,display_name,role,dept_code,phone,status,created_at)"
                   " VALUES(?,?,?,?,?,?,?,?)",
                   (u[0], db.sha256(u[1]), u[2], u[3], u[4], u[5], "在职", t(-200, 9)))
    for w in WORKSHOPS:
        cn.execute("INSERT INTO workshops(code,name,manager,capacity_min,status,remark) VALUES(?,?,?,?,?,?)", w)
    for ln in LINES:
        cn.execute("INSERT INTO lines(code,name,workshop,leader,takt_sec,status,remark) VALUES(?,?,?,?,?,?,?)", ln)
    for st in STATIONS:
        cn.execute("INSERT INTO stations(code,name,line,seq,type) VALUES(?,?,?,?,?)", st)
    for r in RULES:
        cn.execute("INSERT INTO rules(code,name,category,value,unit,enabled,remark) VALUES(?,?,?,?,?,?,?)", r)

    # 团队
    teams = [("TM-01", "机加一班", "WS-01", "赵磊", "赵磊、孙鹏、李强、王海", "白班"),
             ("TM-02", "机加二班", "WS-01", "孙鹏", "孙鹏、周杰、徐磊", "中班"),
             ("TM-03", "SMT 一班", "WS-02", "刘敏", "刘敏、何芳、陈曦、张倩", "白班"),
             ("TM-04", "总装一班", "WS-03", "王强", "王强、张勇、李娜、吴刚", "白班"),
             ("TM-05", "总装二班", "WS-03", "张勇", "张勇、刘洋、郑凯", "中班"),
             ("TM-06", "包装班", "WS-04", "陈静", "陈静、胡敏", "白班")]
    for tm in teams:
        cn.execute("INSERT INTO teams(code,name,workshop,leader,members,shift) VALUES(?,?,?,?,?,?)", tm)

    for e in EQUIP:
        code, name, typ, line, station, vendor, model, buy, status = e
        hours = round(RND.uniform(1200, 9800), 1)
        # 保养日期：约 1/5 逾期、1/5 临期
        if code in ("EQ-0005", "EQ-0013", "EQ-0016"):
            next_at = d(-RND.randint(1, 12))
        elif code in ("EQ-0002", "EQ-0009", "EQ-0019", "EQ-0023"):
            next_at = d(RND.randint(1, 6))
        else:
            next_at = d(RND.randint(10, 60))
        cn.execute("INSERT INTO equipment(code,name,type,line,station,vendor,model,buy_date,status,run_hours,"
                   "down_min,failures,last_maint_at,next_maint_at,oee_target)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, name, typ, line, station, vendor, model, buy, status, hours,
                    round(RND.uniform(60, 900), 1), RND.randint(0, 6),
                    d(-RND.randint(8, 40)), next_at, 0.85))
        cn.execute("INSERT INTO maint_plans(code,equipment,type,cycle_days,cycle_hours,last_at,next_at,owner,status)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   ("MP-" + code[-4:], code, "一级保养" if code[-1] in "13579" else "二级保养",
                    30 if code[-1] in "13579" else 90, 500, d(-RND.randint(8, 40)), next_at, "周航", "启用"))

    for m in MATERIALS:
        code, name, spec, unit, cat, mtype, safety, on_hand, cost, lead = m
        cn.execute("INSERT INTO materials(code,name,spec,unit,category,mtype,abc,safety_stock,on_hand,"
                   "std_cost,lead_days,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, name, spec, unit, cat, mtype, "C", safety, on_hand, cost, lead, "启用", t(-30, 10)))

    for i, (mat, items) in enumerate(BOMS.items()):
        code = "BOM-%s-%02d" % (mat[-4:], 1)
        cn.execute("INSERT INTO boms(code,material_code,version,status,remark,updated_at) VALUES(?,?,?,?,?,?)",
                   (code, mat, "V1.0", "已发布", "", t(-60, 9)))
        for j, (comp, qty) in enumerate(items):
            cn.execute("INSERT INTO bom_items(bom_code,component,qty,loss_rate,seq) VALUES(?,?,?,?,?)",
                       (code, comp, qty, 0.01 if FINISHED and j % 3 == 0 else 0.0, (j + 1) * 10))

    for i, (mat, steps) in enumerate(ROUTINGS.items()):
        rcode = "RT-%s-%02d" % (mat[-4:], 1)
        cn.execute("INSERT INTO routings(code,material_code,version,name,status,updated_at) VALUES(?,?,?,?,?,?)",
                   (rcode, mat, "V1.0", "%s 标准工艺" % mat, "已发布", t(-60, 9)))
        for j, (proc, station, etype, std, cycle, key) in enumerate(steps):
            cn.execute("INSERT INTO routing_steps(routing_code,seq,process,station,equip_type,std_min,cycle_sec,"
                       "is_key,remark) VALUES(?,?,?,?,?,?,?,?,?)",
                       (rcode, (j + 1) * 10, proc, station, etype, std, cycle, key, ""))

    for dc in DEFECT_CODES:
        cn.execute("INSERT INTO defect_codes(code,name,category,severity,remark) VALUES(?,?,?,?,?)",
                   (dc[0], dc[1], dc[2], dc[3], ""))

    # ------------------------------------------------------------ 工单
    finished_wos = []          # (no, material, qty, batch, day_offset)
    seq_by_day = {}
    for idx, (mat, qty, status, off, line, customer) in enumerate(WO_PLAN):
        day = d(off)
        k = day.replace("-", "")
        seq_by_day[k] = seq_by_day.get(k, 0) + 1
        no = "WO%s-%04d" % (k, seq_by_day[k])
        rcode = "RT-%s-%02d" % (mat[-4:], 1)
        bcode = "BOM-%s-%02d" % (mat[-4:], 1)
        ws = {"LN-101": "WS-01", "LN-102": "WS-01", "LN-201": "WS-02", "LN-202": "WS-02",
              "LN-301": "WS-03", "LN-302": "WS-03", "LN-401": "WS-04"}[line]
        team = {"WS-01": "TM-01", "WS-02": "TM-03", "WS-03": "TM-04", "WS-04": "TM-06"}[ws]
        owner = {"WS-01": "zhaolei", "WS-02": "liyun", "WS-03": "qianwei", "WS-04": "wuping"}[ws]
        span = 3 if qty < 100 else 5
        plan_start, plan_end = d(off), d(off + span)
        actual_start = t(off, 8, 30) if status in ("已开工", "已完工", "已入库", "已关闭") else ""
        actual_end = t(off + span - 1, 17, 30) if status in ("已完工", "已入库", "已关闭") else ""
        cn.execute("INSERT INTO work_orders(no,material_code,qty,workshop,line,priority,status,plan_start,"
                   "plan_end,actual_start,actual_end,routing_code,bom_code,sales_no,customer,planner,owner,"
                   "team,remark,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, mat, qty, ws, line, "紧急" if idx % 7 == 0 else "普通", status, plan_start, plan_end,
                    actual_start, actual_end, rcode, bcode, "SO-2026%04d" % (1000 + idx), customer,
                    "liyun", owner, team, "", t(off - 2, 9)))

        # 工序
        steps = ROUTINGS.get(mat, [("装配", "ST-3011", "装配台", 5.0, 30, 0)])
        progress = {"草稿": 0.0, "已下达": 0.0, "已开工": 0.55, "已完工": 1.0,
                    "已入库": 1.0, "已关闭": 1.0, "已取消": 0.0}[status]
        ops = []
        for j, (proc, station, etype, std, cycle, key) in enumerate(steps):
            op_plan = qty
            if status in ("已开工",) and j > 0:
                op_prog = 0.0 if j >= 2 else progress
            else:
                op_prog = progress
            good = round(op_plan * op_prog * RND.uniform(0.975, 0.995), 2) if op_prog else 0
            ng = round(op_plan * op_prog * RND.choice([0, 0, 0.004, 0.008, 0.015]), 2) if op_prog else 0
            eq = next((e[0] for e in EQUIP if e[2] == etype and e[3] == line), "")
            if not eq:
                eq = next((e[0] for e in EQUIP if e[2] == etype), "")
            op_status = "已完成" if op_prog >= 1 else ("进行中" if op_prog > 0 else "待开工")
            cn.execute("INSERT INTO wo_operations(wo_no,seq,process,station,equipment,plan_qty,good_qty,ng_qty,"
                       "std_min,actual_min,status,operator,start_at,end_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (no, (j + 1) * 10, proc, station, eq, op_plan, good, ng,
                        round(std * op_plan, 2), round(std * op_plan * RND.uniform(0.95, 1.18), 2) if op_prog else 0,
                        op_status, "zhaolei" if ws == "WS-01" else ("liyun" if ws == "WS-02" else "qianwei"),
                        t(off, 8, 30) if op_prog else "", t(off + j, 16, 0) if op_prog >= 1 else ""))
            ops.append({"seq": (j + 1) * 10, "process": proc, "eq": eq, "std": std,
                        "cycle": cycle, "good": good, "ng": ng, "prog": op_prog})

        # 用料
        for j, (comp, per) in enumerate(BOMS.get(mat, [])):
            need = round(per * qty * 1.01, 2)
            issued = need if status in ("已下达", "已开工", "已完工", "已入库", "已关闭") else round(need * 0.3, 2)
            state = "已齐套" if issued >= need else "待齐套"
            cn.execute("INSERT INTO wo_materials(wo_no,material_code,need_qty,issued_qty,unit,state)"
                       " VALUES(?,?,?,?,?,?)",
                       (no, comp, need, issued, "件", state))

        # 报工
        if status in ("已开工", "已完工", "已入库", "已关闭"):
            rep_no = 0
            for op in ops:
                if op["prog"] <= 0:
                    continue
                rep_no += 1
                q = round(op["good"] + op["ng"], 2)
                shift = ["白班", "中班"][rep_no % 2]
                cn.execute("INSERT INTO prod_reports(no,wo_no,seq,process,qty,good_qty,ng_qty,std_min,"
                           "actual_min,equipment,operator,batch_no,shift,reported_at,remark)"
                           " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("RP%s%02d-%02d" % (k, seq_by_day[k], rep_no), no, op["seq"], op["process"], q, op["good"], op["ng"],
                            round(op["std"] * q, 2), round(op["std"] * q * RND.uniform(0.96, 1.15), 2),
                            op["eq"], "zhaolei" if ws in ("WS-01", "WS-03") else "liyun",
                            "", shift, t(min(0, off + int(round((rep_no - 1) * (span - 1)
                                                             / max(1, len(ops) - 1)))), 9 + rep_no), ""))

        # 检验
        if status in ("已开工", "已完工", "已入库", "已关闭"):
            cn.execute("INSERT INTO inspections(no,wo_no,type,seq,process,sample_qty,defect_qty,result,"
                       "standard,inspector,inspected_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("IQ%s%02d-FAI" % (k, seq_by_day[k]), no, "首件", 10, ops[0]["process"], 5, 0, "合格",
                        "首件全尺寸检验", "sunqi", t(off, 9, 10), ""))
            for it in range(3):
                cn.execute("INSERT INTO inspection_items(inspection_no,item,value,lsl,usl,result)"
                           " VALUES(?,?,?,?,?,?)",
                           ("IQ%s%02d-FAI" % (k, seq_by_day[k]), ["长度(mm)", "宽度(mm)", "平面度(mm)"][it],
                            round(RND.uniform(99.9, 100.1), 3), 99.7, 100.3, "合格"))
            # 巡检
            if status in ("已开工", "已完工", "已入库", "已关闭"):
                cn.execute("INSERT INTO inspections(no,wo_no,type,seq,process,sample_qty,defect_qty,result,"
                           "standard,inspector,inspected_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("IQ%s%02d-P01" % (k, seq_by_day[k]), no, "巡检", ops[min(1, len(ops) - 1)]["seq"],
                            ops[min(1, len(ops) - 1)]["process"], 20, RND.choice([0, 0, 0, 1]),
                            "正常", "每 2 小时巡检", "sunqi", t(off, 14, 0), ""))
            # 末件 / 完工检
            if status in ("已完工", "已入库", "已关闭"):
                bad = RND.choice([0, 0, 0, 0, 1])
                concl = mes.inspect_conclusion(50, bad, 0.02)
                cn.execute("INSERT INTO inspections(no,wo_no,type,seq,process,sample_qty,defect_qty,result,"
                           "standard,inspector,inspected_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("IQ%s%02d-FQC" % (k, seq_by_day[k]), no, "完工检", ops[-1]["seq"], ops[-1]["process"], 50, bad,
                            concl, "GB/T 2828.1 抽样", "sunqi", t(off + span - 1, 16, 40), ""))

        # 不良
        if status in ("已开工", "已完工", "已入库", "已关闭") and RND.random() < 0.75:
            for dn in range(RND.choice([1, 1, 2])):
                dc = RND.choice(DEFECT_CODES)
                disp = "待处置" if status == "已开工" else RND.choice(["返修", "报废", "让步接收"])
                cn.execute("INSERT INTO defects(wo_no,inspection_no,defect_code,qty,process,equipment,operator,"
                           "occur_at,disposition,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (no, "IQ%s%02d-P01" % (k, seq_by_day[k]), dc[0], RND.choice([1, 1, 2, 3]),
                            ops[0]["process"], ops[0]["eq"], "zhaolei", t(off, 15 + dn, 0), disp, ""))

        # 批次
        if status in ("已入库", "已关闭"):
            bno = "B%s-%02d" % (k, seq_by_day[k])
            good_total = round(qty * RND.uniform(0.985, 0.998), 2)
            cn.execute("INSERT INTO batches(no,material_code,wo_no,qty,good_qty,workshop,line,produced_at,"
                       "expire_at,status,parent_batch,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (bno, mat, no, qty, good_total, ws, line, t(off + span - 1, 17, 0),
                        d(off + span - 1 + 730) if mat in FINISHED else d(off + span - 1 + 365),
                        "正常", "", ""))
            finished_wos.append((no, mat, qty, bno, off + span - 1))
            # 组件批次关联
            for comp, per in BOMS.get(mat, [])[:4]:
                cb = "B%s-C%02d" % (k, BOMS[mat].index((comp, per)) + 1)
                cn.execute("INSERT INTO batches(no,material_code,wo_no,qty,good_qty,workshop,line,"
                           "produced_at,expire_at,status,parent_batch,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (cb, comp, no, round(per * qty, 2), round(per * qty, 2), ws, line,
                            t(off + 1, 10), d(off + 400), "正常", bno, "组件批次"))
                cn.execute("INSERT INTO batch_links(parent_batch,child_batch,material_code,qty,wo_no)"
                           " VALUES(?,?,?,?,?)", (bno, cb, comp, round(per * qty, 2), no))

        # 库存
        if status in ("已入库", "已关闭"):
            cn.execute("INSERT INTO stocks(material_code,warehouse,batch_no,qty,updated_at) VALUES(?,?,?,?,?)",
                       (mat, "成品仓" if mat in FINISHED else "半成品仓",
                        "B%s-%02d" % (k, seq_by_day[k]), round(qty * 0.98, 2), t(off + span - 1, 18)))

    # 原料批次与库存 + 半成品库存
    for i, m in enumerate(MATERIALS):
        if m[5] == "半成品":
            cn.execute("INSERT INTO stocks(material_code,warehouse,batch_no,qty,updated_at)"
                       " VALUES(?,?,?,?,?)", (m[0], "半成品仓", "SF2609%03d" % (i + 1), m[7], t(-20, 10)))
            continue
        if m[5] != "原材料":
            continue
        bn = "RM2609%03d" % (i + 1)
        cn.execute("INSERT INTO batches(no,material_code,wo_no,qty,good_qty,workshop,line,produced_at,"
                   "expire_at,status,parent_batch,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (bn, m[0], "", m[7], m[7], "", "", t(-40, 10), d(300), "正常", "", "外购来料批次"))
        cn.execute("INSERT INTO stocks(material_code,warehouse,batch_no,qty,updated_at) VALUES(?,?,?,?,?)",
                   (m[0], "原料仓", bn, m[7], t(-40, 10)))

    # ------------------------------------------------------------ 设备日志与日指标
    for e in EQUIP:
        code, typ, status = e[0], e[2], e[8]
        prev = "运行"
        for k in range(6):
            off = -RND.randint(0, 12)
            reason = RND.choice(["换型调机", "待料", "设备故障", "计划保养", "待检", "其他"])
            mins = RND.choice([15, 20, 30, 45, 60, 90, 120])
            cn.execute("INSERT INTO equip_logs(equipment,status,prev_status,reason,minutes,wo_no,operator,"
                       "start_at,end_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (code, "停机" if reason != "计划保养" else "保养", prev, reason, mins, "", "zhouhang",
                        t(off, RND.randint(8, 20), 0), t(off, RND.randint(8, 20), 30)))
            prev = "运行"
        if status in ("故障", "保养", "停机"):
            cn.execute("INSERT INTO equip_logs(equipment,status,prev_status,reason,minutes,wo_no,operator,"
                       "start_at,end_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (code, status, "运行",
                        "设备故障" if status == "故障" else ("计划保养" if status == "保养" else "待料"),
                        120 if status == "故障" else 60, "", "zhouhang", t(0, 8, 0), ""))
        # 点检
        for k in range(3):
            cn.execute("INSERT INTO equip_checks(no,equipment,check_type,result,items_json,checker,checked_at,"
                       "remark) VALUES(?,?,?,?,?,?,?,?)",
                       ("EC-%s-%02d" % (code[-4:], k + 1), code, "日常点检",
                        "正常" if k < 2 else RND.choice(["正常", "异常"]),
                        '[{"item":"油位","result":"正常"},{"item":"气压","result":"正常"},{"item":"安全门","result":"正常"}]',
                        "zhouhang", t(-k, 8, 15), ""))
        # 日指标（14 天）
        cycle = CYCLE.get(typ, 40)
        base_out = max(20, int(480 * 60 / max(cycle, 8) * RND.uniform(0.8, 1.1)))
        for k in range(14):
            plan = 480 if k % 7 not in (5, 6) else 0
            if plan == 0:
                continue
            run = plan - RND.choice([0, 0, 10, 20, 35, 50, 75, 110])
            out = round(base_out * (run / 480) * RND.uniform(0.92, 1.05), 0)
            good = round(out * RND.uniform(0.972, 0.998), 0)
            cn.execute("INSERT INTO equip_metrics(equipment,day,plan_min,run_min,output,good,ideal_cycle)"
                       " VALUES(?,?,?,?,?,?,?)", (code, d(-k), plan, run, out, good, cycle))

    # 保养工单
    for i, e in enumerate(EQUIP[:12]):
        st = ["已完成", "已完成", "执行中", "待执行"][i % 4]
        cn.execute("INSERT INTO maint_orders(no,equipment,plan_code,type,reason,status,plan_at,start_at,"
                   "finish_at,downtime_min,cost,owner,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("MT2026%04d" % (900 + i), e[0], "MP-" + e[0][-4:],
                    "计划保养" if i % 3 else "故障维修", "月度保养" if i % 3 else "主轴异响",
                    st, d(-i * 2), t(-i * 2, 8) if st != "待执行" else "",
                    t(-i * 2, 12) if st == "已完成" else "",
                    120 if st == "已完成" else 0, 1200 + i * 150, "zhouhang", ""))

    # 安灯呼叫
    for i, (ln, st, typ, lvl, stt) in enumerate([
            ("LN-101", "ST-1012", "设备", "紧急", "待响应"),
            ("LN-201", "ST-2013", "质量", "一般", "处理中"),
            ("LN-301", "ST-3013", "物料", "一般", "已关闭"),
            ("LN-302", "ST-3023", "质量", "紧急", "已关闭")]):
        cn.execute("INSERT INTO andon(no,line,station,type,level,status,reporter,created_at,closed_at,remark)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("AD2026%04d" % (100 + i), ln, st, typ, lvl, stt, "zhaolei",
                    t(-i, 10 + i), t(-i, 12 + i) if stt == "已关闭" else "", "产线呼叫"))

    # 变更日志与集成
    cn.execute("INSERT INTO api_keys(name,key_hash,prefix,scope,owner,status,created_at,last_used_at)"
               " VALUES(?,?,?,?,?,?,?,?)",
               ("ERP 生产订单同步", db.sha256("fck_demo_erp_read"), "fck_demo", "read", "admin", "启用",
                t(-60, 9), t(-1, 10)))
    cn.execute("INSERT INTO webhooks(name,url,events,secret,status,created_at) VALUES(?,?,?,?,?,?)",
               ("MES → ERP 工单状态", "https://erp.example.com/hooks/mes", "wo.stage_changed,wo.reported",
                "whsec_demo_mes", "启用", t(-60, 9)))

    for no, mat, qty, bno, off in finished_wos[:8]:
        cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
                   ("work_order", no, "upsert", "qianwei",
                    mes.dumps({"no": no, "materialCode": mat, "qty": qty, "status": "已入库", "batch": bno}),
                    t(off, 18)))
    cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
               ("batch", finished_wos[0][3] if finished_wos else "B-DEMO", "upsert", "wuping",
                mes.dumps({"batch": finished_wos[0][3] if finished_wos else "B-DEMO"}), t(-3, 18)))

    cn.commit()
    if hasattr(cn, "commit"):
        pass
