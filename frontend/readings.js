import {h} from './base.js'
import {heading,choices,feedback,table} from './view.js'
import {wire,canEdit} from './forms.js'
import {readings,record} from './reading_store.js'
import {stations} from './fleet_store.js'
export async function render(root,session){
 const [units,rows]=await Promise.all([stations(),readings()])
 root.innerHTML=heading('周读数','周一锚定抄表口径。同一站点保留明确零更换记录，与缺页分开。')+`
 <div class="meter-log"><section>${Array.from(Map.groupBy(rows,r=>r.station),([code,records])=>`<details open><summary>${h(units.find(r=>r.code===code)?.title||code)}</summary>${table(['周起始','出水（L）','更换','来源'],records.map(r=>[r.week_of,r.liters,r.changes,r.note]))}</details>`).join('')}</section>
 ${canEdit(session)?`<form class="panel compact-form"><h2>登记班组周读数</h2><label>饮水台<select name="station">${choices(units.filter(x=>x.in_service),r=>r.title)}</select></label>
 <label>周一起算<input name="week_of" type="date" value="2026-11-23" required></label><label>出水升数<input name="liters" type="number" min="0" required></label><label>实换根数<input name="changes" type="number" min="0" required></label><label>抄表来源<input name="note" required></label><button>保存抄表证据</button>${feedback}</form>`:''}</div>`
 wire(root.querySelector('form'),record,()=>render(root,session))
}
