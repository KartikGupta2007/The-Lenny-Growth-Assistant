Design Document — The Lenny Growth Assistant

1. Design Overview

The Lenny Growth Assistant is designed as a focused AI workspace rather than a generic chatbot.

The primary interaction is conversational:

Ask a product/growth question → receive a grounded answer → inspect sources → continue the conversation or turn the result into an artifact.

The interface should make the underlying complexity of RAG, agents, embeddings, model providers, and infrastructure invisible to the user while still providing enough transparency to establish trust.

The core design priorities are:

1. Clarity — Users should immediately understand what the assistant does.
2. Trust — Grounded answers should visibly expose their sources.
3. Focus — The chat should remain the primary interaction.
4. Continuity — Conversations should preserve context.
5. Creation — Users should be able to transform knowledge into reusable artifacts.
6. Feedback — Loading, success, empty, and failure states should always be understandable.
7. Safety — Generated HTML should be presented as untrusted content and rendered within a controlled boundary.

⸻

2. UI/UX Principles

2.1 Conversation First

The primary screen should immediately focus the user on asking a question.

The interface should avoid exposing unnecessary technical concepts such as:

* Embeddings
* Vector databases
* Chunking
* Retrieval pipelines
* Agent routing

These are implementation details.

The user should instead see:

What can I help you explore?
Ask about product, growth, strategy,
retention, startups, or other topics
covered by Lenny's Podcast.

⸻

2.2 Grounding Should Be Visible

The assistant should not feel like an unexplained black box.

When an answer uses transcript information, the response should provide a clear source section.

Example:

Assistant
Retention should be treated as a measure of whether
users continue receiving meaningful value from the product...
Sources
────────────────────────
Brian Chesky — Episode Title
Andrew Chen — Episode Title

Sources should be visually distinguishable from generated content.

⸻

2.3 Progressive Disclosure

The interface should show the important information first and secondary details when requested.

Primary:

Answer

Secondary:

Sources

Additional:

Episode metadata
Transcript excerpt
Source URL

This keeps answers readable without hiding provenance.

⸻

2.4 Minimal Cognitive Load

The user should not have to understand how the assistant works.

The interface should favor:

* Clear labels.
* Familiar controls.
* Consistent placement.
* Limited visual noise.
* Short explanatory text.

⸻

2.5 Clear System States

Every asynchronous operation should communicate its state.

Examples:

Thinking...
Searching transcripts...
Generating answer...
Creating artifact...

The user should never wonder whether the application is frozen.

⸻

3. Information Architecture

The application is organized around four primary areas:

┌─────────────────────────────────────────────────────┐
│ Header                                              │
├───────────────┬───────────────────────┬─────────────┤
│               │                       │             │
│   Sidebar     │       Chat            │  Artifact   │
│               │                       │   Viewer    │
│ New Chat      │       Messages        │             │
│               │                       │             │
│ Recent Chats  │       Input           │             │
│               │                       │             │
└───────────────┴───────────────────────┴─────────────┘

3.1 Sidebar

Contains:

* New Chat.
* Recent conversations.
* Current session indicator.
* Optional application information.

The sidebar should remain secondary to the conversation.

⸻

3.2 Chat Area

Contains:

* Conversation history.
* User messages.
* Assistant responses.
* Source references.
* Loading states.
* Error states.
* Message composer.

The chat is the primary workspace.

⸻

3.3 Artifact Viewer

The artifact viewer appears when the assistant generates a document or visual artifact.

It should display:

* Artifact title/type.
* Rendered content.
* Loading state.
* Rendering error state.
* Close/collapse control.

The artifact viewer should not replace the conversation.

⸻

4. Main User Journey

4.1 First Visit

The user sees an empty-state screen.

Example:

        Lenny Growth Assistant
Ask questions about product and growth
using knowledge from Lenny's Podcast.
        [ Ask a question... ]
Try:
• How should I think about product-market fit?
• What are common retention strategies?
• How can I improve onboarding?

The goal is to communicate the product’s purpose immediately.

