"""归档 CSV 的纯函数构建（不依赖数据库/Web 框架，便于独立测试）。

底稿页面与归档导出必须展示一致的最优解歧义说明；本模块只接收
reconcile 产出的 result 字典，输出带 BOM 的 CSV 文本。旧数据
（phase_one 无 ambiguity 字段）兼容读取，并明确标注不代表无歧义。
"""

import csv
import io

HEADER = ["stage", "receipt_id", "milestone_ids", "receipt_amount_cents",
     "milestone_sum_cents", "delta_cents", "currency", "party",
     "note", "max_days", "input_sha256"]


def _ambiguity_rows(result):
 """生成与底稿同口径的最优解歧义说明行；旧数据无 ambiguity 字段时兼容。"""
 phase_one = result.get("phase_one", {})
 ambiguity = phase_one.get("ambiguity")
 blank = ["", "", "", "", "", "", ""]
 if not ambiguity:
  return [["ambiguity_note",
     "旧版运行结果，未保存最优解歧义分析；配对以当时求解器输出为准，"
     "不代表无歧义。"] + blank]
 rows = []
 status_label = {"complete": "完整", "degraded": "降级-未完成",
     "failed": "分析失败"}.get(ambiguity.get("status"),
           str(ambiguity.get("status", "")))
 summary = (
  f"状态={status_label}；是否存在歧义={'是' if ambiguity.get('has_ambiguity') else '否'}；"
  f"可入最优配对边={len(ambiguity.get('ambiguous_edges', []))}；"
  f"可拒配委托={len(ambiguity.get('can_reject_milestones', []))}；"
  f"可拒配凭证={len(ambiguity.get('can_reject_receipts', []))}；"
  f"替代方案={ambiguity.get('alternative_count', 0)}")
 if ambiguity.get("alternatives_truncated"):
  summary += (f"（枚举截断：{ambiguity.get('truncated_reason', '')}，"
        f"截断不等于无歧义）")
 else:
  summary += "（枚举完整）"
 rows.append(["ambiguity_summary", summary] + blank)
 rows.append(["ambiguity_note", ambiguity.get("note", "")] + blank)
 for edge in ambiguity.get("ambiguous_edges", []):
  rows.append(["ambiguous_edge", edge["receipt_id"], edge["milestone_id"],
         "", "", "", "",
         "可出现在某个全局最优方案的委托-凭证配对"] + [""])
 for entry in ambiguity.get("can_reject_milestones", []):
  rows.append(["can_reject_milestone", "", entry["milestone_id"],
         "", "", "", "",
         f"该委托可在某个全局最优方案中保持未配（拒配成本"
         f"{entry['reject_cost']}分/项）"] + [""])
 for entry in ambiguity.get("can_reject_receipts", []):
  rows.append(["can_reject_receipt", entry["receipt_id"], "",
         "", "", "", "",
         f"该凭证可在某个全局最优方案中保持未配（拒配成本"
         f"{entry['reject_cost']}分/项）"] + [""])
 for alt in ambiguity.get("alternatives", []):
  pair_text = "|".join(f"{p['milestone_id']}={p['receipt_id']}"
            for p in alt["pairs"]) or "(无真实配对)"
  note = ("未配委托=" + ("|".join(alt["unmatched_milestone_ids"]) or "无")
      + "；未配凭证=" + ("|".join(alt["unmatched_receipt_ids"]) or "无")
      + "；任一方案内委托/凭证不重复占用，目标总分与基线相同")
  rows.append(["alternative_plan", f"方案#{alt['sequence']}", pair_text,
         "", "", "", "", note, ""])
 return rows


def build_reconciliation_csv(result):
 out = io.StringIO()
 writer = csv.writer(out)
 writer.writerow(HEADER)
 max_days = result["policy"]["max_days"]
 input_hash = result["input_sha256"]
 for match in result["phase_one"]["matches"] + result["phase_two"]["groups"]:
  writer.writerow([match["stage"], match["receipt_id"],
        "|".join(match["milestone_ids"]),
        match["receipt_amount_cents"], match["milestone_sum_cents"],
        match["delta_cents"], "CNY", match["party"], "",
        max_days, input_hash])
 for side in ["receipts", "milestones"]:
  for entry in result["unmatched"][side]:
   is_receipt = side == "receipts"
   writer.writerow([
    "unmatched_" + side[:-1],
    entry["external_id"] if is_receipt else "",
    entry["external_id"] if not is_receipt else "",
    entry["amount_cents"] if is_receipt else "",
    entry["amount_cents"] if not is_receipt else "",
    "", "CNY", entry["party"], "", max_days, input_hash,
   ])
 for extra in _ambiguity_rows(result):
  writer.writerow(extra[:9] + [max_days, input_hash])
 return "﻿" + out.getvalue()
