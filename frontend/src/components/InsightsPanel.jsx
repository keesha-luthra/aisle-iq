import React from 'react';
import { AlertTriangle, Info, ShieldAlert } from 'lucide-react';

export default function InsightsPanel({ anomalies }) {
  if (!anomalies || anomalies.length === 0) {
    return (
      <div className="flex items-center gap-4 p-4 rounded-xl bg-green-500/5 border border-green-500/20">
        <div className="w-10 h-10 rounded-full bg-green-500/10 flex items-center justify-center">
          <Info className="text-green-400" size={20} />
        </div>
        <div>
          <div className="font-semibold text-green-400 mb-1">All systems nominal</div>
          <div className="text-sm text-gray-400">No spatial anomalies or queue bottlenecks detected.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {anomalies.map((a, i) => {
        const isCritical = a.severity?.toUpperCase() === 'CRITICAL';
        const isWarn = a.severity?.toUpperCase() === 'WARN';
        
        let colorClass = 'text-blue-400';
        let bgClass = 'bg-blue-500/5';
        let borderClass = 'border-blue-500/20';
        let Icon = Info;

        if (isCritical) {
          colorClass = 'text-red-400';
          bgClass = 'bg-red-500/5';
          borderClass = 'border-red-500/20';
          Icon = ShieldAlert;
        } else if (isWarn) {
          colorClass = 'text-yellow-400';
          bgClass = 'bg-yellow-500/5';
          borderClass = 'border-yellow-500/20';
          Icon = AlertTriangle;
        }

        return (
          <div key={i} className={`flex items-start gap-4 p-4 rounded-xl border ${bgClass} ${borderClass}`}>
            <div className="mt-0.5">
              <Icon className={colorClass} size={20} />
            </div>
            <div>
              <div className={`font-semibold mb-1 ${colorClass}`}>{a.anomaly_type}</div>
              <div className="text-sm text-gray-400">{a.description}</div>
            </div>
          </div>
        )
      })}
    </div>
  );
}
