import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from './client'
import type { Department } from './types'

/** GET /reference/departments (signed-in users only), cached for the session. */
export function useDepartments() {
  return useQuery({
    queryKey: ['reference', 'departments'],
    queryFn: () => unwrap(api.GET('/reference/departments')),
    staleTime: Infinity,
  })
}

/** "Finance (D02)" when the department list is loaded, else just the id. */
export function departmentLabel(departmentId: string, departments: readonly Department[] | undefined): string {
  const department = departments?.find((d) => d.department_id === departmentId)
  return department ? `${department.name} (${department.department_id})` : departmentId
}
