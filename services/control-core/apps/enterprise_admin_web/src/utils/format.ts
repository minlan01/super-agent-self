export const formatTime = (t: string): string =>
  t ? new Date(t).toLocaleString() : '-'