⸻

5. New Chat Flow

When the user clicks New Chat:

New Chat
   ↓
Create session
   ↓
Clear conversation view
   ↓
Show empty state
   ↓
Ready for question

The user should receive immediate visual confirmation that they are in a new conversation.

⸻

6. Question & Answer Flow

User enters question
        ↓
Send
        ↓
Loading state
        ↓
Retrieval / generation
        ↓
Assistant response
        ↓
Sources displayed

The response should appear progressively where practical rather than leaving the user with an unexplained blank screen.

⸻

7. Follow-Up Questions

The interface should make follow-up conversation feel natural.

Example:

User:
How can I improve retention?
Assistant:
...
User:
What about for a B2B product?

The second question should remain visually connected to the same conversation.

The UI should not require the user to repeat context.

⸻

8. Source Interaction

Each grounded response should expose source information.

Example:

Sources · 3
▸ Brian Chesky — Building Airbnb
▸ Andrew Chen — Growth Loops
▸ Elena Verna — Retention

Clicking a source can expose:

Episode
Guest
Publication date
Source URL
Relevant transcript excerpt

The source presentation should be compact enough that it doesn’t overwhelm the answer.

⸻

9. Unsupported Question State

If the transcript knowledge base does not provide sufficient evidence, the UI should communicate that clearly.

Example:

I couldn't find enough information in Lenny's
Podcast transcripts to answer this reliably.
Try asking about:
• Product strategy
• Growth
• Retention
• Product-market fit

Avoid presenting an unsupported answer as if it were grounded.

⸻

10. Model Selection

The application supports configurable model providers.

The model selector shows every provider the application supports. A provider
that cannot be used in the current environment stays visible but is disabled,
with the reason shown beside it.

Local environment

Model
● Ollama        Local    llama3.1:8b
○ Claude        Cloud    claude-sonnet-5

Deployment without Ollama

Model
○ Ollama        Local    llama3.1:8b
  Ollama runs on the machine hosting the API and is not available in
  this environment. Use a cloud model instead.
● Claude        Cloud    claude-sonnet-5

An unavailable provider is never selectable. It is disabled rather than hidden
so that the user can see the local option exists and understand why it is not
offered here, instead of watching an option disappear between environments.

Each option carries a kind indicator:

Ollama · Local

or:

Claude · Cloud

Availability is decided by the backend and delivered by GET /api/providers.
The frontend holds no environment logic of its own, so one bundle behaves
correctly in development and in production.

⸻

11. Artifact Generation UX

When the user requests an artifact:

User:
Turn this into a product strategy document.

The assistant should acknowledge the action:

Creating product strategy artifact...

Then the artifact viewer opens beside the conversation.

┌──────────────────────────┬──────────────────────────┐
│          CHAT            │        ARTIFACT           │
│                          │                          │
│ User                     │ Product Strategy         │
│                          │                          │
│ Assistant                │ # Strategy               │
│                          │                          │
│                          │ ## Problem                │
│                          │ ...                      │
└──────────────────────────┴──────────────────────────┘

The conversation should remain accessible while the user reviews the artifact.

⸻

12. Artifact Viewer States

Loading

Generating artifact...

Success

Display the rendered artifact.

Empty

No artifact selected.

Error

We couldn't render this artifact.
The generated content may be invalid or
could not pass the safety checks.

The user should be able to return to the conversation without losing context.

⸻

13. Artifact Types

The viewer should support:

Markdown

Rendered as formatted content:

* Headings
* Paragraphs
* Lists
* Bold/italic text
* Code blocks where appropriate

HTML/CSS

Rendered inside the application’s controlled artifact environment.

Raw HTML should not be the primary presentation.

⸻

14. Responsive Behavior

The desktop experience should prioritize the split chat/artifact workflow.

Desktop

Sidebar | Chat | Artifact

The artifact panel can occupy approximately one-third to one-half of the available workspace when active.

Tablet

Use:

Sidebar | Chat

with the artifact viewer becoming an expandable panel or overlay.

