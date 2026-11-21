import { BillListView } from './BillListView'
import { REVIEW_STATUSES } from './listQuery'

/**
 * /review: the AP clerk's queue, the bills table fixed to needs review and on hold. The order is the server's
 * (newest received first); GET /bills has no sort parameter yet.
 */
export default function ReviewQueuePage() {
  return <BillListView title="Review queue" fixedStatus={REVIEW_STATUSES} emptyMessage="No bills need review." />
}
