import React, { useState, useEffect } from 'react';

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 50);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <div className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? 'py-2 bg-black/60 backdrop-blur-md border-b border-white/10' : 'pt-6 px-6 md:px-12 lg:px-16'}`}>
      <div className={`${scrolled ? 'px-6 md:px-12 lg:px-16 max-w-7xl mx-auto w-full' : ''}`}>
        <nav className={`flex items-center justify-between ${!scrolled ? 'liquid-glass rounded-xl px-4 py-2' : 'py-2'}`}>
          <a href="#" className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-white">
            <img src="/logo.png" alt="AisleIQ Logo" className="h-8 w-auto mix-blend-screen" />
            AisleIQ
          </a>
          <div className="hidden md:flex items-center gap-8 text-sm text-white">
            <a href="#metrics" className="hover:text-gray-300 transition-colors">Metrics</a>
            <a href="#camera-feeds" className="hover:text-gray-300 transition-colors">Camera Feeds</a>
            <a href="#heatmaps" className="hover:text-gray-300 transition-colors">Heatmaps</a>
            <a href="#funnel" className="hover:text-gray-300 transition-colors">Funnel</a>
          </div>
          <a href="#dashboard" className="bg-white text-black px-6 py-2 rounded-lg text-sm font-medium hover:bg-gray-100 transition-colors">
            View Dashboard
          </a>
        </nav>
      </div>
    </div>
  );
}
