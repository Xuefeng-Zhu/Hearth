# Security

## Workspace access

Keep production workspace routes behind Sprite URL authentication. Origin and Fetch Metadata checks on browser writes and Timeline streaming guard against cross-origin requests. Scheduler and proactivity tick routes also require the workspace tick token. The separate Pages publisher exposes approved snapshots through their share URLs and requires a publisher credential for changes. [HTTP boundary](architecture.md#http-and-workspace-access), [Signed-out edge check](testing.md#signed-out-edge-authorization-matrix)

## Untrusted content

Hearth presents retrieved mail and memory excerpts, attachment context, web results, Browserbase pages, and worker findings as reference data outside the model's system instructions. Shared chat and worker tool handling marks successful recall, search, Browserbase, gateway, artifact-read, and worker results as untrusted. An inbound email can trigger an existing user-configured rule. Inbox classification and email-triggered automation summaries run with an empty tool list. [Agent](../hearth/agent.py), [Tool results](../hearth/tool_calls.py), [Inbox classification](../hearth/mail_content.py)

Chat and worker email tools accept recipients entered by the user in recent chat or saved as the delivery recipient. The fictional Mock demo can also use its seeded recipients. A saved recurring task can use an address in its approved instructions and still requires send approval at runtime. After a turn reads retrieved excerpts or external tool results, actions in approval categories require confirmation even with **Allow without asking**. In those turns, a raw gateway request in the Send category must match a gateway command entered directly by the user in the current turn. Configured Inbox and automation deliveries use their saved settings and rules. [Approvals](approvals-and-tasks.md#approvals)

Mocked regression tests cover AgentMail Inbox, Exa, Browserbase, imported mail retrieved in a later chat, and a worker consuming a tool result. Persistent provenance across summaries and derived content, connector-specific write scopes, sensitive-read checks, and broader local mutation checks remain deferred. [Run 50 fixtures](../tests/test_untrusted_content.py) · [Design review](../DESIGN-REVIEW.md)
