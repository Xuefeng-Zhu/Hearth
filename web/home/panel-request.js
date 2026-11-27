export function panelRequestPrompt(description) {
  const text = description.trim();
  return text ? `Create one Home panel from this description. Ask me in Chat for any required details.\n\n${text}` : "";
}

export function panelRequestFeedback(turn) {
  const actions = [...(turn?.actions?.values() || [])].filter((action) => action.kind === "panel");
  const titles = actions.filter((action) => action.status === "complete").flatMap((action) => action.panel_titles || []);
  if (titles.length === 1) return { message: `${titles[0]} added to Home.` };
  if (titles.length) return { message: `${titles.length} panels added to Home.` };
  if (turn?.error) return { message: turn.error };
  if (turn?.stopped) return { message: "Panel request stopped." };
  if (actions.some((action) => action.status === "pending")) {
    return { message: "Review the panel request in Chat.", openChat: true };
  }
  return { message: "Continue the panel request in Chat.", openChat: true };
}
