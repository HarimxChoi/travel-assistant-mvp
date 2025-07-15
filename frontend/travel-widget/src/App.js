import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import './App.css';

const ContactForm = ({ onSubmit }) => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (name && email) {
      onSubmit({ name, email });
    }
  };

  return (
    <div className="form-container">
      <form onSubmit={handleSubmit} className="contact-form">
        <h4>Please provide your details</h4>
        <p>While I search, please fill in your contact information for the final report.</p>
        <input 
          type="text" 
          placeholder="Your Name" 
          value={name} 
          onChange={(e) => setName(e.target.value)} 
          required 
        />
        <input 
          type="email" 
          placeholder="Your Email" 
          value={email} 
          onChange={(e) => setEmail(e.target.value)} 
          required 
        />
        <button type="submit">Submit Info</button>
      </form>
    </div>
  );
};


const SuggestedReplies = ({ suggestions, onSelect }) => {
  if (suggestions.length === 0) return null;

  return (
    <div className="suggested-replies">
      {suggestions.map((text, index) => (
        <button key={index} onClick={() => onSelect(text)} className="suggestion-btn">
          {text}
        </button>
      ))}
    </div>
  );
};


function App() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [threadId, setThreadId] = useState(null);
  const [suggestedReplies, setSuggestedReplies] = useState([]);
  const [showContactForm, setShowContactForm] = useState(false); 
  const [userInfo, setUserInfo] = useState(null); 
  
  const messagesEndRef = useRef(null);
  const pollingIntervalRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };
  
  useEffect(scrollToBottom, [messages]);

  const welcomeMessage = `
Hi! I'm Astra, your AI travel consultant. ✈️🏨🚗

I can help you plan your entire trip at once. Just tell me what you need.

**For example, you can ask:**

*   **For a simple query:**
    *"Find me a flight from ICN to CDG next Monday."*

*   **For a complex plan:**
    *"I'm planning a 4-day trip from Paris to New York next month. Find me a flight, recommend some great value hotels in central Manhattan, show me what activities or exhibitions are on, and I'll also need a car rental from the airport. My total budget is $2000."*

How can I help you get started?
  `;

  useEffect(() => {
    setMessages([{ type: 'bot', text: welcomeMessage }]);
    setSuggestedReplies([
      'Search for flights ✈️',
      'Recommend hotels 🏨',
      'Rent a car 🚗',
      'Plan a full trip 🗺️',
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
        const { status, result, form_to_display } = response.data;

        if (form_to_display === 'contact_info' && !userInfo) {
          setShowContactForm(true);
        }

        if (status === 'completed') {
          clearInterval(pollingIntervalRef.current);
          setIsLoading(false);
          setShowContactForm(false); 
          const botResponse = { type: 'bot', text: result.reply };
          setMessages(prev => [...prev.slice(0, -1), botResponse]);
        } else if (status === 'failed') {
          clearInterval(pollingIntervalRef.current);
          setIsLoading(false);
          setShowContactForm(false);
          const errorText = `An error occurred: ${result?.error || 'Unknown error'}`;
          setMessages(prev => [...prev.slice(0, -1), { type: 'bot', text: errorText, isError: true }]);
        }
        
      } catch (error) {
        console.error("Polling error:", error);
        clearInterval(pollingIntervalRef.current);
        setIsLoading(false);
        setShowContactForm(false);
        setMessages(prev => [...prev.slice(0, -1), { type: 'bot', text: "Failed to get a response.", isError: true }]);
      }
    }, 2500); 
  };

  const handleSendMessage = async (messageText = inputValue) => { 
    if (!messageText.trim() || isLoading || !threadId) return;

    const userMessage = { type: 'user', text: messageText };
    setMessages(prev => [...prev, userMessage, { type: 'bot', text: 'Astra is thinking...', isLoading: true }]);
    setIsLoading(true);
    setInputValue('');
    setSuggestedReplies([]);

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
  
  // [NEW] form submit handler
  const handleFormSubmit = (data) => {
    console.log("User Info Submitted:", data);
    setUserInfo(data);
    setShowContactForm(false);
    setMessages(prev => [...prev, { type: 'bot', text: "Thanks! I've saved your information." }]);
  };

  const handleSuggestionSelect = (suggestion) => {
    handleSendMessage(suggestion);
  };

  const handleKeyPress = (event) => {
    if (event.key === 'Enter' && !isLoading) {
      handleSendMessage();
    }
  };

  return (
    <div className="chat-widget">
      <div className="widget-header">Astra Travel Assistant</div>
      <div className="messages-container">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.type} ${msg.isError ? 'error' : ''}`}>
            {msg.isLoading ? (
              <div className="loading-message">{msg.text}</div> 
            ) : (
              <ReactMarkdown children={msg.text} />
            )}
          </div>
        ))}
        {/* form redering logic */}
        {showContactForm && <ContactForm onSubmit={handleFormSubmit} />}
        <div ref={messagesEndRef} />
      </div>
      
      <SuggestedReplies suggestions={suggestedReplies} onSelect={handleSuggestionSelect} />

      <div className="input-container">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask for a flight, hotel, or a full plan..."
          disabled={isLoading}
        />
        <button onClick={() => handleSendMessage()} disabled={isLoading}>
          {isLoading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}

export default App;