Mobile

Use a single primary column:

Chat

The artifact viewer becomes a dedicated full-screen view or bottom-sheet style experience.

The chat should remain usable without horizontal scrolling.

⸻

15. Responsive Layout Principles

The layout should:

* Avoid horizontal overflow.
* Preserve readable text widths.
* Keep the message composer accessible.
* Allow long source titles to wrap.
* Prevent the artifact viewer from making chat unusable.
* Adapt navigation to available screen width.

⸻

16. Accessibility

Accessibility should be considered from the beginning rather than added after implementation.

Keyboard navigation

All important controls should be reachable through the keyboard.

Examples:

* New Chat.
* Session selection.
* Message composer.
* Send.
* Model selector.
* Source expansion.
* Artifact viewer controls.

Focus states

Interactive elements should have clearly visible focus states.

Semantic structure

Use appropriate semantic elements:

header
nav
main
aside
section
button
form

rather than using generic containers for every interaction.

Screen readers

Important states should be announced where appropriate.

For example:

"Response generated."
"Searching transcripts."
"Artifact generation failed."

Color

Do not rely on color alone to communicate:

* Errors.
* Provider availability.
* Success.
* Loading states.

Icons and text labels should reinforce those states.

⸻

17. Message Composer

The composer should be persistent at the bottom of the chat.

Example:

┌───────────────────────────────────────────────┐
│ Ask a product or growth question...      ➤   │
└───────────────────────────────────────────────┘

Expected behavior:

* Enter → send.
* Shift + Enter → new line.
* Disabled while appropriate.
* Clear loading state.
* Prevent empty submissions.
* Maintain accessibility labels.

⸻

18. Loading Experience

LLM responses can take time, particularly when using Ollama.

Instead of a static spinner, use meaningful status text:

Searching Lenny's transcripts...

Then:

Generating response...

For artifact generation:

Creating artifact...

This helps the user understand what the system is doing.

⸻

19. Error UX

Errors should be actionable and understandable.

Example

Instead of:

500 Internal Server Error

show:

Something went wrong while generating the response.
Please try again.

For a provider issue:

Ollama is currently unavailable.
You can switch to the available cloud model
or start Ollama locally.

Technical details should be available for debugging but not dominate the user-facing experience.

⸻

20. Empty Retrieval UX

If no sufficiently relevant transcript content is found:

I couldn't find enough relevant material in
Lenny's Podcast transcripts to answer this reliably.

The interface should avoid presenting unrelated search results merely to make the UI look populated.

⸻

21. Visual Hierarchy

The interface should establish a clear hierarchy:

Level 1

User question / assistant answer.

Level 2

Sources and artifact controls.

Level 3

Metadata and technical details.

The answer should visually dominate the source metadata without hiding it.

⸻

22. Design Decisions

22.1 Chat + Artifact Split View

Decision: Use a split workspace when artifacts are generated.

Why:

The assignment requires artifacts to render beside the chat. Keeping both visible allows users to iterate on an artifact while retaining the conversation that produced it.

⸻

22.2 Sources Inside Responses

Decision: Attach sources directly to the relevant assistant response.

Why:

Users should understand which evidence supports an answer without navigating to a separate knowledge-base screen.

⸻

22.3 Model Selector Shows Unavailable Providers, Disabled

Decision: Show every provider the backend knows about. One that cannot be used
here stays visible but disabled, with the reason.

Why:

A deployed environment may not have Ollama. Hiding it would leave the user
wondering whether local models exist at all; showing it disabled answers the
question and explains the environment. The backend refuses a disabled provider
anyway, so the UI is a courtesy rather than the control.

Implemented as a listbox popover in the composer, not a native select: the
options carry a kind badge, the model id and an explanation.

⸻

22.4 No Separate Knowledge-Base UI for MVP

Decision: Do not expose the vector database, chunks, or embedding infrastructure as primary UI.

Why:

These are implementation details rather than user goals.

Source information is exposed when relevant, but the knowledge infrastructure remains behind the assistant.

