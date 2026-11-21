import type { ComboboxItem, ComboboxParsedItem, OptionsFilter } from '@mantine/core'

import type { PickerUser } from '../api/types'
import { ROLE_LABELS, ROLES } from './roles'

/** The picker's options: one group per role (in ROLES order), people sorted by name within each. */
export function groupUsersByRole(users: readonly PickerUser[]) {
  return ROLES.map((role) => ({
    group: ROLE_LABELS[role],
    items: users
      .filter((u) => u.role === role)
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
      .map((u): ComboboxItem => ({ value: u.user_id, label: u.full_name })),
  })).filter((group) => group.items.length > 0)
}

/** The text a search matches against for one user: name, title, department, user id and role. */
function searchText(user: PickerUser): string {
  return [user.full_name, user.title, user.department_id, user.user_id, ROLE_LABELS[user.role]].join(' ').toLowerCase()
}

/** A Select filter that matches every word of the search against searchText, keeping the role groups. */
export function makeUserFilter(byId: Map<string, PickerUser>): OptionsFilter {
  return ({ options, search }) => {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean)
    const matches = (item: ComboboxItem) => {
      const user = byId.get(item.value)
      const text = user ? searchText(user) : item.label.toLowerCase()
      return words.every((word) => text.includes(word))
    }
    const out: ComboboxParsedItem[] = []
    for (const option of options) {
      if ('group' in option) {
        const items = option.items.filter(matches)
        if (items.length > 0) out.push({ ...option, items })
      } else if (matches(option)) {
        out.push(option)
      }
    }
    return out
  }
}
