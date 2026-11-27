import { render } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";
import { html, Icon } from "../ui.js";

function Library() {
  return html`
    <div class="artifact-library">
      <div class="section-intro artifact-intro">
        <div><h2>Saved work</h2><p>Files and pages created by Hearth, plus files in your Box folder.</p></div>
        <div class="artifact-box-control">
          <span id="artifact-box-status" class="artifact-box-status" role="status">Checking Box…</span>
          <button type="button" class="artifact-icon-button" id="artifact-refresh" aria-label="Refresh artifacts" title="Refresh artifacts"><${Icon} name="refresh" /></button>
          <button type="button" class="artifact-control file-question-launch" id="file-question-open">
            <${Icon} name="message" /> Ask my files
          </button>
        </div>
      </div>
      <div id="artifact-connection" class="artifact-connection" hidden>
        <span id="artifact-connection-copy"></span>
        <a href="#settings/connections" id="artifact-connect">Open Connections</a>
      </div>
      <div class="artifact-connection artifact-load-error" id="artifact-load-error" hidden>
        <p id="artifact-error-message" role="status"></p>
        <button class="artifact-control" id="artifact-try-again" type="button">Try again</button>
      </div>
      <div class="artifact-toolbar">
        <label class="artifact-search"><${Icon} name="search" />
          <span class="visually-hidden">Search artifacts</span>
          <input id="artifact-search" type="search" maxlength="160" placeholder="Search artifacts…" />
        </label>
        <label>
          <span class="visually-hidden">Sort artifacts</span>
          <select id="artifact-sort"><option value="recent">Most recent</option><option value="name">Name A–Z</option></select>
        </label>
        <div class="artifact-layout-toggle" role="group" aria-label="Artifact layout">
          <button type="button" id="artifact-grid" aria-label="Grid view" title="Grid view" aria-pressed="true"><${Icon} name="grid" /></button>
          <button type="button" id="artifact-list" aria-label="List view" title="List view" aria-pressed="false"><${Icon} name="list" /></button>
        </div>
      </div>
      <div class="artifact-filters" id="artifact-filters" role="group" aria-label="Artifact filters">
        <div role="group" aria-label="File format">
          <button type="button" data-format-filter="all" aria-pressed="true">All</button>
          <button type="button" data-format-filter="documents" aria-pressed="false">Documents</button>
          <button type="button" data-format-filter="pdfs" aria-pressed="false">PDFs</button>
          <button type="button" data-format-filter="sheets" aria-pressed="false">Sheets</button>
          <button type="button" data-format-filter="slides" aria-pressed="false">Slides</button>
          <button type="button" data-format-filter="pages" aria-pressed="false">Pages</button>
        </div>
        <div role="group" aria-label="Artifact kind">
          <button type="button" data-format-filter="plan" aria-pressed="false">Plans</button>
          <button type="button" data-format-filter="list" aria-pressed="false">Lists</button>
          <button type="button" data-format-filter="note" aria-pressed="false">Notes</button>
          <button type="button" data-format-filter="transcript" aria-pressed="false">Transcripts</button>
          <button type="button" data-format-filter="export" aria-pressed="false">Exports</button>
        </div>
      </div>
      <p class="artifact-count" id="artifact-count" role="status">Loading artifacts…<span class="loading-skeleton" aria-hidden="true"></span></p>
      <div class="artifact-collection" id="artifact-collection"></div>
      <div id="artifact-empty" class="artifact-empty" hidden>
        <span class="artifact-kind-icon" aria-hidden="true"><${Icon} name="files" /></span>
        <h3 id="artifact-empty-title">No artifacts yet</h3>
        <p id="artifact-empty-hint">Ask Hearth to create a document, PDF, spreadsheet, slide deck, or page.</p>
        <button class="artifact-control" id="artifact-clear-filters" type="button" hidden>Clear filters</button>
      </div>
    </div>
  `;
}

