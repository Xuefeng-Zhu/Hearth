import { html, Icon } from "../ui.js";
import { Markdown } from "../artifacts/markdown.js";
import { highlighted, ListSearchExcerpt } from "../list-search-view.js";
import { timeFormatter } from "../time.js";

const date = timeFormatter({ dateStyle: "medium", timeStyle: "short" });

export function SkillsView() {
  return html`
      <div class="section-intro split-heading">
        <div>
          <h2>Reusable playbooks</h2>
          <p>Use a playbook in chat or create one for a routine of your own.</p>
        </div>
        <button type="button" class="settings-button primary-setting" id="skill-new"><${Icon} name="plus" size=${17} /> New skill</button>
      </div>
      <div id="skills-search" class="list-search"></div>
      <p class="meta" id="skills-status" role="status"></p>
      <div id="skills-search-empty" class="list-search-empty" hidden></div>
      <div id="skill-list" class="skill-list list-search-results" aria-label="Playbooks"></div>
  `;
}

export function SkillEditor({ skill, mode, previewText, viewing, pending, confirming }) {
  const preview = mode === "preview";
  const historical = !!viewing && viewing !== skill?.revision;
  const readonly = !!skill?.builtin || historical;
  const description = skill?.builtin ? "Built-in playbook · Duplicate it to make changes."
    : skill?.description || (mode ? "Write a Markdown playbook Hearth can load in chat." : "");
  return html`
  <form id="skill-form" aria-busy=${pending ? "true" : null}>
    <header class="skill-editor-header split-heading">
      <div>
        <h2 id="skill-title">${skill?.name || (mode ? "New skill" : "Skill")}</h2>
        <p class="meta" id="skill-description">${description}</p>
      </div>
      <button type="button" class="skill-button" id="skill-close" aria-label="Close skill editor" autofocus><${Icon} name="x" size=${20} /></button>
    </header>
    <div class="skill-editor-body">
      <div class="skill-editor-toolbar">
        <div class="skill-mode" role="group" aria-label="Editor mode">
          <button type="button" class="skill-button" id="skill-source-mode" aria-pressed=${String(!preview)}>Markdown</button>
          <button type="button" class="skill-button" id="skill-preview-mode" aria-pressed=${String(preview)}>Preview</button>
        </div>
        <label id="skill-history" hidden=${!skill?.versions.length}>${"Version history "}<select id="skill-versions">${skill?.versions.map((version) => html`
              <option key=${version.id} value=${version.id}>${`Version ${version.number} · ${version.id === skill.revision
                ? "Current" : date.format(new Date(version.at))}`}</option>`)}</select></label>
      </div>
      <div id="skill-source" hidden=${preview}>
        <label class="visually-hidden" for="skill-markdown">Skill Markdown</label>
        <textarea id="skill-markdown" readonly=${readonly} aria-readonly=${mode ? String(readonly) : null} spellcheck="false" maxlength="12000" rows="12" aria-describedby="skill-markdown-help"></textarea>
        <p id="skill-markdown-help" class="meta">Include name, description, when_to_use, and tools in the YAML front matter.</p>
      </div>
      <div id="skill-preview" class="skill-preview" role="region" aria-label="Markdown preview" tabindex="0" hidden=${!preview}>
          ${previewText === undefined ? null : previewText ? html`<${Markdown} text=${previewText} />`
            : html`<p class="meta">Add instructions to preview the playbook.</p>`}
        </div>
    </div>
    <footer class="skill-editor-footer">
      <p class="meta" id="skill-feedback" role="status"></p>
      <div class="skill-delete-confirm" id="skill-delete-confirm" hidden=${!confirming}>
        <p>Delete this skill? You can restore it from Timeline.</p>
        <div class="action-row">
          <button type="button" class="skill-button" id="skill-delete-cancel">Cancel</button>
          <button type="button" class="skill-button skill-danger" id="skill-delete-confirm-button">Delete skill</button>
        </div>
      </div>
      <div class="skill-editor-actions">
        <button type="button" class="skill-button skill-danger" id="skill-delete" hidden=${!skill || readonly}><${Icon} name="trash" size=${17} /> Delete</button>
        <button type="button" class="skill-button" id="skill-duplicate" hidden=${!skill?.builtin}><${Icon} name="copy" size=${17} /> Duplicate to edit</button>
        <button type="button" class="skill-button" id="skill-try" hidden=${!skill || historical}><${Icon} name="message" size=${17} /> Try it</button>
        <button type="submit" class="skill-button skill-primary" id="skill-save" hidden=${readonly}>Save skill</button>
      </div>
    </footer>
  </form>
  `;
}

export function SkillList({ skills, open }) {
  return skills.map((skill) => {
    const matches = skill.search_matches;
    return html`<article class="skill-card" key=${skill.id}>
      <span class="skill-mark"><${Icon} name="skill" size=${21} /></span>
      <div class="skill-card-body">
        <h3><button type="button" class="skill-card-link" data-skill=${skill.id} aria-haspopup="dialog"
          onClick=${(event) => open(skill.id, event.currentTarget)}><span>${highlighted(matches?.name, skill.name)}</span></button></h3>
        <p>${highlighted(matches?.description, skill.description)}</p>
        <${ListSearchExcerpt} matches=${matches} />
        <div class="skill-stats">
          ${skill.builtin && html`<span class="skill-badge">Built-in</span>`}
          <span>${skill.last_used ? html`${"Last used "}<time dateTime=${skill.last_used}>${date.format(new Date(skill.last_used))}</time>`
            : "Never used"}</span>
          <span>${`${skill.use_count} ${skill.use_count === 1 ? "use" : "uses"}`}</span>
        </div>
      </div>
    </article>`;
  });
}
