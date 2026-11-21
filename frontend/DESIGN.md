# Design rules

The single source of design rules for the frontend, for this chunk and every later one. AP Automation is a calm,
dense, trustworthy finance tool that an accounting team uses all day. It is product UI, not a marketing site.

Values live in code: colours, type and component defaults in `src/theme.ts`, global CSS in `src/styles/global.css`,
shared components in `src/ui/`. If a rule here and the code disagree, fix one of them in the same change.
Two tests enforce parts of this file: `src/ui/contrast.test.ts` (every colour pair) and `src/design.test.ts`
(searches the sources for the "Never" list).

## 1. Colour

Brand values come from Brandfetch (an unclaimed brand page for Brim). They are defined once, in `BRAND` in
`src/theme.ts`, so official values can replace them in one place. Brim's logo and wordmark are not used; the app name
is `APP_NAME` ("AP Automation").

| Colour | Value | Role | Contrast |
|---|---|---|---|
| Blumine | `#1E5572` | Primary: buttons, links, active navigation text, focus rings. Mantine palette `blumine`, shade 6 | 8.08:1 on white |
| Robin's Egg | `#00C2D5` | Decorative accent only: the 3px bar along the top of the header and the active-navigation bar. Later, the first chart series | 2.17:1 on white: never text, never behind text, never a focus ring or button fill |
| Sand | `#F1D49B` | Highlight surfaces only: the selected table row and the "changed" marker behind an edited field. Always with ink text | ink on Sand 11.03:1 |
| Sand tint | `#F9EED7` | Slim highlight banners: the one-line delegate banner (border `#EAD7AE`). Ink text | ink 13.75:1, secondary 5.95:1 |
| Ink | `#0B2533` | Body text (near-black, derived from Blumine) | 15.83:1 on white, 14.71:1 on page |
| Secondary | `#4A5D6A` | The only secondary text colour (titles under names, hints, metadata) | 6.85:1 on white, 6.37:1 on page |
| Placeholder | `#5A6C78` | Input placeholders | 5.45:1 on white |
| White | `#FFFFFF` | Surfaces: header, sidebar, panels, tables | |
| Page | `#F4F7F9` | Page background and table headers (one very light cool neutral) | |
| Border | `#CED8DF` | Dividers, table rules, panel borders (decorative) | |
| Control border | `#7A8C98` | Inputs and default buttons, so controls are identifiable | 3.48:1 on white |
| Primary tint | `#EAF2F6` | Active navigation item, row hover, and the part of an invoice a flag points at (with a 2px Blumine outline) | Blumine on it 7.13:1, ink 13.97:1 |

There are no lighter text greys than Secondary. Mantine's `c="dimmed"` is mapped to Secondary and its placeholder
colour to Placeholder, so Mantine defaults stay inside the palette.

**Severity** colours carry meaning and nothing else:

| Severity | Badge | Contrast |
|---|---|---|
| block | white on red `#B42318` | 6.57:1 |
| warn | white on orange-amber `#B54708` (clearly apart from Sand) | 5.43:1 |
| info | slate `#34495C` on `#EAEFF4` | 8.05:1 |

**Status** badges are dark text on a light tint with a 1px border, in five tones (`STATUS_TONES`); the mapping of
every bill, payment, vendor, bank-change and user status to a tone and a label is in `src/ui/statusStyles.ts`:

| Tone | Text on background | Contrast | Used for |
|---|---|---|---|
| neutral | `#3D4F5B` on `#EEF2F5` | 7.56:1 | void, credit open, cancelled, on leave |
| progress | `#1E5572` on `#E8F1F6` | 7.06:1 | pending approval, scheduled, released |
| success | `#0E5C36` on `#E6F4EC` | 7.11:1 | approved, paid, settled, verified, active |
| attention | `#7A3E00` on `#FDF0E2` | 7.45:1 | needs review, on hold, outstanding, pending review, pending verification |
| danger | `#912018` on `#FDECEA` | 7.58:1 | rejected, failed |

Other pairs: the role badge (Blumine on primary tint) is 7.13:1; the inline error box has a red title `#B42318` on
`#FDECEA` (5.75:1) with an ink message (13.84:1); the Blumine focus ring is 8.08:1 on white and 7.51:1 on the page
background (3:1 needed). `CONTRAST_PAIRS` in `src/theme.ts` lists every pair; add a new pair there when you add a
colour, and the contrast test checks it.

## 2. Typography

- **IBM Plex Sans** for all UI and body text. **IBM Plex Serif** for the page title only (`<Title order={1}>`, one
  per page), the one editorial touch. Section headings are `order={2}` and below, in Plex Sans, so a page keeps its
  heading order (h1, then h2 sections, then h3) without a second serif. **IBM Plex Mono** for IDs and codes
  (AP-00427, V004, PAY-00012, GL 6310, HST13).
- Self-hosted through Fontsource (`src/styles/fonts.css`): Sans 400/500/600, Serif 600, Mono 400/500, Latin and Latin
  Extended only. No font CDN. Never Inter.
- One scale, in the theme: 12 (xs, metadata), 13 (sm, compact UI), 14 (md, body), 16 (lg), 20 (xl). Headings: h1 28
  (serif, the page title), h2 18 (section), h3 16 (subsection, e.g. one flag), h4 14; all semibold.
- Money and other numbers use tabular figures (`font-variant-numeric: tabular-nums`) and are right-aligned in tables.
- No all-caps labels. Badges are sentence case too.
- Shared components (`src/ui/DataText.tsx`):
  - `<Id>AP-00427</Id>`: mono, slightly smaller than the text around it. Use it wherever an ID stands on its own (a
    cell, a header, a link). Inside a sentence an ID may stay in the body font.
  - `<MoneyText value="12345.60" currency="CAD" align="right" />`: formatted by `lib/money` ("$12,345.60",
    "US$1,000.00"), tabular, a right-aligned block with `align="right"`.
  - `<DateText value="2026-11-02" />` or `kind="timestamp"`: formatted by `lib/dates`, as a `<time>` element.

