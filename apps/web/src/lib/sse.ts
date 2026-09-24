export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Split a growing text buffer into complete server-sent events and the unfinished remainder.
 * Comment lines (": keep-alive") are ignored; multi-line data is joined with newlines.
 */
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  let rest = buffer.replace(/\r\n/g, "\n");
  const events: SseEvent[] = [];
  for (let end = rest.indexOf("\n\n"); end !== -1; end = rest.indexOf("\n\n")) {
    const block = rest.slice(0, end);
    rest = rest.slice(end + 2);
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length > 0) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}
