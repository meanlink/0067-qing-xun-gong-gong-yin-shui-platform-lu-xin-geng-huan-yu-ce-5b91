import {h} from './base.js'
export function demandLine(r,station) {
 const reserve=station?.reserve||0
 return `<tr><th scope="row">${h(station?.title||r.station)}</th><td>${r.expected.toFixed(2)}</td><td><strong>${r.upper}</strong></td><td>${reserve}</td><td>${Math.max(0,r.upper-reserve)}</td><td>${r.calibration.samples} 周 / ${r.calibration.positive} 个更换周</td><td><code class="basis-chip">${h((r.basis||'').slice(0,8))}</code></td></tr>`
}
