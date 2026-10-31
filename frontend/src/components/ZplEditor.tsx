import { useComputedColorScheme } from '@mantine/core'
import CodeMirror from '@uiw/react-codemirror'

import { zplLanguage } from '../utils/zplLanguage'

interface ZplEditorProps {
  value: string
  onChange: (value: string) => void
  height?: string
  readOnly?: boolean
}

export function ZplEditor({ value, onChange, height = '420px', readOnly }: ZplEditorProps) {
  const scheme = useComputedColorScheme('light')
  return (
    <CodeMirror
      aria-label="ZPL code"
      value={value}
      height={height}
      theme={scheme}
      readOnly={readOnly}
      extensions={[zplLanguage]}
      basicSetup={{ foldGutter: false, autocompletion: false }}
      onChange={onChange}
    />
  )
}