function PageDialog() {
  return html`
    <div class="page-dialog-shell">
      <header class="page-dialog-head">
        <div>
          <div class="page-dialog-meta">
            <span class="artifact-badge is-page">HTML / Page</span>
            <p class="page-dialog-version" id="page-dialog-version"></p>
          </div>
          <h2 id="page-dialog-title">Page preview</h2>
        </div>
        <button type="button" class="icon-button" id="page-close" aria-label="Close page preview"><${Icon} name="x" /></button>
        <div class="page-actions" id="page-actions"></div>
      </header>
      <p class="page-feedback" id="page-feedback" role="status"></p>
      <section class="page-approval" id="page-approval" aria-label="Share approval" hidden></section>
      <div class="page-workspace" id="page-workspace" hidden>
        <section class="page-preview" aria-label="Page preview">
          <div class="page-preview-bar">
            <span id="page-size" class="page-size"></span>
            <div class="page-devices" role="group" aria-label="Preview device">
              <button type="button" id="page-phone" aria-pressed="true"><${Icon} name="device-phone" size=${16} /> Phone</button>
              <button type="button" id="page-desktop" aria-pressed="false"><${Icon} name="monitor" size=${16} /> Desktop</button>
            </div>
          </div>
          <div class="page-preview-stage" id="page-preview-stage">
            <div class="page-preview-fit" id="page-preview-fit"></div>
          </div>
        </section>
        <section class="page-history" aria-labelledby="page-history-title">
          <h3 id="page-history-title">Version history</h3>
          <ol id="page-versions"></ol>
        </section>
      </div>
    </div>
  `;
}

function Drawer() {
  return html`
    <div class="artifact-drawer-shell">
      <header class="artifact-drawer-header">
        <div class="artifact-drawer-heading">
          <div>
            <div id="artifact-detail-meta" class="artifact-badges"></div>
            <h2 id="artifact-drawer-title">Artifact</h2>
          </div>
          <button type="button" class="artifact-icon-button" id="artifact-close" aria-label="Close artifact" title="Close artifact"><${Icon} name="x" /></button>
        </div>
        <p class="artifact-detail-filename" id="artifact-filename"></p>
        <div class="artifact-detail-actions" id="artifact-actions"></div>
        <p id="artifact-detail-status" class="artifact-detail-status" role="status"></p>
      </header>
      <div class="artifact-drawer-body" id="artifact-detail-body"></div>
    </div>
  `;
}

function FileQuestions() {
  return html`
    <div class="artifact-drawer-shell">
      <header class="artifact-drawer-header">
        <div class="artifact-drawer-heading">
          <div>
            <h2 id="file-question-title">Ask my files</h2>
            <p class="meta file-question-provider">Questions about your Box files</p>
          </div>
          <button type="button" class="artifact-icon-button" id="file-question-close" aria-label="Close Ask my files">
            <${Icon} name="x" />
          </button>
        </div>
      </header>
      <div class="artifact-drawer-body">
        <form id="file-question-form" class="file-question-form">
          <fieldset id="file-question-scope">
            <legend>Which files should Hearth read?</legend>
            <label class="file-question-choice"><input type="radio" name="file-scope" value="recent" defaultChecked /> All recent</label>
            <label class="file-question-choice"><input type="radio" name="file-scope" value="selected" /> Select files</label>
          </fieldset>
          <div class="file-question-picker" id="file-question-picker" hidden>
            <label for="file-question-search">Find a file</label>
            <input type="search" id="file-question-search" maxlength="160" />
            <p class="meta" id="file-question-selection" role="status"></p>
            <div class="file-question-list" id="file-question-list" role="group" aria-label="Box files"></div>
          </div>
          <p class="meta" id="file-question-limit">Up to 25 files</p>
          <label for="file-question-input">Question</label>
          <textarea id="file-question-input" rows="3" maxlength="1500" required placeholder="What do the files say about…"></textarea>
          <button type="submit" class="artifact-control file-question-submit" id="file-question-submit">Ask Hearth</button>
          <p class="meta" id="file-question-status" role="status"></p>
        </form>
        <section id="file-question-result" class="file-question-result" aria-labelledby="file-answer-title" hidden></section>
      </div>
    </div>
  `;
}

export function mountArtifacts(byId) {
  render(html`<${Library} />`, byId("artifacts-view"));
  render(html`<${PageDialog} />`, byId("page-dialog"));
  render(html`<${Drawer} />`, byId("artifact-drawer"));
  render(html`<${FileQuestions} />`, byId("file-question-dialog"));
}
