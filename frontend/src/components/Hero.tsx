import React from 'react';
import { AnimatedHeading } from './AnimatedHeading';
import { FadeIn } from './FadeIn';

export function Hero() {
  return (
    <div className="relative w-full h-screen overflow-hidden bg-black text-white font-sans">
      {/* Video Background */}
      <video
        className="absolute inset-0 w-full h-full object-cover"
        autoPlay
        loop
        muted
        playsInline
        src="/bg.mp4"
      />

      {/* Foreground Content */}
      <div className="relative z-10 w-full h-full flex flex-col">
        {/* Top spacer for the global fixed navbar */}
        <div className="pt-24"></div>

        {/* Hero Content */}
        <div className="px-6 md:px-12 lg:px-16 flex-1 flex flex-col justify-end pb-12 lg:pb-16">
          <div className="flex flex-col md:flex-row justify-between items-end gap-8">
            <div className="max-w-3xl">
              <FadeIn delay={1000} duration={1200}>
                <AnimatedHeading 
                  text="Shaping tomorrow" 
                  className="text-6xl md:text-8xl lg:text-9xl font-light tracking-tighter text-white mb-6"
                />
              </FadeIn>
              
              <FadeIn delay={1200} duration={1000} className="flex flex-wrap gap-4 mt-8">
                <a href="#dashboard" className="liquid-glass border border-white/20 text-white px-8 py-3 rounded-lg font-medium hover:bg-white hover:text-black transition-colors duration-300 inline-block">
                  Explore Now
                </a>
              </FadeIn>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
