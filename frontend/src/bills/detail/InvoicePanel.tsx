import { Group, List, SimpleGrid, Stack, Table, Text, Title, Tooltip, VisuallyHidden } from '@mantine/core'
import { Fragment, type ReactNode } from 'react'

import { departmentLabel, glAccountName, personName, useDepartments, useGlAccounts, usePeople } from '../../api/reference'
import type { BillDetail, BillLine } from '../../api/types'
import { parseDateOnly } from '../../lib/dates'
import { decimalToPercent } from '../../lib/decimal'
import { isMoney, parseMoneyInput } from '../../lib/money'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import {
  LOW_CONFIDENCE,
  confidenceFor,
  confidencePercent,
  differs,
  extractionWarnings,
  snapshotText,
  type Snapshot,
} from '../extraction'
import { vendorMatchLine } from '../labels'
import { FieldRegion } from './FieldRegion'
import type { InvoiceRegion } from './highlight'

type Kind = 'text' | 'date' | 'id' | 'money'

/**
 * A raw value shown by kind: a date via lib/dates, an id in mono, money via lib/money (the snapshot may hold "6452.3",
 * which is normalised first; anything that still isn't money is shown as sent), else plain text.
 */
function Value({ raw, kind, currency }: { raw: string | null; kind: Kind; currency: string }) {
  if (raw === null || raw === '') return <Text span c="dimmed" inherit>none</Text>
  if (kind === 'date' && parseDateOnly(raw)) return <DateText value={raw} />
  if (kind === 'id') return <Id>{raw}</Id>
  if (kind === 'money') {
    const money = isMoney(raw) ? raw : parseMoneyInput(raw)
    return money ? <MoneyText value={money} currency={currency} /> : <>{raw}</>
  }
  return <>{raw}</>
}

/** Wraps a value read with low confidence: amber underline, a tooltip with the percentage, and the same in text. */
function LowConfidence({ confidence, children }: { confidence: number | null; children: ReactNode }) {
  if (confidence === null || confidence >= LOW_CONFIDENCE) return <>{children}</>
  const percent = confidencePercent(confidence)
  return (
    <Tooltip label={`Read with ${percent} confidence`}>
      <span className="app-low-confidence" tabIndex={0}>
        {children}
        <VisuallyHidden>{` (low confidence, ${percent})`}</VisuallyHidden>
      </span>
    </Tooltip>
  )
}

interface FieldProps {
  label: string
  region: InvoiceRegion
  kind: Kind
  current: string | null
  /** The snapshot path of the extracted value; omit for bills without a snapshot. */
  extractedPath?: string
  /** The field_confidence key, when it differs from the snapshot path. */
  confidenceKey?: string
  /** What to show for the current value instead of the raw text (a name next to an id). */
  display?: ReactNode
}

/**
 * One invoice field: the current value, or "extracted → current" with a Sand "changed" marker when a person
 * corrected what intake read. Low extraction confidence is underlined.
 */
function Field({ label, region, kind, current, extractedPath, confidenceKey, display, snapshot, currency }: FieldProps & {
  snapshot: Snapshot | null
  currency: string
}) {
  const extracted = extractedPath && snapshot ? snapshotText(snapshot, extractedPath) : null
  const changed = Boolean(snapshot && extractedPath) && differs(extracted, current, kind === 'money' ? 'money' : 'text')
  const confidence = snapshot ? confidenceFor(snapshot, confidenceKey ?? extractedPath ?? region) : null
  const currentView = display ?? <Value raw={current} kind={kind} currency={currency} />
  return (
    <Fragment>
      <Text component="dt" size="sm" c="dimmed">{label}</Text>
      <Text component="dd" size="sm" m={0}>
        <FieldRegion name={region}>
          {changed ? (
            <>
              <LowConfidence confidence={confidence}>
                <Text span c="dimmed" inherit><Value raw={extracted} kind={kind} currency={currency} /></Text>
              </LowConfidence>
              <span aria-hidden>{' → '}</span>
              <VisuallyHidden>{' extracted, changed to '}</VisuallyHidden>
              <span className="app-changed">{currentView}</span>
            </>
          ) : (
            <LowConfidence confidence={confidence}>{currentView}</LowConfidence>
          )}
        </FieldRegion>
      </Text>
    </Fragment>
  )
}

