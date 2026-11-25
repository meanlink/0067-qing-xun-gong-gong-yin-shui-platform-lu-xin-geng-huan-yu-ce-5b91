import {h,empty} from './base.js'
import {heading,choices,feedback} from './view.js'
import {wire,canEdit} from './forms.js'
import {forecasts,run} from './demand_store.js'
import {stations} from './fleet_store.js'
import {scenario} from './supply_labels.js'
import {demandLine} from './stock_math.js'
export async function render(root,session){
 const [units,data]=await Promise.all([stations(),forecasts()])
 root.innerHTML=heading('更换量情景','零更换周留在概率估计里，阳性周的换芯强度随出水量变化。')+`
 ${canEdit(session)?`<form class="forecast-settings panel"><label>饮水台<select name="station">${choices(units.filter(r=>r.in_service),r=>r.title)}</select></label>
 <label>下周人流<select name="scenario">${Object.entries(scenario).map(([k,v])=>`<option value="${k}">${h(v)}</option>`).join('')}</select></label><button>预测所需滤芯</button>${feedback}</form>`:''}
 <div class="forecast-lines">${Array.from(Map.groupBy(data,r=>r.demand_class),([key,rows])=>`<section><h2>${h(scenario[key])}</h2>
 <div class="table-scroll"><table><thead><tr><th>饮水台</th><th>均值（根）</th><th>90% 上界</th><th>在站</th><th>缺口</th><th>历史凭证</th></tr></thead><tbody>${rows.map(r=>demandLine(r,units.find(x=>x.code===r.station))).join('')}</tbody></table></div></section>`).join('')||empty('没有可比情景。连续至少四周读数后可运行。')}</div>`
 wire(root.querySelector('form'),run,()=>render(root,session))
}
