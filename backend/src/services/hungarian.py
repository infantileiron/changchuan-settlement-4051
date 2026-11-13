import math
import time
import numpy as np
from scipy.optimize import linear_sum_assignment

# 对偶推导的墙上时间预算（秒）与松弛上限；超时即让歧义分析降级，
# 不影响 SciPy 已求出的主匹配分配。
DUAL_TIME_BUDGET = 3.0
DUAL_RELAX_CAP = 20_000_000


def assign_with_reject(costs, reject_cost):
 m = len(costs); n = len(costs[0]) if m else 0
 if not m or not n:
  return {"matches": [], "unmatched_left": list(range(m)),
    "unmatched_right": list(range(n)),
    "objective": (m + n) * reject_cost}
 if any(len(row) != n for row in costs) or not math.isfinite(reject_cost) or reject_cost <= 0:
  raise ValueError("匹配矩阵或拒配分数无效")
 finite = [v for row in costs for v in row if v is not None]
 if any(not math.isfinite(v) or v < 0 for v in finite):
  raise ValueError("匹配成本须为非负有限分数")
 size = m + n
 forbidden = (size + 1) * (2 * reject_cost + max(finite, default=0) + 1)
 matrix = np.full((size, size), forbidden, dtype=float)
 for i, row in enumerate(costs):
  for j, value in enumerate(row):
   if value is not None:
    matrix[i, j] = value
  matrix[i, n + i] = reject_cost
 for j in range(n):
  matrix[m + j, j] = reject_cost
 matrix[m:, n:] = 0
 # SciPy 1.14 的 linear_sum_assignment 仅返回最优分配（无对偶参数）。
 rr, cc = linear_sum_assignment(matrix)
 matches = []
 for i, j in zip(rr, cc):
  if i < m and j < n:
   if costs[i][j] is None:
    raise ValueError("求解器选中禁配边")
   matches.append({"left": int(i), "right": int(j), "cost": float(costs[i][j])})
 used_left = {x["left"] for x in matches}
 used_right = {x["right"] for x in matches}
 assignment = [0] * size
 for i, j in zip(rr, cc):
  assignment[int(i)] = int(j)
 # 对偶势不被 SciPy 暴露：由最优分配经差分约束最短路推导一组可行最优对偶，
 # 供等号图歧义分析。推导是尽力而为——失败只标记 dual_error，主分配不受影响。
 dual_u = dual_v = None
 dual_error = ""
 try:
  dual_u, dual_v = _dual_potentials(matrix, np.array(assignment, dtype=int),
             forbidden)
 except Exception as exc:
  dual_error = str(exc)[:300]
 return {"matches": matches,
  "unmatched_left": [i for i in range(m) if i not in used_left],
  "unmatched_right": [j for j in range(n) if j not in used_right],
  "objective": float(matrix[rr, cc].sum()),
  "reject_cost_per_item": reject_cost, "forbidden_bound": forbidden,
  "expanded_matrix": [[None if matrix[i, j] >= forbidden / 2 else float(matrix[i, j])
            for j in range(size)] for i in range(size)],
  "assignment": assignment,
  "dual_u": None if dual_u is None else [float(x) for x in dual_u],
  "dual_v": None if dual_v is None else [float(x) for x in dual_v],
  "dual_error": dual_error,
  "left_size": m, "right_size": n}


def _dual_potentials(matrix, assignment, forbidden):
 """由最优完美匹配推导一组可行最优对偶 u/v。

 令 p[i]=assignment[i]、q[j] 为列 j 的匹配行。匹配取等要求
 v[j]=C[q[j],j]-u[q[j]]；可行性 u[i]+v[j]<=C[i][j] 代入得差分约束
 u[i]-u[q[j]] <= C[i,j]-C[q[j],j]，即 u 空间有向边 q[j]->i，
 权为 C[i,j]-C[q[j],j]。最优分配保证无负环，用 SPFA 求最短路得可行 u，
 再由匹配等式构造 v，最后校验可行性与匹配取等。禁配单元格不参与约束。
 """
 size = matrix.shape[0]
 inverse = np.empty(size, dtype=int)
 inverse[assignment] = np.arange(size)
 # 构建 u 空间差分约束邻接表：edge k -> i，weight w。
 adjacency = [[] for _ in range(size)]
 for i in range(size):
  for j in range(size):
   if matrix[i, j] >= forbidden / 2:
    continue
   k = int(inverse[j])
   weight = float(matrix[i, j] - matrix[k, j])
   adjacency[k].append((i, weight))
 # SPFA：超级源连所有节点（初始距离 0 入队），求最短距离即最紧可行 u。
 dist = [0.0] * size
 in_queue = [True] * size
 queue = list(range(size))
 relaxations = 0
 start = time.monotonic()
 head = 0
 while head < len(queue):
  if time.monotonic() - start > DUAL_TIME_BUDGET or relaxations > DUAL_RELAX_CAP:
   raise TimeoutError("对偶势推导超过时间或松弛预算，歧义分析需降级")
  k = queue[head]; head += 1
  in_queue[k] = False
  dk = dist[k]
  for i, weight in adjacency[k]:
   relaxations += 1
   candidate = dk + weight
   if candidate + 1e-7 < dist[i]:
    dist[i] = candidate
    if not in_queue[i]:
     in_queue[i] = True
     queue.append(i)
 u = np.array(dist, dtype=float)
 v = np.array([float(matrix[int(inverse[j]), j]) - u[int(inverse[j])]
        for j in range(size)], dtype=float)
 # 校验：非禁配边 c >= u+v；匹配边取等号。
 for i in range(size):
  for j in range(size):
   c = float(matrix[i, j])
   if c >= forbidden / 2:
    continue
   if c < u[i] + v[j] - 1e-7:
    raise ValueError("对偶可行性校验失败")
 for i in range(size):
  j = int(assignment[i])
  if abs(float(matrix[i, j]) - (u[i] + v[j])) > 1e-7:
   raise ValueError("匹配边对偶取等校验失败")
 return u, v
