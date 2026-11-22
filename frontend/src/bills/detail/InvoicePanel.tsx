import { Anchor, Button, Group, List, Popover, SimpleGrid, Stack, Table, Text, Title, Tooltip, VisuallyHidden } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { Fragment, useState, type ReactNode } from 'react'

import { API_PREFIX } from '../../api/client'
import { departmentLabel, glAccountName, personName, useDepartments, useGlAccounts, usePeople } from '../../api/reference'
import type { BillDetail, BillLine } from '../../api/types'
import { accountEnding } from '../../lib/accounts'
import { parseDateOnly } from '../../lib/dates'
import { decimalToPercent, formatUnitPrice } from '../../lib/decimal'
import { isMoney, parseMoneyInput } from '../../lib/money'
import { notifyError } from '../../api/notify'
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
import { useCodeLine } from '../mutations'
import { CodingModal } from './CodingModal'
import { HeaderEditModal } from './HeaderEditModal'
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

/**
 * "Why?": the coding suggestion's reason, exactly as the server wrote it (plain text, not parsed), in a small popover.
 * The popover floats, so it carries the theme's one shadow.
 */
function WhyReason({ reason, lineNo }: { reason: string; lineNo: number }) {
  return (
    <Popover width={300} position="bottom-start" shadow="md">
      <Popover.Target>
        <Button variant="subtle" size="compact-xs" px={4} aria-label={`Why? The reason for line ${lineNo}'s coding`}>
          Why?
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Text size="sm" style={{ overflowWrap: 'anywhere' }}>{reason}</Text>
      </Popover.Dropdown>
    </Popover>
  )
}

/** How a line's coding was set: "Suggested · 97%", "Confirmed by clerk" or "Changed by clerk"; null when not coded. */
function codingStatusText(line: BillLine): string | null {
  if (line.coding_status === 'accepted') return 'Confirmed by clerk'
  if (line.coding_status === 'overridden') return 'Changed by clerk'
  if (line.coding_status === 'suggested') {
    const confidence = line.suggestion_confidence
    return confidence !== null && confidence !== undefined ? `Suggested \u00b7 ${confidencePercent(confidence)}` : 'Suggested'
  }
  return null
}

/**
 * The coding cell of a line, each fact once: the GL number (mono) and account name on one line, the department
 * name with its id on the next, then how the coding was set in secondary text, with the suggestion's reason behind
 * "Why?".
 */
function CodingCell({ line }: { line: BillLine }) {
  const gl = useGlAccounts()
  const departments = useDepartments()
  if (!line.gl_account && !line.suggested_gl_account) {
    return <Text size="sm" c="dimmed">Not coded</Text>
  }
  const glNumber = line.gl_account ?? line.suggested_gl_account ?? ''
  const glName = glAccountName(glNumber, gl.data)
  const department = line.department_id ?? line.suggested_department_id
  const status = codingStatusText(line)
  return (
    <Stack gap={0}>
      <Text size="sm"><Id>{glNumber}</Id>{glName ? ` ${glName}` : ''}</Text>
      {department && <Text size="xs">{departmentLabel(department, departments.data)}</Text>}
      {(status || line.suggestion_reason) && (
        <Group gap={4} wrap="wrap" align="center">
          {status && <Text size="xs" c="dimmed">{status}</Text>}
          {line.suggestion_reason && <WhyReason reason={line.suggestion_reason} lineNo={line.line_no} />}
        </Group>
      )}
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
        <Text size="sm" c="dimmed">Imported from the dataset history, so there is no record of what the invoice itself showed.</Text>
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
                  {/* The account by its last four digits, as on every page; institution and transit as printed. */}
                  {key === 'account' ? `account ${accountEnding(value, true)}` : <>{key} <Id>{value ?? ''}</Id></>}
                </Fragment>
              ))}
          </Text>
        </FieldRegion>
      </Stack>
    </FieldRegion>
  )
}

/**
 * AP's coding actions for one line, when allowed_actions.code_lines allows them: accept the suggestion as it is (one
 * click) or change it. Both re-run the controls.
 */
