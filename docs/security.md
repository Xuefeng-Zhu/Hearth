# Security

## Untrusted content

Hearth presents retrieved mail and memory excerpts, web results, Browserbase pages, and worker findings as reference data outside the model's system instructions. An inbound email can trigger an existing user-configured rule. Inbox classification and email-triggered automation summaries run with an empty tool list.

Chat and worker email tools accept recipients entered by the user in the recent chat or saved as the delivery recipient. A saved recurring task can use an address in its approved instructions and still requires send approval at runtime. After a turn reads retrieved excerpts or external tool results, actions in approval categories require confirmation even with Always allow. In those turns, a raw gateway request in the Send category must match a gateway command entered directly by the user in the current turn. Configured Inbox and automation deliveries continue to use their saved settings and rules.

Mocked regression tests cover AgentMail Inbox, Exa, Browserbase, imported mail retrieved in a later chat, and a worker consuming a tool result. Persistent provenance across summaries and derived content, connector-specific write scopes, sensitive-read checks, and broader local mutation checks remain deferred. [Run 50 fixtures](../tests/test_untrusted_content.py) · [Design review](../DESIGN-REVIEW.md)
