// App.js

import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  // --- State Hooks ---
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  // Add a new state to hold the conversation thread ID
  const [threadId, setThreadId] = useState(null);

  const messagesEndRef = useRef(null);

  // --- Effects ---

  // Auto-scroll to the bottom when a new message is added
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };
  useEffect(() => {
    scrollToBottom();
  }, [messages]);
  
  // Set the initial bot message and generate a unique thread ID for this session
  useEffect(() => {
    setMessages([
      { type: 'bot', text: "Hi there! I'm Ascend's AI Assistant. How can I help you plan your trip today?" }
    ]);
    // Generate a simple, unique ID for this conversation session
    const newThreadId = `session_${Math.random().toString(36).substring(2, 11)}`;
    setThreadId(newThreadId);
    console.log("New conversation started with Thread ID:", newThreadId);
  }, []);

  // --- Core Function ---

  const sendMessage = async () => {
    // --- 1. Input Validation ---
    // Do not send if input is empty, a request is already in progress, or threadId is not set.
    if (!inputValue.trim() || isLoading || !threadId) return;

    const userMessage = { type: 'user', text: inputValue };
    
    // --- 2. Optimistic UI Update ---
    // Immediately add the user's message and a clean loading indicator to the UI.
    setMessages(prev => [...prev, userMessage, { type: 'bot', text: '...', isLoading: true, isError: false }]);
    setIsLoading(true);
    setInputValue('');

    try {
      // --- 3. API Call ---
      const apiUrl = process.env.REACT_APP_API_URL || 'http://localhost:8008/chat';
      console.log(`Requesting API at: ${apiUrl} with thread_id: ${threadId}`);

      const response = await axios.post(
        apiUrl, 
        {
          message: userMessage.text,
          thread_id: threadId 
        }, 
        {
          timeout: 30000 // Set a 15-second timeout. If no response, it will throw an error.
        }
      );
      
      // --- 4. Success Logic ---
      // This block runs ONLY if the request was successful (status 2xx).
      const botResponse = { 
        type: 'bot', 
        text: response.data.reply, // Get the reply from the backend
        isError: false 
      };
      
      // Replace the loading indicator ('...') with the actual bot response.
      setMessages(prev => [...prev.slice(0, -1), botResponse]);

    } catch (error) {
      // --- 5. Comprehensive Error Handling ---
      // This block runs if the `axios.post` call fails for ANY reason.
      console.error("Error sending message:", error);

      let errorText = 'An unexpected error occurred. Please try again.';
      
      // Diagnose the type of error to provide a better user message.
      if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
        // This is a timeout error.
        errorText = "The server is taking too long to respond. Please try again later.";
      } else if (error.code === 'ERR_NETWORK') {
        // This is a network error (e.g., server is down, no internet).
        errorText = "Unable to connect to the server. Please check if the backend is running and your internet connection.";
      } else if (error.response) {
        // The server responded, but with an error status code (4xx or 5xx).
        const status = error.response.status;
        const detail = error.response.data?.detail || 'No further details.';
        errorText = `Server Error (${status}): ${detail}`;
      }
      
      const errorMessage = { type: 'bot', text: errorText, isError: true };
      
      // Replace the loading indicator ('...') with the detailed error message.
      setMessages(prev => [...prev.slice(0, -1), errorMessage]);

    } finally {
      // --- 6. Cleanup ---
      // This block runs ALWAYS, whether the request succeeded or failed.
      // It ensures the loading state is turned off, allowing the user to send another message.
      setIsLoading(false);
    }
  };

  // --- JSX Rendering ---

  return (
    <div className="chat-widget">
      <div className="widget-header">
        Ascend Travel Assistant
      </div>
      <div className="messages-container">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.type}`}>
            {msg.isLoading ? '...' : msg.text}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="input-container">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
          placeholder="e.g., Book a flight to SFO..."
          disabled={isLoading}
        />
        <button onClick={sendMessage} disabled={isLoading}>
          {isLoading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}

export default App;