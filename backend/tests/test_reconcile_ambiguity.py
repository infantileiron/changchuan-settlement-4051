"""reconcile 歧义翻译层与归档导出的集成测试。

生产 hungarian 依赖 SciPy/NumPy；本测试用纯 Python 参考实现替换
assign_with_reject（返回结构完全一致，含 expanded_matrix/assignment/
dual_u/dual_v/left_size/right_size），在无原生依赖环境验证：

1. 同额同日歧义被完整翻译为 external_id 口径，保留求解器原始分配；
2. 替代方案与基线目标总分相同、委托/凭证不重复占用；
3. 阶段二仍在第一阶段余项上运行，不重用已消耗分录；
4. 归档 CSV 与底稿同口径展示歧义，旧数据（无 ambiguity）兼容读取。
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.hungarian_reference import hungarian


class _NumpyStub:
 """仅满足 hungarian 模块导入期符号存在；运行期由纯 Python 替身取代。"""

 @staticmethod
 def full(shape, fill_value, dtype=None):
  rows, cols = shape
  return [[fill_value] * cols for _ in range(rows)]


# 无原生 SciPy/NumPy 环境下的导入桩；生产环境使用真实库。
if "numpy" not in sys.modules:
 sys.modules["numpy"] = types.SimpleNamespace(full=_NumpyStub.full)
if "scipy" not in sys.modules:
 scipy_stub = types.ModuleType("scipy")
 optimize_stub = types.ModuleType("scipy.optimize")
 optimize_stub.linear_sum_assignment = lambda *a, **k: (_ for _ in ()).throw(
  RuntimeError("测试应以纯 Python 替身替换 assign_with_reject"))
 scipy_stub.optimize = optimize_stub
 sys.modules["scipy"] = scipy_stub
 sys.modules["scipy.optimize"] = optimize_stub

from src.services import reconcile as reconcile_mod
from src.services import export_csv


def _pure_assign_with_reject(costs, reject_cost):
 """与生产 assign_with_reject 同结构的纯 Python 实现（仅测试替身）。"""
 m = len(costs)
 n = len(costs[0]) if m else 0
 if not m or not n:
  return {"matches": [], "unmatched_left": list(range(m)),
    "unmatched_right": list(range(n)),
    "objective": (m + n) * reject_cost}
 size = m + n
 finite = [v for row in costs for v in row if v is not None]
 forbidden = (size + 1) * (2 * reject_cost + max(finite, default=0) + 1)
 matrix = [[forbidden] * size for _ in range(size)]
 for i in range(m, size):
  for j in range(n, size):
   matrix[i][j] = 0.0
 for i, row in enumerate(costs):
  for j, value in enumerate(row):
   if value is not None:
    matrix[i][j] = float(value)
  matrix[i][n + i] = float(reject_cost)
 for j in range(n):
  matrix[m + j][j] = float(reject_cost)
 assignment, u, v = hungarian([row[:] for row in matrix])
 matches = []
 for i, j in enumerate(assignment):
  if i < m and j < n:
   assert costs[i][j] is not None
   matches.append({"left": i, "right": j, "cost": float(costs[i][j])})
 used_left = {x["left"] for x in matches}
 used_right = {x["right"] for x in matches}
 return {
  "matches": matches,
  "unmatched_left": [i for i in range(m) if i not in used_left],
  "unmatched_right": [j for j in range(n) if j not in used_right],
  "objective": sum(matrix[i][assignment[i]] for i in range(size)),
  "reject_cost_per_item": reject_cost,
  "forbidden_bound": forbidden,
  "expanded_matrix": [[None if matrix[i][j] >= forbidden / 2 else float(matrix[i][j])
            for j in range(size)] for i in range(size)],
  "assignment": assignment,
  "dual_u": [float(x) for x in u],
  "dual_v": [float(x) for x in v],
  "left_size": m,
  "right_size": n,
 }


POLICY = {
 "amount_tolerance": 0, "max_days": 7, "require_reference": True,
 "date_weight": 1.0, "reference_weight": 20.0, "reject_cost": 40.0,
 "max_candidates": 16, "max_group_size": 4, "max_group_amount": 2000000,
}


def item(ident, side, amount, party="同额客户", reference="JOB-X",
    booking_date="2026-11-03"):
 return {"external_id": ident, "side": side, "party": party,
   "reference": reference, "amount_cents": amount,
   "currency": "CNY", "booking_date": booking_date}


def test_same_amount_same_day_ambiguity_translated():
 reconcile_mod.assign_with_reject = _pure_assign_with_reject
 items = [
  item("M1", "milestone", 10000), item("M2", "milestone", 10000),
  item("R1", "receipt", 10000), item("R2", "receipt", 10000),
 ]
 result = reconcile_mod.reconcile(items, POLICY)
 amb = result["phase_one"]["ambiguity"]
 assert amb["status"] == "complete"
 assert amb["has_ambiguity"] is True
 # 四条同额兼容边都能进入某个最优方案。
 edge_keys = {(e["milestone_id"], e["receipt_id"])
       for e in amb["ambiguous_edges"]}
 assert edge_keys == {("M1", "R1"), ("M1", "R2"), ("M2", "R1"), ("M2", "R2")}
 # 唯一替代方案：交换配对；与基线都不重复占用。
 assert amb["alternative_count"] == 1
 baseline_pairs = {(p["milestone_id"], p["receipt_id"])
       for p in amb["baseline"]["pairs"]}
 alt = amb["alternatives"][0]
 alt_pairs = {(p["milestone_id"], p["receipt_id"]) for p in alt["pairs"]}
 assert baseline_pairs != alt_pairs
 assert baseline_pairs | alt_pairs == edge_keys
 for plan in [amb["baseline"], alt]:
  ms = [p["milestone_id"] for p in plan["pairs"]]
  rs = [p["receipt_id"] for p in plan["pairs"]]
  assert len(ms) == len(set(ms)) and len(rs) == len(set(rs))
 # 保留求解器原始分配：phase_one 与基线同口径。
 phase_pairs = {(m["milestone_ids"][0], m["receipt_id"])
         for m in result["phase_one"]["matches"]}
 assert phase_pairs == baseline_pairs
 print("OK same-amount ambiguity: 允许边", len(edge_keys),
       "替代方案", amb["alternative_count"], "原始分配保留")


def test_unique_solution_has_no_alternatives():
 reconcile_mod.assign_with_reject = _pure_assign_with_reject
 # 不同金额打破平局，唯一最优。
 items = [
  item("M1", "milestone", 10000, reference="JOB-1"),
  item("M2", "milestone", 20000, reference="JOB-2"),
  item("R1", "receipt", 10000, reference="JOB-1"),
  item("R2", "receipt", 20000, reference="JOB-2"),
 ]
 result = reconcile_mod.reconcile(items, POLICY)
 amb = result["phase_one"]["ambiguity"]
 assert amb["has_ambiguity"] is False
 assert amb["alternative_count"] == 0
 assert amb["alternatives_truncated"] is False
 print("OK unique solution: 无替代方案，has_ambiguity=False")


def test_csv_export_contains_ambiguity_section():
 reconcile_mod.assign_with_reject = _pure_assign_with_reject
 items = [
  item("M1", "milestone", 10000), item("M2", "milestone", 10000),
  item("R1", "receipt", 10000), item("R2", "receipt", 10000),
 ]
 result = reconcile_mod.reconcile(items, POLICY)
 csv_text = export_csv.build_reconciliation_csv(result)
 assert csv_text.startswith("﻿")
 assert "ambiguity_summary" in csv_text
 assert "ambiguous_edge" in csv_text
 assert "alternative_plan" in csv_text
 assert "截断不等于无歧义" not in csv_text  # 完整枚举时不应出现截断文案
 print("OK csv export: 含歧义说明区块，与底稿同口径")


def test_csv_export_legacy_result_without_ambiguity():
 # 旧数据：phase_one 无 ambiguity 字段，仍可导出且明确标注不可据此判定无歧义。
 legacy = {
  "phase_one": {"matches": [], "objective_with_rejections": 80.0,
          "compatible_edges": 0},
  "phase_two": {"groups": [], "searches": []},
  "unmatched": {"receipts": [], "milestones": []},
  "policy": {"amount_tolerance": 0, "max_days": 7},
  "input_sha256": "deadbeef",
 }
 csv_text = export_csv.build_reconciliation_csv(legacy)
 assert "ambiguity_note" in csv_text
 assert "旧版运行结果" in csv_text
 print("OK legacy export: 旧数据兼容读取，并标注不代表无歧义")


def test_phase_two_does_not_reuse_phase_one_items():
 reconcile_mod.assign_with_reject = _pure_assign_with_reject
 # 一对一消耗 R1/M1；剩余两张委托合并对应 R2，验证不重用 M1/R1。
 items = [
  item("M1", "milestone", 5000, reference="JOB-1"),
  item("M2", "milestone", 3000, reference="B-1"),
  item("M3", "milestone", 7000, reference="B-1"),
  item("R1", "receipt", 5000, reference="JOB-1"),
  item("R2", "receipt", 10000, reference="B-1"),
 ]
 result = reconcile_mod.reconcile(items, POLICY)
 consumed_one = {m["receipt_id"] for m in result["phase_one"]["matches"]}
 merged_receipts = {g["receipt_id"] for g in result["phase_two"]["groups"]}
 assert not (consumed_one & merged_receipts)
 all_m = [i for match in
    result["phase_one"]["matches"] + result["phase_two"]["groups"]
    for i in match["milestone_ids"]]
 all_r = [match["receipt_id"] for match in
    result["phase_one"]["matches"] + result["phase_two"]["groups"]]
 assert len(all_m) == len(set(all_m))
 assert len(all_r) == len(set(all_r))
 print("OK phase two: 不重用第一阶段分录，委托/凭证全局不重复占用")


if __name__ == "__main__":
 test_same_amount_same_day_ambiguity_translated()
 test_unique_solution_has_no_alternatives()
 test_csv_export_contains_ambiguity_section()
 test_csv_export_legacy_result_without_ambiguity()
 test_phase_two_does_not_reuse_phase_one_items()
 print("ALL RECONCILE/EXPORT INTEGRATION TESTS PASSED")
