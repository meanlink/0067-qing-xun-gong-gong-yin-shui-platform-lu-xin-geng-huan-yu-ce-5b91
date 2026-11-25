import {api,waitJob} from './base.js'
export const forecasts=()=>api('/api/demand')
export async function run(data){
 const {job_id}=await api('/api/demand','POST',data)
 return waitJob(job_id)
}
