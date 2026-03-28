// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyC9xC8cZCHODygT-qyf92KR2kbXPmCtHS8",
  authDomain: "ai-scribe-21776.firebaseapp.com",
  projectId: "ai-scribe-21776",
  storageBucket: "ai-scribe-21776.firebasestorage.app",
  messagingSenderId: "475956549476",
  appId: "1:475956549476:web:0cc2343882d0174c4d8c71",
  measurementId: "G-NB8FX3077J"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);
const auth = getAuth(app);
const provider = new GoogleAuthProvider();

export { auth, provider };