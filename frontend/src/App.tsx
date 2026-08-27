/**
 * The chat application.
 *
 * Data flow, in one place:
 *
 *   load providers + sessions -> select a session -> GET its messages
 *   -> send a message -> append the user turn and the answer
 *
 * All state is plain React state; there is no store. All backend calls go
 * through api/client.ts.
 */

import { useCallback, useEffect, useState } from 'react';

import {
  createSession,
  deleteSession,
  getArtifact,
  getSession,
  listSessions,
  sendMessage,
  type Artifact,
  type ArtifactSummary,
  type ChatMessage,
  type Session,
  type Source,
} from './api/client';
import { ChatHeader } from './components/ChatHeader';
import { Landing } from './components/Landing';
import { MessageComposer } from './components/MessageComposer';
import { MessageList } from './components/MessageList';
import { Sidebar } from './components/Sidebar';
import { SidePanel, type PanelContent } from './components/SidePanel';
import { STORAGE_KEYS } from './constants';
import { firstQuestion, getConversationTitle } from './conversationTitle';
import { useProviders } from './hooks/useProviders';
import { useTheme } from './hooks/useTheme';

/** How many sidebar labels to fetch up front. */
const LABELLED_SESSIONS = 30;

function friendlyError(error: unknown): string {
  // Backend messages are already user-safe; the client's own errors are too.
  return error instanceof Error
    ? error.message
    : 'Something went wrong. Please try again.';
}

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.sidebar) === 'true';
  } catch {
    return false;
  }
}

