import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown'; 
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [threadId, setThreadId] = useState(null);
  
  const messagesEndRef = useRef(null);
  const pollingIntervalRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };
  
  useEffect(scrollToBottom, [messages]);

  useEffect(() => {
    setMessages([
      { type: 'bot', text: "Hi! I'm your AI travel assistant. How can I help you plan your next adventure?" }
    ]);
    const newThreadId = `session_${Date.now()}`;
    setThreadId(newThreadId);
    return () => {
      if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
    };
  }, []);

  const pollForResult = (taskId) => {
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);

    pollingIntervalRef.current = setInterval(async () => {
      try {
        const baseUrl = process.env.REACT_APP_API_URL || 'http://localhost:8008';
        const statusUrl = `${baseUrl}/chat/status/${taskId}`;
        const response = await axios.get(statusUrl);
        const { status, result } = response.data;

        if (status === 'completed') {
          clearInterval(pollingIntervalRef.current);
          setIsLoading(false);
          const botResponse = { type: 'bot', text: result.reply };
          setMessages(prev => [...prev.slice(0, -1), botResponse]);
        } else if (status === 'failed') {
          clearInterval(pollingIntervalRef.current);
          setIsLoading(false);
          const errorText = `An error occurred: ${result?.error || 'Unknown error'}`;
          setMessages(prev => [...prev.slice(0, -1), { type: 'bot', text: errorText, isError: true }]);
        }
        
      } catch (error) {
        console.error("Polling error:", error);
        clearInterval(pollingIntervalRef.current);
        setIsLoading(false);
        setMessages(prev => [...prev.slice(0, -1), { type: 'bot', text: "Failed to get a response.", isError: true }]);
      }
    }, 2500); 
  };

  const handleSendMessage = async () => { 
    if (!inputValue.trim() || isLoading || !threadId) return;

    const userMessage = { type: 'user', text: inputValue };
    setMessages(prev => [...prev, userMessage, { type: 'bot', text: 'Astra is thinking...', isLoading: true }]);
    setIsLoading(true);
    setInputValue('');

    try {
      const baseUrl = process.env.REACT_APP_API_URL || 'http://localhost:8008';
      const chatUrl = `${baseUrl}/chat`;
      const response = await axios.post(chatUrl, { message: userMessage.text, thread_id: threadId });
      if (response.data.task_id) {
        pollForResult(response.data.task_id);
      } else {
        throw new Error("Failed to start the background task.");
      }
    } catch (error) {
      console.error("Error sending initial message:", error);
      setIsLoading(false);
      const errorText = error.response?.data?.detail || "Could not connect to the assistant.";
      setMessages(prev => [...prev.slice(0, -1), { type: 'bot', text: errorText, isError: true }]);
    }
  };

  const handleKeyPress = (event) => {
    if (event.key === 'Enter' && !isLoading) {
      handleSendMessage();
    }
  };

  return (
    <div className="chat-widget">
      <div className="widget-header">Ascend Travel Assistant</div>
      <div className="messages-container">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.type} ${msg.isError ? 'error' : ''}`}>
            {msg.isLoading ? (
              <div className="loading-message">{msg.text}</div> 
            ) : (
              <ReactMarkdown>{msg.text}</ReactMarkdown>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="input-container">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="e.g., A flight from NYC to SFO..."
          disabled={isLoading}
        />
        <button onClick={handleSendMessage} disabled={isLoading}>
          {isLoading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}

export default App;