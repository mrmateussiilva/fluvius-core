import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/styles/main.css', import.meta.url), 'utf8')
const lightTheme = css.match(/:root\s*\{([\s\S]*?)\n\s*\}/)?.[1]

if (!lightTheme) {
  throw new Error('Não foi possível localizar os tokens do tema claro.')
}

function token(name) {
  const match = lightTheme.match(
    new RegExp(`--color-${name}:\\s*(\\d+)\\s+(\\d+)\\s+(\\d+);`),
  )
  if (!match) throw new Error(`Token --color-${name} não encontrado.`)
  return match.slice(1).map(Number)
}

function luminance([red, green, blue]) {
  const channel = (value) => {
    const normalized = value / 255
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
}

function contrast(first, second) {
  const lighter = Math.max(luminance(first), luminance(second))
  const darker = Math.min(luminance(first), luminance(second))
  return (lighter + 0.05) / (darker + 0.05)
}

const checks = [
  ['ink / panel', 'ink', 'panel', 7],
  ['ink-secondary / panel', 'ink-secondary', 'panel', 7],
  ['ink-muted / panel', 'ink-muted', 'panel', 7],
  ['ink-faint / panel', 'ink-faint', 'panel', 4.5],
  ['line-strong / panel', 'line-strong', 'panel', 3],
  ['success-strong / success-soft', 'success-strong', 'success-soft', 4.5],
  ['warning-strong / warning-soft', 'warning-strong', 'warning-soft', 4.5],
  ['danger-strong / danger-soft', 'danger-strong', 'danger-soft', 4.5],
  ['info-strong / info-soft', 'info-strong', 'info-soft', 4.5],
]

let failed = false
for (const [label, foreground, background, minimum] of checks) {
  const ratio = contrast(token(foreground), token(background))
  const passed = ratio >= minimum
  failed ||= !passed
  console.log(`${passed ? 'PASS' : 'FAIL'} ${label}: ${ratio.toFixed(2)}:1 (mínimo ${minimum}:1)`)
}

if (failed) process.exitCode = 1
