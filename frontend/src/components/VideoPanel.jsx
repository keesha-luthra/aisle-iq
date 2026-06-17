import React from 'react';
import { Camera, Users, ArrowRightLeft, Activity } from 'lucide-react';

export default function VideoPanel({ camId, label, source, stats, selectedStore }) {
  const isAnnotated = source === 'ANNOTATED';

  return (
    <div className="flex flex-col h-full bg-black/40 backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-white/10">
        <Camera size={18} className="text-gray-400" />
        <span className="font-medium text-white flex-1 truncate">
          {label}
        </span>
        <div className="flex gap-2 text-[10px] font-bold tracking-wider">
          <span className="bg-red-500/20 text-red-400 px-2 py-1 rounded-sm flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span> LIVE
          </span>
          {isAnnotated ? (
            <span className="bg-blue-500/20 text-blue-400 px-2 py-1 rounded-sm border border-blue-500/30">
              SPATIAL
            </span>
          ) : (
            <span className="bg-gray-500/20 text-gray-400 px-2 py-1 rounded-sm border border-gray-500/30">
              RAW
            </span>
          )}
        </div>
      </div>

      {/* Video Container */}
      <div className="relative w-full aspect-video bg-black/60 flex items-center justify-center overflow-hidden">
        <video 
          src={`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/video/${selectedStore}/${camId}`} 
          autoPlay 
          loop 
          muted 
          playsInline
          className="w-full h-full object-cover"
        />
      </div>

      {/* Stats */}
      <div className="flex justify-between p-4 bg-black/40 border-t border-white/10">
        <StatBlock icon={<Users size={14} />} label="Active" value={stats?.active_visitors_count || 0} />
        <StatBlock icon={<Activity size={14} />} label="Tracks" value={stats?.active_tracks || 0} />
        <StatBlock icon={<ArrowRightLeft size={14} />} label="Entries" value={stats?.entries || 0} />
        <StatBlock icon={<ArrowRightLeft size={14} className="rotate-180" />} label="Exits" value={stats?.exits || 0} />
      </div>
    </div>
  );
}

function StatBlock({ icon, label, value }) {
  return (
    <div className="text-center">
      <div className="text-gray-500 text-[10px] uppercase tracking-widest font-semibold flex items-center justify-center gap-1">
        {icon} {label}
      </div>
      <div className="text-white font-light text-xl mt-1">
        {value}
      </div>
    </div>
  );
}
