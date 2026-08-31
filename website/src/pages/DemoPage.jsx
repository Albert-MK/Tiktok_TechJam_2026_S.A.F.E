import { useEffect, useRef, useState } from 'react';
import animatedShoppingIcon from '../../bloub-squircle-attentif-bleu-anime.svg';
import BackgroundVideo from '../components/BackgroundVideo';
import ChatStateIcon from '../components/ChatStateIcon';
import Nav from '../components/Nav';
import { usePageSetup } from '../hooks';
import { useChatStore } from '../store/useChatStore';

export default function DemoPage() {
  usePageSetup('demo-page');
  const [input, setInput] = useState('');
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const { messages, isLoading, error, send, reset } = useChatStore();

  useEffect(() => {
    document.title = 'TikTok TechJam Demo | Start a conversation';
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, isLoading, error]);

  const submit = (event) => {
    event.preventDefault();
    const value = input.trim();
    if (!value) return;
    setInput('');
    send(value);
  };

  const startNewConversation = () => {
    setInput('');
    reset();
    scrollRef.current?.scrollTo({ top: 0, behavior: 'auto' });
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const moveGlassHighlight = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty('--glass-x', `${((event.clientX - bounds.left) / bounds.width) * 100}%`);
    event.currentTarget.style.setProperty('--glass-y', `${((event.clientY - bounds.top) / bounds.height) * 100}%`);
  };

  const resetGlassHighlight = (event) => {
    event.currentTarget.style.setProperty('--glass-x', '24%');
    event.currentTarget.style.setProperty('--glass-y', '0%');
  };

  return (
    <>
      <a className="skip-link" href="#demo-chat">Skip to chat</a>
      <Nav demo />
      <main className="demo-scene has-media">
        <BackgroundVideo className="demo-background-media" src="/assets/shoptun-demo-video.mp4?v=frontend-2" poster="/assets/shoptun-demo-video-poster.jpg?v=frontend-2" />
        <div className="sky-noise" aria-hidden="true"/>
        <section id="demo-chat" className="chatbox liquid-glass" aria-label="TikTok TechJam conversation demo" onPointerMove={moveGlassHighlight} onPointerLeave={resetGlassHighlight}>
          <button className="new-chat-button floating-new-chat" type="button" onClick={startNewConversation}>New conversation</button>

          <div className="chat-scroll" ref={scrollRef}>
            {messages.length === 0 && !isLoading ? <Welcome /> : (
              <div className="conversation-state" aria-live="polite">
                {messages.map((message) => <Message key={message.id} message={message} onSuggestedReply={send} />)}
                {isLoading && <Typing />}
                {error && <div className="chat-error" role="alert">{error}</div>}
              </div>
            )}
          </div>

          <form className="chat-composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="message-input">Message TikTok TechJam</label>
            <input ref={inputRef} id="message-input" name="message" autoComplete="off" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Message TikTok TechJam…" disabled={isLoading}/>
            <button type="submit" aria-label="Send message" disabled={isLoading || !input.trim()}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 14-7-4 14-3-6-7-1Z"/></svg></button>
          </form>
        </section>
      </main>
    </>
  );
}

function Welcome() {
  return (
    <div className="welcome-state chat-only-welcome">
      <img className="welcome-icon" src={animatedShoppingIcon} alt="" aria-hidden="true" />
      <p className="eyebrow">Conversational shopping</p>
      <h1>Start with a message.</h1>
      <p>Tell TikTok TechJam what you need. Continue naturally as your preferences change.</p>
    </div>
  );
}

function Message({ message, onSuggestedReply }) {
  if (message.role === 'user') {
    return <div className="live-message user"><div className="bubble">{message.text}</div></div>;
  }

  return (
    <div className="live-message assistant">
      <ChatStateIcon state="answered" className="live-avatar" />
      <div className="assistant-response">
        <div className="bubble">{message.text}</div>
        {message.action && <ActionTrace action={message.action} />}
        {(message.removedPreferences?.length > 0 || message.preferences?.length > 0) && (
          <PreferenceTrace removed={message.removedPreferences} active={message.preferences} />
        )}
        {message.candidateStatus && <CandidateStatus text={message.candidateStatus} />}
        {message.recommendation && <RecommendationCard recommendation={message.recommendation} />}
        {message.isComplete && <div className="match-complete"><i aria-hidden="true"/>Target matched <span>Rank 1</span></div>}
        {message.suggestedReply && (
          <button className="suggested-reply" type="button" onClick={() => onSuggestedReply(message.suggestedReply)}>
            <span>Continue verified session</span>
            {message.suggestedReply}
          </button>
        )}
      </div>
    </div>
  );
}

function ActionTrace({ action }) {
  return (
    <div className="action-trace">
      <span>Asked for: <strong>{action.label}</strong></span>
      <code>ask_attribute: {action.value}</code>
    </div>
  );
}

function PreferenceTrace({ removed = [], active = [] }) {
  return (
    <div className="preference-trace" aria-label="Active shopping preferences">
      {removed.map((item) => <span className="is-removed" key={`removed-${item}`}>{item}</span>)}
      {active.map((item) => <span key={item}>{item}</span>)}
    </div>
  );
}

function CandidateStatus({ text }) {
  return <div className="candidate-status"><i aria-hidden="true"/>{text}<span>Gathering evidence</span></div>;
}

function RecommendationCard({ recommendation }) {
  return (
    <article className="mock-recommendation" aria-label={`Rank ${recommendation.rank} recommendation: ${recommendation.name}`}>
      <div className="recommendation-rank" aria-hidden="true">0{recommendation.rank}</div>
      <div className="recommendation-copy">
        <p>Strongest match</p>
        <h2>{recommendation.name}</h2>
        <code>ASIN {recommendation.asin}</code>
      </div>
      <div className="recommendation-verdict">
        <span>Rank</span>
        <strong>{recommendation.rank}</strong>
      </div>
    </article>
  );
}

function Typing() {
  return <div className="live-message assistant typing-message"><ChatStateIcon state="thinking" className="live-avatar"/><div className="typing-dots" aria-label="TikTok TechJam is thinking"><i/><i/><i/></div></div>;
}
