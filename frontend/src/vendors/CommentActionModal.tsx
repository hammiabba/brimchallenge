import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core'
import type { UseMutationResult } from '@tanstack/react-query'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'

interface CommentActionModalProps {
  opened: boolean
  onClose: () => void
  /** The modal title and the confirm button's label ("Approve vendor"). */
  title: string
  /** One line saying what happens. */
  description: string
  /** The mutation to run with the comment (null when left empty). */
  mutation: UseMutationResult<unknown, Error, string | null>
  /** The comment can't be left empty (rejecting a bill). */
  commentRequired?: boolean
  /** Called after the server accepted the action. */
  onDone: () => void
  /** A red confirm button, for refusing actions (reject, hold). */
  danger?: boolean
}

/**
 * A confirm dialog with a comment, for the one-click decisions (approve or hold a vendor, verify or reject a bank
 * change, approve or reject a bill). The comment is optional unless `commentRequired`. The server decides who may do
 * it: a refusal (403, 409) shows its message here, with the request id.
 */
export function CommentActionModal({
  opened, onClose, title, description, mutation, onDone, danger, commentRequired,
}: CommentActionModalProps) {
  const [comment, setComment] = useState('')

  function close() {
    mutation.reset()
    setComment('')
    onClose()
  }

  function confirm() {
    mutation.mutate(comment.trim() || null, {
      onSuccess: () => {
        setComment('')
        onDone()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title={title}>
      <Stack gap="sm">
        <Text size="sm">{description}</Text>
        <Textarea
          label="Comment"
          description={commentRequired ? 'Required. Kept in the audit log.' : 'Optional. Kept in the audit log.'}
          required={commentRequired}
          value={comment}
          onChange={(event) => setComment(event.currentTarget.value)}
          maxLength={2000}
          rows={3}
        />
        {mutation.isError && <ErrorAlert error={mutation.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button
            color={danger ? 'red' : undefined}
            onClick={confirm}
            loading={mutation.isPending}
            disabled={commentRequired && comment.trim() === ''}
          >
            {title}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