/** The coding cell of a line: GL (mono) and name, department name, and how the coding was set. */
function CodingCell({ line }: { line: BillLine }) {
  const gl = useGlAccounts()
  const departments = useDepartments()
  const people = usePeople()
  if (!line.gl_account && !line.suggested_gl_account) {
    return <Text size="sm" c="dimmed">Not coded</Text>
  }
  const glNumber = line.gl_account ?? line.suggested_gl_account ?? ''
  const department = line.department_id ?? line.suggested_department_id
  let how: ReactNode = null
  if (line.coding_status === 'accepted') {
    how = line.coded_by ? `Confirmed by clerk (${personName(line.coded_by, people.data)})` : 'Confirmed by clerk'
  } else if (line.coding_status === 'overridden') {
    how = `Changed by clerk${line.suggested_gl_account ? `; suggested ${line.suggested_gl_account}` : ''}`
  } else if (line.coding_status === 'suggested') {
    const confidence = line.suggestion_confidence !== null && line.suggestion_confidence !== undefined
      ? `, ${confidencePercent(line.suggestion_confidence)}` : ''
    how = `Suggested${confidence}${line.suggestion_reason ? `: ${line.suggestion_reason}` : ''}`
  }
  return (
    <Stack gap={0}>
      <Text size="sm"><Id>{glNumber}</Id> {glAccountName(glNumber, gl.data) ?? ''}</Text>
      {department && <Text size="xs">{departmentLabel(department, departments.data)}</Text>}
      {how && <Text size="xs" c="dimmed">{how}</Text>}
    </Stack>
  )
}

/** The vendor as printed on the invoice and how intake matched it; masked bank details exactly as sent. */
function VendorBlock({ bill, snapshot }: { bill: BillDetail; snapshot: Snapshot | null }) {
  if (!snapshot) {
    return (
      <FieldRegion name="vendor">
        <Text size="sm">
          {bill.vendor_name ?? 'No vendor'} {bill.vendor_id && <Id>{bill.vendor_id}</Id>}
        </Text>
        <Text size="sm" c="dimmed">Loaded from the dataset history: there is no extraction snapshot for this bill.</Text>
      </FieldRegion>
    )
  }
  const bank = ['institution', 'transit', 'account']
    .map((key) => [key, snapshotText(snapshot, `vendor.bank.${key}`)] as const)
    .filter(([, value]) => value !== null)
  return (
    <FieldRegion name="vendor">
      <Stack gap={4}>
        <Text size="sm">
          {snapshotText(snapshot, 'vendor.name_on_invoice') ?? 'No name read'}
          {bill.vendor_name && bill.vendor_name !== snapshotText(snapshot, 'vendor.name_on_invoice') && (
            <Text span c="dimmed" inherit>{` (vendor master: ${bill.vendor_name})`}</Text>
          )}
        </Text>
        <Text size="sm" c="dimmed">
          {vendorMatchLine(snapshot.vendor && (snapshot.vendor as Snapshot).match_method,
            snapshot.vendor && (snapshot.vendor as Snapshot).match_score)}
        </Text>
        <FieldRegion name="vendor.gst_number">
          <Text size="sm">GST/HST number: <Value raw={snapshotText(snapshot, 'vendor.gst_number')} kind="id" currency="CAD" /></Text>
        </FieldRegion>
        <FieldRegion name="vendor.bank">
          <Text size="sm">
            Bank:{' '}
            {bank.length === 0
              ? <Text span c="dimmed" inherit>none on the invoice</Text>
              : bank.map(([key, value], index) => (
                <Fragment key={key}>
                  {index > 0 && ', '}
                  {key} <Id>{value ?? ''}</Id>
                </Fragment>
              ))}
          </Text>
        </FieldRegion>
      </Stack>
    </FieldRegion>
  )
}

