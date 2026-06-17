import React from 'react';

export function Footer() {
  return (
    <footer className="w-full py-12 px-6 md:px-12 lg:px-16 border-t border-white/10 bg-black text-white">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center">
        <div className="mb-4 md:mb-0">
          <div className="flex items-center gap-2 text-2xl font-semibold tracking-tight mb-2">
            <img src="/logo.png" alt="AisleIQ Logo" className="h-8 w-auto mix-blend-screen opacity-80" />
            AisleIQ
          </div>
          <div className="text-sm text-gray-400">Spatial Intelligence & Analytics.</div>
        </div>
        <div className="flex gap-8 text-sm text-gray-400">
          <a href="#" className="hover:text-white transition-colors">Privacy</a>
          <a href="#" className="hover:text-white transition-colors">Terms</a>
          <a href="#" className="hover:text-white transition-colors">Support</a>
        </div>
      </div>
    </footer>
  );
}
