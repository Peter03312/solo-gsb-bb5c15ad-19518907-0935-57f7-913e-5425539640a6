// 常见移调乐器预设。diatonic / chromatic 均为“记谱音 -> 实际发声音”的【完整】有向音程
// （含真实八度差，不做八度压缩）。
// 例：中音萨克斯记谱 A4 实际发 C4 => 大六度下行：字母 -5、半音 -9；
//     Bb 小号记谱 D4 实际发 C4 => 小二度下行：字母 -1、半音 -2。
export const INSTRUMENT_PRESETS = [
  { id: 'c', label: 'C 调乐器（不偏移）', d: 0, c: 0 },
  { id: 'bb-trumpet', label: 'Bb 小号 / 单簧管（低大二度）', d: -1, c: -2 },
  { id: 'bb-tenor-sax', label: 'Bb 次中音萨克斯（高大九度记谱）', d: -8, c: -14 },
  { id: 'eb-alto', label: 'Eb 中音萨克斯（高大六度记谱）', d: -5, c: -9 },
  { id: 'eb-bari', label: 'Eb 上低音萨克斯（高大十三度记谱）', d: -12, c: -21 },
  { id: 'f-horn', label: 'F 圆号（高纯五度记谱）', d: -4, c: -7 },
  { id: 'a-clarinet', label: 'A 调单簧管（高小三度记谱）', d: -2, c: -3 },
  { id: 'd-trumpet', label: 'D 调小号（高大六度记谱）', d: -6, c: -10 },
  { id: 'eb-trumpet', label: 'Eb 调小号（低大三度，发声高小三度）', d: 2, c: 3 },
  { id: 'piccolo', label: '短笛（记谱低八度，发声高八度）', d: 7, c: 12 },
  { id: 'xylophone', label: '木琴（记谱低八度，发声高八度）', d: 7, c: 12 },
  { id: 'glockenspiel', label: '钟琴（记谱低两个八度）', d: 14, c: 24 },
  { id: 'dblbass', label: '低音提琴 / 电贝司（记谱高八度）', d: -7, c: -12 },
  { id: 'guitar', label: '吉他（记谱高八度）', d: -7, c: -12 },
  { id: 'custom', label: '自定义…', d: null, c: null },
]

export function findPreset(d, c) {
  return (
    INSTRUMENT_PRESETS.find(
      (p) => p.id !== 'custom' && p.d === Number(d) && p.c === Number(c),
    ) || null
  )
}

// 常见目标【书写】音域（记谱音域，非实际发声音域）
export const RANGE_PRESETS = [
  { id: 'alto-sax', label: '中音萨克斯记谱（Bb2–F#5）', low: 'Bb2', high: 'F#5' },
  { id: 'tenor-sax', label: '次中音萨克斯记谱（Ab2–E5）', low: 'Ab2', high: 'E5' },
  { id: 'bari-sax', label: '上低音萨克斯记谱（C2–A4）', low: 'C2', high: 'A4' },
  { id: 'trumpet', label: '小号记谱（F#3–D6）', low: 'F#3', high: 'D6' },
  { id: 'horn', label: '圆号记谱（E2–C5）', low: 'E2', high: 'C5' },
  { id: 'clarinet', label: 'Bb 单簧管记谱（E3–C6）', low: 'E3', high: 'C6' },
  { id: 'flute', label: '长笛（C4–D7）', low: 'C4', high: 'D7' },
  { id: 'voice', label: '人声音域（C3–C5）', low: 'C3', high: 'C5' },
]
