import React from "react";
import { NAVY } from "./theme";

/** A person: head and shoulders in a navy disc. */
export const UserAvatar: React.FC<{ size?: number }> = ({ size = 96 }) => (
  <svg width={size} height={size} viewBox="0 0 96 96">
    <circle cx="48" cy="48" r="48" fill={NAVY} />
    <circle cx="48" cy="38" r="15" fill="#fff" />
    <path d="M20 84c3-17 14-26 28-26s25 9 28 26a48 48 0 0 1-56 0z" fill="#fff" />
  </svg>
);

/** A coding agent: a rounded robot head with two eyes, an antenna and a code bracket on the chest. */
export const AgentIcon: React.FC<{ size?: number; color?: string }> = ({ size = 40, color = "#2f5f8f" }) => (
  <svg width={size} height={size} viewBox="0 0 48 48">
    <circle cx="24" cy="6" r="3" fill={color} />
    <rect x="23" y="8" width="2" height="6" fill={color} />
    <rect x="8" y="14" width="32" height="24" rx="8" fill={color} />
    <rect x="14" y="22" width="7" height="7" rx="2" fill="#fff" />
    <rect x="27" y="22" width="7" height="7" rx="2" fill="#fff" />
    <rect x="17" y="32" width="14" height="2.5" rx="1.25" fill="#fff" />
    <rect x="4" y="22" width="3" height="8" rx="1.5" fill={color} />
    <rect x="41" y="22" width="3" height="8" rx="1.5" fill={color} />
    <path d="M16 46l-4-4 4-4M32 46l4-4-4-4" stroke={color} strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** The browser-agent judge: a browser window with an eye. */
export const JudgeIcon: React.FC<{ size?: number; color?: string }> = ({ size = 40, color = "#3f8f5f" }) => (
  <svg width={size} height={size} viewBox="0 0 48 48">
    <rect x="4" y="8" width="40" height="34" rx="5" fill={color} />
    <rect x="4" y="8" width="40" height="8" rx="5" fill={color} />
    <circle cx="10" cy="12" r="1.8" fill="#fff" />
    <circle cx="15" cy="12" r="1.8" fill="#fff" />
    <circle cx="20" cy="12" r="1.8" fill="#fff" />
    <path d="M11 29c4-7 9-10 13-10s9 3 13 10c-4 7-9 10-13 10s-9-3-13-10z" fill="#fff" />
    <circle cx="24" cy="29" r="4.5" fill={color} />
    <circle cx="25.5" cy="27.5" r="1.4" fill="#fff" />
  </svg>
);
