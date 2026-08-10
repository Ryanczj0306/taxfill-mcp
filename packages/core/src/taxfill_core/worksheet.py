"""The onboarding worksheet — the canonical fill-in-the-blank intake surface (H3, N-3/N-5).

A zero-experience user has no idea what a tax interview will ask, so the first
``intake_checklist`` call on an empty profile hands them this worksheet: every
fact the interview needs, pre-shaped as DATE-RANGED tables (the real 2026-08-04
session showed one-word answers are the failure mode — "I'm in California" vs
"I moved from WA to CA on March 1" are different returns).

The module is the single runtime source: ``docs/INTAKE_WORKSHEET.md`` (English,
canonical) and ``docs/INTAKE_WORKSHEET.zh-CN.md`` (localization) must match
these constants byte-for-byte — ``test_worksheet.py`` enforces it, so editing
either side without the other fails CI. The strings live here (not read from
``docs/``) because the built wheel does not ship ``docs/``.
"""
from __future__ import annotations

__all__ = ["WORKSHEET_LANGUAGES", "intake_worksheet"]

_WORKSHEET_EN = """\
# Tax situation self-report worksheet (English — canonical)

> **What this is.** A fill-in-the-blank worksheet a tax-inexperienced user can complete
> *before* (or during) the agent interview, so the agent gets date-ranged facts instead of
> one-word answers. Sourced from the 2026-08-04 real session (see
> [`FIELD_NOTES.md`](FIELD_NOTES.md) — gap N-1/N-2/N-3). Localizations:
> [`INTAKE_WORKSHEET.zh-CN.md`](INTAKE_WORKSHEET.zh-CN.md). Both are emitted at runtime by
> `intake_checklist` via `taxfill_core.worksheet` (this file is sync-tested against that
> module).

**Three rules that matter more than the tables:**

1. **If you don't know, write "don't know."** Never guess. A guessed number gets copied
   onto a real form, which is far more dangerous than a blank.
2. **Everything about status or address gets a DATE RANGE**, never a single word.
   "I'm in California" and "I moved from WA to CA on March 1" are two completely
   different tax returns.
3. **One worksheet per person.** Two unmarried people (even living together, sharing
   expenses) are **two separate taxpayers** under U.S. tax law — each files their own
   return; they cannot file jointly. Fill in one worksheet each.

---

## Part 0 · What are you here to do

- [ ] File taxes for a year (which year: ______)
- [ ] Back-file earlier years (which years: ______)
- [ ] **Budget / plan a future year's taxes** (which year: ______) ← this produces no
      mailable form, only numbers

Privacy: **budgeting needs NO SSN / ITIN, no bank account number, no street number.**
Provide those only when a form is actually being prepared for mailing — and even then,
leaving them blank to hand-write is recommended.

---

## Part 1 · Identity and visa timeline

Citizenship (passport country): ____________　　First date you ever entered the U.S.: __________

U.S. citizen or green-card holder?　□ Yes　□ No

**Visa timeline** — starting from your first U.S. entry, in order, missing nothing.
**A change of status, a change of school, starting OPT, an H-1B taking effect — each gets
its own row.**

| # | Status (be specific) | Start date | End date ("present" if ongoing) | What you were doing |
|---|---|---|---|---|
| 1 | e.g. F-1 (enrolled — bachelor's/master's/PhD) | 2021-08-20 | 2025-05-15 | studying |
| 2 | e.g. F-1 OPT (12-month work authorization) | 2025-06-01 | 2026-05-31 | working full-time |
| 3 | e.g. F-1 STEM OPT (24-month extension) | | | |
| 4 | e.g. cap-gap (bridge after H-1B selection) | | | |
| 5 | e.g. H-1B (start = the I-797 start date) | 2026-10-01 | present | working full-time |
| 6 | | | | |

**Why this much detail:** during F-1 (including OPT/STEM OPT), your U.S. days do **not**
count toward the Substantial Presence Test, and your wages are **not subject to Social
Security / Medicare (FICA, 7.65%)**; the day an H-1B takes effect, both flip at once.
So "F-1 to H-1B" as five words computes to nothing — the whole difference is in the dates.

Commonly confused points — please confirm as you go:
- OPT belongs to **F-1**; it is not a separate visa.
- H-1B keys on the **start date on the I-797 approval notice** — not the day you heard,
  and not your onboarding date.
- If you **left the U.S.** during any period (home visits, travel), Part 2 must say so.

## Part 2 · Days in the U.S.

| Year | Total days in the U.S. that year (an estimate is fine — mark it "approx.") |
|---|---|
| Target year (______) | |
| Prior year (______) | |
| Two years prior (______) | |

Total **calendar years** you have held F-1 / J-1 student status (a stay spanning a year
boundary counts as two, even one day): ______

> These numbers decide whether you are a nonresident (1040-NR), a resident (1040), or
> dual-status (both). The student exemption has a cap (generally 5 calendar years) —
> after that, F-1 days start counting.

## Part 3 · Household (as of December 31 of the target year)

On that day you were:　□ Unmarried　□ Married (date: __________)　□ Widowed

If you live with a partner but are **not married**:
- Their name/alias: __________　Their status (visa + whether on OPT): __________
- → **They fill in their own copy of this worksheet**; you each file your own return.
  You **cannot** claim them as a dependent (a nonresident generally fails the dependent
  residency requirement), and you cannot file jointly.

Any children / dependents to claim?　□ No　□ Yes (name, birth year, SSN/ITIN or not: ______)

Marrying (or married) during the target year?　□ No　□ Yes (date __________)
> This one moves real money: after marriage, if both spouses are nonresidents the default
> is separate 1040-NRs; but where eligible, the §6013(g)/(h) election lets both file
> jointly as residents (MFJ) — different standard deduction, different brackets.

## Part 4 · States (the part most often missed — and most often overpaid)

**Do not write just one state name.** Cut the target year, January 1 through December 31,
into **segments**, one row each:

| From | To | I lived in (state + city) | I worked in (state) | Remote? | Employer/school's state |
|---|---|---|---|---|---|
| 01-01 | | | | □ Y □ N | |
| | | | | □ Y □ N | |
| | 12-31 | | | □ Y □ N | |

Confirm each trigger (tick them — this is how things stop getting missed):
- [ ] **Moved across state lines** during the year? Move-out/move-in dates: __________
- [ ] Living in state A while **working remotely for a company in state B**?
      (This often triggers returns in BOTH states.)
- [ ] **Business travel / short assignment** in another state over ~30 days? Which state,
      how many days: __________
- [ ] School in one state, internship in another?
- [ ] The state you lived in and **W-2 Box 15 (State) disagree**?
- [ ] Any period **outside the U.S.**? From/to: __________
- [ ] No-income-tax states (WA / TX / FL / NV / SD / WY / AK / TN / NH) still get their
      real date ranges — because the **other** segment in a taxing state means you file
      that state.

## Part 5 · Income and tax documents

**One row per W-2** (one per employer; a job-change year usually has 2+):

| Employer | Work state | Period | Box 1 wages | Box 2 fed withheld | Box 4 Social Security | Box 6 Medicare | Box 15 state | Box 17 state withheld |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
| | | | | | | | | |

> **Boxes 4 / 6 matter especially**: if an employer withheld FICA in error during OPT,
> that money comes back via Form 843 + 8316; if withholding did NOT start once H-1B took
> effect, the payroll needs fixing. For budgeting, these two boxes directly set take-home.

Other income (amount if any; "none" if none; "don't know" if unsure):

| Type | Document | Amount | Notes |
|---|---|---|---|
| Bank interest | 1099-INT | | |
| Dividends | 1099-DIV | | |
| Stock / crypto sales | 1099-B | | cost basis, buy/sell dates |
| RSU / option vests or exercises | usually inside the W-2 | | vest dates, share counts |
| Freelance / gig work | 1099-NEC | | |
| Tuition | 1098-T | | do scholarships exceed tuition? |
| Student-loan interest | 1098-E | | |
| Scholarship / fellowship / RA-TA exempt portion | 1042-S | | income code, withholding rate |
| Marketplace health coverage (healthcare.gov / state exchange) | 1095-A | | **always disclose it** — omitting it freezes the refund |
| Foreign income / foreign accounts | | | |

## Part 6 · Tax already paid (required to compute owe-vs-refund)

- Federal withheld (so far / projected full-year): __________
- State withheld: __________
- Quarterly estimated payments you made (Form 1040-ES): __________ (dates + amounts)
- Last year (____) you filed:　□ 1040　□ 1040-NR　□ didn't file
- Last year's AGI: __________　Last year's total tax: __________
  > These two numbers drive the §6654 safe harbor (generally: prepay 100% of last year's
  > tax, or 90% of this year's, and there is no underpayment penalty). For budgeting this
  > is the "should I pay in more now?" test.

## Part 7 · Forward-looking facts (budgeting only)

- Target-year salary / hourly rate + expected bonus: __________
- 401(k) contribution rate or amount: __________　　□ Roth　□ Traditional (pre-tax)
- HSA contribution: __________
- Expected stock sales / RSU vests: __________
- Moving (across state lines)? __________
- Status changing (H-1B start date, green-card queue, departure)? __________

---

## After you fill this in

Paste the worksheet to the agent (or save it as a file for the agent to read). The agent
will:

1. Use `residency` to classify NRA / RA / dual-status from your **visa timeline + day
   counts**, showing its reasoning;
2. Use `state_scope` to list which states you file and in what role (resident /
   nonresident / part-year) from your **state segments**;
3. Use `calc` + `estimate_refund` to produce cited numbers (**always labeled ESTIMATE**);
4. List anything missing as a **gap — it will not guess for you**.

⚠️ This toolchain produces a **review draft, not tax advice**; it does not e-file for
you. You verify every number, sign, and mail it yourself.
"""

