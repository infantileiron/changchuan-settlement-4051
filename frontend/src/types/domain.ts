export type Role="admin"|"analyst"|"viewer";export interface User{email:string;role:Role}export interface Entity{id:string;created_at:string;[key:string]:any}export interface MatchRow{stage:string;milestone_ids:string[];receipt_id:string;milestone_sum_cents:number;receipt_amount_cents:number;delta_cents:number;currency:string;party:string;score:number|null}
export interface AmbiguousEdge{milestone_id:string;receipt_id:string;score:number}
export interface RejectableItem{milestone_id?:string;receipt_id?:string;reject_cost:number}
export interface AlternativePlan{sequence:number;pairs:AmbiguousEdge[];unmatched_milestone_ids:string[];unmatched_receipt_ids:string[]}
export interface AmbiguityReport{
 status:"complete"|"degraded"|"failed";degraded:boolean;has_ambiguity:boolean|null;
 truncated_reason:string;alternatives_truncated:boolean;
 max_alternatives:number;time_budget_seconds:number;analysis_time_ms:number;
 tight_edges:number;scc_count:number;optimal_objective:number;
 ambiguous_edges:AmbiguousEdge[];can_reject_milestones:RejectableItem[];
 can_reject_receipts:RejectableItem[];baseline:{pairs:AmbiguousEdge[];unmatched_milestone_ids:string[];unmatched_receipt_ids:string[]};
 alternatives:AlternativePlan[];alternative_count:number;note:string;
}
