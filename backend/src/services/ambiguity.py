"""第一阶段一对一匹配的最优解歧义分析。

匈牙利法只返回一组最优配对。同额同日时若干配对只是任选：
本模块在保持拒配成本口径不变的前提下，回答两个问题：

1. 每条真实兼容边、每个委托/凭证的拒配，是否能出现在某个全局最优方案中；
2. 枚举可回查的替代最优方案（受数量与时间预算限制，超时显式标注未完成）。

判定依据为最小权完美匹配的等号图（equality graph）：
对扩展方阵的最优完美匹配 M 取一组对偶 u/v，满足 c_ij = u_i + v_j
的边称为紧边；紧边构成的等号图中，一条边属于某个最优完美匹配，
当且仅当它在等号图残量有向图上与匹配边处于同一强连通分量（SCC），
或本身就是匹配边。

节点编号
--------
扩展方阵行、列共用整数区间 [0, size)，语义不同。本模块把列节点整体
偏移 size：行节点 id = i（[0, size)），列节点 id = size + j。
残量有向图规则：非匹配紧边 行i -> 列(size+j)，匹配边 列(size+j) -> 行i。
环从行节点出发严格交替 行->列->行，偶数位为行、奇数位为列。

扩展方阵含 dummy 互配零边，其排列不改变真实委托/凭证的去向，业务上
视为同一方案。枚举起点限定真实节点，并按“真实配对 + 真实拒配”规范化去重。

所有替代方案目标总分相同，且任何方案中每个委托/凭证最多消耗一次
（完美匹配本身保证节点不重复占用）。
"""

import time

# 枚举替代方案的默认预算：替代方案条数上限与墙上时间（秒）。
MAX_ALTERNATIVES = 200
TIME_BUDGET_SECONDS = 3.0
# 浮点对偶比较容差：成本为整数分与权重的有限混合，误差远小于 1e-7。
TIGHT_EPS = 1e-7


def _tarjan_scc(node_count, adjacency):
 """迭代 Tarjan，返回每个节点的分量编号（按发现顺序，保证可复现）。"""
 index = [-1] * node_count
 low = [0] * node_count
 on_stack = [False] * node_count
 stack = []
 component = [-1] * node_count
 counter = 0
 component_counter = 0
 for root in range(node_count):
  if index[root] != -1:
   continue
  index[root] = low[root] = counter
  counter += 1
  stack.append(root)
  on_stack[root] = True
  work = [(root, 0)]
  while work:
   node, edge_pos = work[-1]
   neighbors = adjacency[node]
   if edge_pos < len(neighbors):
    work[-1] = (node, edge_pos + 1)
    nxt = neighbors[edge_pos]
    if index[nxt] == -1:
     index[nxt] = low[nxt] = counter
     counter += 1
     stack.append(nxt)
     on_stack[nxt] = True
     work.append((nxt, 0))
    elif on_stack[nxt]:
     low[node] = min(low[node], index[nxt])
   else:
    if low[node] == index[node]:
     while True:
      pop = stack.pop()
      on_stack[pop] = False
      component[pop] = component_counter
      if pop == node:
       break
     component_counter += 1
    work.pop()
    if work:
     parent = work[-1][0]
     low[parent] = min(low[parent], low[node])
 return component


def _cycles_from(start, adjacency, started, time_budget):
 """枚举从 start 出发回到 start 的简单有向环（节点 id 序列）。

 邻接表已排序，显式栈 DFS 顺序确定，结果可复现，且避免深图递归溢出。
 用 on_stack 保证简单环；只保留以 start 为最小 id 起点的环，避免同一环
 在不同起点重复产出。超时返回 None，由调用方标注未完成。
 """
 cycles = []
 # 每个栈帧为 (node, 下一个待访问邻接点下标)。
 stack = [start]
 edge_pos = [0]
 on_stack = {start}
 while stack:
  if time.monotonic() - started > time_budget:
   return None
  node = stack[-1]
  neighbors = adjacency[node]
  pos = edge_pos[-1]
  if pos < len(neighbors):
   edge_pos[-1] = pos + 1
   nxt = neighbors[pos]
   if nxt == start and len(stack) >= 2:
    cycles.append(tuple(stack))
    continue
   if nxt in on_stack or nxt < start:
    continue
   stack.append(nxt)
   edge_pos.append(0)
   on_stack.add(nxt)
  else:
   stack.pop()
   edge_pos.pop()
   on_stack.discard(node)
 return cycles


