import React from 'react';
import { FadeIn } from './FadeIn';

export default function MetricCard({ title, value, trend, suffix }) {
  return (
    <FadeIn>
      <div className="liquid-glass rounded-xl p-6 h-full flex flex-col justify-center">
        <div className="text-gray-400 text-sm md:text-base font-medium mb-2">{title}</div>
        <div className="flex items-baseline gap-2">
          <div className="text-3xl md:text-4xl font-light text-white">{value}</div>
          {suffix && <div className="text-gray-400 font-medium">{suffix}</div>}
        </div>
        
        {trend && (
          <div className={`mt-3 text-xs flex items-center gap-1 ${trend.isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {trend.isPositive ? '↑' : '↓'} {Math.abs(trend.value)}% from last week
          </div>
        )}
      </div>
    </FadeIn>
  );
}