function CodingActions({ bill, line }: { bill: BillDetail; line: BillLine }) {
  const [open, setOpen] = useState(false)
  const accept = useCodeLine(bill, line.line_no)
  const canAccept = line.coding_status === 'suggested' && Boolean(line.suggested_gl_account && line.suggested_department_id)

  function acceptSuggestion() {
    accept.mutate({ gl_account: line.suggested_gl_account!, department_id: line.suggested_department_id! }, {
      onSuccess: () => notifications.show({ title: 'Suggestion accepted', message: `Line ${line.line_no} of ${bill.bill_id}` }),
      onError: (error) => notifyError(error),
    })
  }

  return (
    <Group gap="xs" wrap="wrap" mt={4}>
      {canAccept && (
        <Button size="xs" onClick={acceptSuggestion} loading={accept.isPending}
          aria-label={`Accept suggestion for line ${line.line_no}`}>
          Accept
        </Button>
      )}
      <Button size="xs" variant="default" onClick={() => setOpen(true)} aria-label={`Change coding of line ${line.line_no}`}>
        Change
      </Button>
      <CodingModal bill={bill} line={line} opened={open} onClose={() => setOpen(false)} />
    </Group>
  )
}

/**
 * The lines table: quantities as sent, unit prices and amounts as money (unit prices keep any decimals beyond two),
 * and the coding (with AP's actions). Cell text wraps between words (app-wrap-cells), so a column grows to fit its
 * longest word ("Telecommunications") instead of splitting it; the minimum width leaves room for the numbers and the
 * coding buttons before the table scrolls sideways.
 */
function LinesTable({ bill }: { bill: BillDetail }) {
  const canCode = bill.allowed_actions?.code_lines?.allowed ?? false
  return (
    <FieldRegion name="lines">
      <Table.ScrollContainer minWidth={540}>
        <Table aria-label="Invoice lines" withTableBorder bg="white" className="app-wrap-cells">
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
                <Table.Td data-numeric>{formatUnitPrice(line.unit_price, bill.currency)}</Table.Td>
                <Table.Td data-numeric><MoneyText value={line.amount} currency={bill.currency} /></Table.Td>
                <Table.Td>
                  <CodingCell line={line} />
                  {canCode && <CodingActions bill={bill} line={line} />}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </FieldRegion>
  )
}

/**
 * The subtotal, then each tax, then the total, in the order they add up (extracted → current when a person corrected
 * an amount).
 */
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
      <Table aria-label="Taxes and totals" withTableBorder bg="white" maw={420}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Tax</Table.Th>
            <Table.Th data-numeric>Rate</Table.Th>
            <Table.Th data-numeric>Amount</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {totalRow('Subtotal', 'subtotal', bill.subtotal, 'subtotal')}
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
  const fileName = snapshot ? snapshotText(snapshot, 'source.file_name') : null
  const emailId = snapshot ? snapshotText(snapshot, 'source.email_id') : null
  // The original file opens only when the server says this user may open it (view_document) and there is one.
  const canViewFile = (bill.allowed_actions?.view_document?.allowed ?? false) && Boolean(bill.file_hash)
  const canEdit = bill.allowed_actions?.edit?.allowed ?? false
  const [editing, setEditing] = useState(false)

  return (
    <Stack gap="md">
      <Group justify="space-between" align="baseline">
        <Group gap="sm" align="baseline">
          <Title order={2}>Invoice</Title>
          {canEdit && <Button size="xs" variant="default" onClick={() => setEditing(true)}>Edit details</Button>}
        </Group>
        {(fileName || emailId) && (
          <Text size="xs" c="dimmed">
            {fileName && (canViewFile ? (
              <Anchor href={`${API_PREFIX}/intake/files/${bill.file_hash}`} target="_blank" rel="noopener noreferrer"
                size="xs">
                {fileName}
                <VisuallyHidden> (original file, opens in a new tab)</VisuallyHidden>
              </Anchor>
            ) : fileName)}
            {emailId && `${fileName ? ', ' : ''}from email ${emailId}`}
          </Text>
        )}
      </Group>
      {/* Keyed on the row version: after any write the form starts again from the bill as it now stands. */}
      {canEdit && <HeaderEditModal bill={bill} opened={editing} onClose={() => setEditing(false)} />}

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
