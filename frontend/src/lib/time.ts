/**
 * The browser is the source of truth for the reader's timezone.
 *
 * The API stores and transports every timestamp in UTC, but the server also
 * groups events by day and prints certificates. Both need the reader's UTC
 * offset, otherwise a record registered at 00:35 in India is filed under the
 * previous day and the workspace reads as if it belongs to yesterday.
 */

/** Minutes east of UTC for the reader's timezone (Asia/Kolkata -> 330). */
export function timezoneOffsetMinutes() {
  return -new Date().getTimezoneOffset();
}

/** Short timezone label, e.g. "IST" or "UTC+05:30". */
export function timezoneLabel() {
  try {
    const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" }).formatToParts(new Date());
    const name = parts.find((part) => part.type === "timeZoneName")?.value;
    if (name) return name;
  } catch {
    // Intl is unavailable: fall back to the numeric offset.
  }
  const minutes = timezoneOffsetMinutes();
  if (minutes === 0) return "UTC";
  const sign = minutes > 0 ? "+" : "-";
  const hours = Math.floor(Math.abs(minutes) / 60);
  const rest = Math.abs(minutes) % 60;
  return `UTC${sign}${String(hours).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

/** Add the reader's timezone to an API path so server-rendered dates match the screen. */
export function withReaderTimezone(path: string) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}tz_offset=${timezoneOffsetMinutes()}`;
}
