#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
互联网/IT 外包劳动维权赔偿计算器

用法：
    python3 calc.py --demo                 # 跑内置样例，查看输出格式
    python3 calc.py --config case.json     # 【推荐】用 JSON 一次性输入（agent 场景）
    python3 calc.py --interactive          # 命令行交互问答
    python3 calc.py --config case.json --json    # 输出 JSON，便于程序处理

说明：
  - 计算结果为【估算】，不构成法律意见。各地裁审口径不同，以当地规定为准。
  - 社保、公积金为【行政追缴】项目，不属劳动仲裁受案范围，不计入可主张金额合计，
    单列展示（这两笔常常比赔偿金更可观）。
"""

import argparse
import json
import sys
from datetime import date

MONTHS_PER_YEAR = 12
DAYS_PER_MONTH_FOR_WAGE = 21.75   # (365 - 104) / 12


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def parse_date(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s))


def months_between(start, end):
    """
    完整的日历月数（用于计算工龄 / 经济补偿的 N）。

    例：2021-03-29 → 2022-03-29 = 12 个月（正好一整年）
        2021-03-29 → 2022-12-06 = 20 个月（另余 8 天，不足一月不计）
        2021-03-29 → 2021-09-28 = 5 个月（另余 30 天，不足一月不计）
    """
    total = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        total -= 1          # 最后一段不足一个日历月，不计入
    return max(total, 0)


def days_between(start, end):
    """剩余不足一月的天数。"""
    return (end - start).days


def years_between(start, end):
    return (end - start).days / 365.25


def severance_months(total_months):
    """
    经济补偿的月数 N（劳动合同法第 47 条）：
      满 1 年 → 1 个月；6 个月以上不满 1 年 → 按 1 年；不满 6 个月 → 0.5 个月
    """
    if total_months < 6:
        return 0.5
    full = total_months // 12
    rem = total_months % 12
    if rem >= 6:
        return full + 1
    elif rem > 0:
        return full + 0.5
    return float(full)


def money(x):
    return f"{x:,.0f}"


def line(char="-", width=78):
    return char * width


# --------------------------------------------------------------------------
# 核心计算
# --------------------------------------------------------------------------

class Claim:
    def __init__(self, key, name, amount, basis, evidence, confidence):
        self.key = key
        self.name = name
        self.amount = round(amount, 2)
        self.basis = basis
        self.evidence = evidence
        self.confidence = confidence      # ★ 1~5，谈判取舍依据
        self.tier = "core"                # core / normal / stretch

    @property
    def stars(self):
        return "★" * self.confidence + "☆" * (5 - self.confidence)


def compute(cfg):
    city = cfg.get("city", "未填写")
    min_wage = float(cfg.get("monthly_min_wage") or 0)
    cap = cfg.get("avg_wage_3x_cap") or 0          # 当地上年度职工月平均工资 3 倍
    cap = float(cap) if cap else None

    join = parse_date(cfg.get("join_date"))
    end = parse_date(cfg.get("end_date")) or date.today()

    # ---- 1. 基数 ---------------------------------------------------------
    incomes = cfg.get("months_income") or []
    if incomes:
        base = sum(float(x) for x in incomes) / len(incomes)
        base_note = f"近 {len(incomes)} 个月应得工资平均"
    else:
        base = float(cfg.get("avg_monthly_wage") or 0)
        base_note = "用户提供的月均应得工资"

    base_used = base
    cap_applied = False
    if cap and base > cap:
        base_used = cap
        cap_applied = True

    # ---- 2. 工龄 ---------------------------------------------------------
    if cfg.get("service_months_override"):
        total_months = int(cfg["service_months_override"])
        months_note = "用户指定（已合并换签主体的工龄）"
    elif join:
        total_months = months_between(join, end)
        months_note = f"{join} → {end}"
    else:
        total_months = 0
        months_note = "未填写"

    n_raw = severance_months(total_months)
    if cfg.get("severance_months") is not None:
        n_raw = float(cfg["severance_months"])
    n_months = n_raw

    capped_years = False
    if cap_applied and n_months > 12:
        n_months = 12
        capped_years = True

    years = round(total_months / 12, 2)

    # ---- 3. 解除类赔偿 ---------------------------------------------------
    claims = []
    claim_type = (cfg.get("claim_type") or "none").lower()

    if claim_type in ("2n", "违法解除", "illegal"):
        amt = 2 * n_months * base_used
        claims.append(Claim(
            "2n", "违法解除劳动合同赔偿金 (2N)", amt,
            f"劳动合同法第87条：2 × N({n_months}个月) × 月均基数 ¥{money(base_used)}",
            "解除通知书 + 公司举证不能（退项≠客观情况重大变化；违纪证据不足）",
            4))
    elif claim_type in ("n", "经济补偿", "severance"):
        amt = n_months * base_used
        claims.append(Claim(
            "n", "解除劳动合同经济补偿金 (N)", amt,
            f"劳动合同法第46、47条：N({n_months}个月) × 月均基数 ¥{money(base_used)}",
            "解除通知书 / 被迫解除通知书及送达回执",
            5))
    elif claim_type in ("n+1", "n_plus_1"):
        amt = n_months * base_used
        claims.append(Claim(
            "n", "解除劳动合同经济补偿金 (N)", amt,
            f"N({n_months}个月) × 月均基数 ¥{money(base_used)}",
            "解除通知书", 5))
        last = float(cfg.get("last_month_wage") or base)
        claims.append(Claim(
            "notice", "代通知金 (+1)", last,
            f"劳动合同法第40条 + 实施条例第20条：上一个月工资 ¥{money(last)}"
            f"（实务中代通知金是否适用3倍封顶存在争议，本工具未封顶）",
            "公司未提前30日书面通知的证据", 4))

    if cfg.get("notice_pay_alone"):
        last = float(cfg.get("last_month_wage") or base)
        claims.append(Claim(
            "notice", "代通知金 (+1)", last,
            f"未提前30日书面通知：上一个月工资 ¥{money(last)}",
            "公司未提前30日书面通知的证据", 3))

    # ---- 4. 待岗工资 / 生活费差额 ----------------------------------------
    oh = cfg.get("onhold") or {}
    if oh.get("enabled"):
        s = parse_date(oh.get("start_date"))
        e = parse_date(oh.get("end_date")) or end
        paid = float(oh.get("paid_per_month") or 0)
        ratio = float(oh.get("life_ratio") or 0.8)
        provided = bool(oh.get("provided_work"))
        m = oh.get("months") or (months_between(s, e) if s else 0)
        m = int(m)
        standard = float(oh.get("contract_wage") or base)
        life = min_wage if provided else min_wage * ratio
        daily = standard / DAYS_PER_MONTH_FOR_WAGE      # 日工资，用于不足整月时折算

        if m >= 1:
            should = standard + life * (m - 1)     # 第1个周期全额，之后生活费
            formula = (f"第1个月 ¥{money(standard)} + 之后 {m-1} 个月 × "
                       f"¥{money(life)}(最低工资×{ratio:g})")
        else:
            # 不足一个整月 → 按天折算（第一个工资支付周期内按原工资日标准）
            d = int(oh.get("days") or (days_between(s, e) if s else 0))
            d = max(d, 0)
            should = daily * d
            formula = (f"不足整月，按 {d} 天折算：日工资 ¥{money(daily)}"
                       f"(¥{money(standard)}÷21.75) × {d} 天")

        gap = max(should - paid * m, 0)
        gap_low = max((min_wage * ratio * max(m, 1)) - paid * m, 0)   # 若法院认定待岗合法
        claims.append(Claim(
            "onhold", "待岗期间工资/生活费差额", gap,
            f"工资支付暂行规定第12条｜{formula} − 实发 ¥{money(paid)}×{m}个月\n"
            f"    ⚠ 裁判口径区间：待岗不合法→按原工资补 ¥{money(gap)}；"
            f"待岗合法→仅按生活费补 ¥{money(gap_low)}；"
            f"法院也常【酌定】取中间值（A案、B案均酌定）",
            "待岗通知 + 打卡记录（证明仍出勤）+ 工资流水",
            4))

    # ---- 5. 单方降薪差额 -------------------------------------------------
    pc = cfg.get("paycut") or {}
    if pc.get("enabled"):
        before = float(pc.get("before") or base)
        after = float(pc.get("after") or 0)
        m = int(pc.get("months") or 0)
        gap = max((before - after) * m, 0)
        claims.append(Claim(
            "paycut", "单方降薪工资差额", gap,
            f"(原工资 ¥{money(before)} − 降薪后 ¥{money(after)}) × {m} 个月",
            "降薪通知 + 异议函（证明未同意）+ 工资流水 + 个税明细",
            5))

    # ---- 6. 加班费 -------------------------------------------------------
    ot = cfg.get("overtime") or {}
    if ot.get("enabled"):
        hourly = base_used / DAYS_PER_MONTH_FOR_WAGE / 8
        wd = float(ot.get("weekday_hours") or 0)
        we = float(ot.get("weekend_hours") or 0)
        hd = float(ot.get("holiday_hours") or 0)
        a_wd = hourly * wd * 1.5
        a_we = hourly * we * 2.0
        a_hd = hourly * hd * 3.0
        total_ot = a_wd + a_we + a_hd
        claims.append(Claim(
            "overtime", "加班费", total_ot,
            (f"小时工资 ¥{hourly:.1f}(月工资÷21.75÷8)："
             f"延时 {wd:g}h×150%=¥{money(a_wd)} ＋ 休息日 {we:g}h×200%=¥{money(a_we)} "
             f"＋ 法定节假日 {hd:g}h×300%=¥{money(a_hd)}"),
            "打卡记录(录屏) + 该时段工作产出(代码提交/工单/群消息) + 领导安排记录",
            3))
        claims[-1].tier = "stretch"

    # ---- 7. 未休年休假 ---------------------------------------------------
    al = cfg.get("annual_leave") or {}
    if al.get("enabled"):
        days = float(al.get("unused_days") or 0)
        daily = base_used / DAYS_PER_MONTH_FOR_WAGE
        amt = daily * 2.0 * days          # 300% 中 100% 已随工资发放，补足 200%
        claims.append(Claim(
            "annual_leave", "未休年休假工资 (300%中的200%)", amt,
            f"日工资 ¥{money(daily)}(月工资÷21.75) × 200% × {days:g} 天；"
            f"注意200%部分适用1年时效，实务仅支持近2年",
            "考勤/请假系统记录 + 公司未安排休假的证明（公司举证）",
            4))
        claims[-1].tier = "normal"

    # ---- 8. 年终奖 / 十三薪 ---------------------------------------------
    yb = cfg.get("year_end_bonus") or {}
    if yb.get("enabled"):
        annual = float(yb.get("annual_amount") or 0)
        mw = float(yb.get("months_worked") or 12)
        amt = annual * mw / 12
        claims.append(Claim(
            "bonus", "年终奖 / 十三薪（按在职月数折算）", amt,
            f"¥{money(annual)} × {mw:g}/12 个月；"
            f"薪金类必给；考核类适用最高法指导案例183号（非本人过失离职+完成年度工作→支持）",
            "Offer/薪酬确认书 + 往年发放记录 + 绩效合格证明",
            3))
        claims[-1].tier = "normal"

    # ---- 9. 公积金差额（行政追缴，不进仲裁） -----------------------------
    hf = cfg.get("housing_fund") or {}
    fund_gap = 0.0
    if hf.get("enabled"):
        m = int(hf.get("months") or 0)
        actual = float(hf.get("actual_base") or 0)
        should = float(hf.get("should_base") or base)
        rate = float(hf.get("rate") or 0.12)
        unit_ratio = float(hf.get("unit_share") or 0.5)   # 单位部分占比，通常0.5
        total_gap = max(should - actual, 0) * rate * 2 * m    # 单位+个人合计，全部进个人账户
        fund_gap = total_gap
        # 各市对缴存基数设有【上限】（多为当地社平工资 3 倍），超过部分不计
        cap = float(hf.get("base_cap") or 0)
        capped = False
        if cap and should > cap:
            should = cap
            capped = True
        total_gap = max(should - actual, 0) * rate * 2 * m
        fund_gap = total_gap
        hf_detail = {
            "months": m, "actual_base": actual, "should_base": should,
            "rate": rate, "capped": capped,
            "unit_part": total_gap * unit_ratio,
            "personal_part": total_gap * (1 - unit_ratio),
            "total": total_gap,
        }
    else:
        hf_detail = None

    # ---- 10. 社保差额（行政追缴，不进仲裁） ------------------------------
    si = cfg.get("social_insurance") or {}
    si_gap = 0.0
    if si.get("enabled"):
        m = int(si.get("months") or 0)
        actual = float(si.get("actual_base") or 0)
        should = float(si.get("should_base") or base)
        rate = float(si.get("employer_rate") or 0.28)
        si_gap = max(should - actual, 0) * rate * m
        si_detail = {
            "months": m, "actual_base": actual, "should_base": should,
            "employer_rate": rate, "employer_gap": si_gap,
        }
    else:
        si_detail = None

    # ---- 三档汇总 --------------------------------------------------------
    def s(tiers):
        return sum(c.amount for c in claims if c.tier in tiers)

    conservative = s({"core"})
    reasonable = s({"core", "normal"})
    aggressive = s({"core", "normal", "stretch"})

    # ---- 一裁终局检查 ------------------------------------------------------
    final_threshold = min_wage * 12 if min_wage else None

    return {
        "meta": {
            "city": city, "min_wage": min_wage,
            "join": str(join) if join else None,
            "end": str(end),
            "total_months": total_months, "years": years,
            "months_note": months_note,
            "n_months": n_months, "n_raw": n_raw,
            "base_raw": base, "base_used": base_used,
            "base_note": base_note,
            "cap_applied": cap_applied, "capped_years": capped_years,
            "final_threshold": final_threshold,
        },
        "claims": claims,
        "tiers": {
            "conservative": conservative,
            "reasonable": reasonable,
            "aggressive": aggressive,
        },
        "fund": hf_detail,
        "social": si_detail,
    }


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def render(r, as_json=False):
    if as_json:
        out = {
            "meta": r["meta"],
            "claims": [{"key": c.key, "name": c.name, "amount": c.amount,
                        "basis": c.basis, "evidence": c.evidence,
                        "confidence": c.confidence, "tier": c.tier}
                       for c in r["claims"]],
            "tiers": r["tiers"],
            "fund": r["fund"],
            "social": r["social"],
        }
        return json.dumps(out, ensure_ascii=False, indent=2)

    m = r["meta"]
    L = []
    L.append(line("="))
    L.append("互联网/IT 外包劳动维权 · 赔偿清单".center(70))
    L.append(line("="))
    L.append(f"城市：{m['city']}    月最低工资：¥{money(m['min_wage'])}")
    L.append(f"在职：{m['join']} → {m['end']}    "
             f"共 {m['total_months']} 个月（约 {m['years']} 年）  [{m['months_note']}]")
    L.append(f"经济补偿月数 N = {m['n_months']} 个月")
    L.append(f"月均工资基数：¥{money(m['base_raw'])}  →  "
             f"实际采用 ¥{money(m['base_used'])}   ({m['base_note']})")
    if m["cap_applied"]:
        L.append(f"  ⚠ 触发封顶：基数高于当地职工月平均工资3倍，按封顶值计算"
                 + ("，且年限砍至12年" if m["capped_years"] else ""))
    L.append("")

    L.append(line())
    L.append("【一】可主张金额明细（劳动仲裁 / 诉讼）")
    L.append(line())
    if not r["claims"]:
        L.append("（未填写任何主张项）")
    else:
        L.append(f"{'项目':<28}{'金额(元)':>14}   {'把握':<6}{'依据'}")
        L.append(line("-"))
        for c in r["claims"]:
            L.append(f"{c.name:<28}{money(c.amount):>14}   {c.stars:<6}")
            L.append(f"    └ 计算：{c.basis}")
            L.append(f"    └ 证据：{c.evidence}")
        L.append(line("-"))
        L.append(f"{'合计':<28}{money(sum(c.amount for c in r['claims'])):>14}")

    L.append("")
    L.append(line())
    L.append("【二】三档报价策略")
    L.append(line())
    t = r["tiers"]
    L.append(f"  保守档（几乎必得：主赔偿金 + 工资差额）      ¥{money(t['conservative'])}")
    L.append(f"  合理档（+ 年假 + 年终奖 + 代通知金）          ¥{money(t['reasonable'])}")
    L.append(f"  激进档（+ 全部加班费，用于开口报价）          ¥{money(t['aggressive'])}")
    L.append("")
    L.append("  → 谈判开口报【激进档】，落点【合理档】，底线【保守档】")
    L.append("  → 把握度 ★★★ 以下的项目，必要时可作为让步筹码砍掉换取快速到账")

    L.append("")
    L.append(line())
    L.append("【三】行政追缴（不计入仲裁，但往往是更大的一笔）")
    L.append(line())
    f = r["fund"]
    if f:
        L.append(f"  住房公积金欠缴")
        L.append(f"    期间 {f['months']} 个月 ｜ 实缴基数 ¥{money(f['actual_base'])} "
                 f"→ 应缴基数 ¥{money(f['should_base'])} ｜ 比例 {f['rate']*100:g}%")
        if f.get("capped"):
            L.append(f"    ⚠ 已按缴存基数上限 ¥{money(f['should_base'])} 封顶（各地上限多为社平工资3倍）")
        L.append(f"    应补缴进个人账户合计：¥{money(f['total'])} "
                 f"（其中单位部分 ¥{money(f['unit_part'])}，个人部分 ¥{money(f['personal_part'])}）")
        L.append(f"    ⚠ 估算值，最终以公积金中心核定为准（受基数上下限、比例、补缴起始月影响）")
        L.append(f"    路径：公积金中心(12329)投诉 → 责令限期办理 → 逾期申请法院强制执行")
        L.append(f"    时效：无时效限制，可追溯至入职首月（1999年4月起）")
    else:
        L.append("  住房公积金：未填写")
    L.append("")
    s = r["social"]
    if s:
        L.append(f"  社会保险基数差")
        L.append(f"    期间 {s['months']} 个月 ｜ 实缴基数 ¥{money(s['actual_base'])} "
                 f"→ 应缴基数 ¥{money(s['should_base'])} ｜ 单位费率 {s['employer_rate']*100:g}%")
        L.append(f"    单位应补缴约：¥{money(s['employer_gap'])}（另加每日万分之五滞纳金 + 1~3倍罚款）")
        L.append(f"    路径：12366 税务 / 12333 社保稽核投诉")
        L.append(f"    注意：补缴不属仲裁受案范围，这笔钱不进个人口袋，是【谈判施压的核心筹码】")
    else:
        L.append("  社会保险：未填写")

    L.append("")
    L.append(line())
    L.append("【四】程序提示")
    L.append(line())
    if m["final_threshold"]:
        th = m["final_threshold"]
        L.append(f"  一裁终局门槛（当地月最低工资×12）：¥{money(th)}")
        core = t["conservative"]
        if core <= th:
            L.append(f"  ✅ 保守档 ¥{money(core)} ≤ 门槛，可争取【一裁终局】"
                     f"——裁决作出即生效，公司不能起诉拖延")
        else:
            L.append(f"  ⚠ 保守档 ¥{money(core)} > 门槛，公司可起诉拖延。"
                     f"可考虑拆分请求或放弃超出部分换取终局")
    L.append("  时效：仲裁 1 年，自知道或应当知道权利被侵害之日起算；")
    L.append("        劳动报酬争议在职期间不受限，但终止后 1 年内必须提出")
    L.append("  加速：监察12333 + 税务12366 + 公积金12329 三线并行施压；")
    L.append("        立案时同步申请财产保全（48小时裁定）")
    L.append("")
    L.append("  ⚠ 本结果为估算，不构成法律意见。各地裁审口径存在差异，")
    L.append("     金额较大或情形复杂时请咨询当地执业律师（12348 法援热线）。")
    L.append(line("="))
    return "\n".join(L)


# --------------------------------------------------------------------------
# 内置样例 & 交互
# --------------------------------------------------------------------------

DEMO = {
    "city": "深圳",
    "monthly_min_wage": 2700,
    "avg_wage_3x_cap": 0,
    "join_date": "2021-06-01",
    "end_date": "2024-10-23",
    "avg_monthly_wage": 20000,
    "last_month_wage": 20000,
    "claim_type": "2N",
    "service_months_override": 40,
    "onhold": {
        "enabled": True,
        "start_date": "2024-09-01",
        "end_date": "2024-10-23",
        "paid_per_month": 2360,
        "life_ratio": 0.8,
        "provided_work": False,
        "contract_wage": 20000,
    },
    "paycut": {"enabled": False},
    "overtime": {"enabled": True, "weekday_hours": 300,
                 "weekend_hours": 240, "holiday_hours": 24},
    "annual_leave": {"enabled": True, "unused_days": 20},
    "year_end_bonus": {"enabled": True, "annual_amount": 40000, "months_worked": 10},
    "housing_fund": {"enabled": True, "months": 40, "actual_base": 2700,
                     "should_base": 20000, "rate": 0.12},
    "social_insurance": {"enabled": True, "months": 40, "actual_base": 2700,
                         "should_base": 20000, "employer_rate": 0.28},
}


def ask(prompt, default=None, cast=float, allow_empty=True):
    """带默认值的提问。"""
    suffix = f"  [默认 {default}]" if default is not None else ""
    try:
        raw = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    if not raw:
        if default is None and not allow_empty:
            return ask(prompt, default, cast, allow_empty)
        return default
    try:
        return cast(raw)
    except Exception:
        print("  ⚠ 输入无法解析，请重新输入")
        return ask(prompt, default, cast, allow_empty)


def interactive():
    print(line("="))
    print("IT 外包劳动维权 · 案件信息采集（直接回车用默认值）")
    print(line("="))
    cfg = {}
    cfg["city"] = ask("所在城市", "深圳", str)
    cfg["monthly_min_wage"] = ask("当地月最低工资（元）", 2700)
    cfg["avg_wage_3x_cap"] = ask("当地上年度职工月平均工资×3（封顶线，不知道填0）", 0)
    cfg["join_date"] = ask("入职日期 YYYY-MM-DD", "2021-06-01", str)
    cfg["end_date"] = ask("离职/拟离职日期 YYYY-MM-DD", str(date.today()), str)

    print("\n-- 工资基数 --")
    mode = ask("录入方式：1=给月均值  2=逐月录入12个月", 1, int)
    if mode == 2:
        incomes = []
        for i in range(1, 13):
            v = ask(f"  第{i}个月应得工资（含奖金补贴）", 0)
            incomes.append(v)
        cfg["months_income"] = incomes
    else:
        cfg["avg_monthly_wage"] = ask("解除前12个月平均【应得】工资（含奖金/补贴/提成）", 0)
    cfg["last_month_wage"] = ask("离职上一个月的工资（代通知金用）",
                                 cfg.get("avg_monthly_wage", 0))

    print("\n-- 工龄（换签过主体的按合并后总月数填） --")
    cfg["service_months_override"] = ask("合并后总在职月数（无换签直接回车按日期算）", 0)
    if not cfg["service_months_override"]:
        cfg["service_months_override"] = None

    print("\n-- 解除定性 --")
    print("  1=违法解除(2N)  2=经济补偿(N)  3=N+1(含代通知金)  0=暂不算")
    t = ask("选择", 1, int)
    cfg["claim_type"] = {1: "2N", 2: "N", 3: "N+1", 0: "none"}.get(t, "none")

    print("\n-- 待岗 --")
    if ask("是否涉及待岗？1=是 0=否", 0, int) == 1:
        cfg["onhold"] = {
            "enabled": True,
            "start_date": ask("  待岗开始日期", "2024-09-01", str),
            "end_date": ask("  待岗结束日期", str(date.today()), str),
            "paid_per_month": ask("  待岗期间每月实发", 0),
            "contract_wage": ask("  劳动合同约定月工资", cfg.get("avg_monthly_wage", 0)),
            "life_ratio": ask("  生活费比例（一般0.8，北京0.7）", 0.8),
            "provided_work": ask("  待岗期间是否提供了正常劳动？1=是 0=否", 0, int) == 1,
        }

    print("\n-- 单方降薪 --")
    if ask("是否涉及单方降薪？1=是 0=否", 0, int) == 1:
        cfg["paycut"] = {
            "enabled": True,
            "before": ask("  降薪前月工资", cfg.get("avg_monthly_wage", 0)),
            "after": ask("  降薪后月工资", 0),
            "months": ask("  持续月数", 0),
        }

    print("\n-- 加班 --")
    if ask("是否主张加班费？1=是 0=否", 0, int) == 1:
        cfg["overtime"] = {
            "enabled": True,
            "weekday_hours": ask("  工作日延时加班总小时数", 0),
            "weekend_hours": ask("  休息日加班总小时数", 0),
            "holiday_hours": ask("  法定节假日加班总小时数", 0),
        }

    print("\n-- 未休年休假 --")
    if ask("是否主张未休年休假？1=是 0=否", 0, int) == 1:
        cfg["annual_leave"] = {
            "enabled": True,
            "unused_days": ask("  未休天数（注意时效，实务只支持近2年）", 0),
        }

    print("\n-- 年终奖/十三薪 --")
    if ask("是否主张年终奖？1=是 0=否", 0, int) == 1:
        cfg["year_end_bonus"] = {
            "enabled": True,
            "annual_amount": ask("  全年应发金额", 0),
            "months_worked": ask("  当年度在职月数", 12),
        }

    print("\n-- 住房公积金 --")
    if ask("是否核查公积金差额？1=是 0=否", 1, int) == 1:
        cfg["housing_fund"] = {
            "enabled": True,
            "months": ask("  在职总月数", cfg.get("service_months_override") or 0),
            "actual_base": ask("  实际缴存基数（不知道填最低工资）",
                               cfg.get("monthly_min_wage", 0)),
            "should_base": ask("  应缴基数（填真实月均工资）",
                               cfg.get("avg_monthly_wage", 0)),
            "rate": ask("  单位缴存比例（如12%填0.12）", 0.12),
        }

    print("\n-- 社会保险 --")
    if ask("是否核查社保基数差？1=是 0=否", 1, int) == 1:
        cfg["social_insurance"] = {
            "enabled": True,
            "months": ask("  在职总月数", cfg.get("service_months_override") or 0),
            "actual_base": ask("  实际缴费基数", cfg.get("monthly_min_wage", 0)),
            "should_base": ask("  应缴基数", cfg.get("avg_monthly_wage", 0)),
            "employer_rate": ask("  单位综合费率（约0.26~0.30）", 0.28),
        }
    return cfg


def main():
    ap = argparse.ArgumentParser(description="IT 外包劳动维权赔偿计算器")
    ap.add_argument("--config", help="案件 JSON 文件路径")
    ap.add_argument("--demo", action="store_true", help="运行内置样例")
    ap.add_argument("--interactive", action="store_true", help="交互式录入")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
    elif args.interactive:
        cfg = interactive()
    elif args.demo:
        cfg = DEMO
    else:
        ap.print_help()
        print("\n提示：先跑 --demo 看输出格式，再参照 DEMO 结构准备 JSON。")
        return 0

    try:
        result = compute(cfg)
    except Exception as exc:
        print(f"计算出错：{exc}", file=sys.stderr)
        raise

    print(render(result, as_json=args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
