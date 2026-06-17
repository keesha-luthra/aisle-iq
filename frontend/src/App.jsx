import React from 'react';
import { Navbar } from './components/Navbar';
import { Hero } from './components/Hero';
import { Dashboard } from './components/Dashboard';
import { Footer } from './components/Footer';

function App() {
  return (
    <div className="bg-black min-h-screen text-white font-sans selection:bg-white/30 selection:text-white relative">
      <Navbar />
      <main>
        <Hero />
        <Dashboard />
      </main>
      <Footer />
    </div>
  );
}

export default App;
