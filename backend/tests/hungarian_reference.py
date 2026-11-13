"""纯 Python 最小权匈牙利参考实现（仅测试用）。

生产路径使用 scipy.linear_sum_assignment；本地/CI 无 SciPy 时，
测试用本实现提供 assignment 与等号图对偶，覆盖 ambiguity 模块逻辑。
算法为经典 1-indexed O(n^3) 最小权指派，返回 0-indexed 分配与对偶 u/v。
"""

INF = float("inf")


def hungarian(cost):
 n = len(cost)
 u = [0.0] * (n + 1)
 v = [0.0] * (n + 1)
 p = [0] * (n + 1)
 way = [0] * (n + 1)
 for i in range(1, n + 1):
  p[0] = i
  j0 = 0
  minv = [INF] * (n + 1)
  used = [False] * (n + 1)
  while p[j0] != 0:
   used[j0] = True
   i0 = p[j0]
   delta = INF
   j1 = 0
   for j in range(1, n + 1):
    if not used[j]:
     cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
     if cur < minv[j]:
      minv[j] = cur
      way[j] = j0
     if minv[j] < delta:
      delta = minv[j]
      j1 = j
   for j in range(n + 1):
    if used[j]:
     u[p[j]] += delta
     v[j] -= delta
    else:
     minv[j] -= delta
   j0 = j1
  while True:
   j1 = way[j0]
   p[j0] = p[j1]
   j0 = j1
   if j0 == 0:
     break
 assignment = [0] * n
 for j in range(1, n + 1):
  if p[j] != 0:
   assignment[p[j] - 1] = j - 1
 return assignment, u[1:], v[1:]