## 3. Surfaces and layout

- Structure comes from spacing, alignment and 1px borders, not shadows. There is one shadow (`theme.shadows`, all
  sizes equal), and only floating elements use it: menus, dropdowns, modals, drawers, notifications.
- Pages are sections with headings and dividers on the page background. A card (a bordered white panel) only where
  content truly stands alone, such as the sign-in panel. Never a card inside a card.
- 4px corners everywhere. Every radius size in the theme is 4px, so nothing is pill-shaped.
- The shell: a white header with the 3px Robin's Egg bar on top, a white sidebar, the page on the page background.
- Tables are the core component. The theme sets the defaults, so later chunks get them for free: compact rows,
  sticky header on the page neutral, no zebra stripes, row hover in the primary tint, 1px row rules. Mark numeric
  cells (and their header) with `data-numeric` to right-align them in tabular figures; mark the selected row with
  `data-selected` for the Sand highlight. An edited field gets `className="app-changed"` (Sand, ink text).
- Links inside a table (a bill id in the bills list) are underlined on hover; links in running text are always
  underlined.
- Loading tables and pages show static skeleton rows (`<Skeleton animate={false} />`), never a pulsing skeleton and
  never a spinner on a blank page. A spinner is fine for a small region (a lazy screen loading).
- Values read by intake with low confidence (below 80%) get a 2px amber (warn) underline, a tooltip with the
  percentage, and the same in visually hidden text (`className="app-low-confidence"`).
- A flag's `field` marks the part of the invoice it is about: wrap that part in `<FieldRegion name=...>`; while the
  flag is hovered, focused or pinned it gets the primary tint and a 2px Blumine outline. Not Sand: Sand means edited
  or selected.
- The approval route is a vertical timeline (`app-timeline` in global.css): a status icon (green approved, red
  rejected, grey waiting) on a 1px line, with the words beside it, so colour is never the only signal.
- Slim banners (the delegate line) are one line of ink text on the Sand tint with an info icon; any longer
  explanation goes in the icon's tooltip, and the icon-only button has an `aria-label`.

```tsx
<Table>
  <Table.Thead>
    <Table.Tr><Table.Th>Bill</Table.Th><Table.Th data-numeric>Total CAD</Table.Th></Table.Tr>
  </Table.Thead>
  <Table.Tbody>
    <Table.Tr data-selected={selected || undefined}>
      <Table.Td><Id>AP-00427</Id></Table.Td>
      <Table.Td data-numeric><MoneyText value={bill.total_cad} /></Table.Td>
    </Table.Tr>
  </Table.Tbody>
</Table>
```

## 4. Icons and motion

- `@tabler/icons-react` only, always through `<Icon icon={IconX} />` (`src/ui/Icon.tsx`), which fixes the stroke at
  1.75 and hides the icon from screen readers. Use icons sparingly, next to a label. An icon-only button needs an
  `aria-label`.
- Motion is functional only: hover and focus states, and transitions of at most 150 ms (modals, drawers, popovers,
  menus, tooltips, notifications, the mobile sidebar). Nothing bounces, floats, pulses or reveals on scroll.
  `prefers-reduced-motion` turns every transition into an instant change (theme `respectReducedMotion` and
  `global.css`).
- Keyboard focus is always visible: a 2px Blumine ring (`focusRing: 'auto'` for Mantine components, `:focus-visible`
  for everything else).

## 5. Copy

- Plain, specific, task-first: "Submit for approval", "Release payment", "3 bills need review".
- Say a thing once: no subtitle that repeats the title, no tooltip that repeats the label.
- Empty and placeholder states say what is missing and what comes next, in one line, without illustrations:
  "Payment scheduling and release are not built yet. They will list payments by date."
- Errors show the server's message and the request id (small, mono), so a user can quote it.
- Only real data from the API. No invented people, avatars, metrics, charts or sample rows. A person is shown as
  name, title and department (an initials avatar at most).

## 6. Shared pieces

| Piece | Where | Use |
|---|---|---|
| `StatusBadge kind status` | `src/ui/Badges.tsx` | Bill, payment, vendor, bank-change and user statuses, and flag resolutions |
| `SeverityBadge severity` | `src/ui/Badges.tsx` | Flag severity |
| `SeverityCountBadge severity count` | `src/ui/Badges.tsx` | Open-flag counts in a list ("2 block"); nothing for zero |
| `RoleBadge role` | `src/ui/Badges.tsx` | The signed-in user's role |
| `Id`, `MoneyText`, `DateText` | `src/ui/DataText.tsx` | IDs, amounts, dates and timestamps |
| `Icon` | `src/ui/Icon.tsx` | Every icon |
| `ErrorAlert` | `src/api/ErrorAlert.tsx` | An error inside a screen or form |
| `notifyError` | `src/api/notify.tsx` | An error after an action (a notification) |

## Never

- Purple or violet, anywhere.
- Gradients of any kind.
- Glassmorphism, blur, glow or neon effects.
- 3D shapes, blobs or decorative illustrations.
- A card inside a card.
- All-caps eyebrow labels.
- Emojis, in UI text, code or comments.
- The Inter font.
- Heroicons, Lucide or any icon set other than Tabler.
- Bounce, float, pulse or scroll-reveal animation.
- Buzzword copy: seamless, next-gen, reimagine, powerful, effortless, AI-powered, smart.
- Light-grey body text (nothing lighter than Secondary).
- Fake people, avatars, metrics or testimonials.
- Landing-page patterns: hero sections, feature grids.
