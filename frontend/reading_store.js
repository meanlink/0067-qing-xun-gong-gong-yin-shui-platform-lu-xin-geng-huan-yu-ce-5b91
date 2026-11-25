import {api} from './base.js'
export const readings=()=>api('/api/readings')
export const record=d=>api('/api/readings','POST',{...d,liters:Number(d.liters),changes:Number(d.changes)})