def analyze_optimal_ambiguity(matrix, assignment, dual_u, dual_v,
         left_size, right_size,
         max_alternatives=MAX_ALTERNATIVES,
         time_budget=TIME_BUDGET_SECONDS):
 """分析扩展方阵最优完美匹配的歧义（矩阵索引层面）。

 参数
 ----
 matrix: 扩展方阵（list[list[float]]），禁配边为 None；尺寸 m+n。
 assignment: 长度 size 的序列，assignment[行] = 列，来自最优完美匹配。
 dual_u, dual_v: 同一最优解的对偶变量，matrix[i][j]=u_i+v_j 即紧边。
 left_size/right_size: 真实委托行数 m、真实凭证列数 n。

 返回 dict：
   allowed_real_pairs: 可出现在某最优方案的真实兼容边 (i, j)，i<m、j<n；
   allowed_reject_left/right: 可保持未配（走专属拒配 dummy）的真实行/列；
   base_canonical/alternatives: 基线与替代方案的规范化真实配对/拒配；
   alternatives_truncated/truncated_reason: 预算耗尽标记；
   tight_edges/scc_count/analysis_time_ms: 过程证据。
 """
 started = time.monotonic()
 size = len(matrix)
 m, n = left_size, right_size
 if size == 0 or len(assignment) != size or m + n != size or any(
   col is None or col < 0 for col in assignment):
  raise ValueError("歧义分析需要完整的最优完美匹配及正确的左右尺寸")

 def is_real_row(i):
  return i < m

 def is_real_col(j):
  return j < n

 # 1) 收集紧边（等号图），禁配边显式排除。
 tight_forward = [[] for _ in range(size)]  # 行 i -> 列 j（非匹配紧边）
 tight_edge_count = 0
 for i, row in enumerate(matrix):
  for j, value in enumerate(row):
   if value is None:
    continue
   if abs(value - (dual_u[i] + dual_v[j])) <= TIGHT_EPS:
    tight_edge_count += 1
    if assignment[i] != j:
     tight_forward[i].append(j)
 for neighbors in tight_forward:
  neighbors.sort()

 # 2) 残量有向图，列节点偏移 size：行 id [0,size)，列 id [size,2size)。
 node_count = 2 * size
 adjacency = [[] for _ in range(node_count)]
 for i, neighbors in enumerate(tight_forward):
  for j in neighbors:
   adjacency[i].append(size + j)          # 非匹配紧边 行->列
 for row_i, col_j in enumerate(assignment):
  adjacency[size + col_j].append(row_i)   # 匹配边 列->行
 for neighbors in adjacency:
  neighbors.sort()
 component = _tarjan_scc(node_count, adjacency)

 # 3) 允许边判定（匹配边，或同 SCC 的紧边），仅保留有业务含义的边。
 allowed_real_pairs = set()
 allowed_reject_left = set()
 allowed_reject_right = set()

 def consider(i, j, is_matched):
  if not is_matched and component[i] != component[size + j]:
   return
  if is_real_row(i) and is_real_col(j):
   allowed_real_pairs.add((i, j))
  elif is_real_row(i) and (not is_real_col(j)) and j == n + i:
   allowed_reject_left.add(i)            # 委托 i 走专属拒配 dummy
  elif (not is_real_row(i)) and is_real_col(j) and i == m + j:
   allowed_reject_right.add(j)           # 凭证 j 走专属拒配 dummy
  # dummy-dummy 互配边不含真实业务含义，不纳入允许集合。

 for i in range(size):
  consider(i, assignment[i], True)
  for j in tight_forward[i]:
   consider(i, j, False)

 # 4) 规范化：只看真实配对与真实拒配，dummy 内部排列视为同一方案。
 def canonical(assign):
  pairs = frozenset((i, assign[i]) for i in range(m) if assign[i] < n)
  rej_l = frozenset(i for i in range(m) if assign[i] == n + i)
  rej_r = frozenset(j for j in range(n) if assign[m + j] == j)
  return (pairs, rej_l, rej_r)

 def flip_cycle(assign, cycle):
  # 列节点已偏移 size，故 id < size 即为行节点（含真实行与 dummy 行），
  # id >= size 为列节点。环严格交替，每个行节点的后继列即其新配对；
  # 必须覆盖环上所有行节点（含 dummy 行），否则会产生重复占用。
  candidate = list(assign)
  length = len(cycle)
  for pos, node in enumerate(cycle):
   if node < size:
    candidate[node] = cycle[(pos + 1) % length] - size
  return tuple(candidate)

 def residual_graph(assign):
  # 等号图（紧边集合）固定，但匹配边随翻转变化；残量图须按当前匹配重建：
  # 非匹配紧边 行->偏移列，当前匹配边 偏移列->行。
  graph = [[] for _ in range(2 * size)]
  for i, neighbors in enumerate(tight_forward):
   for j in neighbors:
    if assign[i] != j:
     graph[i].append(size + j)
  for row_i, col_j in enumerate(assign):
   graph[size + col_j].append(row_i)
  for neighbors in graph:
   neighbors.sort()
  return graph

 base_canon = canonical(assignment)
 seen = {base_canon}
 alternatives = []
 queue = [tuple(assignment)]
 truncated_reason = ""
 # 起点限定真实节点：真实委托行 [0,m) 与真实凭证的列 dummy 行 (m+j)，
 # 避免在 dummy-dummy 零边海洋里指数爆炸；纯 dummy 环规范化后与基线相同。
 real_starts = list(range(m)) + [m + j for j in range(n)]
 while queue and len(alternatives) < max_alternatives:
  if time.monotonic() - started > time_budget:
   truncated_reason = "time_budget"
   break
  current = queue.pop(0)
  current_graph = residual_graph(current)
  progressed = False
  for start in real_starts:
   if truncated_reason:
    break
   cycles = _cycles_from(start, current_graph, started, time_budget)
   if cycles is None:
    truncated_reason = "time_budget"
    break
   for cycle in cycles:
    candidate = flip_cycle(current, cycle)
    # 校验翻转后仍为合法完美匹配（列不重复），防御性断言。
    if len(set(candidate)) != size:
     raise ValueError("交替环翻转破坏完美匹配")
    key = canonical(candidate)
    if key not in seen:
     seen.add(key)
     alternatives.append({
      "real_pairs": sorted(key[0]),
      "reject_left": sorted(key[1]),
      "reject_right": sorted(key[2]),
     })
     queue.append(candidate)
     progressed = True
     if len(alternatives) >= max_alternatives:
      truncated_reason = "alternative_limit"
      break
  if truncated_reason:
   break
  if not progressed:
   break
 completed = truncated_reason == ""
 return {
  "tight_edges": tight_edge_count,
  "scc_count": max(component) + 1,
  "allowed_real_pairs": sorted(allowed_real_pairs),
  "allowed_reject_left": sorted(allowed_reject_left),
  "allowed_reject_right": sorted(allowed_reject_right),
  "base_canonical": {
   "real_pairs": sorted(base_canon[0]),
   "reject_left": sorted(base_canon[1]),
   "reject_right": sorted(base_canon[2]),
  },
  "alternatives": alternatives,
  "alternative_count_total": len(alternatives),
  "alternatives_truncated": not completed,
  "truncated_reason": truncated_reason,
  "analysis_time_ms": round((time.monotonic() - started) * 1000, 3),
  "time_budget_seconds": time_budget,
  "max_alternatives": max_alternatives,
 }
