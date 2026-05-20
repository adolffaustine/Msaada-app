import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as echarts from 'echarts';
import { postChat, getHistory, postReset } from './api.js';

const SESSION_KEY = 'msaada_session_v1';


function getOrCreateSessionId() {
  let sid = localStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

// Render a small subset of markdown (**bold**) safely without innerHTML.
function FormattedText({ text }) {
  const parts = [];
  const re = /\*\*([^*\n]+)\*\*/g;
  let cursor = 0;
  for (const m of (text || '').matchAll(re)) {
    if (m.index > cursor) parts.push(text.slice(cursor, m.index));
    parts.push(<strong key={parts.length}>{m[1]}</strong>);
    cursor = m.index + m[0].length;
  }
  if (cursor < (text || '').length) parts.push(text.slice(cursor));
  return <>{parts.map((p, i) => typeof p === 'string' ? <span key={i}>{p}</span> : p)}</>;
}

function ChartCard({ chart }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, null, { renderer: 'svg' });
    const series = [];
    if (chart.recv_mbps?.length) series.push({
      name: 'Download (Mbps)', type: 'line', smooth: true, showSymbol: false,
      data: chart.recv_mbps, lineStyle: { width: 2, color: '#1e345e' },
      areaStyle: { color: 'rgba(30,52,94,.08)' },
    });
    if (chart.sent_mbps?.length) series.push({
      name: 'Upload (Mbps)', type: 'line', smooth: true, showSymbol: false,
      data: chart.sent_mbps, lineStyle: { width: 2, color: '#00b380' },
      areaStyle: { color: 'rgba(0,179,128,.12)' },
    });
    if (chart.capacity_mbps) series.push({
      name: 'Capacity', type: 'line', data: [],
      markLine: {
        symbol: 'none', silent: true,
        lineStyle: { type: 'dashed', color: '#b53d2e', width: 1.5 },
        label: { formatter: 'Capacity', color: '#b53d2e' },
        data: [{ yAxis: chart.capacity_mbps }],
      },
    });
    c.setOption({
  // FIX 1: Adjust grid properties to give the labels proper container padding
  grid: { 
    left: '10%',   // Dynamic percentage scales perfectly regardless of digits
    right: '4%', 
    top: 40, 
    bottom: 30,
    containLabel: true // Forces ECharts to calculate labels safely inside the grid box!
  },
  legend: { top: 0, textStyle: { color: '#3d4a5c', fontSize: 11 } },
  tooltip: { trigger: 'axis', valueFormatter: v => (v ?? 0).toFixed(2) + ' Mbps' },
  xAxis: { type: 'time', axisLabel: { color: '#6b7a90', fontSize: 10 } },
  yAxis: { 
    type: 'value', 
    name: 'Mbps', 
    axisLabel: { 
      color: '#6b7a90', 
      fontSize: 10,
      // FIX 2: Restrict the text area from causing wide container layout shifts
      overflow: 'truncate' 
    } 
  },
  series,
});
    const onResize = () => c.resize();
    window.addEventListener('resize', onResize);
    return () => { window.removeEventListener('resize', onResize); c.dispose(); };
  }, [chart]);

  return (
    <div className="chart-card">
      <div className="chart-head">
        <span className="chart-title">Recent usage on {chart.interface || 'your link'}</span>
        {chart.capacity_mbps ? <span className="chart-cap">Capacity: {chart.capacity_mbps} Mbps</span> : null}
      </div>
      <div ref={ref} style={{ width: '100%', height: 240 }} />
    </div>
  );
}

