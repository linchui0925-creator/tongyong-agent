import { useEffect, useRef, useState } from 'react';
import './ContactModal.css';

export interface ContactModalProps {
  open: boolean;
  onClose: () => void;
}

interface FormState {
  name: string;
  email: string;
  topic: ContactTopic;
  message: string;
}

type ContactTopic = 'cooperation' | 'support' | 'feedback' | 'other';

const topicLabels: Record<ContactTopic, string> = {
  cooperation: '合作咨询',
  support: '技术支持',
  feedback: '功能建议',
  other: '其他',
};

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ContactModal({ open, onClose }: ContactModalProps) {
  const [form, setForm] = useState<FormState>({
    name: '',
    email: '',
    topic: 'cooperation',
    message: '',
  });
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);

  // Lock scroll while open + reset state on close.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    setDone(false);
    setSubmitError(null);
    setErrors({});
    // Focus the first field on next paint so screen readers announce the modal.
    requestAnimationFrame(() => firstFieldRef.current?.focus());
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const validate = (state: FormState): Partial<Record<keyof FormState, string>> => {
    const next: Partial<Record<keyof FormState, string>> = {};
    if (!state.name.trim()) next.name = '请填写姓名';
    else if (state.name.trim().length > 60) next.name = '姓名不超过 60 字符';
    if (!state.email.trim()) next.email = '请填写邮箱';
    else if (!emailRegex.test(state.email.trim())) next.email = '邮箱格式不正确';
    if (!state.message.trim()) next.message = '请简要描述你的需求';
    else if (state.message.trim().length < 10) next.message = '描述至少 10 个字符，方便我们了解背景';
    else if (state.message.trim().length > 2000) next.message = '描述不超过 2000 字符';
    return next;
  };

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm(prev => {
      const next = { ...prev, [key]: value };
      // Live-clear errors for the changed field if it now validates.
      if (errors[key]) {
        const v = validate(next);
        if (!v[key]) {
          setErrors(e => {
            const { [key]: _, ...rest } = e;
            return rest;
          });
        }
      }
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const v = validate(form);
    setErrors(v);
    if (Object.keys(v).length > 0) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const resp = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          email: form.email.trim(),
          topic: form.topic,
          message: form.message.trim(),
        }),
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        throw new Error(text || `提交失败 (${resp.status})`);
      }
      setDone(true);
    } catch (err) {
      console.error('[ContactModal] submit failed', err);
      setSubmitError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const onBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div className="contact-backdrop" onClick={onBackdropClick} role="presentation">
      <div
        className="contact-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-title"
        ref={dialogRef}
      >
        <button
          type="button"
          className="contact-close"
          onClick={onClose}
          aria-label="关闭"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        {done ? (
          <div className="contact-success">
            <div className="contact-success-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <h2 id="contact-title" className="contact-title">已收到你的来信</h2>
            <p className="contact-sub">
              我们会在 1–2 个工作日内通过邮箱 <strong>{form.email}</strong> 联系你。
            </p>
            <button type="button" className="contact-submit" onClick={onClose}>好的</button>
          </div>
        ) : (
          <>
            <header className="contact-head">
              <h2 id="contact-title" className="contact-title">联系我们</h2>
              <p className="contact-sub">告诉我们你的想法 — 合作、技术支持、功能建议都可以。</p>
            </header>

            <form className="contact-form" onSubmit={handleSubmit} noValidate>
              <div className="contact-row">
                <label className="contact-field">
                  <span className="contact-label">姓名</span>
                  <input
                    ref={firstFieldRef}
                    type="text"
                    value={form.name}
                    onChange={e => update('name', e.target.value)}
                    placeholder="例如：张三"
                    autoComplete="name"
                    aria-invalid={!!errors.name}
                    maxLength={60}
                  />
                  {errors.name && <span className="contact-error">{errors.name}</span>}
                </label>

                <label className="contact-field">
                  <span className="contact-label">邮箱</span>
                  <input
                    type="email"
                    value={form.email}
                    onChange={e => update('email', e.target.value)}
                    placeholder="例如：you@example.com"
                    autoComplete="email"
                    aria-invalid={!!errors.email}
                    maxLength={120}
                  />
                  {errors.email && <span className="contact-error">{errors.email}</span>}
                </label>
              </div>

              <fieldset className="contact-field">
                <legend className="contact-label">主题</legend>
                <div className="contact-topic-grid" role="radiogroup">
                  {(Object.keys(topicLabels) as ContactTopic[]).map(t => (
                    <label key={t} className={`contact-topic ${form.topic === t ? 'is-selected' : ''}`}>
                      <input
                        type="radio"
                        name="topic"
                        value={t}
                        checked={form.topic === t}
                        onChange={() => update('topic', t)}
                      />
                      <span>{topicLabels[t]}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <label className="contact-field">
                <span className="contact-label">详细描述</span>
                <textarea
                  value={form.message}
                  onChange={e => update('message', e.target.value)}
                  placeholder="简单介绍一下背景、需求、或者你想解决的问题……"
                  rows={5}
                  aria-invalid={!!errors.message}
                  maxLength={2000}
                />
                <span className="contact-counter">{form.message.length} / 2000</span>
                {errors.message && <span className="contact-error">{errors.message}</span>}
              </label>

              {submitError && <div className="contact-form-error" role="alert">{submitError}</div>}

              <div className="contact-actions">
                <button type="button" className="contact-cancel" onClick={onClose}>取消</button>
                <button type="submit" className="contact-submit" disabled={submitting}>
                  {submitting ? '提交中…' : '发送'}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
