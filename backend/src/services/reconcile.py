import hashlib,json
from datetime import date
from .compatibility import compatible,cost
from .hungarian import assign_with_reject
from .ambiguity import analyze_optimal_ambiguity
from .subset_sum import bounded_subset_sum

POLICY_FIELDS=["amount_tolerance","max_days","require_reference","date_weight","reference_weight","reject_cost","max_candidates","max_group_size","max_group_amount"]

def _build_ambiguity(first,milestones,receipts):
 """把第一阶段矩阵索引层面的歧义分析翻译为 external_id 口径。

 任何异常或超时都不改变既有配对分配，只在结果里显式标注降级状态；
 替代方案中的委托/凭证与基线一样遵守“每个分录最多消耗一次”。
 """
 m=first["left_size"]; n=first["right_size"]
 if first.get("dual_u") is None or first.get("dual_v") is None:
  # 对偶推导失败：等号图无法构造，歧义分析降级，绝不假装无歧义。
  return {"status":"failed","degraded":True,"has_ambiguity":None,
    "truncated_reason":"dual_unavailable","alternatives_truncated":True,
    "max_alternatives":0,"time_budget_seconds":0,"analysis_time_ms":0,
    "tight_edges":0,"scc_count":0,"optimal_objective":first["objective"],
    "ambiguous_edges":[],"can_reject_milestones":[],"can_reject_receipts":[],
    "baseline":{"pairs":[],"unmatched_milestone_ids":[],
        "unmatched_receipt_ids":[]},
    "alternatives":[],"alternative_count":0,
    "note":"最优解对偶推导未完成（"+first.get("dual_error","未知原因")
      +"），无法判定配对是否任选；已保留求解器原始配对，本结果不能据此判定无歧义。"}
 try:
  analysis=analyze_optimal_ambiguity(
   first["expanded_matrix"],first["assignment"],
   first["dual_u"],first["dual_v"],m,n)
 except Exception as exc:  # 歧义分析是附加证据，失败不得拖垮主匹配
  return {"status":"failed","degraded":True,"has_ambiguity":None,
    "truncated_reason":"analysis_error","alternatives_truncated":True,
    "max_alternatives":0,"time_budget_seconds":0,"analysis_time_ms":0,
    "tight_edges":0,"scc_count":0,"optimal_objective":first["objective"],
    "ambiguous_edges":[],"can_reject_milestones":[],"can_reject_receipts":[],
    "baseline":{"pairs":[],"unmatched_milestone_ids":[],
        "unmatched_receipt_ids":[]},
    "alternatives":[],"alternative_count":0,
    "note":"最优解歧义分析失败（"+str(exc)[:200]
      +"），已保留求解器原始配对，不得据此判定无歧义。"}
 def mid(i):return milestones[i]["external_id"]
 def rid(j):return receipts[j]["external_id"]
 ambiguous_edges=[{"milestone_id":mid(i),"receipt_id":rid(j),
        "score":first["expanded_matrix"][i][j]}
       for (i,j) in analysis["allowed_real_pairs"]]
 can_reject_milestones=[{"milestone_id":mid(i),
        "reject_cost":first["reject_cost_per_item"]}
       for i in analysis["allowed_reject_left"]]
 can_reject_receipts=[{"receipt_id":rid(j),
       "reject_cost":first["reject_cost_per_item"]}
       for j in analysis["allowed_reject_right"]]
 alternatives=[]
 for seq,alt in enumerate(analysis["alternatives"],start=1):
  alternatives.append({
   "sequence":seq,
   "pairs":[{"milestone_id":mid(i),"receipt_id":rid(j),
       "score":first["expanded_matrix"][i][j]}
      for (i,j) in alt["real_pairs"]],
   "unmatched_milestone_ids":[mid(i) for i in alt["reject_left"]],
   "unmatched_receipt_ids":[rid(j) for j in alt["reject_right"]],
  })
 # 基线自身的规范化配对（与 phase_one.matches 同源），供前端/导出对照。
 base=analysis["base_canonical"]
 baseline={
  "pairs":[{"milestone_id":mid(i),"receipt_id":rid(j),
      "score":first["expanded_matrix"][i][j]} for (i,j) in base["real_pairs"]],
  "unmatched_milestone_ids":[mid(i) for i in base["reject_left"]],
  "unmatched_receipt_ids":[rid(j) for j in base["reject_right"]],
 }
 # 歧义判定（精确）：唯一最优方案时，允许边恰为基线配对、可拒配项恰为
 # 基线实际拒配。因此只有当“可入最优配对边多于基线配对”（存在可替换真实
 # 配对）或“可拒配集合超出基线实际拒配”（某已配项也能拒配）或确有替代方案
 # 时，才构成歧义。基线内本来就有的配对/拒配不算歧义。
 base_reject_left=set(base["reject_left"]);base_reject_right=set(base["reject_right"])
 extra_reject_left=set(analysis["allowed_reject_left"])-base_reject_left
 extra_reject_right=set(analysis["allowed_reject_right"])-base_reject_right
 has_ambiguity=(analysis["alternative_count_total"]>0
       or len(ambiguous_edges)>len(base["real_pairs"])
       or bool(extra_reject_left) or bool(extra_reject_right))
 status="complete"
 if analysis["alternatives_truncated"]:
  status="degraded"
 return {
  "status":status,"degraded":analysis["alternatives_truncated"],
  "has_ambiguity":has_ambiguity,
  "truncated_reason":analysis["truncated_reason"],
  "alternatives_truncated":analysis["alternatives_truncated"],
  "max_alternatives":analysis["max_alternatives"],
  "time_budget_seconds":analysis["time_budget_seconds"],
  "analysis_time_ms":analysis["analysis_time_ms"],
  "tight_edges":analysis["tight_edges"],"scc_count":analysis["scc_count"],
  "optimal_objective":first["objective"],
  "ambiguous_edges":ambiguous_edges,
  "can_reject_milestones":can_reject_milestones,
  "can_reject_receipts":can_reject_receipts,
  "baseline":baseline,"alternatives":alternatives,
  "alternative_count":analysis["alternative_count_total"],
  "note":("替代方案枚举达到预算上限，结果不完整；允许边与可拒配项仍基于"
      "等号图强连通分量完整判定，截断不等于没有歧义。"
      if analysis["alternatives_truncated"] else
      "所有替代方案与基线目标总分相同，且每个委托/凭证在任一方案中最多消耗一次。"),
 }

