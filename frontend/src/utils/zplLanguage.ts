import { StreamLanguage, type StreamParser } from '@codemirror/language'

interface ZplState {
  inFieldData: boolean
  inComment: boolean
}

/** Minimal ZPL highlighting: commands, field data, variables and comments. */
const zplParser: StreamParser<ZplState> = {
  name: 'zpl',
  startState: () => ({ inFieldData: false, inComment: false }),
  token(stream, state) {
    // A ^FX comment runs to the next command, which may be on a later line.
    if (state.inComment) {
      if (stream.match(/[^^~]+/)) return 'comment'
      state.inComment = false
    }
    if (stream.match(/\^FX[^^~]*/i)) {
      state.inFieldData = false
      state.inComment = true
      return 'comment'
    }
    if (stream.match(/\{\{\s*[A-Za-z_][\w.-]*\s*\}\}/)) return 'variableName'
    if (stream.match(/[\^~](FD|FV|SN)/i)) {
      state.inFieldData = true
      return 'keyword'
    }
    if (stream.match(/[\^~](A[0-9A-Z@]?|[A-Z0-9]{2})/i)) {
      state.inFieldData = false
      return 'keyword'
    }
    if (state.inFieldData) {
      if (stream.match(/[^^~{]+/) || stream.next()) return 'string'
    }
    if (stream.match(/-?\d+(\.\d+)?/)) return 'number'
    stream.next()
    return null
  },
}

export const zplLanguage = StreamLanguage.define(zplParser)