⸻

22.5 Persistent Sessions

Decision: Provide a sidebar containing recent sessions.

Why:

Users may work on product/growth questions over multiple conversations and should be able to return to previous work.

⸻

22.6 Progressive Disclosure of Sources

Decision: Two levels of disclosure. Citation markers in the answer text are
clickable and open that episode in the side panel; beneath the answer a single
collapsed row names the number of sources, expanding to the full list.

Why:

This balances transparency with readability. Eight retrieved chunks routinely
come from four or five episodes, so the list is grouped by episode -- and
because only about half of answers actually emit `[n]` markers (smaller local
models often omit them), the collapsed row is always present. Sources are never
invisible, whichever the model did.

⸻

22.7 One Side Panel, Two Kinds of Content

Decision: The right-hand panel shows either a generated artifact or a cited
source.

Why:

Both are "the thing behind the answer", both want the same width and the same
close behaviour, and one panel keeps the layout predictable.

⸻

22.8 Theme

Decision: Light and dark are both designed. The application follows the
operating system by default and offers a toggle in the sidebar footer.

Why:

The default respects the environment; the toggle means a reviewer can see
either without changing their machine.

⸻

23. Artifact Security UX

The user should not need to understand the technical security implementation.

If generated content cannot safely be rendered, the application should explain the outcome:

This artifact could not be safely rendered.
The generated HTML contained content that
did not pass the application's safety checks.

The system should never silently execute unsafe generated content.

⸻

24. Design System Principles

The implementation should use a consistent design system covering:

* Typography.
* Spacing.
* Border radius.
* Buttons.
* Inputs.
* Cards.
* Status indicators.
* Source cards.
* Message bubbles.
* Panels.
* Dialogs.

Avoid introducing custom styling for every individual component.

⸻

25. Interaction States Summary

Component	States
Chat	Empty, active, loading, error
Message	Sending, generated, failed
Retrieval	Searching, results, no results, failed
Sources	Collapsed, expanded, opened in the panel
Model	Available, unavailable, switching
Artifact	Empty, generating, rendered, failed
Session	New, active, archived/history
Application	Ready, degraded, unavailable

⸻

26. Example Complete User Journey

1. User opens application
          ↓
2. Empty chat screen
          ↓
3. User asks:
   "How should I improve retention?"
          ↓
4. UI shows:
   "Searching Lenny's transcripts..."
          ↓
5. Assistant retrieves relevant chunks
          ↓
6. UI shows:
   "Generating response..."
          ↓
7. Answer appears
          ↓
8. Sources appear below answer
          ↓
9. User asks:
   "Turn this into an essay."
          ↓
10. Ship 30 skill runs
          ↓
11. Artifact viewer opens
          ↓
12. ~1,250-word essay rendered
          ↓
13. User asks:
    "Now create a landing page from this."
          ↓
14. Artifact skill generates HTML/CSS
          ↓
15. HTML is sanitized
          ↓
16. Artifact viewer renders landing page

⸻

27. Design Success Criteria

The design will be considered successful if a first-time evaluator can:

* Understand the product within seconds.
* Start a conversation without instructions.
* Understand when the assistant is working.
* Distinguish generated answers from source material.
* Identify the source behind an answer.
* Continue a conversation naturally.
* Generate an artifact without leaving the application.
* Understand whether Ollama or a cloud provider is active.
* Recover from errors without confusion.
* Use the application comfortably on desktop and smaller screens.

⸻

28. Final Design Principle

The interface should make the product feel simple even though the underlying system is complex.

The user experience should effectively reduce the entire architecture to:

                 ASK
                  ↓
              EXPLORE
                  ↓
             GET GROUNDED
               ANSWER
                  ↓
              CREATE
                  ↓
             REVIEW
             ARTIFACT

The complexity of:

RAG
Embeddings
Vector Search
Agents
LLMs
Ollama
PostgreSQL
Sanitization

should remain behind the interface, while trust, sources, state, and useful outputs remain visible to the user.