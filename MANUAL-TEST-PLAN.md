# Manual UI test plan

Run after `./scripts/dev.sh`, with <http://localhost:5173> open. Each step is
one action and one thing to look for. Roughly ten minutes.

Ollama answers take 30–80 seconds; Claude about 15. Pick Claude in the header
if you want to move quickly.

## Conversations

| # | Do | Expect |
| --- | --- | --- |
| 1 | Open the app with no conversations | Centred greeting, a focused composer, four suggestion cards, and "No conversations yet" in the sidebar |
| 2 | Type a question on the landing screen and send | The conversation is created on send and appears in the sidebar under "Today" |
| 3 | Ask *"What does Lenny say about product-market fit?"* | A "searching the transcripts" state, then a grounded answer |
| 4 | Look under the answer | A **Sources** list: numbered episode, guest, "Watch episode" |
| 5 | Click a source link | Opens that YouTube episode in a new tab |
| 6 | Ask *"What about customer interviews?"* | Answers in context of the previous turn |
| 7 | Look at the sidebar label | Short title from the first question, truncated with "…" |
| 8 | Hover the label | Tooltip shows the full original question |
| 9 | Click **New chat**, ask something else | Second conversation; the first is untouched |
| 10 | Switch between the two | Each shows only its own messages |

## Grounding

| # | Do | Expect |
| --- | --- | --- |
| 11 | Ask *"How do I make sourdough bread?"* | Refusal styled distinctly, no sources, answers in ~2s (no model call) |
| 12 | Ask a normal question again | Normal grounded answer — the refusal did not break the thread |

## Models

| # | Do | Expect |
| --- | --- | --- |
| 13 | Look at the header | **Ollama** (LOCAL) and **Claude** (CLOUD) |
| 14 | Switch provider, ask a question | Answer comes from the selected model |
| 15 | Stop Ollama (`brew services stop ollama`), reload | Ollama shown but disabled; hovering gives the reason; Claude still selectable |
| 16 | Restart Ollama, reload | Ollama selectable again |

## Artifacts

| # | Do | Expect |
| --- | --- | --- |
| 17 | Ask *"Write a Ship 30 essay about product-market fit."* | Panel opens with a formatted essay; the chat shows a short note, not the essay |
| 18 | Read the essay | Hook, headings, bold, and guests named from real episodes |
| 19 | Ask *"Build me a landing page about growth loops."* | Panel shows a styled, rendered page |
| 20 | View source on the artifact frame | `<iframe sandbox="" srcdoc=…>`; no `<script>`, no `onclick` |
| 21 | Close the panel, click **Open "…"** on the message | The artifact opens again |
| 22 | Ask *"Write a Ship 30 essay about sourdough bread."* | Refusal; **no** artifact created |

## Persistence

| # | Do | Expect |
| --- | --- | --- |
| 23 | Reload the page | Conversations still listed |
| 24 | Open the conversation with the essay | All messages, with their collapsed source rows, and the artifact still openable |

## Deleting

| # | Do | Expect |
| --- | --- | --- |
| 25 | Hover a conversation | A trash button appears |
| 26 | Click it | Inline "Delete?" — nothing is deleted yet |
| 27 | Click **Cancel** | The conversation stays |
| 28 | Delete a non-active conversation | It disappears; the open one is untouched |
| 29 | Delete the active conversation | Another conversation opens automatically |
| 30 | Delete the last one | Empty state returns |
| 31 | Reload | Deleted conversations stay deleted |

## Responsive

| # | Do | Expect |
| --- | --- | --- |
| 32 | Narrow the window below 1200px with an artifact open | Panel becomes an overlay with a dimmed backdrop |
| 33 | Narrow below 860px | Sidebar collapses behind ☰; composer stays full width |
| 34 | Open the ☰ drawer | Slides in over a dimmed backdrop; tapping the backdrop closes it |
| 35 | Scroll at 390px wide | No horizontal scrolling anywhere |

## Keyboard and accessibility

| # | Do | Expect |
| --- | --- | --- |
| 36 | Tab through the sidebar | Visible focus ring; the delete button becomes visible when focused |
| 36a | Click a superscript citation in an answer | The side panel opens on that episode, with a "Watch the episode" link |
| 36b | Click a **N sources** row | Expands to the episodes, deduplicated, each opening the panel |
| 36c | Open the model menu, press ↓/↑ then Esc | Focus moves between options; Esc closes and returns focus to the trigger |
| 36d | Click the theme button in the sidebar footer | Light and dark swap; the choice survives a reload |
| 36e | Collapse the sidebar with the top-left button | Becomes a 60px icon rail; still collapsed after a reload |
| 37 | Press Escape on a delete confirmation | Cancels |
| 38 | Type a question and press Enter | Sends |
| 39 | Press Shift+Enter | New line, does not send |
| 40 | Tab to a source link and press Enter | Opens the episode |
| 41 | Paste 2,001 characters | Send disabled, with the character count and limit shown |

## Errors

| # | Do | Expect |
| --- | --- | --- |
| 42 | Stop the backend, send a message | "Could not reach the assistant…" — no stack trace, conversation still visible |
| 43 | Restart the backend, retry | Works again |
