import {h,empty,badge} from './base.js'

export function table(headers, rows, message = '暂无记录，请先补齐上游资料。') {
  if (!rows.length) return empty(message)
  return `<div class="table-scroll"><table><thead><tr>${headers.map(x=>`<th scope="col">${h(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${h(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
}
export function choices(rows, label, value = row => row.code) {
  return rows.map(row => `<option value="${h(value(row))}">${h(label(row))}</option>`).join('')
}
export const states = Object.freeze({draft:'待核查',open:'办理中',approved:'已批准',closed:'已办结',held:'暂缓',ready:'已就绪',assigned:'已指派',published:'已发布',pending:'待处理',archived:'已封存'})
export const stateBadge = value => badge(states[value] || value,value)
export function heading(title, body) {
  return `<header class="module-heading"><h1>${h(title)}</h1><p>${h(body)}</p></header>`
}
export const feedback = '<p role="status" aria-live="polite"></p>'
