import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import Handout from './Handout.jsx';
import './style.css';

const Page = window.location.pathname === '/handout' ? Handout : App;

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>,
);
