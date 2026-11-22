import { Anchor, Button, FileInput, Group, Select, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconUpload } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { useDepartments } from '../api/reference'
import { useCurrentUser } from '../auth/context'
import { Icon } from '../ui/Icon'
import { useSubmitInvoice } from './queries'

/** The file types the server reads (ALLOWED_EXTS in backend/app/intake/upload.py); it refuses anything else (415). */
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.gif,.webp,application/pdf,image/*'

/**
 * /submit: upload one invoice. The server reads, codes and checks it in the background, and it then waits in the AP
 * review queue; My submissions shows how it went. Employees submit for their own department (the server enforces it).
 */
export default function SubmitPage() {
  const user = useCurrentUser()
  const departments = useDepartments()
  const submit = useSubmitInvoice()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [departmentId, setDepartmentId] = useState<string | null>(user.department_id)

  function send() {
    if (!file) return
    submit.mutate({ file, departmentId }, {
      onSuccess: (item) => {
        notifications.show({ title: 'Invoice submitted', message: `${item.file_name} is queued for reading.` })
        void navigate('/submissions')
      },
    })
  }

  return (
    <Stack gap="lg" maw={640}>
      <Title order={1}>Submit invoice</Title>
      <form onSubmit={(event) => { event.preventDefault(); send() }}>
        <Stack gap="sm">
          <FileInput
            label="Invoice file"
            description="One PDF or image (PNG, JPG, TIFF)"
            placeholder="Choose a file"
            accept={ACCEPT}
            value={file}
            onChange={setFile}
            leftSection={<Icon icon={IconUpload} />}
            clearable
            required
          />
          <Select
            label="Department"
            description="The department the invoice is for"
            data={(departments.data ?? []).map((d) => ({ value: d.department_id, label: `${d.name} (${d.department_id})` }))}
            value={departmentId}
            onChange={setDepartmentId}
            clearable
          />
          {submit.isError && <ErrorAlert error={submit.error} />}
          <Group>
            <Button type="submit" disabled={!file} loading={submit.isPending}>Submit invoice</Button>
          </Group>
        </Stack>
      </form>
      <Text size="sm" c="dimmed">
        {'The invoice is read and checked automatically. Follow it in '}
        <Anchor component={Link} to="/submissions" inherit>My submissions</Anchor>.
      </Text>
    </Stack>
  )
}
