/**
 * Client-side checks on a chosen file, for quick feedback only: the server checks the type (415) and the size (413)
 * again and its answer is what counts. The lists mirror backend/app/intake/upload.py (ALLOWED_EXTS) and the API's
 * body limit (MAX_BODY_BYTES, 10 MB).
 */
export const ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif', '.webp'] as const

/** The native file picker's filter. */
export const ACCEPT = ALLOWED_EXTENSIONS.join(',')

export const MAX_FILE_BYTES = 10 * 1024 * 1024

/** The extension of a file name, lower case and with its dot (".pdf"), or "" when it has none. */
function extension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot).toLowerCase() : ''
}

/** Why a file won't be sent, in one line, or null when it looks fine. */
export function fileProblem(file: File): string | null {
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(extension(file.name))) {
    return 'Only PDF and image files (PNG, JPG, TIFF, BMP, GIF, WebP) can be submitted.'
  }
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_FILE_BYTES) return 'The file is larger than 10 MB.'
  return null
}
