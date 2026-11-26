// The caller owns the connection. A new parser can resume from its last event ID.
export function createSSEParser(lastEventId = "") {
  const decoder = new TextDecoder();
  let line = "", afterCR = false;
  let event = "", data = [], id, retry;

  function readLine(events) {
    if (!line) {
      if (id !== undefined) lastEventId = id;
      if (data.length) events.push({ event: event || "message", data: data.join("\n"), id, lastEventId });
      event = "";
      data = [];
      id = undefined;
      return;
    }
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    else if (field === "id" && !value.includes("\0")) id = value;
    else if (field === "retry" && /^[0-9]+$/.test(value)) retry = Number(value);
    line = "";
  }

  return {
    get lastEventId() { return lastEventId; },
    get retry() { return retry; },
    push(chunk) {
      const events = [];
      for (const character of decoder.decode(chunk, { stream: true })) {
        if (afterCR && character === "\n") {
          afterCR = false;
          continue;
        }
        afterCR = character === "\r";
        if (afterCR || character === "\n") readLine(events);
        else line += character;
      }
      return events;
    },
  };
}