function TicketCard({ ticket }) {
  return (
    <div className="ticket-card">
      <div className="ticket-head">
        <span className="ticket-title">Ticket logged</span>
        <span className="ticket-sev">{ticket.severity || 'medium'}</span>
      </div>
      <div className="ticket-ref">Reference: <span className="mono">{ticket.id}</span></div>
      <div className="ticket-hint">Our team will follow up with you shortly.</div>
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);
  const [items, setItems] = useState([]);
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [voiceOn, setVoiceOn] = useState(() => localStorage.getItem('msaada_voice') !== 'off');
  const [listening, setListening] = useState(false);
  const recogRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    (async () => {
      const data = await getHistory(sessionId);
      const msgs = data.messages || [];
      if (msgs.length) {
        setItems(msgs.map(m => ({ kind: 'bubble', role: m.role === 'user' ? 'user' : 'bot', text: m.text })));
      } else {
        const greeting = "Hi! I'm Msaada, your Liquid Technologies support assistant. I can help diagnose your network connection. To get started, please provide your site name or CID.";
        setItems([{ kind: 'bubble', role: 'bot', text: greeting }]);
        speak(greeting);
      }
    })();
    // eslint-disable-next-line
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [items, typing]);

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    const r = new SR();
    r.lang = 'en-US'; r.continuous = false; r.interimResults = true;
    let final = '';
    r.onstart = () => { setListening(true); final = ''; };
    r.onend = () => { setListening(false); if (final.trim()) { setInput(final.trim()); send(final.trim()); } };
    r.onerror = () => setListening(false);
    r.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t + ' ';
        else interim += t;
      }
      setInput((final + interim).trim());
    };
    recogRef.current = r;
  }, []); // eslint-disable-line

  const speak = useCallback((text) => {
    if (!voiceOn || !text || !('speechSynthesis' in window)) return;
    const clean = text.replace(/[\*_`#]/g, '').replace(/\s+/g, ' ').trim();
    if (!clean) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(clean);
    u.rate = 1.0; u.lang = 'en-US';
    window.speechSynthesis.speak(u);
  }, [voiceOn]);

  const send = async (textOverride) => {
    const text = (textOverride ?? input).trim();
    if (!text) return;
    setItems(it => [...it, { kind: 'bubble', role: 'user', text }]);
    setInput('');
    setTyping(true);
    try {
      const data = await postChat(sessionId, text);
      setSessionId(data.sessionId || sessionId);
      localStorage.setItem(SESSION_KEY, data.sessionId || sessionId);
      setTyping(false);
      const next = [];
      if (data.reply) next.push({ kind: 'bubble', role: 'bot', text: data.reply });
      if (data.card?.chart) next.push({ kind: 'chart', chart: data.card.chart });
      if (data.card?.ticket) next.push({ kind: 'ticket', ticket: data.card.ticket });
      setItems(it => [...it, ...next]);
      speak(data.reply);
    } catch {
      setTyping(false);
      setItems(it => [...it, { kind: 'bubble', role: 'bot', text: "Connection problem — please try again." }]);
    }
  };

  const newChat = async () => {
    await postReset(sessionId);
    window.speechSynthesis.cancel();
    const sid = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sid);
    setSessionId(sid);
    const greeting = "Hi! I'm Msaada, your Liquid Technologies support assistant. I can help diagnose your network connection. To get started, please provide your site name or CID.";
    setItems([{ kind: 'bubble', role: 'bot', text: greeting }]);
    speak(greeting);
  };

  const toggleVoice = () => {
    const next = !voiceOn;
    setVoiceOn(next);
    localStorage.setItem('msaada_voice', next ? 'on' : 'off');
    if (!next) window.speechSynthesis.cancel();
  };

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const onMic = () => {
    if (!recogRef.current) return;
    if (listening) recogRef.current.stop();
    else { window.speechSynthesis.cancel(); try { recogRef.current.start(); } catch {} }
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo" />
          <div>
            <div className="brand-title">Msaada</div>
            <div className="brand-sub">Liquid Technologies — connectivity support</div>
          </div>
        </div>
        <div className="topbar-actions">
          <button className="pill" onClick={toggleVoice}>Voice: {voiceOn ? 'on' : 'off'}</button>
          <button className="pill" onClick={newChat}>New chat</button>
        </div>
      </header>

      <main className="messages">
        {items.map((it, i) => {
          if (it.kind === 'chart') return <ChartCard key={i} chart={it.chart} />;
          if (it.kind === 'ticket') return <TicketCard key={i} ticket={it.ticket} />;
          return (
            <div key={i} className={'bubble-row ' + (it.role === 'user' ? 'right' : 'left')}>
              <div className={'bubble ' + (it.role === 'user' ? 'user' : 'bot')}>
                {it.role === 'bot' ? <FormattedText text={it.text} /> : it.text}
              </div>
            </div>
          );
        })}
        {typing ? (
          <div className="bubble-row left">
            <div className="bubble bot dots"><span></span><span></span><span></span></div>
          </div>
        ) : null}
        <div ref={endRef} />
      </main>

      <div className="composer-wrap">
        <div className="composer">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            rows={1}
            placeholder="Type your registered site name or CID — e.g. 'Meticulous Tanzania' or 'LTZ1900201'"
          />
          <button className={'mic ' + (listening ? 'on' : '')} onClick={onMic} aria-label="mic">🎙</button>
          <button className="send" onClick={() => send()} aria-label="send">➤</button>
        </div>
        <p className="hint">Press Enter to send · Shift+Enter for newline · Click mic to speak</p>
      </div>
    </div>
  );
}
