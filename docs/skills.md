# Skills

Skills are reusable playbooks for Hearth. Open **Skills** after **Memory** in the sidebar or mobile drawer. The library shows which playbooks are built in, when Hearth last loaded each one, and its use count.

- **Plan a dinner party** checks memory for guest allergies and dietary needs, proposes a menu, and creates an Excel shopping list.
- **Weekly family brief** reads reminders, recurring tasks, and memory to summarize the coming week.
- **Research and compare** uses Exa to find sources and Browserbase Fetch to read them, then presents a comparison table. It needs both providers for the full workflow and honors the global search and browsing switches.
- **Draft an email** writes a draft in chat. If you explicitly ask Hearth to send it, review and approve the send on its card.

## Use a playbook

Ask in chat naturally or name the skill. Hearth supplies the brain with skill names and descriptions so it can load a matching playbook before using its tools. The chat displays **Using skill** when Hearth loads the playbook. **Try it** opens a new side chat pinned to the selected skill. Enter a request in that chat to run the skill. Usage is counted when a turn loads the playbook, including turns that later fail.

Use a connected brain for model-based matching and to follow custom playbooks. Mock can demonstrate built-in dinner planning and the family brief with local data.

## Write and revise a playbook

Choose **New skill** to write your own or **Duplicate to edit** to start from a built-in. Each skill has a unique name and uses YAML front matter with four fields, followed by Markdown instructions.

```markdown
---
name: Review the week ahead
description: Group upcoming reminders by day.
when_to_use: Use for a quick calendar-style overview of upcoming reminders.
tools: [list_reminders]
---

1. Load the upcoming reminders.
2. Group them by day and call out anything due today.
```

Use **Preview** to check the rendered instructions and **Save skill** to save a version. Use **Version history** to read previous versions. The tool list limits what the agent can call while the skill is active. Existing connector settings, file request rules, and approval policies still apply. Use `tools: []` for a playbook that needs no tools. The Markdown may be up to 12,000 characters.

In chat, ask Hearth to save or revise a skill. You can say “remember how to do this” to prompt a suggestion after completing a workflow. **Settings → Approvals → Skills** defaults to **Always ask** for chat-created and chat-edited skills. The approval card shows the proposed Markdown. A direct editor save applies immediately, and deletion asks for confirmation.

## Versions and Undo

Hearth stores current skill Markdown in `live/skills/` under `HEARTH_DATA_DIR` and keeps previous versions in `live/skills/.versions/`. On the Sprite this is under the persistent Hearth data directory. Built-in playbooks ship with the application and can be read or duplicated in the library.

Create, duplicate, edit, and delete add Timeline entries. **Undo** acts on the most recent change to that skill. Undo an edit to restore its previous version, or undo a deletion to return it to the library. You can undo successive changes to the same skill in reverse order. An Undo preserves the version history and leaves other workspace data intact.
