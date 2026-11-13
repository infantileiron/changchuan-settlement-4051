<script setup lang="ts">
import {ref,computed} from 'vue';
import type {AmbiguityReport} from '../types/domain';
import {fixed} from '../utils/format';
const props=defineProps<{ambiguity:AmbiguityReport|null|undefined}>();
const showAlts=ref(false);
const statusText:Record<string,string>={complete:'完整',degraded:'降级 · 未完成',failed:'分析失败'};
const reasonText:Record<string,string>={time_budget:'超过时间预算',alternative_limit:'达到替代方案条数上限'};
const hasData=computed(()=>!!props.ambiguity);
const ambiguous=computed(()=>props.ambiguity?.has_ambiguity===true);
</script>
<template>
 <section class="ambiguity-panel">
  <div class="ambiguity-head">
   <h2>一对一全局最优解 · 歧义说明</h2>
   <span v-if="hasData" :class="['amb-status',ambiguity!.status]">{{statusText[ambiguity!.status]||ambiguity!.status}}</span>
  </div>
  <p v-if="!hasData" class="amb-legacy">旧版运行结果，未保存最优解歧义分析；当前配对以当时求解器输出为准，<strong>不代表没有歧义</strong>。</p>
  <template v-else>
   <p v-if="ambiguity!.status==='failed'" class="amb-warning">{{ambiguity!.note}} 已保留求解器原始配对，不得据此判定无歧义。</p>
   <template v-else>
    <div class="amb-summary">
     <div><small>是否存在同分解</small><strong :class="{ambiguous}">{{ambiguous?'存在歧义':'唯一最优'}}</strong></div>
     <div><small>可入最优配对边</small><strong>{{ambiguity!.ambiguous_edges.length}}</strong><span>同额同日任选的委托-凭证</span></div>
     <div><small>可保持未配 · 委托/凭证</small><strong>{{ambiguity!.can_reject_milestones.length}} / {{ambiguity!.can_reject_receipts.length}}</strong><span>含双侧拒配成本口径</span></div>
     <div><small>替代最优方案</small><strong>{{ambiguity!.alternative_count}}</strong><span>目标总分均为 {{fixed(ambiguity!.optimal_objective)}}</span></div>
    </div>
    <div v-if="ambiguity!.alternatives_truncated" class="amb-warning">
     大批量分析已降级（{{reasonText[ambiguity!.truncated_reason]||ambiguity!.truncated_reason}}，上限 {{ambiguity!.max_alternatives}} 条 / {{ambiguity!.time_budget_seconds}} 秒）。
     允许边与可拒配项仍按等号图强连通分量完整判定，<strong>枚举未完成不等于没有歧义</strong>。
    </div>
    <p class="amb-note">{{ambiguity!.note}}</p>
    <details class="amb-details">
     <summary>逐笔查看可出现在最优方案中的委托与未配可能（{{ambiguity!.ambiguous_edges.length}} 条配对边）</summary>
     <div class="table-wrap">
      <table>
       <thead><tr><th>类型</th><th>委托</th><th>凭证</th><th>说明 / 拒配成本(分/项)</th></tr></thead>
       <tbody>
        <tr v-for="e in ambiguity!.ambiguous_edges" :key="'e'+e.milestone_id+e.receipt_id">
         <td><span class="amb-tag edge">可配对</span></td><td>{{e.milestone_id}}</td><td>{{e.receipt_id}}</td><td>该配对可出现在某个全局最优方案，评分 {{fixed(e.score)}}</td>
        </tr>
        <tr v-for="m in ambiguity!.can_reject_milestones" :key="'rm'+m.milestone_id">
         <td><span class="amb-tag reject">可未配</span></td><td>{{m.milestone_id}}</td><td>—</td><td>该委托可在某个全局最优方案中保持未配，拒配 {{m.reject_cost}} 分/项</td>
        </tr>
        <tr v-for="r in ambiguity!.can_reject_receipts" :key="'rr'+r.receipt_id">
         <td><span class="amb-tag reject">可未配</span></td><td>—</td><td>{{r.receipt_id}}</td><td>该凭证可在某个全局最优方案中保持未配，拒配 {{r.reject_cost}} 分/项</td>
        </tr>
       </tbody>
      </table>
     </div>
    </details>
    <details v-if="ambiguity!.alternatives.length" class="amb-details" :open="showAlts">
     <summary>可回查替代方案（{{ambiguity!.alternatives.length}} 条{{ambiguity!.alternatives_truncated?'，已截断':''}}）</summary>
     <article v-for="alt in ambiguity!.alternatives" :key="alt.sequence" class="alt-plan">
      <h3>方案 #{{alt.sequence}}</h3>
      <div class="table-wrap">
       <table>
        <thead><tr><th>委托</th><th>凭证</th><th>评分</th></tr></thead>
        <tbody>
         <tr v-for="p in alt.pairs" :key="alt.sequence+p.milestone_id+p.receipt_id">
          <td>{{p.milestone_id}}</td><td>{{p.receipt_id}}</td><td>{{fixed(p.score)}}</td>
         </tr>
         <tr v-if="!alt.pairs.length"><td colspan="3">本方案无真实一对一配对（全部走拒配）</td></tr>
        </tbody>
       </table>
      </div>
      <p class="alt-unmatched">
       保持未配委托：{{alt.unmatched_milestone_ids.join('、')||'无'}}；
       保持未配凭证：{{alt.unmatched_receipt_ids.join('、')||'无'}}。
       本方案内每个委托/凭证最多消耗一次，与基线目标总分相同。
      </p>
     </article>
    </details>
   </template>
  </template>
 </section>
</template>