/** The lines table: quantities and unit prices as sent, amounts as money, and the coding. */
function LinesTable({ bill }: { bill: BillDetail }) {
  return (
    <FieldRegion name="lines">
      <Table.ScrollContainer minWidth={640}>
        <Table aria-label="Invoice lines" withTableBorder bg="white" stickyHeader={false}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th data-numeric>Line</Table.Th>
              <Table.Th>Description</Table.Th>
              <Table.Th data-numeric>Qty</Table.Th>
              <Table.Th data-numeric>Unit price</Table.Th>
              <Table.Th data-numeric>Amount</Table.Th>
              <Table.Th>Coding</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {bill.lines.map((line) => (
              <Table.Tr key={line.line_no}>
                <Table.Td data-numeric>{line.line_no}</Table.Td>
                <Table.Td>{line.description}</Table.Td>
                <Table.Td data-numeric>{line.quantity}</Table.Td>
                <Table.Td data-numeric>{line.unit_price}</Table.Td>
                <Table.Td data-numeric><MoneyText value={line.amount} currency={bill.currency} /></Table.Td>
                <Table.Td><CodingCell line={line} /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </FieldRegion>
  )
}

/** The taxes table with the subtotal and total below it (extracted → current when corrected). */
function TaxesTable({ bill, snapshot }: { bill: BillDetail; snapshot: Snapshot | null }) {
  /** A total row: the amount, with the extracted amount first when a person corrected it. */
  const totalRow = (label: string, region: InvoiceRegion, current: string, path: string) => {
    const extracted = snapshot ? snapshotText(snapshot, path) : null
    const changed = snapshot !== null && differs(extracted, current, 'money')
    return (
      <Table.Tr>
        <Table.Th scope="row" colSpan={2}>{label}</Table.Th>
        <Table.Td data-numeric>
          <FieldRegion name={region}>
            {changed && extracted && (
              <>
                <Text span c="dimmed" size="sm"><Value raw={extracted} kind="money" currency={bill.currency} /></Text>
                <span aria-hidden>{' → '}</span>
                <VisuallyHidden>{' extracted, changed to '}</VisuallyHidden>
              </>
            )}
            <span className={changed ? 'app-changed' : undefined}>
              <MoneyText value={current} currency={bill.currency} fw={label === 'Total' ? 600 : undefined} />
            </span>
          </FieldRegion>
        </Table.Td>
      </Table.Tr>
    )
  }
  return (
    <FieldRegion name="taxes">
      <Table aria-label="Taxes and totals" withTableBorder bg="white" stickyHeader={false} maw={420}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Tax</Table.Th>
            <Table.Th data-numeric>Rate</Table.Th>
            <Table.Th data-numeric>Amount</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {bill.taxes.length === 0 && (
            <Table.Tr><Table.Td colSpan={3}><Text size="sm" c="dimmed">No tax charged.</Text></Table.Td></Table.Tr>
          )}
          {bill.taxes.map((tax, index) => (
            <Table.Tr key={`${tax.tax_code}-${index}`}>
              <Table.Td><Id>{tax.tax_code}</Id></Table.Td>
              <Table.Td data-numeric>{decimalToPercent(tax.rate)}</Table.Td>
              <Table.Td data-numeric><MoneyText value={tax.amount} currency={bill.currency} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
        <Table.Tfoot>
          {totalRow('Subtotal', 'subtotal', bill.subtotal, 'subtotal')}
          {totalRow('Total', 'total', bill.total, 'total')}
        </Table.Tfoot>
      </Table>
    </FieldRegion>
  )
}

/**
 * The left column of the bill detail: the invoice as read and as it stands now (fields, vendor, warnings, lines,
 * taxes and totals). Every part a flag can point at is a FieldRegion.
 */
export function InvoicePanel({ bill }: { bill: BillDetail }) {
  const people = usePeople()
  const snapshot = (bill.extracted ?? null) as Snapshot | null
  const warnings = extractionWarnings(snapshot)
  const common = { snapshot, currency: bill.currency }
  const source = snapshot
    ? [snapshotText(snapshot, 'source.file_name'), snapshotText(snapshot, 'source.email_id')]
      .filter(Boolean).join(', from email ')
    : null

  return (
    <Stack gap="md">
      <Group justify="space-between" align="baseline">
        <Title order={2}>Invoice</Title>
        {source && <Text size="xs" c="dimmed">{source}</Text>}
      </Group>

      <SimpleGrid component="dl" cols={2} spacing="xs" verticalSpacing={6} m={0}
        style={{ gridTemplateColumns: 'max-content 1fr' }}>
        <Field {...common} label="Invoice number" region="invoice_number" kind="id"
          current={bill.vendor_invoice_number} extractedPath="invoice_number" />
        <Field {...common} label="Invoice date" region="invoice_date" kind="date" current={bill.invoice_date}
          extractedPath="invoice_date" />
        <Field {...common} label="Due date" region="due_date" kind="date" current={bill.due_date ?? null}
          extractedPath="due_date" />
        <Field {...common} label="Currency" region="currency" kind="text" current={bill.currency} extractedPath="currency" />
        <Field {...common} label="Ship-to province" region="ship_to_province" kind="text"
          current={bill.ship_to_province ?? null} extractedPath="ship_to_province" />
        <Field {...common} label="PO" region="po_number" kind="id" current={bill.po_id ?? null} extractedPath="po_number" />
        <Field {...common} label="Contract" region="contract_id" kind="id" current={bill.contract_id ?? null}
          extractedPath="contract_id" />
        <Field {...common} label="Requester" region="requester_user_id" kind="id"
          current={bill.requester_user_id ?? null} extractedPath="requester_user_id"
          display={bill.requester_user_id
            ? <>{personName(bill.requester_user_id, people.data)} <Id>{bill.requester_user_id}</Id></>
            : undefined} />
      </SimpleGrid>

      <Stack gap={4}>
        <Title order={3}>Vendor on the invoice</Title>
        <VendorBlock bill={bill} snapshot={snapshot} />
      </Stack>

      {warnings.length > 0 && (
        <Stack gap={4}>
          <Title order={3}>Extraction warnings</Title>
          <List size="sm">{warnings.map((w) => <List.Item key={w}>{w}</List.Item>)}</List>
        </Stack>
      )}

      <Stack gap={4}>
        <Title order={3}>Lines</Title>
        <LinesTable bill={bill} />
      </Stack>

      <Stack gap={4}>
        <Title order={3}>Taxes and totals</Title>
        <TaxesTable bill={bill} snapshot={snapshot} />
      </Stack>
    </Stack>
  )
}
