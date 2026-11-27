import { render } from "preact";
import { html, Icon } from "../ui.js";

export function mountTasks(byId) {
  render(html`
    <div class="section-intro split-heading delivery-intro">
      <div><h2>Recurring tasks</h2><p>Schedule Hearth to run a prompt and deliver the result.</p></div>
      <button type="button" class="primary-setting automation-button" id="new-task"><${Icon} name="plus" />New task</button>
    </div>
    <p class="meta" id="tasks-feedback" role="status"></p>
    <div id="task-approval"></div>
    <div id="tasks-content" class="automation-task-grid"></div>
  `, byId("tasks-panel"));
}
