import backWave from './back-wave.png'
import frontWave from './front-wave.png'
import seatedWave from './seated-wave.png'
import sideWave from './side-wave.png'
import topWave from './top-wave.png'

export const yxzCharacter = {
  id: 'yxz',
  name: '宜小智',
  brand: 'YCSL',
  description: '宜小智 AI 智能创造系统的互动机器人形象。',
  poses: {
    frontWave: {
      id: 'front-wave',
      label: '正面欢迎',
      image: frontWave,
      usage: 'welcome',
    },
    sideWave: {
      id: 'side-wave',
      label: '侧身交流',
      image: sideWave,
      usage: 'listening',
    },
    seatedWave: {
      id: 'seated-wave',
      label: '坐姿互动',
      image: seatedWave,
      usage: 'thinking',
    },
    backWave: {
      id: 'back-wave',
      label: '背面展示',
      image: backWave,
      usage: 'processing',
    },
    topWave: {
      id: 'top-wave',
      label: '俯身回应',
      image: topWave,
      usage: 'success',
    },
  },
  defaultPose: 'frontWave',
} as const

export type YXZPoseId = keyof typeof yxzCharacter.poses

export function getYXZPose(pose: YXZPoseId = yxzCharacter.defaultPose) {
  return yxzCharacter.poses[pose]
}
