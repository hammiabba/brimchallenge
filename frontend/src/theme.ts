/**
 * The Mantine theme: neutral greys, one calm blue as the primary colour, system fonts (nothing fetched), small
 * radii and compact tables for dense AP work. No logos or brand colours.
 */
import { createTheme, type MantineColor, type MantineColorsTuple } from '@mantine/core'

import type { Severity } from './api/types'

/** A muted slate blue, light to dark. Shade 7 is the primary on a light background. */
const slate: MantineColorsTuple = [
  '#eef3f8',
  '#dde6ef',
  '#b9cadd',
  '#93adca',
  '#7394ba',
  '#5f85b0',
  '#537cab',
  '#436a96',
  '#395e87',
  '#2b5078',
]

export const theme = createTheme({
  primaryColor: 'slate',
  primaryShade: 7,
  colors: { slate },
  defaultRadius: 'sm',
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  headings: { fontWeight: '600' },
  components: {
    Table: {
      defaultProps: { verticalSpacing: 'xs', horizontalSpacing: 'sm', highlightOnHover: true, fz: 'sm' },
    },
    Badge: {
      defaultProps: { variant: 'light', radius: 'sm' },
    },
  },
})

/**
 * Badge colours for flag severities (used by the bill screens): block stops the bill, warn needs a person to look,
 * info is shown for context. Grey for info keeps it apart from the blue primary colour.
 */
export const SEVERITY_COLORS: Record<Severity, MantineColor> = {
  block: 'red',
  warn: 'yellow',
  info: 'gray',
}