_WORKSHEET_ZH_CN = """\
# 报税情况自述表（中文 / zh-CN）

> **What this is.** A fill-in-the-blank worksheet a tax-inexperienced user can complete
> *before* (or during) the agent interview, so the agent gets date-ranged facts instead of
> one-word answers. Sourced from the 2026-08-04 real session (see
> [`FIELD_NOTES.md`](FIELD_NOTES.md) — gap N-1/N-2/N-3). Canonical English version:
> [`INTAKE_WORKSHEET.md`](INTAKE_WORKSHEET.md) — both are emitted at runtime by
> `intake_checklist` via `taxfill_core.worksheet` (this file is the zh-CN localization
> and is sync-tested against that module).

**三条规则，比表格本身重要：**

1. **不知道就写「不知道」**，不要猜。猜出来的数字会被填进真表格，比空着危险得多。
2. **所有跟身份、住址有关的事都要写「日期段」**，不要写一个词。"我在加州" 和 "我 3 月 1 日从 WA 搬到 CA" 是两份完全不同的税表。
3. **一个人一份表。** 没结婚的两个人（哪怕同住、共同承担开销）在美国税法上是**两个独立纳税人**，各报各的，不能合报。请各填一份。

---

## 第 0 部分 · 你要做什么

- [ ] 报某一年的税（哪一年：______）
- [ ] 补报以前的年份（哪几年：______）
- [ ] **做未来的税务预算 / 规划**（哪一年：______）← 这份不产出可寄出的表，只算钱

隐私：**做预算完全不需要 SSN / ITIN、银行账号、地址门牌号。** 真要填表寄出时再给，而且建议
留空由你手写。

---

## 第 1 部分 · 身份与签证时间线

国籍（护照国家）：____________　　首次进入美国的日期：__________

美国公民或绿卡持有者？　□ 是　□ 否

**签证时间线** —— 从第一次来美国开始，按时间顺序，一段都不要漏。**换身份、换学校、开始 OPT、
H-1B 生效，都要单独一行。**

| # | 身份（写具体） | 开始日期 | 结束日期（还在就写"至今"） | 期间在做什么 |
|---|---|---|---|---|
| 1 | 例：F-1（在读，本科/硕士/博士） | 2021-08-20 | 2025-05-15 | 上学 |
| 2 | 例：F-1 OPT（12 个月实习许可） | 2025-06-01 | 2026-05-31 | 全职工作 |
| 3 | 例：F-1 STEM OPT（24 个月延期） | | | |
| 4 | 例：cap-gap（H-1B 抽中后的过渡期） | | | |
| 5 | 例：H-1B（生效日 = I-797 上的 start date） | 2026-10-01 | 至今 | 全职工作 |
| 6 | | | | |

**为什么要分这么细：** F-1（含 OPT/STEM OPT）期间，你在美国的天数**不算入**"实质居留测试"，
而且工资**不扣 Social Security / Medicare（FICA，7.65%）**；H-1B 生效那天起，两条同时反转。
所以 "F-1 转 H-1B" 只写这五个字，税是算不出来的——差别全在日期上。

常见搞混的点，请顺手确认：
- OPT 属于 **F-1**，不是另一种签证。
- H-1B 看的是 **I-797 批准函上的生效日**，不是你收到通知的日期、也不是入职日期。
- 如果中间**离开过美国**（回国、旅行），第 2 部分要写清楚。

## 第 2 部分 · 在美天数

| 年份 | 当年在美国的总天数（估计也行，写"约") |
|---|---|
| 目标年（______） | |
| 前一年（______） | |
| 前两年（______） | |

以 F-1 / J-1 学生身份**待过的日历年**一共几个（跨年算两个，哪怕只待一天）：______

> 这几个数字决定你是 nonresident（1040-NR）、resident（1040），还是 dual-status（两份都要）。
> 学生免除年数有上限（一般 5 个日历年），用完之后 F-1 的天数就开始计入了。

## 第 3 部分 · 家庭状况（按目标年 12 月 31 日）

那天你是：□ 未婚　□ 已婚（结婚日期：__________）　□ 丧偶

如果同住有伴侣但**没结婚**：
- 对方姓名/代称：__________　对方身份（签证 + 是否 OPT）：__________
- → **对方需要自己填一份这张表**，你们各报各的。你**不能**把对方当 dependent 报
  （非居民一般不符合 dependent 的居民身份要件），也不能合报。

有需要申报的子女 / 被抚养人吗？　□ 没有　□ 有（姓名、出生年、有无 SSN/ITIN：______）

目标年内计划结婚 / 已结婚？　□ 无　□ 有（日期 __________）
> 这一项金额影响很大：结婚后如果双方都是非居民，默认只能各报 1040-NR；但符合条件时可以做
> §6013(g)/(h) 选择，两人都按居民合报（MFJ），标准扣除和税率档都不同。

## 第 4 部分 · 州（最容易漏、也最容易多缴的一部分）

**不要只写一个州名。** 把目标年从 1 月 1 日到 12 月 31 日按时间**切成几段**，每段一行：

| 起 | 止 | 我住在（州 + 城市） | 我工作在（州） | 是否远程 | 雇主/学校所在州 |
|---|---|---|---|---|---|
| 01-01 | | | | □ 是 □ 否 | |
| | | | | □ 是 □ 否 | |
| | 12-31 | | | □ 是 □ 否 | |

逐条确认（勾一下，避免漏）：
- [ ] 目标年内**搬过家跨州**吗？搬入/搬出日期：__________
- [ ] 人在 A 州、**远程给 B 州的公司**上班吗？（这常触发两个州都要报）
- [ ] 到别的州**出差 / 短期驻场**超过约 30 天吗？哪个州、多少天：__________
- [ ] 学校在一个州、实习在另一个州吗？
- [ ] 住的州和 W-2 第 15 栏（Box 15 State）**不一致**吗？
- [ ] 年内有一段时间**不在美国**吗？起止：__________
- [ ] 无个人所得税的州（WA / TX / FL / NV / SD / WY / AK / TN / NH）也要照实写日期段——
      因为**另一段**在有税的州，就得报那个州。

## 第 5 部分 · 收入与税务文件

**每一份 W-2 一行**（有几个雇主就有几行；换工作那年通常 2 份以上）：

| 雇主 | 工作所在州 | 期间 | Box 1 工资 | Box 2 联邦扣缴 | Box 4 社保税 | Box 6 Medicare | Box 15 州 | Box 17 州扣缴 |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
| | | | | | | | | |

> **Box 4 / Box 6 特别重要**：如果你 OPT 期间雇主错扣了 FICA，这笔钱可以通过 Form 843 + 8316
> 要回来；如果 H-1B 生效后没开始扣，说明工资单要改。做预算时这两栏直接决定你到手多少。

其他收入（有就写金额，没有写"无"，不确定写"不知道"）：

| 类型 | 文件 | 金额 | 备注 |
|---|---|---|---|
| 银行利息 | 1099-INT | | |
| 股息 | 1099-DIV | | |
| 卖股票 / 加密货币 | 1099-B | | 成本价、买入卖出日期 |
| RSU / 期权 归属或行权 | 通常已在 W-2 里 | | 归属日、股数 |
| 自由职业 / 接活 | 1099-NEC | | |
| 学费 | 1098-T | | 奖学金是否超过学费 |
| 学生贷款利息 | 1098-E | | |
| 奖学金 / 助学金 / RA-TA 免税部分 | 1042-S | | 收入代码、扣缴率 |
| Marketplace 医保（healthcare.gov / 州交易所） | 1095-A | | **有就一定要说**，漏了退税会被冻结 |
| 海外收入 / 海外账户 | | | |

## 第 6 部分 · 已经交了多少税（算"还要补/能退"必需）

- 联邦已扣缴（到目前为止 / 预计全年）：__________
- 州已扣缴：__________
- 自己交过的季度预缴（Form 1040-ES）：__________ （日期 + 金额）
- 上一年（____ 年）报的是 □ 1040　□ 1040-NR　□ 没报
- 上一年的 AGI：__________　上一年的 total tax：__________
  > 这两个数用来算 §6654 安全港（一般：预缴达到上年税额的 100%，或本年应缴的 90%，就不罚
  > 少缴罚金）。做预算时这是"要不要现在补交"的判断依据。

## 第 7 部分 · 只跟"做预算"有关的前瞻信息

- 目标年的年薪 / 时薪 + 预计奖金：__________
- 401(k) 供款比例或金额：__________　　□ Roth　□ 传统（税前）
- HSA 供款：__________
- 预计卖股票 / RSU 归属：__________
- 会搬家吗（跨州）：__________
- 身份会变吗（H-1B 生效日、绿卡排队、离境）：__________

---

## 填完之后

把这张表贴给 agent（或存成文件让它读）。agent 会：

1. 用 `residency` 按你的**签证时间线 + 天数**判定 NRA / RA / dual-status，并给出推理过程；
2. 用 `state_scope` 按你的**州时间段**列出要报哪些州、以什么身份（居民 / 非居民 / 部分年）；
3. 用 `calc` + `estimate_refund` 出带出处的数字（**永远标注为 ESTIMATE**）；
4. 缺的信息**列成 gap，不会替你猜**。

⚠️ 这套工具产出的是**审阅草稿，不是税务建议**；不代你 e-file。最后你自己核对每个数字、
自己签名、自己寄出。
"""

_WORKSHEETS = {"en": _WORKSHEET_EN, "zh-CN": _WORKSHEET_ZH_CN}
WORKSHEET_LANGUAGES = tuple(sorted(_WORKSHEETS))


def intake_worksheet(language: str = "en") -> str:
    """The onboarding worksheet markdown in the requested language.

    Args:
        language: "en" (canonical) or "zh-CN".

    Returns:
        The full worksheet as markdown, ready to show a user or save to a file.
    """
    try:
        return _WORKSHEETS[language]
    except KeyError:
        raise ValueError(
            f"no worksheet for language {language!r} — available: {sorted(_WORKSHEETS)}"
        ) from None
