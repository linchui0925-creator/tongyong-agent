import { Attachment } from '../types';

const API_BASE_URL = '/api/chat/attachments';

export async function uploadAttachments(files: File[], sessionId?: string): Promise<Attachment[]> {
  if (!files.length) return [];

  const form = new FormData();
  files.forEach((file) => form.append('files', file));
  if (sessionId) form.append('session_id', sessionId);

  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    body: form,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `附件上传失败: ${response.status}`);
  }

  const data = await response.json();
  return data.attachments || [];
}
