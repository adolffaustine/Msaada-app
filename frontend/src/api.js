const API = 'https://chatbot.liquidmatics.co.tz/api';

export async function postChat(sessionId, message) {
  const r = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, message }),
  });
  if (!r.ok) throw new Error('chat error ' + r.status);
  return r.json();
}

export async function* streamChat(sessionId, message) {
  const r = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, message }),
  });
  if (!r.ok) throw new Error('chat error ' + r.status);

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)); } catch {}
      }
    }
  }
}

export async function getHistory(sessionId) {
  const r = await fetch(`${API}/history?sessionId=${encodeURIComponent(sessionId)}`);
  if (!r.ok) return { messages: [] };
  return r.json();
}

export async function postReset(sessionId) {
  await fetch(`${API}/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  });
}
