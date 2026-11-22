import { Anchor, Box, Button, Divider, Group, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconFocus2 } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { codeAsWords, personName, useFlagHelp, usePeople } from '../../api/reference'
import type { BillDetail, BillFlag } from '../../api/types'
import { SeverityBadge, StatusBadge } from '../../ui/Badges'
import { DateText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { CommentActionModal } from '../../vendors/CommentActionModal'
import { useResolveFlag } from '../mutations'
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

/** Flags only their own workflow clears (backend services/bills.py VERIFY_TO_CLEAR): no Resolve button for them. */
const VERIFY_TO_CLEAR: ReadonlySet<string> = new Set(['BANK_CHANGE_UNVERIFIED'])

/**
 * Resolve and Override for one open flag, from the bill's allowed_actions: resolve_flags for resolving any flag and
 * overriding a warning, override_blocking_flags for overriding a block (finance manager or controller only). Both
 * need a comment, kept in the audit log. Someone who may resolve but not override a block is told why.
 */
function FlagActions({ flag, bill, title }: { flag: BillFlag; bill: BillDetail; title: string }) {
  const [open, setOpen] = useState<'resolved' | 'overridden' | null>(null)
  const resolve = useResolveFlag(bill, flag.id, 'resolved')
  const override = useResolveFlag(bill, flag.id, 'overridden')
  const actions = bill.allowed_actions ?? {}
  // An unverified bank change is cleared by verifying it, not by marking it fixed (the server refuses that too).
  const clearedByVerification = VERIFY_TO_CLEAR.has(flag.code)
  const canResolve = (actions.resolve_flags?.allowed ?? false) && !clearedByVerification
  const overrideAction = flag.severity === 'block' ? actions.override_blocking_flags : actions.resolve_flags
  const canOverride = overrideAction?.allowed ?? false
  if (!canResolve && !canOverride && !clearedByVerification) return null
  // The dialogs stay mounted once the flag is closed, so their success handling still runs after the bill refreshes.
  const isOpen = flag.resolution === 'open'

  function done(verb: string) {
    notifications.show({ title: `Flag ${verb}`, message: `${title} on ${bill.bill_id}` })
    setOpen(null)
  }

  return (
    <Stack gap={4}>
      {isOpen && (
        <Group gap="xs" wrap="nowrap">
          {canResolve && <Button size="xs" onClick={() => setOpen('resolved')}>Resolve</Button>}
          {canOverride && <Button size="xs" variant="default" onClick={() => setOpen('overridden')}>Override</Button>}
        </Group>
      )}
      {isOpen && clearedByVerification && (
        <Text size="xs" c="dimmed">
          {'Verify the bank change in '}
          <Anchor component={Link} to="/bank-changes" inherit>Bank changes</Anchor>
          {' to clear this flag.'}
        </Text>
      )}
      {isOpen && !canOverride && flag.severity === 'block' && (
        <Text size="xs" c="dimmed">Only a finance manager or the controller can override a blocking flag.</Text>
      )}
      <CommentActionModal
        opened={open === 'resolved'}
        onClose={() => setOpen(null)}
        title="Resolve flag"
        description={`Mark "${title}" as fixed and say what you did or checked.`}
        mutation={resolve}
        onDone={() => done('resolved')}
        commentRequired
      />
      <CommentActionModal
        opened={open === 'overridden'}
        onClose={() => setOpen(null)}
        title="Override flag"
        description={`Accept the bill despite "${title}" and say why.${flag.severity === 'block' ? ' This lets a blocked bill go on to approval.' : ''}`}
        mutation={override}
        onDone={() => done('overridden')}
        danger
        commentRequired
      />
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
        {/* On a bill that is already paid the flag can no longer hold anything up; say so before "What to do",
            which was written for bills on their way to payment. */}
        {bill.status === 'paid' && flag.resolution === 'open' && (
          <Text size="sm" fw={500}>
            Found after payment: this bill was already paid. If the problem holds, ask the vendor for a credit note or a
            refund.
          </Text>
        )}
        {help?.help && (
          <Text size="sm"><Text span fw={600} inherit>What to do: </Text>{help.help}</Text>
        )}
        <FlagEvidence evidence={flag.evidence} currency={bill.currency} duplicates={bill.latest_run?.duplicates} />
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
          <Resolution flag={flag} />
          <FlagActions flag={flag} bill={bill} title={help?.title ?? codeAsWords(flag.code)} />
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
      {!run && <Text size="sm">Not checked yet, so this bill has no flags.</Text>}
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
