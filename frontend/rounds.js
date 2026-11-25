import {h} from './base.js'
import {heading,feedback,table} from './view.js'
import {wire} from './forms.js'
import {stations} from './fleet_store.js'
import {rounds,bundle} from './route_store.js'
import {routeTotal} from './supply_labels.js'
export async function render(root,session){
 const [routes,units]=await Promise.all([rounds(),stations()])
 root.innerHTML=heading('区域轮换单','同一区域一张取货单，按站点和滤芯型号领料，每站每周只领一次。')+`
 <div class="round-deck">${routes.map(r=>`<article class="panel"><small>${h(r.code)} · ${h(r.service_on)}</small><h2>${h(r.district)}轮换</h2><p><meter min="0" max="${r.capacity}" value="${routeTotal(r.pickups)}"></meter> ${routeTotal(r.pickups)} / ${r.capacity} 根</p>
 ${table(['饮水台','料号','取货数'],r.pickups.map(x=>[x.station,x.cartridge,x.quantities]),'还未并单。')}
 ${session.role==='reviewer'?`<form class="compact-form"><input type="hidden" name="route" value="${h(r.code)}"><fieldset><legend>同区站点</legend>
 ${units.filter(x=>x.district===r.district&&x.in_service).map(x=>`<label><input type="checkbox" name="station" value="${h(x.code)}"> ${h(x.title)}（${x.upper==null?'待预测':'缺 '+Math.max(0,x.upper-x.reserve)}）</label>`).join('')}</fieldset><button>合并并审签领料</button>${feedback}</form>`:''}</article>`).join('')}</div>`
 for (const form of root.querySelectorAll('form'))wire(form,data=>bundle(data.route,new FormData(form).getAll('station')),()=>render(root,session))
}
