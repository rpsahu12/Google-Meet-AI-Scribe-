import React, { useState, useEffect, useRef } from 'react';
import {
  Video, Play, Loader2, FileText, CheckCircle, Copy, Download,
  Clock, Users, Mic, Sparkles, RotateCcw, AlertCircle, LogOut, Radio
} from 'lucide-react';

const GithubIcon = ({ size = 24 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
    <path d="M9 18c-4.51 2-5-2-7-2" />
  </svg>
);

import { signInWithPopup, signOut, onAuthStateChanged, getIdToken } from 'firebase/auth';
import { auth, provider } from './firebase';
import './App.css';

function App() {
  const [user, setUser] = useState(null);
  const [meetLink, setMeetLink] = useState('');
  const [status, setStatus] = useState('idle');
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [copied, setCopied] = useState(false);
  const [meetings, setMeetings] = useState([]);
  const pollIntervalRef = useRef(null);
  const askingStartTimeRef = useRef(null); // tracks when 'asking' state began

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
    });
    return () => unsubscribe();
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem('meetings');
    if (saved) setMeetings(JSON.parse(saved));
  }, []);

  const handleSignIn = async () => {
    try {
      await signInWithPopup(auth, provider);
    } catch (err) {
      setError('Failed to sign in. Please try again.');
    }
  };

  const handleSignOut = async () => {
    if (window.confirm("Are you sure you want to log out?")) {
      try { await signOut(auth); } catch (err) { console.error(err); }
    }
  };

  // Timer
  useEffect(() => {
    let interval;
    if (status === 'in-meeting' || status === 'processing') {
      interval = setInterval(() => setElapsedTime(t => t + 1), 1000);
    }
    return () => clearInterval(interval);
  }, [status]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (pollIntervalRef.current) clearInterval(pollIntervalRef.current); };
  }, []);

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleDeployBot = async (e) => {
    e.preventDefault();
    if (!meetLink) return;

    setError(null);
    setElapsedTime(0);
    setSummary(null);
    setStatus('asking');
    askingStartTimeRef.current = Date.now(); // start the 30s asking timer

    try {
      const idToken = await getIdToken(user);

      const initResponse = await fetch('https://aiscribe.mooo.com/deploy-bot', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${idToken}`
        },
        body: JSON.stringify({ url: meetLink })
      });

      if (!initResponse.ok) {
        const errorData = await initResponse.json();
        throw new Error(errorData.detail || 'Failed to deploy bot');
      }

      const { job_id: jobId } = await initResponse.json();
      console.log('Job initiated:', jobId);

      pollIntervalRef.current = setInterval(async () => {
        try {
          const statusResponse = await fetch(`https://aiscribe.mooo.com/job-status/${jobId}`);
          if (!statusResponse.ok) throw new Error('Failed to fetch job status');

          const { status: jobStatus, result, error: jobError } = await statusResponse.json();

          if (jobStatus === 'pending') {
            setStatus('asking');
          } else if (jobStatus === 'recording') {
            // ── 30s minimum on 'asking' screen ──────────────────────────────
            // The host needs time to admit the bot. Don't jump to 'in-meeting'
            // until at least 30 seconds have passed since the bot was deployed.
            const elapsed = Date.now() - (askingStartTimeRef.current || Date.now());
            if (elapsed >= 30000) {
              setStatus('in-meeting');
            }
            // If < 30s, stay on 'asking' — next poll will check again
          } else if (jobStatus === 'processing') {
            setStatus('processing');
          } else if (jobStatus === 'completed') {
            clearInterval(pollIntervalRef.current);

            const newSummary = {
              executive: result?.executive || 'No summary available',
              actionItems: result?.actionItems || [],
              duration: result?.duration || 'Unknown',
              participants: result?.participants || [],
              audioFile: result?.audioFile || null
            };
            setSummary(newSummary);
            setStatus('complete');

            const newMeeting = {
              id: Date.now(),
              link: meetLink,
              date: new Date().toISOString(),
              summary: newSummary
            };
            const updated = [newMeeting, ...meetings].slice(0, 10);
            setMeetings(updated);
            localStorage.setItem('meetings', JSON.stringify(updated));

          } else if (jobStatus === 'failed') {
            clearInterval(pollIntervalRef.current);
            throw new Error(jobError || 'Job failed');
          }
        } catch (pollErr) {
          console.error('Polling error:', pollErr);
          clearInterval(pollIntervalRef.current);
          setError(pollErr.message || 'Failed to get job status');
          setStatus('idle');
        }
      }, 2000);

    } catch (err) {
      console.error('Bot deployment error:', err);
      setError(err.message || 'Failed to deploy bot. Please check the meet link and try again.');
      setStatus('idle');
    }
  };

  const handleCopySummary = () => {
    if (!summary) return;
    const text = `Meeting Summary\n\nExecutive Summary:\n${summary.executive}\n\nAction Items:\n${summary.actionItems.map(item => `- [${item.priority?.toUpperCase()}] ${item.assignee}: ${item.task}`).join('\n')}`;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!summary) return;
    const text = `MEETING SUMMARY\n================\n\nExecutive Summary:\n${summary.executive}\n\nAction Items:\n${summary.actionItems.map(item => `- [${item.priority?.toUpperCase()}] ${item.assignee}: ${item.task}`).join('\n')}\n\nGenerated by Google Meet AI Scribe`;
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `meeting-summary-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleReset = () => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setStatus('idle');
    setMeetLink('');
    setSummary(null);
    setElapsedTime(0);
    setError(null);
  };

  const loadMeeting = (meeting) => {
    setSummary(meeting.summary);
    setMeetLink(meeting.link);
    setStatus('complete');
  };

  const getStatusProgress = () => {
    const map = { asking: 25, 'in-meeting': 55, processing: 80, complete: 100 };
    return map[status] || 0;
  };

  // ─── Login Screen ───────────────────────────────────────────
  if (!user) {
    return (
      <div className="app-container">
        <a href="https://github.com/rpsahu12/Google-Meet-AI-Scribe-" target="_blank"
          rel="noopener noreferrer" className="github-link-fixed" title="View source on GitHub">
          <GithubIcon size={28} />
        </a>
        <div className="login-container">
          <div className="login-card">
            <div className="login-logo">
              <div className="logo-icon"><Sparkles size={48} /></div>
              <h1>Google Meet AI Scribe</h1>
              <p className="login-subtitle">AI-powered meeting transcription and summarization</p>
            </div>
            <button onClick={handleSignIn} className="signin-btn">
              <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google" className="google-icon" />
              Sign in with Google
            </button>
            <p className="login-note">Sign in to access your AI meeting assistant</p>
          </div>
        </div>
      </div>
    );
  }

  // ─── Main Dashboard ──────────────────────────────────────────
  return (
    <div className="app-container">
      <header className="header">
        <a href="https://github.com/rpsahu12/Google-Meet-AI-Scribe-" target="_blank"
          rel="noopener noreferrer" className="github-link" title="View source on GitHub">
          <GithubIcon size={24} />
        </a>
        <div className="logo-section">
          <div className="logo-icon"><Sparkles size={32} /></div>
          <h1>Google Meet AI Scribe</h1>
        </div>
        <div className="header-user">
          <div className="user-info">
            <img src={user.photoURL} alt={user.displayName} className="user-avatar" />
            <span className="user-name">{user.displayName}</span>
          </div>
          <button onClick={handleSignOut} className="signout-btn" title="Sign out">
            <LogOut size={18} />
          </button>
        </div>
        <p className="subtitle">AI-powered meeting transcription and summarization</p>
      </header>

      <main className="main-content">

        {/* Error Banner */}
        {error && (
          <div className="error-banner">
            <AlertCircle size={20} />
            <span>{error}</span>
            <button onClick={() => setError(null)} className="error-close">×</button>
          </div>
        )}

        {/* Input Section */}
        <section className="deploy-section">
          <form onSubmit={handleDeployBot} className="meet-form">
            <div className="input-wrapper">
              <Video className="input-icon" size={20} />
              <input
                type="url"
                placeholder="Paste Google Meet link (e.g., https://meet.google.com/abc-defg-hij)"
                value={meetLink}
                onChange={(e) => setMeetLink(e.target.value)}
                required
                disabled={status !== 'idle' && status !== 'complete'}
                className="meet-input"
              />
            </div>
            <button
              type="submit"
              className={`deploy-btn ${status !== 'idle' && status !== 'complete' ? 'disabled' : ''}`}
              disabled={status !== 'idle' && status !== 'complete'}
            >
              {status === 'idle' || status === 'complete' ? (
                <><Play size={18} /><span>{status === 'complete' ? 'Start New' : 'Deploy Bot'}</span></>
              ) : (
                <><Loader2 size={18} className="spinner" /><span>Active</span></>
              )}
            </button>
          </form>
        </section>

        {/* Progress Bar */}
        {status !== 'idle' && status !== 'complete' && (
          <div className="progress-container">
            <div className="progress-bar" style={{ width: `${getStatusProgress()}%` }} />
          </div>
        )}

        {/* Status & Timer */}
        {status !== 'idle' && (
          <section className="status-section">
            <div className="status-header">
              <div className="status-indicator">
                <div className={`status-dot ${status}`} />
                <span className="status-text">
                  {status === 'asking' && 'Bot is asking to join the meeting...'}
                  {status === 'in-meeting' && 'Bot is in the meeting, recording audio...'}
                  {status === 'processing' && 'Recording finished — generating AI summary...'}
                  {status === 'complete' && 'Meeting complete!'}
                </span>
              </div>
              {(status === 'in-meeting' || status === 'processing') && (
                <div className="timer">
                  <Clock size={16} />
                  <span>{formatTime(elapsedTime)}</span>
                </div>
              )}
              {status === 'complete' && (
                <button onClick={handleReset} className="reset-btn">
                  <RotateCcw size={16} /><span>New Meeting</span>
                </button>
              )}
            </div>
          </section>
        )}

        {/* Recording State — replaces fake transcription */}
        {status === 'in-meeting' && (
          <section className="transcription-section">
            <div className="section-header">
              <Radio size={20} className="section-icon" />
              <h3>Recording in Progress</h3>
            </div>
            <div className="transcription-content">
              <div className="waiting-state">
                <Loader2 size={28} className="spinner" />
                <p>The bot is inside the meeting and recording audio.</p>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  The AI summary will be generated automatically once the meeting ends.
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Processing State */}
        {status === 'processing' && (
          <section className="transcription-section">
            <div className="section-header">
              <Sparkles size={20} className="section-icon" />
              <h3>Generating Summary</h3>
            </div>
            <div className="transcription-content">
              <div className="waiting-state">
                <Loader2 size={28} className="spinner" />
                <p>Gemini AI is analysing the recording and generating your summary...</p>
              </div>
            </div>
          </section>
        )}

        {/* Summary Section */}
        {status === 'complete' && summary && (
          <section className="summary-section">
            <div className="summary-header">
              <div className="section-header">
                <FileText size={20} className="section-icon" />
                <h3>Meeting Summary</h3>
              </div>
              <div className="summary-actions">
                <button onClick={handleCopySummary} className="action-btn">
                  <Copy size={18} /><span>{copied ? 'Copied!' : 'Copy'}</span>
                </button>
                <button onClick={handleDownload} className="action-btn">
                  <Download size={18} /><span>Export</span>
                </button>
              </div>
            </div>

            <div className="summary-meta">
              {summary.participants?.length > 0 && (
                <div className="meta-item">
                  <Users size={16} />
                  <span>{summary.participants.length} participant{summary.participants.length !== 1 ? 's' : ''}</span>
                </div>
              )}
              {summary.duration && (
                <div className="meta-item">
                  <Clock size={16} />
                  <span>{summary.duration}</span>
                </div>
              )}
            </div>

            <div className="summary-card">
              <div className="summary-block">
                <h4 className="block-title">Executive Summary</h4>
                <p className="summary-text">{summary.executive}</p>
              </div>

              {summary.actionItems?.length > 0 && (
                <div className="summary-block">
                  <h4 className="block-title">Action Items</h4>
                  <ul className="action-list">
                    {summary.actionItems.map((item, idx) => (
                      <li key={idx} className={`action-item priority-${item.priority?.toLowerCase()}`}>
                        <CheckCircle size={18} className="check-icon" />
                        <div className="action-content">
                          <span className="action-assignee">{item.assignee}</span>
                          <span className="action-task">{item.task}</span>
                        </div>
                        {item.priority && (
                          <span className={`priority-badge ${item.priority?.toLowerCase()}`}>
                            {item.priority}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Meeting History */}
        {meetings.length > 0 && status === 'idle' && (
          <section className="history-section">
            <div className="section-header">
              <Clock size={20} className="section-icon" />
              <h3>Recent Meetings</h3>
            </div>
            <div className="history-list">
              {meetings.map((meeting) => (
                <div key={meeting.id} className="history-item">
                  <div className="history-info">
                    <FileText size={18} />
                    <div>
                      <p className="history-date">
                        {new Date(meeting.date).toLocaleDateString('en-US', {
                          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                        })}
                      </p>
                      <p className="history-link">{meeting.link}</p>
                    </div>
                  </div>
                  <button onClick={() => loadMeeting(meeting)} className="view-btn">
                    View Summary
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>

      <footer className="footer">
        <p>Powered by AI • Secure & Private</p>
      </footer>
    </div>
  );
}

export default App;