#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc.py 回归测试

运行：python3 test_calc.py

测试用例来自真实判例与法律边界：
  - A公司卓某案（2021-03-29 → 2022-12-06，判决认定 1 年 8 个月余，N=2）
  - 劳动合同法第 47 条关于"6 个月"的边界
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calc import months_between, severance_months, compute, DAYS_PER_MONTH_FOR_WAGE  # noqa: E402

FAILED = []


def check(name, got, expect):
    ok = got == expect
    print(f"{'✅' if ok else '❌'} {name:<44} 得到 {got} / 期望 {expect}")
    if not ok:
        FAILED.append(name)


print("=" * 78)
print("一、工龄（完整日历月数）计算")
print("=" * 78)
check("A案 2021-03-29→2022-12-06（判决认定20个月）",
      months_between(date(2021, 3, 29), date(2022, 12, 6)), 20)
check("差1天满6个月 2021-03-29→2021-09-28",
      months_between(date(2021, 3, 29), date(2021, 9, 28)), 5)
check("正好满6个月 2021-03-29→2021-09-29",
      months_between(date(2021, 3, 29), date(2021, 9, 29)), 6)
check("正好满1年 2021-03-29→2022-03-29",
      months_between(date(2021, 3, 29), date(2022, 3, 29)), 12)
check("1年5个月 2021-03-29→2022-08-29",
      months_between(date(2021, 3, 29), date(2022, 8, 29)), 17)
check("跨年且月末 2020-01-31→2021-01-30",
      months_between(date(2020, 1, 31), date(2021, 1, 30)), 11)

print()
print("=" * 78)
print("二、经济补偿月数 N（劳动合同法第 47 条）")
print("=" * 78)
check("不满6个月 → 0.5", severance_months(5), 0.5)
check("满6个月 → 1", severance_months(6), 1)
check("6个月以上不满1年 → 1", severance_months(11), 1)
check("满1年 → 1", severance_months(12), 1)
check("1年5个月 → 1.5", severance_months(17), 1.5)
check("1年6个月 → 2（按一年计）", severance_months(18), 2)
check("5年4个月 → 5.5", severance_months(64), 5.5)
check("10年整 → 10", severance_months(120), 10)

print()
print("=" * 78)
print("三、真实判例对照：A公司卓某案")
print("=" * 78)
r = compute({
    "city": "广州", "monthly_min_wage": 2300,
    "join_date": "2021-03-29", "end_date": "2022-12-06",
    "avg_monthly_wage": 18000, "claim_type": "N",
})
n_claim = [c for c in r["claims"] if c.key == "n"]
check("工龄（月）", r["meta"]["total_months"], 20)
check("N（月）", r["meta"]["n_months"], 2)
check("经济补偿金（元）= 法院判决 36,000", n_claim[0].amount, 36000)

print()
print("=" * 78)
print("四、封顶规则（劳动合同法第 47 条第 2 款）")
print("=" * 78)
r2 = compute({
    "city": "北京", "monthly_min_wage": 2540, "avg_wage_3x_cap": 35000,
    "join_date": "2011-01-01", "end_date": "2026-01-01",
    "avg_monthly_wage": 60000, "claim_type": "N",
})
check("基数被封顶为 35,000", r2["meta"]["base_used"], 35000)
check("年限被砍至 12", r2["meta"]["n_months"], 12)
check("封顶标记", r2["meta"]["cap_applied"], True)

print()
print("=" * 78)
print("五、工资拆分：基数按实际到手，不按合同")
print("=" * 78)
r3 = compute({
    "city": "深圳", "monthly_min_wage": 2700,
    "join_date": "2020-06-01", "end_date": "2025-09-30",
    "service_months_override": 64,
    "months_income": [20000] * 12,
    "claim_type": "2N",
})
check("2N = 2 × 5.5 × 20000 = 220,000",
      [c for c in r3["claims"] if c.key == "2n"][0].amount, 220000)

print()
print("=" * 78)
if FAILED:
    print(f"❌ {len(FAILED)} 项失败：")
    for f in FAILED:
        print(f"   - {f}")
    sys.exit(1)
print("✅ 全部通过")
print("=" * 78)
