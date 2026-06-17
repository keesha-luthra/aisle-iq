import React, { useState, useEffect } from 'react';

interface AnimatedHeadingProps {
  text: string;
  className?: string;
  style?: React.CSSProperties;
}

export function AnimatedHeading({ text, className = '', style }: AnimatedHeadingProps) {
  const [start, setStart] = useState(false);
  const initialDelay = 200;
  const charDelay = 30;
  const transitionDuration = 500;

  useEffect(() => {
    const timer = setTimeout(() => setStart(true), initialDelay);
    return () => clearTimeout(timer);
  }, []);

  const lines = text.split('\n');

  return (
    <h1 className={className} style={style}>
      {lines.map((line, lineIndex) => (
        <div key={lineIndex} className="block whitespace-nowrap">
          {line.split('').map((char, charIndex) => {
            const delay = (lineIndex * line.length * charDelay) + (charIndex * charDelay);
            return (
              <span
                key={charIndex}
                className="inline-block"
                style={{
                  opacity: start ? 1 : 0,
                  transform: start ? 'translateX(0)' : 'translateX(-18px)',
                  transition: start
                    ? `opacity ${transitionDuration}ms ease-out ${delay}ms, transform ${transitionDuration}ms ease-out ${delay}ms`
                    : 'none',
                }}
              >
                {char === ' ' ? '\u00A0' : char}
              </span>
            );
          })}
        </div>
      ))}
    </h1>
  );
}
