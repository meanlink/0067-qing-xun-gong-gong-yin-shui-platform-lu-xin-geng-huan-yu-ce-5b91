import {mount} from './base.js'
import {render as fleet} from './fleet.js'
import {render as readings} from './readings.js'
import {render as demand} from './demand.js'
import {render as rounds} from './rounds.js'

const pages = {
  fleet: '饮水台与滤芯',
  readings: '周读数',
  demand: '更换量情景',
  rounds: '区域轮换单'
}
const renderers = {fleet, readings, demand, rounds}
mount({title: '清巡 · 公共饮水台滤芯更换预测', kicker: '桥北社区设施组 · 滤芯巡行单', pages, render: (key, root, session) => renderers[key](root, session)})
