/**
 * Dashboard grid foundation (4.C.1).
 *
 * The HUD is a primitive snap-grid: GRID_COLS × GRID_ROWS whole cells, every
 * widget sized + placed in cell units. The layout is DATA (an `{x,y,w,h}` per
 * widget, the same shape react-grid-layout uses) rendered today via plain CSS
 * Grid — so a future drag-resize is a near-free flip: mutate this layout in
 * state on resize, or hand the identical array to react-grid-layout once it
 * supports React 19 (its current release relies on the now-removed
 * `ReactDOM.findDOMNode`, so CSS Grid is the resize-ready foundation for now).
 *
 * Tiling is exhaustive + non-overlapping across all 12×12 cells (verified by
 * eye against the map below); empty cells would simply reveal the backdrop.
 * (4.C.2: the context meter moved back into the chat widget, so its old row-8
 * strip is gone — the middle band now runs rows 2–8 to keep the grid full.)
 *
 *   cols →            0  1  2 | 3  4  5  6  7 | 8  9 10 11
 *   row 0-1   clock(0-2)      | weather(3-6)  status(7-8) | uptime(9-11)
 *   row 2-4   system(0-2)     | orb(3-7).............. | chat(8-11)......
 *   row 5-8   health(0-2)     | orb(3-7).............. | chat(8-11)......
 *   row 9-11  event-log(0-11) — full-width
 */
export const GRID_COLS = 12;
export const GRID_ROWS = 12;

export interface GridSpec {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type WidgetId =
  | "clock"
  | "weather"
  | "status"
  | "uptime"
  | "system"
  | "orb"
  | "chat"
  | "health"
  | "eventlog";

export const DASHBOARD_LAYOUT: Record<WidgetId, GridSpec> = {
  clock: { x: 0, y: 0, w: 3, h: 2 },
  weather: { x: 3, y: 0, w: 4, h: 2 },
  status: { x: 7, y: 0, w: 2, h: 2 },
  uptime: { x: 9, y: 0, w: 3, h: 2 },
  system: { x: 0, y: 2, w: 3, h: 3 },
  orb: { x: 3, y: 2, w: 5, h: 7 },
  chat: { x: 8, y: 2, w: 4, h: 7 },
  health: { x: 0, y: 5, w: 3, h: 4 },
  eventlog: { x: 0, y: 9, w: 12, h: 3 },
};

/** Cell-units → CSS Grid placement (1-based line numbers). The single point
 *  that turns the resize-ready data model into concrete grid styles. */
export function gridStyle({ x, y, w, h }: GridSpec): React.CSSProperties {
  return {
    gridColumn: `${x + 1} / span ${w}`,
    gridRow: `${y + 1} / span ${h}`,
  };
}
