/** Instrument presets: interval from WRITTEN note to SOUNDING note.
 *
 * L = directed diatonic letter steps, S = directed chromatic semitones.
 * Examples:
 *   Bb trumpet  written C4 -> sounding Bb3  => L=-1, S=-2
 *   F horn      written C5 -> sounding F4   => L=-4, S=-7
 */
export const INSTRUMENT_PRESETS = [
  { id: 'c', label: 'C 调乐器（原调，长笛/小提琴等）', L: 0, S: 0 },
  { id: 'bb-trumpet', label: 'B♭ 小号 / 单簧管（高音）', L: -1, S: -2 },
  { id: 'bb-bass-clarinet', label: 'B♭ 低音单簧管 / 次中音萨克斯', L: -8, S: -14 },
  { id: 'eb-alto', label: 'E♭ 中音萨克斯', L: -5, S: -9 },
  { id: 'eb-bari', label: 'E♭ 上低音萨克斯', L: -12, S: -21 },
  { id: 'f-horn', label: 'F 圆号', L: -4, S: -7 },
  { id: 'a-clarinet', label: 'A 调单簧管', L: -2, S: -3 },
  { id: 'piccolo', label: '短笛（记谱比实际高八度）', L: -7, S: -12 },
  { id: 'bass', label: '低音提琴 / 倍大管（记谱比实际低八度）', L: 7, S: 12 },
  { id: 'guitar', label: '吉他（记谱比实际高八度）', L: -7, S: -12 },
  { id: 'custom', label: '自定义（手动填写步数与半音数）', L: null, S: null },
]

export function findPreset(L, S) {
  return INSTRUMENT_PRESETS.find(
    (p) => p.L === Number(L) && p.S === Number(S)
  )
}