def reconcile(items,policy):
 milestones=sorted([x for x in items if x["side"]=="milestone"],key=lambda x:x["external_id"]);receipts=sorted([x for x in items if x["side"]=="receipt"],key=lambda x:(x["booking_date"],x["external_id"]))
 if not milestones or not receipts:raise ValueError("批次需同时存在委托里程碑和入账凭证")
 matrix=[[cost(m,r,policy) if compatible(m,r,policy) else None for r in receipts] for m in milestones]
 first=assign_with_reject(matrix,policy["reject_cost"]);pairs=[];used_m=set();used_r=set()
 for edge in first["matches"]:
  m=milestones[edge["left"]];r=receipts[edge["right"]];used_m.add(m["external_id"]);used_r.add(r["external_id"])
  pairs.append({"stage":"one_to_one","milestone_ids":[m["external_id"]],"receipt_id":r["external_id"],"milestone_sum_cents":m["amount_cents"],"receipt_amount_cents":r["amount_cents"],"delta_cents":m["amount_cents"]-r["amount_cents"],"currency":"CNY","party":r["party"],"score":edge["cost"]})
 ambiguity=_build_ambiguity(first,milestones,receipts)
 groups=[];searches=[]
 for r in receipts:
  if r["external_id"] in used_r:continue
  if r["amount_cents"]>policy["max_group_amount"]:
   searches.append({"receipt_id":r["external_id"],"reason":"target_above_limit","found":False,"candidates":0,"truncated":0});continue
  eligible=[m for m in milestones if m["external_id"] not in used_m and m["amount_cents"]<=r["amount_cents"]+policy["amount_tolerance"] and compatible(m,r,policy,amount_check=False)]
  eligible.sort(key=lambda m:(abs((date.fromisoformat(m["booking_date"])-date.fromisoformat(r["booking_date"])).days),m["external_id"]))
  truncated=max(0,len(eligible)-policy["max_candidates"]);candidates=eligible[:policy["max_candidates"]]
  found=bounded_subset_sum([m["amount_cents"] for m in candidates],r["amount_cents"],policy["amount_tolerance"],policy["max_group_size"],max_total=policy["max_group_amount"])
  searches.append({"receipt_id":r["external_id"],"candidates":len(candidates),"truncated":truncated,**found})
  if not found["found"]:continue
  chosen=[candidates[i] for i in found["indices"]];ids=[m["external_id"] for m in chosen]
  if used_m.intersection(ids):raise ValueError("合并候选重复消耗委托")
  used_m.update(ids);used_r.add(r["external_id"])
  groups.append({"stage":"merged","milestone_ids":ids,"receipt_id":r["external_id"],"milestone_sum_cents":found["sum_cents"],"receipt_amount_cents":r["amount_cents"],"delta_cents":found["delta_cents"],"currency":"CNY","party":r["party"],"score":None})
 unmatched_m=[m for m in milestones if m["external_id"] not in used_m];unmatched_r=[r for r in receipts if r["external_id"] not in used_r]
 all_m=[i for match in pairs+groups for i in match["milestone_ids"]];all_r=[match["receipt_id"] for match in pairs+groups]
 assert len(all_m)==len(set(all_m)) and len(all_r)==len(set(all_r))
 fingerprint=hashlib.sha256(json.dumps(sorted(items,key=lambda x:x["external_id"]),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
 return {"phase_one":{"matches":pairs,"objective_with_rejections":first["objective"],"compatible_edges":sum(v is not None for row in matrix for v in row),"ambiguity":ambiguity},"phase_two":{"groups":groups,"searches":searches},"unmatched":{"milestones":unmatched_m,"receipts":unmatched_r},"counts":{"milestones":len(milestones),"receipts":len(receipts),"one_to_one":len(pairs),"merged":len(groups),"consumed_milestones":len(used_m),"consumed_receipts":len(used_r),"unmatched_milestones":len(unmatched_m),"unmatched_receipts":len(unmatched_r)},"policy":policy,"items":items,"input_sha256":fingerprint,"assumption":"第一阶段含双侧拒配dummy的一对一全局最小成本；ambiguity字段基于等号图强连通分量给出全部可入最优方案的配对与可拒配项，并枚举可回查替代最优方案（截断时显式标注，不等于无歧义）。第二阶段按日期/ID顺序对剩余分录做受限子集和。两阶段不保证一对多联合全局最优；所有消耗仅在本次试验内，不写银行或自动核销。"}
