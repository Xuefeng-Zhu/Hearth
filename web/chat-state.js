// Only the selected transcript window is loaded. Local turns keep their thread
// identity while streams continue in the background.
export function newConversation(threadId) {
  return { threadId, snapshot: null, pages: [], transcript: {}, turns: new Map() };
}

export function conversationView({ threadId, transcript, turns }) {
  const saved = new Set(transcript.messages?.map((message) => message.id));
  const local = [...turns.values()].filter((turn) => turn.threadId === threadId).map((turn) => ({
    ...turn,
    showPrompt: !turn.approval && !saved.has(turn.user?.id),
    showReply: !!(turn.user || turn.approval || turn.error || turn.stopped),
  }));
  return { transcript, local };
}

function mergeTranscript(pages, snapshot) {
  if (!pages.length) return snapshot;
  const messages = new Map(), actions = new Map(), workers = new Map(), proposals = new Map();
  const message_artifacts = {}, message_uploads = {};
  for (const page of [...pages, snapshot]) {
    for (const message of page.messages) {
      messages.set(message.id, message);
      delete message_artifacts[message.id];
    }
    for (const action of page.actions) actions.set(action.id, action);
    for (const worker of page.workers) workers.set(worker.id, worker);
    for (const proposal of page.self_updates || []) proposals.set(proposal.id, proposal);
    Object.assign(message_artifacts, page.message_artifacts);
    Object.assign(message_uploads, page.message_uploads);
  }
  return { messages: [...messages.values()], actions: [...actions.values()], workers: [...workers.values()],
    self_updates: [...proposals.values()],
    message_artifacts, message_uploads, previous_prompt: pages[0].previous_prompt };
}

function advancePages(state, next) {
  if (!state.pages.length || next.history_revision !== state.snapshot.history_revision ||
      next.around !== state.snapshot.around) return [];
  const oldest = next.messages[0]?.id;
  const overlap = state.snapshot.messages.findIndex((message) => message.id === oldest);
  if (overlap < 0) return [];
  if (overlap === 0) return state.pages;
  return [...state.pages, { ...state.snapshot, messages: state.snapshot.messages.slice(0, overlap),
    cursor: next.before, archived: true }];
}

function streamTurn(turn, { name, payload, eventId }) {
  if (turn.finished || turn.stopped || turn.reply || (eventId && turn.events?.has(eventId))) return turn;
  let fields;
  switch (name) {
    case "queued":
      if (turn.queued) return turn;
      fields = { queued: true, threadId: payload.thread.id, id: payload.reply_id, prompt: payload.prompt,
        attachments: payload.attachments || turn.attachments };
      break;
    case "started":
      if (turn.user) return turn;
      fields = { user: payload.message };
      break;
    case "token": fields = { text: turn.text + payload.text }; break;
    case "reset": fields = { text: "" }; break;
    case "action": fields = { actions: new Map(turn.actions).set(payload.id, payload) }; break;
    case "worker": fields = { workers: new Map(turn.workers).set(payload.id, payload) }; break;
    case "model_warning": fields = { warnings: [...turn.warnings, payload.message] }; break;
    case "done": fields = { reply: payload.message }; break;
    case "stopped": fields = { stopped: true }; break;
    case "skill_loaded": fields = { skill: payload }; break;
    case "browse_active": fields = { browse: payload }; break;
    case "browse_finished": fields = { browse: undefined }; break;
    case "browse_approved": fields = { activity: "Starting approved browser action" }; break;
    case "tool_started":
    case "tool_finished":
    case "demo_listening": fields = { activity: payload.title }; break;
    case "remembered":
    case "tool_warning":
    case "demo_warning": fields = {}; break;
    default: return turn;
  }
  return { ...turn, ...fields, ...(eventId ? { events: new Set(turn.events).add(eventId) } : {}) };
}

// A saved reply can arrive before the stream ends, including after a disconnect.
function settle(state, turns, completed) {
  const byId = new Map(), byPrompt = new Map();
  for (const message of state.transcript.messages || []) {
    if (message.role !== "assistant") continue;
    byId.set(message.id, message);
    if (message.reply_to) byPrompt.set(message.reply_to, message);
  }
  for (const [key, turn] of turns) {
    if (turn.threadId !== state.threadId || turn.stopped) continue;
    const reply = turn.reply ? byId.get(turn.reply.id) : byPrompt.get(turn.user?.id);
    if (!reply) continue;
    if (!turn.reply) completed.push({ turn, reply });
    turns.delete(key);
  }
}

export function reconcile(state, update) {
  let next = state;
  const completed = [];
  const unchanged = { state, completed };
  const turn = state.turns.get(update.key);
  let changedTurn;

  switch (update.type) {
    case "select":
      if (update.threadId === state.threadId) return unchanged;
      next = { ...newConversation(update.threadId), turns: state.turns };
      break;
    case "snapshot": {
      const snapshot = update.snapshot;
      if (snapshot.thread_id !== state.threadId) return unchanged;
      const pages = advancePages(state, snapshot);
      next = { ...state, snapshot, pages, transcript: mergeTranscript(pages, snapshot) };
      break;
    }
    case "page": {
      const { page, cursor, previous } = update;
      if (!state.snapshot || page.thread_id !== state.threadId ||
          page.history_revision !== state.snapshot.history_revision) return unchanged;
      let pages;
      if (previous) {
        if (!state.pages.includes(previous)) return unchanged;
        pages = state.pages.map((old) => old !== previous ? old : { ...old, ...page, ...(old.archived ? {
          messages: old.messages, previous_prompt: old.previous_prompt,
        } : {}) });
      } else {
        if (!cursor || cursor !== (state.pages[0] || state.snapshot).before) return unchanged;
        pages = [{ ...page, cursor }, ...state.pages];
      }
      next = { ...state, pages, transcript: mergeTranscript(pages, state.snapshot) };
      break;
    }
    case "begin": changedTurn = { ...update.turn, key: update.key, text: "", actions: new Map(), warnings: [] }; break;
    case "stream":
      if (!turn) return unchanged;
      changedTurn = streamTurn(turn, update);
      if (changedTurn === turn) return unchanged;
      if (changedTurn.reply) completed.push({ turn: changedTurn, reply: changedTurn.reply });
      break;
    case "finish":
      if (!turn || turn.finished) return unchanged;
      // The server persists a reply before sending done. A background turn
      // with that receipt can be released until its thread is opened again.
      if (!(turn.reply && turn.threadId !== state.threadId) && (!update.error || turn.user)) {
        changedTurn = { ...turn, finished: true, error: update.error, browse: undefined };
      }
      break;
    case "discard":
      if (!turn) return unchanged;
      break;
    case "delete-thread":
      return { state: { ...state, turns: new Map([...state.turns]
        .filter(([, pending]) => pending.threadId !== update.threadId)) }, completed };
    default: return unchanged;
  }

  if (update.type === "select") return { state: next, completed };
  const turns = new Map(next.turns);
  if (update.type === "begin") {
    for (const [key, previous] of turns) {
      if (previous.threadId === update.source && previous.error) turns.delete(key);
    }
  }
  if (changedTurn) turns.set(update.key, changedTurn);
  else if (turn) turns.delete(update.key);
  if (next.transcript !== state.transcript || ["queued", "started", "done"].includes(update.name)) {
    settle(next, turns, completed);
  }
  return { state: { ...next, turns }, completed, turn: changedTurn };
}
