import { Button, Group, Modal, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import { departmentLabel, useDepartments } from '../api/reference'
import type { AdminUser, Role, UserPatch, UserStatus } from '../api/types'
import { ROLE_LABELS, ROLES } from '../auth/roles'
import { parseMoneyInput } from '../lib/money'
import { StatusBadge } from '../ui/Badges'
import { Id, MoneyText } from '../ui/DataText'
import { USER_STATUS } from '../ui/statusStyles'
import { useAdminUsers, useUpdateUser } from './queries'
import { TableShell } from './TableShell'

/**
 * Edit comes first, so it is never the column cut off at the right edge; the user id sits under the name. Eight
 * columns that fit the 1008 px content column at 1280 px.
 */
const COLUMNS = ['', 'Name', 'Role', 'Department', 'Status', 'Approval limit (CAD)', 'Manager', 'Delegate'] as const
const ROLE_OPTIONS = ROLES.map((role) => ({ value: role, label: ROLE_LABELS[role] }))
const STATUS_OPTIONS = Object.entries(USER_STATUS).map(([value, style]) => ({ value, label: style.label }))

/** "Morgan Lee (U001)" from the full user list, or the bare id. */
function userLabel(userId: string | null, users: readonly AdminUser[]): string {
  if (!userId) return ''
  const user = users.find((u) => u.user_id === userId)
  return user ? `${user.full_name} (${user.user_id})` : userId
}

/** The changed fields only, so the audit log records exactly what the controller changed. */
function patchFor(user: AdminUser, draft: Draft, limit: string): UserPatch {
  const patch: UserPatch = {}
  if (draft.role !== user.role) patch.role = draft.role
  if (draft.status !== user.status) patch.status = draft.status
  if (draft.department_id !== user.department_id) patch.department_id = draft.department_id
  if (draft.manager_id !== user.manager_id && draft.manager_id) patch.manager_id = draft.manager_id
  if (draft.delegate_user_id !== user.delegate_user_id && draft.delegate_user_id) patch.delegate_user_id = draft.delegate_user_id
  if (limit !== user.approval_limit_cad) patch.approval_limit_cad = limit
  return patch
}

interface Draft {
  role: Role
  status: UserStatus
  department_id: string
  manager_id: string | null
  delegate_user_id: string | null
  approval_limit: string
}

/** Edit one user's role, status, department, approval limit, manager and delegate. Controller only (server-enforced). */
function EditUserModal({ user, users, onClose }: { user: AdminUser; users: readonly AdminUser[]; onClose: () => void }) {
  const departments = useDepartments()
  const update = useUpdateUser(user.user_id)
  const [draft, setDraft] = useState<Draft>({
    role: user.role, status: user.status, department_id: user.department_id, manager_id: user.manager_id,
    delegate_user_id: user.delegate_user_id, approval_limit: user.approval_limit_cad,
  })
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const limit = parseMoneyInput(draft.approval_limit)
  const patch = limit === null ? null : patchFor(user, draft, limit)
  const others = users.filter((u) => u.user_id !== user.user_id && u.status !== 'terminated')
    .map((u) => ({ value: u.user_id, label: `${u.full_name} (${u.user_id})` }))

  function save() {
    if (!patch) return
    update.mutate(patch, {
      onSuccess: (saved) => {
        notifications.show({ title: 'User updated', message: `${saved.full_name} (${saved.user_id})` })
        onClose()
      },
    })
  }

  return (
    <Modal opened onClose={onClose} title={`Edit ${user.full_name}`} size="lg">
      <form onSubmit={(event) => { event.preventDefault(); save() }}>
        <Stack gap="sm">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <Select label="Role" data={ROLE_OPTIONS} value={draft.role} allowDeselect={false}
              onChange={(value) => value && set('role', value as Role)} />
            <Select label="Status" data={STATUS_OPTIONS} value={draft.status} allowDeselect={false}
              onChange={(value) => value && set('status', value as UserStatus)} />
            <Select label="Department" allowDeselect={false} value={draft.department_id}
              data={(departments.data ?? []).map((d) => ({ value: d.department_id, label: `${d.name} (${d.department_id})` }))}
              onChange={(value) => value && set('department_id', value)} />
            <TextInput label="Approval limit (CAD)" value={draft.approval_limit}
              error={limit === null ? 'Enter an amount like 10000 or 10000.00' : undefined}
              onChange={(event) => set('approval_limit', event.currentTarget.value)} />
            <Select label="Manager" placeholder="None" data={others} value={draft.manager_id} searchable
              onChange={(value) => set('manager_id', value)} />
            <Select label="Delegate" placeholder="None" data={others} value={draft.delegate_user_id} searchable
              onChange={(value) => set('delegate_user_id', value)} />
          </SimpleGrid>
          {update.isError && <ErrorAlert error={update.error} />}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!patch || Object.keys(patch).length === 0} loading={update.isPending}>
              Save changes
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

/** /admin/users: everyone with their role, department, status and approval limit. */
export default function UsersPage() {
  const users = useAdminUsers()
  const departments = useDepartments()
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const all = users.data ?? []

  return (
    <Stack gap="md">
      <Title order={1}>Users</Title>
      {users.isError ? (
        <ErrorAlert error={users.error} title="Can't load users" onRetry={() => void users.refetch()} />
      ) : (
        <TableShell label="Users" columns={COLUMNS} numeric={['Approval limit (CAD)']} loading={users.isPending}
          empty={all.length === 0} emptyMessage="No users yet." minWidth={900}>
          {all.map((user) => (
            <Table.Tr key={user.user_id}>
              <Table.Td>
                <Button size="xs" variant="default" onClick={() => setEditing(user)}
                  aria-label={`Edit ${user.full_name}`}>Edit</Button>
              </Table.Td>
              <Table.Td>
                <Stack gap={0}>
                  <Text size="sm">{user.full_name}</Text>
                  <Text size="xs" c="dimmed">{user.title}</Text>
                  <Text size="xs" c="dimmed"><Id>{user.user_id}</Id></Text>
                </Stack>
              </Table.Td>
              <Table.Td>{ROLE_LABELS[user.role]}</Table.Td>
              <Table.Td>{departmentLabel(user.department_id, departments.data)}</Table.Td>
              <Table.Td><StatusBadge kind="user" status={user.status} /></Table.Td>
              <Table.Td data-numeric><MoneyText value={user.approval_limit_cad} align="right" /></Table.Td>
              <Table.Td>{userLabel(user.manager_id, all)}</Table.Td>
              <Table.Td>{userLabel(user.delegate_user_id, all)}</Table.Td>
            </Table.Tr>
          ))}
        </TableShell>
      )}
      {editing && <EditUserModal user={editing} users={all} onClose={() => setEditing(null)} />}
    </Stack>
  )
}
