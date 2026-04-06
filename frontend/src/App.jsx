import React, { useState, useEffect, useRef } from 'react';
import {
  Video, Play, Loader2, FileText, CheckCircle, Copy, Download,
  Clock, Users, Mic, Sparkles, RotateCcw, AlertCircle, LogOut
} from 'lucide-react';
import { signInWithPopup, signOut, onAuthStateChanged, getIdToken } from 'firebase/auth';
import { auth, provider } from './firebase';
import './App.css';

// Simulated live transcription snippets
const TRANSCRIPTION_SNIPPETS = [
  "Alice: Let's start with the Q3 roadmap review...",
  "Bob: The infrastructure is ready for scaling...",
  "Carol: Marketing campaign shows 23% increase...",
  "David: User engagement metrics look promising...",
  "Alice: Should we proceed with the launch date?",
  "Bob: I recommend adding two more sprint cycles...",
];

function App() {
  const [user, setUser] = useState(null);
  const [meetLink, setMeetLink] = useState('');
  const [status, setStatus] = useState('idle');
  const [summary, setSummary] = useState(null);
  const [transcription, setTranscription] = useState([]);
  const [error, setError] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [copied, setCopied] = useState(false);
  const [meetings, setMeetings] = useState([]);
  const transcriptionRef = useRef(null);
  const pollIntervalRef = useRef(null);

  // Listen to Firebase auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
    });
    return () => unsubscribe();
  }, []);

  // Load meetings from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('meetings');
    if (saved) setMeetings(JSON.parse(saved));
  }, []);

  // Handle Google Sign In
  const handleSignIn = async () => {
    try {
      await signInWithPopup(auth, provider);
    } catch (err) {
      console.error('Sign in error:', err);
      setError('Failed to sign in. Please try again.');
    }
  };

