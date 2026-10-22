#!/usr/bin/env node
/**
 * 麦门渠道官 · 前端计算引擎抽取器。
 *
 * 从 docs/index.html 中抽出与 decider.py 等价的计算函数，
 * 供 parity_check.py 与 Python 端逐场景对拍。
 *
 * 这样做的意义：页面上显示的「省 13.5 元」和 CLI 输出的「省 13.5 元」
 * 必须来自同一套逻辑。页面试算器是 decider.py 的复刻，
 * 对拍能防止两份实现随时间漂移。
 *
 * 用法：node parity_check.mjs
 * 输出：JSON 数组，每项是一个场景的完整计算结果。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const htmlPath = join(here, "..", "..", "..", "docs", "index.html");
const html = readFileSync(htmlPath, "utf8");

// 抽取 <script> 里的计算段（从标记注释行之后到标记注释行之前）
const startMarker = "---- 以下计算逻辑与 decider.py 保持一致 ----";
const endMarker = "---- 计算逻辑结束 ----";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker);
if (start < 0 || end < 0 || end <= start) {
  console.error("未能定位计算逻辑段落，index.html 结构可能已变更");
  process.exit(2);
}
// 取两个标记之间的代码，排除标记行本身（标记是 JS 注释，会被当作语法）
const body = html.slice(start + startMarker.length, end);

// 组装成一个可求值的模块。
// fmt() 定义在页面脚本更靠前的位置，不在计算段内，需一并注入，
// 否则 compare() 调用 fmt 会报 ReferenceError。
const mod = new Function(
  `var fmt = function(n){ return Math.abs(n - Math.round(n)) < 0.005 ? String(Math.round(n)) : n.toFixed(2); };
   ${body}
   return { bestCoupon, channelTotal, compare };`
)();

const { bestCoupon, channelTotal, compare } = mod;

// 场景定义：与 parity_check.py 中的 PY_SCENARIOS 一一对应
const SCENARIOS = [
  {
    name: "默认场景-巨无霸套餐",
    goods: 47, qty: 1, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0.5,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 6, threshold: 0, channel: "any", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  },
  {
    name: "外送券抵扣后持平",
    goods: 47, qty: 1, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0.5,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  },
  {
    name: "无券基线",
    goods: 47, qty: 1, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0.5,
    coupons: []
  },
  {
    name: "时间成本为零",
    goods: 47, qty: 1, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  },
  {
    name: "时间成本极高-外送反超",
    goods: 47, qty: 1, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 200, mc: 0.5,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  },
  {
    name: "高配送费",
    goods: 47, qty: 1, fee: 60, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0.5,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  },
  {
    name: "未达起送价",
    goods: 12, qty: 1, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0.5,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  },
  {
    name: "多份数",
    goods: 22, qty: 3, fee: 9, minOrder: 20, prepD: 25, prepP: 8, travel: 20, mc: 0.5,
    coupons: [
      { discount: 15, threshold: 40, channel: "pickup", on: true },
      { discount: 9, threshold: 30, channel: "delivery", on: true }
    ]
  }
];

const results = SCENARIOS.map((s) => {
  const goods = Math.round(s.goods * s.qty * 100) / 100;
  const d = channelTotal(
    { key: "delivery", label: "外送", coupons: s.coupons, fee: s.fee, minOrder: s.minOrder, prep: s.prepD, travel: 0 },
    goods, s.mc
  );
  const p = channelTotal(
    { key: "pickup", label: "到店自取", coupons: s.coupons, fee: 0, minOrder: 0, prep: s.prepP, travel: s.travel },
    goods, s.mc
  );
  const v = compare(d, p);
  return {
    name: s.name,
    goods,
    delivery: { total: d.total, grand: d.grand, coupon: d.coupon, available: d.available },
    pickup: { total: p.total, grand: p.grand, coupon: p.coupon, available: p.available },
    recommended: v.pick === "pickup" ? "到店自取" : v.pick === "delivery" ? "点外送" : v.pick === "tie" ? "持平" : "都不行"
  };
});

console.log(JSON.stringify(results, null, 2));
