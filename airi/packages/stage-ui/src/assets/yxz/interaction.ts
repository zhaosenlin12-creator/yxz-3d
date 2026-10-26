import type { YXZPoseId } from './index'

export const yxzInteractionPresentation = {
  idle: { label: '欢迎，我是宜小智', pose: 'frontWave' },
  listening: { label: '我在听，请告诉我', pose: 'sideWave' },
  thinking: { label: '正在思考…', pose: 'seatedWave' },
  speaking: { label: '正在回应', pose: 'topWave' },
  processing: { label: '正在处理，请稍候', pose: 'backWave' },
  success: { label: '完成了，看看效果吧', pose: 'topWave' },
} as const satisfies Record<string, { label: string, pose: YXZPoseId }>

export type YXZInteractionStatus = keyof typeof yxzInteractionPresentation

export function getYXZInteractionPresentation(status: YXZInteractionStatus) {
  return yxzInteractionPresentation[status]
}
