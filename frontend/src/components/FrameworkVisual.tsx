import { PILLARS } from "../generated/ontology";

/** A diagram of the framework, never a chart of an organization's results. */
export function FrameworkVisual() {
  return (
    <div className="framework-visual" aria-hidden="true">
      <svg viewBox="0 0 480 280" fill="none">
        <circle className="framework-guide" cx="240" cy="140" r="112" />
        <circle className="framework-guide inner" cx="240" cy="140" r="84" />
        {PILLARS.map((pillar, index) => {
          const angle = (index * 60 - 90) * Math.PI / 180;
          const x = 240 + Math.cos(angle) * 112;
          const y = 140 + Math.sin(angle) * 112;
          const left = x < 239;
          const center = Math.abs(x - 240) < 1;
          return (
            <g key={pillar.code}>
              <path className="framework-spoke" d={`M240 140 L${x} ${y}`} />
              <circle className={`framework-arc arc-${index}`} cx="240" cy="140" r="84" strokeDasharray="73 455" transform={`rotate(${index * 60 - 86} 240 140)`} />
              <circle className="framework-node-halo" cx={x} cy={y} r="7" />
              <circle className="framework-node" cx={x} cy={y} r="3" />
              <text x={center ? x : x + (left ? -15 : 15)} y={center ? y + (y < 140 ? -15 : 24) : y + 4} textAnchor={center ? "middle" : left ? "end" : "start"}>{pillar.name}</text>
            </g>
          );
        })}
        <circle className="framework-center" cx="240" cy="140" r="49" />
        <path className="framework-shield" d="m240 111-13 5v9c0 10 13 17 13 17s13-7 13-17v-9z M234 125l4 4 8-9" />
        <text className="framework-wordmark" x="240" y="161" textAnchor="middle">HAI Score</text>
      </svg>
      <span className="framework-caption">SIX PILLARS. ONE CLEARER PICTURE.</span>
    </div>
  );
}