// Handle Sign Out
  const handleSignOut = async () => {
    const isConfirmed = window.confirm("Are you sure you want to log out?");
    
    if (isConfirmed) {
      try {
        await signOut(auth);
      } catch (err) {
        console.error('Sign out error:', err);
      }
    }
  };

  // Timer for elapsed time
  useEffect(() => {
    let interval;
    if (status === 'in-meeting' || status === 'processing') {
      interval = setInterval(() => setElapsedTime(t => t + 1), 1000);
    }
    return () => clearInterval(interval);
  }, [status]);

  // Simulate live transcription (shown during meeting)
  useEffect(() => {
    if (status !== 'in-meeting') return;

    let snippetIndex = 0;
    const interval = setInterval(() => {
      if (snippetIndex < TRANSCRIPTION_SNIPPETS.length) {
        setTranscription(prev => [...prev, {
          text: TRANSCRIPTION_SNIPPETS[snippetIndex],
          timestamp: new Date().toLocaleTimeString()
        }]);
        snippetIndex++;
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [status]);

  // Auto-scroll transcription
  useEffect(() => {
    if (transcriptionRef.current) {
      transcriptionRef.current.scrollTop = transcriptionRef.current.scrollHeight;
    }
  }, [transcription]);

  // Cleanup polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
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
    setTranscription([]);
    setElapsedTime(0);
    setStatus('asking');

    try {
      // Get the Firebase ID token from the logged-in user
      const idToken = await getIdToken(user);
      console.log('Got ID token for user:', user.uid);

      // Step 1: Initiate the job - backend returns immediately with job_id
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

      const initData = await initResponse.json();
      const jobId = initData.job_id;
      console.log('Job initiated:', jobId);

      // Step 2: Poll for status updates
      pollIntervalRef.current = setInterval(async () => {
        try {
          const statusResponse = await fetch(`https://aiscribe.mooo.com/job-status/${jobId}`);
          if (!statusResponse.ok) {
            throw new Error('Failed to fetch job status');
          }

          const jobData = await statusResponse.json();
          const { status: jobStatus, result, error } = jobData;

          // Map backend status to frontend status
          if (jobStatus === 'pending') {
            setStatus('asking'); // Bot asking to join
          } else if (jobStatus === 'recording') {
            setStatus('in-meeting'); // Bot admitted, meeting in progress
          } else if (jobStatus === 'processing') {
            setStatus('processing'); // Recording done, generating summary
          } else if (jobStatus === 'completed') {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

            const newSummary = {
              executive: result?.executive || 'No summary available',
              actionItems: result?.actionItems || [],
              duration: result?.duration || 'Unknown',
              participants: result?.participants || [],
              audioFile: result?.audioFile || null
            };
            setSummary(newSummary);
            setStatus('complete');

            // Save to history
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
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            throw new Error(error || 'Job failed');
          }
        } catch (pollErr) {
          console.error('Polling error:', pollErr);
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          setError(pollErr.message || 'Failed to get job status');
          setStatus('idle');
        }
      }, 2000); // Poll every 2 seconds

    } catch (err) {
      console.error('Bot deployment error:', err);
      setError(err.message || 'Failed to deploy bot. Please check the meet link and try again.');
      setStatus('idle');
    }
  };

  const handleCopySummary = () => {
    if (!summary) return;
    const text = `Meeting Summary\n\nExecutive Summary:\n${summary.executive}\n\nAction Items:\n${summary.actionItems.map(item => `- [${item.priority.toUpperCase()}] ${item.assignee}: ${item.task}`).join('\n')}`;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!summary) return;
    const text = `MEETING SUMMARY\n================\n\nExecutive Summary:\n${summary.executive}\n\nAction Items:\n${summary.actionItems.map(item => `- [${item.priority.toUpperCase()}] ${item.assignee}: ${item.task}`).join('\n')}\n\nGenerated by Google Meet AI Scribe`;
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
    setTranscription([]);
    setElapsedTime(0);
    setError(null);
  };

  const loadMeeting = (meeting) => {
    setSummary(meeting.summary);
    setMeetLink(meeting.link);
    setStatus('complete');
  };

  const getStatusProgress = () => {
    const stages = ['asking', 'in-meeting', 'processing', 'complete'];
    const currentIndex = stages.indexOf(status);
    return ((currentIndex + 1) / stages.length) * 100;
  };

  // Show login screen if not authenticated
  if (!user) {
    return (
      <div className="app-container">
        <div className="login-container">
          <div className="login-card">
            <div className="login-logo">
              <div className="logo-icon">
                <Sparkles size={48} />
              </div>
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

  // Main dashboard for authenticated users
  return (
    <div className="app-container">
      <header className="header">
        <div className="logo-section">
          <div className="logo-icon">
            <Sparkles size={32} />
          </div>
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
                <>
                  <Play size={18} />
                  <span>{status === 'complete' ? 'Start New' : 'Deploy Bot'}</span>
                </>
              ) : (
                <>
                  <Loader2 size={18} className="spinner" />
                  <span>Active</span>
                </>
              )}
            </button>
          </form>
        </section>

        {/* Progress Bar */}
        {(status === 'asking' || status === 'in-meeting' || status === 'processing') && (
          <div className="progress-container">
            <div className="progress-bar" style={{ width: `${getStatusProgress()}%` }} />
          </div>
        )}

        {/* Status & Timer */}
        {(status !== 'idle') && (
          <section className="status-section">
            <div className="status-header">
              <div className="status-indicator">
                <div className={`status-dot ${status}`} />
                <span className="status-text">
                  {status === 'asking' && 'Asking to join...'}
                  {status === 'in-meeting' && 'Meeting in progress...'}
                  {status === 'processing' && 'Recording finished - Generating summary...'}
                  {status === 'complete' && 'Meeting complete!'}
                </span>
              </div>
              {(status === 'listening' || status === 'processing') && (
                <div className="timer">
                  <Clock size={16} />
                  <span>{formatTime(elapsedTime)}</span>
                </div>
              )}
              {status === 'complete' && (
                <button onClick={handleReset} className="reset-btn">
                  <RotateCcw size={16} />
                  <span>New Meeting</span>
                </button>
              )}
            </div>
          </section>
        )}

        {/* Live Transcription */}
        {status === 'in-meeting' && (
          <section className="transcription-section">
            <div className="section-header">
              <Mic size={20} className="section-icon" />
              <h3>Live Transcription</h3>
            </div>
            <div className="transcription-content" ref={transcriptionRef}>
              {transcription.length === 0 ? (
                <div className="waiting-state">
                  <Loader2 size={24} className="spinner" />
                  <p>Waiting for speech...</p>
                </div>
              ) : (
                transcription.map((item, idx) => (
                  <div key={idx} className="transcript-line">
                    <span className="transcript-time">{item.timestamp}</span>
                    <span className="transcript-text">{item.text}</span>
                  </div>
                ))
              )}
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
                <button onClick={handleCopySummary} className="action-btn" title="Copy">
                  <Copy size={18} />
                  <span>{copied ? 'Copied!' : 'Copy'}</span>
                </button>
                <button onClick={handleDownload} className="action-btn" title="Download">
                  <Download size={18} />
                  <span>Export</span>
                </button>
              </div>
            </div>

            <div className="summary-meta">
              <div className="meta-item">
                <Users size={16} />
                <span>{summary.participants.length} participants</span>
              </div>
              <div className="meta-item">
                <Clock size={16} />
                <span>{summary.duration}</span>
              </div>
            </div>

            <div className="summary-card">
              <div className="summary-block">
                <h4 className="block-title">Executive Summary</h4>
                <p className="summary-text">{summary.executive}</p>
              </div>

              <div className="summary-block">
                <h4 className="block-title">Action Items</h4>
                <ul className="action-list">
                  {summary.actionItems.map((item, idx) => (
                    <li key={idx} className={`action-item priority-${item.priority}`}>
                      <CheckCircle size={18} className="check-icon" />
                      <div className="action-content">
                        <span className="action-assignee">{item.assignee}</span>
                        <span className="action-task">{item.task}</span>
                      </div>
                      <span className={`priority-badge ${item.priority}`}>
                        {item.priority}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
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