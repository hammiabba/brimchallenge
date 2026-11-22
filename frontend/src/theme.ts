/**
 * The design system's single source of colours, type and component defaults. The rules behind these values are in
 * frontend/DESIGN.md; read it before adding a colour, a font size or a shadow.
 *
 * This file is imported by the app, by tests and by the contrast check, so it imports no CSS and nothing at runtime
 * except @mantine/core.
 */
import { createTheme, rem, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core'

// ---------------------------------------------------------------- brand

/**
 * Brim brand colours. Source: Brandfetch, unclaimed brand page for Brim (no official brand guide was available).
 * If official values appear, change them here only; every other colour below is derived from or checked against them.
 */
export const BRAND = {
  /** Primary: buttons, links, active navigation text, focus rings. 8.1:1 on white. */
  blumine: '#1E5572',
  /** Decorative accent only: the header's top bar and the active-navigation bar. 2.2:1 on white, so never text. */
  robinsEgg: '#00C2D5',
  /** Highlight surfaces only (selected row, edited-field marker, delegate banner), always with ink text. */
  sand: '#F1D49B',
} as const

// ---------------------------------------------------------------- text and surfaces

/** Text colours. There is no lighter text grey than `secondary`. */
export const TEXT = {
  /** Body text: a near-black ink derived from Blumine. */
  ink: '#0B2533',
  /** Secondary text (titles under names, hints, metadata). Still 6.9:1 on white. */
  secondary: '#4A5D6A',
  /** Input placeholders: between the two, and still 5.4:1 on white. */
  placeholder: '#5A6C78',
  /** Text on a solid colour (primary buttons, block and warn badges). */
  onSolid: '#FFFFFF',
} as const

/** Surfaces and lines. */
export const SURFACE = {
  white: '#FFFFFF',
  /** Page background and table headers: one very light cool neutral. */
  page: '#F4F7F9',
  /** Dividers, table rules and panel borders (decorative, not text). */
  border: '#CED8DF',
  /** Borders that identify a control (inputs, default buttons): at least 3:1 on white. */
  controlBorder: '#7A8C98',
  /** The border around Sand surfaces. */
  sandBorder: '#D9B66E',
  /** A lighter Sand for slim banners (the delegate line), still with ink text. */
  sandTint: '#F9EED7',
  /** The border around the lighter Sand tint. */
  sandTintBorder: '#EAD7AE',
  /** Row hover and the active navigation background: the lightest Blumine tint. */
  primaryTint: '#EAF2F6',
  /** Small secondary text on a Blumine panel (the sign-in brand panel's demo note): 6.1:1 on Blumine. */
  onPrimaryMuted: '#D2E3EC',
} as const

// ---------------------------------------------------------------- Mantine palettes (shade 6 is the base)

/** Blumine, light to dark; shade 6 is the brand value and the primary shade. */
const blumine: MantineColorsTuple = [
  '#EAF2F6', '#D2E3EC', '#A9C8DA', '#7EABC6', '#5690B3', '#2C6688', '#1E5572', '#1A4A63', '#153D52', '#0F2E3F',
]
/** Cool neutrals. 0 is the page background, 3 the border, 5 the control border, 7 secondary text, 9 ink. */
const gray: MantineColorsTuple = [
  '#F4F7F9', '#EBF0F3', '#DEE5EA', '#CED8DF', '#B3C0C9', '#7A8C98', '#5A6C78', '#4A5D6A', '#2E404C', '#0B2533',
]
/** Block severity and errors. Shade 6 takes white text at 6.6:1. */
const red: MantineColorsTuple = [
  '#FDECEA', '#FBD5D1', '#F5ABA3', '#EE7F74', '#E2574A', '#CC3A2C', '#B42318', '#9A1E15', '#7F1912', '#63140E',
]
/** Warn severity: a saturated orange-amber, clearly apart from Sand. Shade 6 takes white text at 5.4:1. */
const orange: MantineColorsTuple = [
  '#FDEBDD', '#FBD6BA', '#F6B27F', '#EE8F47', '#E0741F', '#C95C0C', '#B54708', '#963B07', '#7A3006', '#5E2505',
]
/** Info severity: slate blue. */
const slate: MantineColorsTuple = [
  '#EAEFF4', '#D5DEE7', '#B0C0CF', '#8BA1B6', '#6C869D', '#587188', '#4A6378', '#3E5466', '#334555', '#273643',
]
/** Success statuses (approved, paid, verified). */
const green: MantineColorsTuple = [
  '#E6F4EC', '#C9E7D5', '#97D0AF', '#63B787', '#3B9C66', '#1F8350', '#146C40', '#0E5C36', '#0B4A2B', '#083820',
]

// ---------------------------------------------------------------- badges

/** One badge style: text on a background, with a 1px border (or the background colour itself for solid badges). */
export interface BadgeTone {
  color: string
  background: string
  border: string
}

/**
 * Status badges: dark text on a light tint. Each status maps to one tone in src/ui/statusStyles.ts. These carry status
 * only; flag severity has its own styles below.
 */
export const STATUS_TONES = {
  /** Nothing to do: void, cancelled, an open credit. */
  neutral: { color: '#3D4F5B', background: '#EEF2F5', border: '#C9D3DA' },
  /** Moving through the process: pending approval, scheduled, released. */
  progress: { color: blumine[6], background: '#E8F1F6', border: '#B7D0DF' },
  /** Done and good: approved, paid, settled, verified, active. */
  success: { color: green[7], background: green[0], border: '#A9D6BC' },
  /** Needs a person: needs review, on hold, outstanding, pending verification. */
  attention: { color: '#7A3E00', background: '#FDF0E2', border: '#F0BF8A' },
  /** Stopped: rejected, failed. */
  danger: { color: '#912018', background: red[0], border: '#F2B8B2' },
} as const satisfies Record<string, BadgeTone>

export type StatusTone = keyof typeof STATUS_TONES

/**
 * Flag severity badges. Block and warn are solid (white text) so they stand out from status tints; info is a slate
 * tint. These colours mean severity and nothing else.
 */
export const SEVERITY_STYLES = {
  block: { color: TEXT.onSolid, background: red[6], border: red[6] },
  warn: { color: TEXT.onSolid, background: orange[6], border: orange[6] },
  info: { color: '#34495C', background: slate[0], border: slate[2] },
} as const satisfies Record<'block' | 'warn' | 'info', BadgeTone>

/** The signed-in user's role badge in the header: Blumine on its lightest tint. */
export const ROLE_TONE: BadgeTone = { color: blumine[6], background: SURFACE.primaryTint, border: blumine[2] }

/** Inline error boxes (ErrorAlert): a light red surface; the title is red, the message stays ink. */
export const ERROR_SURFACE = { title: red[6], background: red[0], border: '#F2B8B2' } as const

// ---------------------------------------------------------------- contrast pairs (checked by src/ui/contrast.test.ts)

/** Every text/background pair the theme defines, with the WCAG minimum it must meet (4.5 text, 3 for UI parts). */
export const CONTRAST_PAIRS: ReadonlyArray<{ name: string; fg: string; bg: string; min: number }> = [
  { name: 'Body text on white', fg: TEXT.ink, bg: SURFACE.white, min: 4.5 },
  { name: 'Body text on page background', fg: TEXT.ink, bg: SURFACE.page, min: 4.5 },
  { name: 'Secondary text on white', fg: TEXT.secondary, bg: SURFACE.white, min: 4.5 },
  { name: 'Secondary text on page background', fg: TEXT.secondary, bg: SURFACE.page, min: 4.5 },
  { name: 'Placeholder on white', fg: TEXT.placeholder, bg: SURFACE.white, min: 4.5 },
  { name: 'White on primary (buttons)', fg: TEXT.onSolid, bg: BRAND.blumine, min: 4.5 },
  { name: 'White text on the Blumine sign-in panel', fg: TEXT.onSolid, bg: BRAND.blumine, min: 4.5 },
  { name: 'Muted text on the Blumine sign-in panel', fg: SURFACE.onPrimaryMuted, bg: BRAND.blumine, min: 4.5 },
  { name: 'Primary text and links on white', fg: BRAND.blumine, bg: SURFACE.white, min: 4.5 },
  { name: 'Primary text on page background', fg: BRAND.blumine, bg: SURFACE.page, min: 4.5 },
  { name: 'Active navigation text on its tint', fg: BRAND.blumine, bg: SURFACE.primaryTint, min: 4.5 },
  { name: 'Body text on row hover tint', fg: TEXT.ink, bg: SURFACE.primaryTint, min: 4.5 },
  { name: 'Ink on Sand', fg: TEXT.ink, bg: BRAND.sand, min: 4.5 },
  { name: 'Ink on Sand tint (delegate banner)', fg: TEXT.ink, bg: SURFACE.sandTint, min: 4.5 },
  { name: 'Secondary text on Sand tint', fg: TEXT.secondary, bg: SURFACE.sandTint, min: 4.5 },
  ...Object.entries(STATUS_TONES).map(([tone, t]) => ({
    name: `Status badge: ${tone}`, fg: t.color, bg: t.background, min: 4.5,
  })),
  ...Object.entries(SEVERITY_STYLES).map(([severity, t]) => ({
    name: `Severity badge: ${severity}`, fg: t.color, bg: t.background, min: 4.5,
  })),
  { name: 'Role badge', fg: ROLE_TONE.color, bg: ROLE_TONE.background, min: 4.5 },
  { name: 'Error text (red 6) on white', fg: red[6], bg: SURFACE.white, min: 4.5 },
  { name: 'Error title on error surface', fg: ERROR_SURFACE.title, bg: ERROR_SURFACE.background, min: 4.5 },
  { name: 'Body text on error surface', fg: TEXT.ink, bg: ERROR_SURFACE.background, min: 4.5 },
  { name: 'Secondary text on error surface', fg: TEXT.secondary, bg: ERROR_SURFACE.background, min: 4.5 },
  { name: 'Focus ring (primary) on white', fg: BRAND.blumine, bg: SURFACE.white, min: 3 },
  { name: 'Focus ring (primary) on page background', fg: BRAND.blumine, bg: SURFACE.page, min: 3 },
  { name: 'Control border on white', fg: SURFACE.controlBorder, bg: SURFACE.white, min: 3 },
]

// ---------------------------------------------------------------- type

export const FONT = {
  sans: '"IBM Plex Sans", "Helvetica Neue", Arial, sans-serif',
  /** Page titles (h1) only. */
  serif: '"IBM Plex Serif", Georgia, "Times New Roman", serif',
  /** IDs and codes (AP-00427, V004, GL 6310, HST13). */
  mono: '"IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace',
} as const

/** The one shadow, for floating elements only (menus, dropdowns, modals, drawers, notifications). */
const FLOATING_SHADOW = '0 4px 12px rgba(11, 37, 51, 0.14)'

/** Transitions are functional and short. */
const TRANSITION_MS = 150
const transitionProps = { duration: TRANSITION_MS }

export const theme = createTheme({
  primaryColor: 'blumine',
  primaryShade: 6,
  colors: { blumine, gray, red, orange, slate, green },
  black: TEXT.ink,
  white: SURFACE.white,

  fontFamily: FONT.sans,
  fontFamilyMonospace: FONT.mono,
  // A limited scale for a dense tool: 14px body, 13px for compact UI, 12px for metadata.
  fontSizes: { xs: rem(12), sm: rem(13), md: rem(14), lg: rem(16), xl: rem(20) },
  lineHeights: { xs: '1.4', sm: '1.45', md: '1.5', lg: '1.5', xl: '1.35' },
  headings: {
    fontFamily: FONT.sans,
    fontWeight: '600',
    sizes: {
      h1: { fontSize: rem(28), lineHeight: '1.25' },
      h2: { fontSize: rem(18), lineHeight: '1.35' },
      h3: { fontSize: rem(16), lineHeight: '1.35' },
      h4: { fontSize: rem(14), lineHeight: '1.4' },
      h5: { fontSize: rem(13), lineHeight: '1.4' },
      h6: { fontSize: rem(12), lineHeight: '1.4' },
    },
  },

  // 4px corners everywhere: every radius size is the same, so nothing can be pill-shaped by accident.
  radius: { xs: rem(4), sm: rem(4), md: rem(4), lg: rem(4), xl: rem(4) },
  defaultRadius: 'sm',
  // One shadow level; Mantine applies shadows only to floating elements by default, and nothing else asks for one.
  shadows: { xs: FLOATING_SHADOW, sm: FLOATING_SHADOW, md: FLOATING_SHADOW, lg: FLOATING_SHADOW, xl: FLOATING_SHADOW },

  focusRing: 'auto',
  respectReducedMotion: true,

  // Plain objects rather than Component.extend(): extend() would import every listed component into the bundle,
  // including ones no screen uses yet (Modal, Drawer, Menu...).
  components: {
    // Page titles (h1; order 1 is the default) are the one serif element. h2 and below are section headings.
    Title: {
      styles: (_theme: unknown, props: { order?: number }) => ({
        root: (props.order ?? 1) === 1 ? { fontFamily: FONT.serif } : {},
      }),
    },
    Badge: {
      defaultProps: { radius: 'sm', size: 'sm' },
      // Sentence case, not all caps.
      styles: { label: { textTransform: 'none', letterSpacing: 0, fontWeight: 600 } },
    },
    Table: {
      defaultProps: {
        stickyHeader: true,
        striped: false,
        highlightOnHover: true,
        withRowBorders: true,
        verticalSpacing: rem(6),
        horizontalSpacing: 'sm',
        fz: 'sm',
      },
      vars: () => ({
        table: {
          '--table-border-color': SURFACE.border,
          '--table-highlight-on-hover-color': SURFACE.primaryTint,
        },
      }),
    },
    Anchor: { defaultProps: { underline: 'always' } },
    AppShell: { defaultProps: { transitionDuration: TRANSITION_MS } },
    Burger: { defaultProps: { transitionDuration: TRANSITION_MS } },
    Modal: { defaultProps: { transitionProps } },
    Drawer: { defaultProps: { transitionProps } },
    Popover: { defaultProps: { transitionProps } },
    Menu: { defaultProps: { transitionProps } },
    Tooltip: { defaultProps: { transitionProps } },
    HoverCard: { defaultProps: { transitionProps } },
    Notification: { defaultProps: { withBorder: true } },
  },
})

/**
 * CSS variables for everything outside Mantine's own components (global.css), and the overrides that keep Mantine's
 * defaults inside the palette: secondary text instead of Mantine's lighter "dimmed" grey, an accessible placeholder,
 * and 3:1 control borders.
 */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {
    '--app-accent': BRAND.robinsEgg,
    '--app-sand': BRAND.sand,
    '--app-sand-border': SURFACE.sandBorder,
    '--app-sand-tint': SURFACE.sandTint,
    '--app-sand-tint-border': SURFACE.sandTintBorder,
    '--app-ink': TEXT.ink,
    '--app-text-secondary': TEXT.secondary,
    '--app-page': SURFACE.page,
    '--app-border': SURFACE.border,
    '--app-primary-tint': SURFACE.primaryTint,
    '--app-on-primary-muted': SURFACE.onPrimaryMuted,
    '--app-font-serif': FONT.serif,
    // The warn colour, for the low-confidence underline (a decoration next to text, at 5.4:1 on white).
    '--app-warn': orange[6],
  },
  light: {
    '--mantine-color-text': TEXT.ink,
    '--mantine-color-body': SURFACE.white,
    '--mantine-color-dimmed': TEXT.secondary,
    '--mantine-color-placeholder': TEXT.placeholder,
    '--mantine-color-default-border': SURFACE.controlBorder,
    '--mantine-color-anchor': BRAND.blumine,
    '--mantine-color-error': red[6],
  },
  dark: {},
})
