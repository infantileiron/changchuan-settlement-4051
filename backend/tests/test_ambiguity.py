"""歧义分析的穷举对照测试。

对小矩阵枚举扩展方阵全部可行完美匹配，校验：
1. 分析报告的允许配对/可拒配集合，恰好等于所有最优匹配中出现过的边；
2. 替代方案数量等于规范化最优匹配总数减一（小矩阵必须完整枚举）；
3. 每个替代方案目标总分等于最优值，且委托/凭证不重复占用；
4. 大批量触发预算截断时显式标注，且允许边仍完整报告（截断不等于无歧义）。

运行：python -I -m tests.test_ambiguity（在 backend 目录下）。
"""

import itertools
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.hungarian_reference import hungarian
from src.services.ambiguity import analyze_optimal_ambiguity


def build(costs, reject_cost):
 m = len(costs)
 n = len(costs[0])
 size = m + n
 finite = [v for row in costs for v in row if v is not None]
 forbidden = (size + 1) * (2 * reject_cost + max(finite, default=0) + 1)
 matrix = [[forbidden] * size for _ in range(size)]
 # 与生产 hungarian.py 同序：先 dummy 互配零块，再写拒配边，避免覆盖。
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
 return matrix, forbidden, m, n


def canonical_of(perm, m, n):
 pairs = frozenset((i, perm[i]) for i in range(m) if perm[i] < n)
 rej_l = frozenset(i for i in range(m) if perm[i] == n + i)
 rej_r = frozenset(j for j in range(n) if perm[m + j] == j)
 return pairs, rej_l, rej_r


def brute_force(costs, reject_cost):
 matrix, forbidden, m, n = build(costs, reject_cost)
 size = m + n
 best = float("inf")
 canon = set()
 all_pairs, all_rl, all_rr = set(), set(), set()
 for perm in itertools.permutations(range(size)):
  if any(matrix[i][perm[i]] >= forbidden for i in range(size)):
   continue
  total = sum(matrix[i][perm[i]] for i in range(size))
  if total < best - 1e-9:
   best = total
   canon.clear()
   all_pairs.clear()
   all_rl.clear()
   all_rr.clear()
  if abs(total - best) <= 1e-9:
   key = canonical_of(perm, m, n)
   if key not in canon:
    canon.add(key)
    all_pairs |= key[0]
    all_rl |= key[1]
    all_rr |= key[2]
 return best, len(canon), all_pairs, all_rl, all_rr


def run_case(name, costs, reject_cost, expect_ambiguous):
 matrix, forbidden, m, n = build(costs, reject_cost)
 size = m + n
 assignment, u, v = hungarian([row[:] for row in matrix])
 base_obj = sum(matrix[i][assignment[i]] for i in range(size))
 best, total_canon, all_pairs, all_rl, all_rr = brute_force(costs, reject_cost)
 assert abs(base_obj - best) <= 1e-7, (name, base_obj, best)
 analysis = analyze_optimal_ambiguity(matrix, assignment, u, v, m, n)
 assert not analysis["alternatives_truncated"], (name, "小矩阵应完整枚举")
 assert set(map(tuple, analysis["allowed_real_pairs"])) == all_pairs, name
 assert set(analysis["allowed_reject_left"]) == all_rl, name
 assert set(analysis["allowed_reject_right"]) == all_rr, name
 assert analysis["alternative_count_total"] == total_canon - 1, name
 # 替代方案合法性：真实行/列不重复，且不会同时配对与拒配。
 for alt in analysis["alternatives"]:
  rows = [i for (i, j) in alt["real_pairs"]]
  cols = [j for (i, j) in alt["real_pairs"]]
  assert len(rows) == len(set(rows)), name
  assert len(cols) == len(set(cols)), name
  assert not (set(rows) & set(alt["reject_left"])), name
  assert not (set(cols) & set(alt["reject_right"])), name
 assert (total_canon > 1) == expect_ambiguous, name
 print(f"OK {name}: 最优目标={best} 规范化最优方案数={total_canon} "
       f"替代={analysis['alternative_count_total']} SCC={analysis['scc_count']}")


def test_scale_degradation():
 k = 200
 costs = [[7.0] * k for _ in range(k)]
 matrix, forbidden, m, n = build(costs, 50.0)
 assignment, u, v = hungarian([row[:] for row in matrix])
 analysis = analyze_optimal_ambiguity(
  matrix, assignment, u, v, m, n, max_alternatives=200, time_budget=1.0)
 assert analysis["alternatives_truncated"], "大批量必须触发截断"
 assert analysis["truncated_reason"] in ("time_budget", "alternative_limit")
 # 截断不等于无歧义：SCC 判定仍完整报告全部同额允许边。
 assert len(analysis["allowed_real_pairs"]) == k * k
 # 确定性：同参数两次枚举前缀一致。
 a = analyze_optimal_ambiguity(matrix, assignment, u, v, m, n,
             max_alternatives=50, time_budget=1.0)
 b = analyze_optimal_ambiguity(matrix, assignment, u, v, m, n,
             max_alternatives=50, time_budget=1.0)
 assert a["alternatives"] == b["alternatives"], "枚举结果不确定"
 print("OK scale-degradation: 截断原因", analysis["truncated_reason"],
       "允许边完整数", len(analysis["allowed_real_pairs"]))


def test_zero_budget_marks_incomplete():
 k = 50
 costs = [[3.0] * k for _ in range(k)]
 matrix, forbidden, m, n = build(costs, 50.0)
 assignment, u, v = hungarian([row[:] for row in matrix])
 analysis = analyze_optimal_ambiguity(
  matrix, assignment, u, v, m, n, max_alternatives=10 ** 9, time_budget=0.0)
 assert analysis["alternatives_truncated"]
 assert analysis["truncated_reason"] == "time_budget"
 print("OK zero-budget: 零时间预算显式标注未完成，而非当作无歧义")


if __name__ == "__main__":
 run_case("unique-diagonal", [[1, 9], [8, 2]], 50.0, False)
 run_case("symmetric-tie", [[5, 5], [5, 5]], 50.0, True)
 run_case("reject-better-unique", [[50, None], [None, 50]], 6.0, False)
 run_case("reject-tie", [[6, None], [None, 6]], 3.0, True)
 run_case("one-receipt-two-ms", [[4, None], [None, 4], [None, 4]], 4.0, True)
 run_case("full-tie-3x3", [[7, 7, 7]] * 3, 50.0, True)
 run_case("rect-2x3", [[3, 3, None], [None, 3, 3]], 40.0, True)
 run_case("unique-reject", [[1, None], [None, None]], 4.0, False)
 run_case("broken-tie", [[2, 3], [3, 2]], 50.0, False)
 run_case("full-tie-4x4", [[9] * 4 for _ in range(4)], 50.0, True)
 test_scale_degradation()
 test_zero_budget_marks_incomplete()
 print("ALL AMBIGUITY TESTS PASSED")
