// 局域网访问安全上下文里也能用的 id 生成。
//
// crypto.randomUUID() 只在「安全上下文」里存在：https:// 或 http://localhost。
// 同事从另一台电脑用 http://192.168.x.x 打开工作台时，浏览器不给这个 API，
// 一调用就抛 "TypeError: crypto.randomUUID is not a function"，
// 于是「聊天能聊、一到生成预览就断」——正是之前局域网反馈的那个现象。
//
// crypto.getRandomValues() 在非安全上下文里是可以用的，所以这里用它取随机
// 字节自己拼 UUID；连 crypto 对象都拿不到时（极老浏览器）再退回 Math.random，
// 保证任何环境下都不会因为「没 id」而中断整条链路。

function randomBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length)
  const webCrypto = typeof globalThis !== 'undefined'
    ? (globalThis.crypto as Crypto | undefined)
    : undefined

  if (webCrypto?.getRandomValues) {
    webCrypto.getRandomValues(bytes)
    return bytes
  }

  for (let i = 0; i < length; i++) {
    bytes[i] = Math.floor(Math.random() * 256)
  }
  return bytes
}

// 标准 UUID v4 字符串（带连字符）。
export function uuidv4(): string {
  const webCrypto = typeof globalThis !== 'undefined'
    ? (globalThis.crypto as Crypto | undefined)
    : undefined

  if (webCrypto?.randomUUID) {
    return webCrypto.randomUUID()
  }

  const bytes = randomBytes(16)
  // version 4 + variant 10xx
  bytes[6] = (bytes[6] & 0x0F) | 0x40
  bytes[8] = (bytes[8] & 0x3F) | 0x80
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0'))
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join(''),
  ].join('-')
}

// 短 id（默认 12 位十六进制），用于会话号之类的内部标识。
export function shortId(length = 12): string {
  return uuidv4().replace(/-/g, '').slice(0, length)
}
