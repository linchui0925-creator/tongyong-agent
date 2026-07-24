import { getCurrentModel } from './llm';

export async function transcribeVoice(file: File, sessionId?: string): Promise<{ success: boolean; text?: string; error?: string }> {
  const current = await getCurrentModel();
  const form = new FormData();
  form.append('file', file);
  if (sessionId) form.append('session_id', sessionId);
  if (current?.id) form.append('model_id', current.id);
  const res = await fetch('/api/voice/transcribe', { method: 'POST', body: form });
  return await res.json();
}

export async function speakText(text: string): Promise<{ success: boolean; audio_url?: string; error?: string }> {
  const current = await getCurrentModel();
  const modelId = current?.id;
  const res = await fetch('/api/voice/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, format: 'mp3', model_id: modelId }),
  });
  return await res.json();
}
