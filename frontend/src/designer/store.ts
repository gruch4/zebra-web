import { useReducer } from 'react'

import { emptyDesign, normalizeDesign, rescaleDesign } from './elements'
import type { Design, DesignElement } from './types'

const HISTORY_LIMIT = 100

export interface DesignerState {
  design: Design
  selectedId: string | null
  past: Design[]
  future: Design[]
  coalesceKey: string | null
}

export type DesignerAction =
  | { type: 'load'; design: Design }
  | { type: 'setLabel'; patch: Partial<Pick<Design, 'width_mm' | 'height_mm' | 'dpi'>> }
  | { type: 'add'; element: DesignElement }
  | { type: 'update'; id: string; patch: Partial<DesignElement>; coalesce?: string }
  | { type: 'remove'; id: string }
  | { type: 'duplicate'; id: string; newId: string }
  | { type: 'reorder'; id: string; direction: 'up' | 'down' }
  | { type: 'nudge'; id: string; dx: number; dy: number }
  | { type: 'select'; id: string | null }
  | { type: 'undo' }
  | { type: 'redo' }

export function initialState(design: Design = emptyDesign()): DesignerState {
  return { design, selectedId: null, past: [], future: [], coalesceKey: null }
}

function commit(state: DesignerState, design: Design, coalesceKey: string | null = null) {
  const coalesce = coalesceKey !== null && coalesceKey === state.coalesceKey
  return {
    ...state,
    design,
    past: coalesce ? state.past : [...state.past, state.design].slice(-HISTORY_LIMIT),
    future: [],
    coalesceKey,
  }
}

function clampPosition<T extends Partial<DesignElement>>(patch: T): T {
  const result = { ...patch }
  if (typeof result.x === 'number') result.x = Math.max(0, Math.round(result.x))
  if (typeof result.y === 'number') result.y = Math.max(0, Math.round(result.y))
  return result
}

function mapElements(design: Design, id: string, fn: (el: DesignElement) => DesignElement) {
  return { ...design, elements: design.elements.map((el) => (el.id === id ? fn(el) : el)) }
}

export function designerReducer(state: DesignerState, action: DesignerAction): DesignerState {
  switch (action.type) {
    case 'load':
      return initialState(normalizeDesign(action.design))
    case 'setLabel': {
      const { dpi, ...size } = action.patch
      // A new resolution rescales the elements so they print at the same size.
      const design =
        dpi !== undefined && dpi !== state.design.dpi
          ? rescaleDesign(state.design, dpi)
          : state.design
      return commit(state, { ...design, ...size })
    }
    case 'add':
      return {
        ...commit(state, { ...state.design, elements: [...state.design.elements, action.element] }),
        selectedId: action.element.id,
      }
    case 'update': {
      if (!state.design.elements.some((el) => el.id === action.id)) return state
      const patch = clampPosition(action.patch)
      const design = mapElements(
        state.design,
        action.id,
        (el) => ({ ...el, ...patch }) as DesignElement,
      )
      return commit(state, design, action.coalesce ? `${action.id}:${action.coalesce}` : null)
    }
    case 'nudge': {
      const element = state.design.elements.find((el) => el.id === action.id)
      if (!element) return state
      return designerReducer(state, {
        type: 'update',
        id: action.id,
        patch: { x: element.x + action.dx, y: element.y + action.dy },
        coalesce: 'nudge',
      })
    }
    case 'remove':
      return {
        ...commit(state, {
          ...state.design,
          elements: state.design.elements.filter((el) => el.id !== action.id),
        }),
        selectedId: state.selectedId === action.id ? null : state.selectedId,
      }
    case 'duplicate': {
      const element = state.design.elements.find((el) => el.id === action.id)
      if (!element) return state
      const copy = { ...element, id: action.newId, x: element.x + 10, y: element.y + 10 }
      return designerReducer(state, { type: 'add', element: copy })
    }
    case 'reorder': {
      const elements = [...state.design.elements]
      const index = elements.findIndex((el) => el.id === action.id)
      const target = action.direction === 'up' ? index + 1 : index - 1
      if (index < 0 || target < 0 || target >= elements.length) return state
      ;[elements[index], elements[target]] = [elements[target], elements[index]]
      return commit(state, { ...state.design, elements })
    }
    case 'select':
      return { ...state, selectedId: action.id, coalesceKey: null }
    case 'undo': {
      const previous = state.past.at(-1)
      if (!previous) return state
      return {
        ...state,
        design: previous,
        past: state.past.slice(0, -1),
        future: [state.design, ...state.future],
        coalesceKey: null,
        selectedId: previous.elements.some((el) => el.id === state.selectedId)
          ? state.selectedId
          : null,
      }
    }
    case 'redo': {
      const [next, ...future] = state.future
      if (!next) return state
      return {
        ...state,
        design: next,
        past: [...state.past, state.design],
        future,
        coalesceKey: null,
      }
    }
  }
}

export function useDesigner(design?: Design) {
  return useReducer(designerReducer, design, (d) => initialState(d))
}
