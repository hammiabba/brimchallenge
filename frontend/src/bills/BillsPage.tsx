import { BillListView } from './BillListView'

/** /bills: every bill the signed-in user may see (the server scopes the list by role and department). */
export default function BillsPage() {
  return <BillListView title="Bills" emptyMessage="No bills yet." />
}
