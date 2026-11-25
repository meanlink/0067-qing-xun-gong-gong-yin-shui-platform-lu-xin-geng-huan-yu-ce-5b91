import {h,badge} from './base.js'
import {heading} from './view.js'
import {stations} from './fleet_store.js'
import {status} from './supply_labels.js'
export async function render(root) {
 const data=await stations()
 root.innerHTML=heading('饮水台与滤芯','滤芯型号和本地留存不同。调度领料以区域和上界缺口为准。')+`<div class="district-index">${Array.from(Map.groupBy(data,r=>r.district),([area,rows])=>`<section><h2>${h(area)}</h2>${rows.map(r=>`<article><h3>${h(r.title)}</h3><p>${h(r.code)} · ${badge(status[r.in_service],r.in_service?'ready':'held')}</p><dl><dt>滤芯</dt><dd>${h(r.cartridge)}</dd><dt>站内保留</dt><dd>${r.reserve} 根</dd><dt>抄表</dt><dd>${r.samples} 周</dd></dl></article>`).join('')}</section>`).join('')}</div>`
}
