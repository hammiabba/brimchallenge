import { Box, Button, Divider, Group, Stack, Text, Title } from '@mantine/core'
import { IconFocus2 } from '@tabler/icons-react'

import { codeAsWords, personName, useFlagHelp, usePeople } from '../../api/reference'
import type { BillDetail, BillFlag } from '../../api/types'
import { SeverityBadge, StatusBadge } from '../../ui/Badges'
import { DateText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { FlagEvidence } from './FlagEvidence'
import { regionFor, useHighlight } from './highlight'

const SEVERITY_ORDER = { block: 0, warn: 1, info: 2 } as const

/** Flags sorted block, then warn, then info; the server's order within a severity. */
function sortFlags(flags: readonly BillFlag[]): BillFlag[] {
  return [...flags].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || a.id - b.id)
}

/** Open, or "Overridden by Priya Raman on Nov 2, 2026, 10:00 AM EST" with the reason given. */
function Resolution({ flag }: { flag: BillFlag }) {
  const people = usePeople()
  if (flag.resolution === 'open') return <StatusBadge kind="flag" status="open" />
  const verb = flag.resolution === 'overridden' ? 'Overridden' : 'Resolved'
  return (
    <Stack gap={2}>
      <Group gap={6} wrap="wrap">
        <StatusBadge kind="flag" status={flag.resolution} />
        <Text size="sm">
          {`${verb} by ${personName(flag.resolved_by, people.data)}`}
          {flag.resolved_at && <> on <DateText value={flag.resolved_at} kind="timestamp" /></>}
        </Text>
      </Group>
      {flag.resolution_comment && <Text size="sm">{`Reason: ${flag.resolution_comment}`}</Text>}
    </Stack>
  )
}

/**
 * One flag as a section: severity and title, this bill's facts (the flag message), what to do (flag help), the
 * evidence, and whether a person has dealt with it. Hovering or focusing it highlights the part of the invoice it
 * is about; "Show on invoice" pins the highlight and scrolls to it.
 */
function FlagSection({ flag, bill }: { flag: BillFlag; bill: BillDetail }) {
  const flagHelp = useFlagHelp()
  const { hover, pin } = useHighlight()
  const help = flagHelp.data?.[flag.code]
  const region = regionFor(flag.field)
  const titleId = `flag-${flag.id}-title`

  return (
    <Box
      component="section"
      aria-labelledby={titleId}
      onMouseEnter={() => hover(region)}
      onMouseLeave={() => hover(null)}
    >
      <Stack gap={6}>
        <Group gap="xs" wrap="nowrap" align="center">
          <SeverityBadge severity={flag.severity} />
          <Title order={3} id={titleId}>{help?.title ?? codeAsWords(flag.code)}</Title>
        </Group>
        <Text size="sm">{flag.message}</Text>
        {help?.help && (
          <Text size="sm"><Text span fw={600} inherit>What to do: </Text>{help.help}</Text>
        )}
        <FlagEvidence evidence={flag.evidence} currency={bill.currency} duplicates={bill.latest_run?.duplicates} />
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
          <Resolution flag={flag} />
          {region && (
            <Button
              variant="subtle"
              size="compact-sm"
              leftSection={<Icon icon={IconFocus2} size={14} />}
              onClick={() => pin(region)}
              onFocus={() => hover(region)}
              onBlur={() => hover(null)}
            >
              Show on invoice
            </Button>
          )}
        </Group>
      </Stack>
    </Box>
  )
}

/** The right column of the bill detail: the latest controls run's flags, most severe first. */
export function FlagsPanel({ bill }: { bill: BillDetail }) {
  const run = bill.latest_run
  const flags = run ? sortFlags(run.flags) : []
  return (
    <Stack gap="md">
      <Title order={2}>Flags</Title>
      {!run && <Text size="sm">No controls run yet, so this bill has no flags.</Text>}
      {run && flags.length === 0 && <Text size="sm">No flags on this bill.</Text>}
      {flags.map((flag, index) => (
        <Stack key={flag.id} gap="md">
          {index > 0 && <Divider />}
          <FlagSection flag={flag} bill={bill} />
        </Stack>
      ))}
    </Stack>
  )
}
