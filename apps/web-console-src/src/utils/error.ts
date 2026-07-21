/**
 * Safely extract an error message from an unknown caught value.
 * Use this in catch blocks: catch (e: unknown) { message.error(getErrorMessage(e)) }
 */
export function getErrorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  if (typeof e === 'string') return e
  if (e && typeof e === 'object' && 'message' in e) return String((e as { message: unknown }).message)
  return String(e)
}
