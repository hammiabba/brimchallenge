import { Anchor, Divider, Grid, Skeleton, Stack, Text, Title } from '@mantine/core'
import { useCallback, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../api/errors'
import { ErrorAlert } from '../api/ErrorAlert'
import { Id } from '../ui/DataText'
import { ApprovalRoute } from './detail/ApprovalRoute'
import { AuditTrail } from './detail/AuditTrail'
import { BillHeader } from './detail/BillHeader'
import { DecisionBar } from './detail/DecisionBar'
import { SubmitBar } from './detail/SubmitBar'
import { FlagsPanel } from './detail/FlagsPanel'
import { HighlightContext, regionDomId, type HighlightState, type InvoiceRegion } from './detail/highlight'
import { InvoicePanel } from './detail/InvoicePanel'
import { PaymentsTable } from './detail/PaymentsTable'
import { useBill } from './queries'

/** The audit trail's empty line for a bill imported from the history: its earlier events were never recorded. */
const HISTORY_AUDIT_MESSAGE = "Imported from the dataset history: what happened before the import isn't in the audit log."

/** Placeholder blocks while the bill loads (static, no pulse). */
function DetailSkeleton() {
  return (
    <Stack gap="md" aria-busy="true" aria-label="Loading bill">
      <Skeleton animate={false} height={28} width={260} />
      <Skeleton animate={false} height={48} />
      <Grid>
        <Grid.Col span={{ base: 12, lg: 7 }}><Skeleton animate={false} height={320} /></Grid.Col>
        <Grid.Col span={{ base: 12, lg: 5 }}><Skeleton animate={false} height={320} /></Grid.Col>
      </Grid>
    </Stack>
  )
}

/** Shown for a 404: the bill doesn't exist, or the server keeps it outside the signed-in user's scope. */
function BillNotFound({ billId }: { billId: string }) {
  return (
    <Stack gap="sm" maw={720}>
      <Title order={1}>Bill not found</Title>
      <Text>There is no bill <Id>{billId}</Id> that you can see.</Text>
      <Anchor component={Link} to="/bills" size="sm" w="fit-content">Back to bills</Anchor>
    </Stack>
  )
}

/**
 * /bills/:billId, the one screen: header, the invoice (left) beside its flags (right), the approval route,
 * payments and the audit trail, all from GET /bills/{bill_id}. Actions are shown only when allowed_actions allows
 * them: Approve and Reject (DecisionBar), Submit for approval (SubmitBar), and AP's edits in the header (department),
 * the invoice panel (details, line coding) and the flags (resolve, override).
 */
export default function BillDetailPage() {
  const { billId = '' } = useParams()
  const bill = useBill(billId)
  const [hovered, setHovered] = useState<InvoiceRegion | null>(null)
  const [pinned, setPinned] = useState<InvoiceRegion | null>(null)

  /** Pins a region and scrolls it into view. */
  const pin = useCallback((region: InvoiceRegion) => {
    setPinned(region)
    document.getElementById(regionDomId(region))?.scrollIntoView({ block: 'center' })
  }, [])
  const highlight = useMemo<HighlightState>(
    () => ({ active: hovered ?? pinned, hover: setHovered, pin }),
    [hovered, pinned, pin],
  )

  if (bill.isPending) return <DetailSkeleton />
  if (bill.error instanceof ApiError && bill.error.status === 404) return <BillNotFound billId={billId} />
  if (bill.isError) {
    return <ErrorAlert error={bill.error} title="Can't load this bill" onRetry={() => void bill.refetch()} />
  }

  const data = bill.data
  return (
    <HighlightContext.Provider value={highlight}>
      <Stack gap="lg">
        <BillHeader bill={data} />
        <DecisionBar bill={data} />
        <SubmitBar bill={data} />
        <Divider />
        <Grid gap="xl">
          <Grid.Col span={{ base: 12, lg: 7 }}><InvoicePanel bill={data} /></Grid.Col>
          <Grid.Col span={{ base: 12, lg: 5 }}><FlagsPanel bill={data} /></Grid.Col>
        </Grid>
        <Divider />
        <ApprovalRoute bill={data} />
        <Divider />
        <PaymentsTable bill={data} />
        <Divider />
        {/* A bill imported from the dataset history has no events from before the import: say so, rather than
            "no events yet" on a bill that was approved and paid. */}
        <AuditTrail bill={data} emptyMessage={data.origin === 'history' ? HISTORY_AUDIT_MESSAGE : undefined} />
      </Stack>
    </HighlightContext.Provider>
  )
}
