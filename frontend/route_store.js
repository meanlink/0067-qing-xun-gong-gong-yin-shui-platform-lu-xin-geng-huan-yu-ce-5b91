import {api} from './base.js'
export const rounds=()=>api('/api/rounds')
export const bundle=(route,stations)=>api('/api/rounds/'+encodeURIComponent(route)+'/bundle','POST',{stations})