export default function App() {
  const { state: providerState, selected: provider, select } = useProviders();
  const { theme, toggle: toggleTheme } = useTheme();

  const [sessions, setSessions] = useState<Session[]>([]);
  const [questions, setQuestions] = useState<Record<string, string>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([]);

  const [panel, setPanel] = useState<PanelContent | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [loadingArtifact, setLoadingArtifact] = useState(false);

  const [loadingSessions, setLoadingSessions] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(storedCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.sidebar, String(collapsed));
    } catch {
      // Non-fatal: the rail just will not be remembered.
    }
  }, [collapsed]);

  // Escape closes the panel, unless a menu is open and handling it itself.
  useEffect(() => {
    if (!panel) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (document.querySelector('[role="listbox"]')) return;
      setPanel(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [panel]);

  /** Remember a conversation's first question; the sidebar title derives from it. */
  const rememberQuestion = useCallback((id: string, loaded: ChatMessage[]) => {
    setQuestions((current) => ({ ...current, [id]: firstQuestion(loaded) }));
  }, []);

  // Sessions, plus enough of each to label it. The list endpoint returns no
  // messages, so labels need one small request each -- fine at this scale, and
  // cheaper than adding a title column to the database.
  useEffect(() => {
    let cancelled = false;

    listSessions()
      .then(async (loaded) => {
        if (cancelled) return;
        setSessions(loaded);
        setLoadingSessions(false);

        const details = await Promise.all(
          loaded.slice(0, LABELLED_SESSIONS).map((session) =>
            getSession(session.id).catch(() => null),
          ),
        );
        if (cancelled) return;
        setQuestions((current) => {
          const next = { ...current };
          for (const detail of details) {
            if (detail) next[detail.id] = firstQuestion(detail.messages);
          }
          return next;
        });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setLoadingSessions(false);
        setError(friendlyError(cause));
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const openArtifact = useCallback(async (id: string) => {
    setPanel({ kind: 'artifact', id });
    setLoadingArtifact(true);
    try {
      setArtifact(await getArtifact(id));
    } catch (cause) {
      setArtifact(null);
      setPanel(null);
      setError(friendlyError(cause));
    } finally {
      setLoadingArtifact(false);
    }
  }, []);

  const openSession = useCallback(
    async (id: string) => {
      setActiveId(id);
      setSidebarOpen(false);
      setError(null);
      setPanel(null);
      setArtifact(null);
      setLoadingMessages(true);
      try {
        const detail = await getSession(id);
        setMessages(detail.messages);
        setArtifacts(detail.artifacts);
        rememberQuestion(id, detail.messages);
      } catch (cause) {
        setMessages([]);
        setArtifacts([]);
        setError(friendlyError(cause));
      } finally {
        setLoadingMessages(false);
      }
    },
    [rememberQuestion],
  );

  function startNewChat() {
    setError(null);
    setActiveId(null);
    setMessages([]);
    setArtifacts([]);
    setPanel(null);
    setArtifact(null);
    setSidebarOpen(false);
  }

  /** Send into a known session. Used by both the landing and the chat. */
  async function sendTo(sessionId: string, text: string) {
    setError(null);
    setSending(true);

    // Show the question immediately; the id is replaced by the stored one.
    const pending: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      sources: [],
      grounded: null,
      provider: null,
    };
    setMessages((current) => [...current, pending]);

    try {
      await sendMessage(sessionId, text, provider);
      // Re-read the conversation so both turns carry their stored ids and
      // provenance rather than a locally assembled approximation.
      const detail = await getSession(sessionId);
      setMessages(detail.messages);
      setArtifacts(detail.artifacts);
      rememberQuestion(sessionId, detail.messages);
      // A turn that produced an artifact opens it straight away.
      const fresh = detail.artifacts.find(
        (a) => !artifacts.some((existing) => existing.id === a.id),
      );
      if (fresh) await openArtifact(fresh.id);
      // The backend orders sessions by activity; mirror that locally.
      setSessions((current) => {
        const active = current.find((session) => session.id === sessionId);
        if (!active) return current;
        return [active, ...current.filter((session) => session.id !== sessionId)];
      });
    } catch (cause) {
      setMessages((current) => current.filter((m) => m.id !== pending.id));
      setError(friendlyError(cause));
    } finally {
      setSending(false);
    }
  }

  async function send(text: string) {
    if (activeId) await sendTo(activeId, text);
  }

  /** Asking from the landing screen creates the conversation on the way. */
  async function ask(text: string) {
    setError(null);
    try {
      const session = await createSession();
      setSessions((current) => [session, ...current]);
      setQuestions((current) => ({ ...current, [session.id]: text }));
      setActiveId(session.id);
      setMessages([]);
      setArtifacts([]);
      setPanel(null);
      await sendTo(session.id, text);
    } catch (cause) {
      setError(friendlyError(cause));
    }
  }

  async function remove(id: string) {
    setError(null);
    const remaining = sessions.filter((session) => session.id !== id);
    try {
      await deleteSession(id);
      setSessions(remaining);
      setQuestions((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      if (id !== activeId) return;
      // The active conversation went: fall back to the next one, or the
      // landing screen when none are left.
      if (remaining.length > 0) await openSession(remaining[0].id);
      else startNewChat();
    } catch (cause) {
      setError(friendlyError(cause));
    }
  }

  const providers =
    providerState.status === 'ready' ? providerState.providers : [];
  const composerDisabled = sending || provider === null;
  const title = activeId
    ? getConversationTitle(questions[activeId])
    : 'New chat';

  const composer = (
    <MessageComposer
      onSend={activeId ? send : ask}
      disabled={composerDisabled}
      sending={sending}
      providers={providers}
      provider={provider}
      onSelectProvider={select}
      autoFocus={messages.length === 0}
    />
  );

  return (
    <div className="app" data-panel={panel !== null} data-rail={collapsed}>
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        questions={questions}
        loading={loadingSessions}
        open={sidebarOpen}
        collapsed={collapsed}
        theme={theme}
        onSelect={openSession}
        onDelete={remove}
        onNewChat={startNewChat}
        onClose={() => setSidebarOpen(false)}
        onToggleCollapsed={() => setCollapsed(!collapsed)}
        onToggleTheme={toggleTheme}
      />

      {sidebarOpen && (
        <button
          type="button"
          className="scrim"
          aria-label="Close conversations"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <main className="chat">
        <ChatHeader title={title} onOpenSidebar={() => setSidebarOpen(true)} />

        <div className="chat-body">
          {error && (
            <p className="chat-error" role="alert">
              {error}
            </p>
          )}

          {activeId === null ? (
            <Landing onPick={ask}>{composer}</Landing>
          ) : loadingMessages ? (
            <div className="messages">
              <div className="skeleton-lines" aria-label="Loading conversation">
                <span />
                <span />
                <span />
              </div>
            </div>
          ) : (
            <MessageList
              messages={messages}
              artifacts={artifacts}
              sending={sending}
              onOpenArtifact={openArtifact}
              onOpenSource={(source: Source) => setPanel({ kind: 'source', source })}
            />
          )}
        </div>

        {activeId !== null && (
          <div className="composer-dock">
            {composer}
            {provider === null && providers.length > 0 && (
              <p className="chat-error" role="alert">
                No model is available right now. Start Ollama locally, or
                configure a cloud provider, to ask a question.
              </p>
            )}
          </div>
        )}
      </main>

      {panel !== null && (
        <button
          type="button"
          className="scrim scrim-panel"
          aria-label="Close panel"
          onClick={() => setPanel(null)}
        />
      )}

      {panel !== null && (
        <SidePanel
          content={panel}
          artifact={artifact}
          loading={loadingArtifact}
          onClose={() => setPanel(null)}
        />
      )}
    </div>
  );
}
